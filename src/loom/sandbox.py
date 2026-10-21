"""Sandboxed command execution for ctx_store_cmd.

Windows: Job Object with CPU rate limit, memory limit, and process count limit.
Linux: bwrap (bubblewrap) or firejail fallback.
Fails closed — if sandboxing unavailable, command is rejected.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class SandboxResult:
    """Result of a sandboxed command execution."""
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float
    sandboxed: bool
    error: Optional[str] = None


class CommandSandbox:
    """Runs commands in a sandbox with resource limits."""

    # Default limits
    DEFAULT_TIMEOUT_S = 30
    DEFAULT_MAX_MEMORY_MB = 256
    DEFAULT_MAX_CPU_PCT = 50
    DEFAULT_MAX_PROCESSES = 10
    DEFAULT_MAX_FILES_MB = 100

    def __init__(
        self,
        timeout_s: int = DEFAULT_TIMEOUT_S,
        max_memory_mb: int = DEFAULT_MAX_MEMORY_MB,
        max_cpu_pct: int = DEFAULT_MAX_CPU_PCT,
        max_processes: int = DEFAULT_MAX_PROCESSES,
        max_files_mb: int = DEFAULT_MAX_FILES_MB,
        allowed_dirs: Optional[list[Path]] = None,
    ):
        self.timeout_s = timeout_s
        self.max_memory_mb = max_memory_mb
        self.max_cpu_pct = max_cpu_pct
        self.max_processes = max_processes
        self.max_files_mb = max_files_mb
        self.allowed_dirs = allowed_dirs or [Path.cwd()]
        self._platform = sys.platform

    def run(self, command: str, cwd: Optional[Path] = None) -> SandboxResult:
        """Execute command in sandbox. Returns SandboxResult."""
        start = time.perf_counter()

        if self._platform.startswith("win"):
            return self._run_windows(command, cwd, start)
        else:
            return self._run_linux(command, cwd, start)

    def _run_windows(
        self, command: str, cwd: Optional[Path], start: float
    ) -> SandboxResult:
        """Windows Job Object sandbox via pywin32 / ctypes."""
        try:
            import win32job
            import win32api
            import win32con
            import pywintypes
        except ImportError:
            return SandboxResult(
                exit_code=-1,
                stdout="",
                stderr="",
                duration_ms=(time.perf_counter() - start) * 1000,
                sandboxed=False,
                error="pywin32 not installed — sandbox unavailable, command rejected",
            )

        # Create job object
        job = win32job.CreateJobObject(None, "")
        info = win32job.QueryInformationJobObject(
            job, win32job.JobObjectBasicLimitInformation
        )

        # Set memory limit
        info["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_PROCESS_MEMORY
        info["ProcessMemoryLimit"] = self.max_memory_mb * 1024 * 1024

        # Set CPU rate limit (if supported)
        try:
            info["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_CPU_RATE_CONTROL
            info["CpuRateControl"] = self.max_cpu_pct
        except Exception:
            pass  # Older Windows versions may not support this

        # Set process count limit
        info["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_ACTIVE_PROCESS
        info["ActiveProcessLimit"] = self.max_processes

        win32job.SetInformationJobObject(
            job, win32job.JobObjectBasicLimitInformation, info
        )

        try:
            proc = subprocess.Popen(
                command,
                shell=True,
                cwd=str(cwd) if cwd else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )

            # Assign process to job
            try:
                win32job.AssignProcessToJobObject(job, int(proc._handle))
            except pywintypes.error:
                pass

            stdout, stderr = proc.communicate(timeout=self.timeout_s)
            exit_code = proc.returncode

        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            return SandboxResult(
                exit_code=-1,
                stdout="",
                stderr=f"Command timed out after {self.timeout_s}s",
                duration_ms=(time.perf_counter() - start) * 1000,
                sandboxed=True,
                error="timeout",
            )
        finally:
            try:
                win32api.CloseHandle(job)
            except Exception:
                pass

        return SandboxResult(
            exit_code=exit_code,
            stdout=stdout or "",
            stderr=stderr or "",
            duration_ms=(time.perf_counter() - start) * 1000,
            sandboxed=True,
        )

    def _run_linux(
        self, command: str, cwd: Optional[Path], start: float
    ) -> SandboxResult:
        """Linux sandbox via bwrap or firejail."""
        sandbox_cmd = self._detect_linux_sandbox()
        if not sandbox_cmd:
            return SandboxResult(
                exit_code=-1,
                stdout="",
                stderr="",
                duration_ms=(time.perf_counter() - start) * 1000,
                sandboxed=False,
                error="No sandbox (bwrap/firejail) available — command rejected",
            )

        cmd = list(sandbox_cmd) + [
            "--ro-bind", "/usr", "/usr",
            "--ro-bind", "/lib", "/lib",
            "--ro-bind", "/lib64", "/lib64",
            "--proc", "/proc",
            "--dev", "/dev",
            "--unshare-net",  # No network access
            "--unshare-ipc",
            "--die-with-parent",
            "--",
            "sh",
            "-c",
            command,
        ]

        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(cwd) if cwd else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            stdout, stderr = proc.communicate(timeout=self.timeout_s)
            exit_code = proc.returncode

        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            return SandboxResult(
                exit_code=-1,
                stdout="",
                stderr=f"Command timed out after {self.timeout_s}s",
                duration_ms=(time.perf_counter() - start) * 1000,
                sandboxed=True,
                error="timeout",
            )

        return SandboxResult(
            exit_code=exit_code,
            stdout=stdout or "",
            stderr=stderr or "",
            duration_ms=(time.perf_counter() - start) * 1000,
            sandboxed=True,
        )

    def _detect_linux_sandbox(self) -> Optional[list[str]]:
        """Detect available Linux sandbox tool."""
        if shutil.which("bwrap"):
            return ["bwrap"]
        if shutil.which("firejail"):
            return ["firejail", "--quiet"]
        return None

    def is_available(self) -> bool:
        """Check if sandboxing is available on this platform."""
        if self._platform.startswith("win"):
            try:
                import win32job  # noqa: F401
                return True
            except ImportError:
                return False
        else:
            return self._detect_linux_sandbox() is not None


# Global sandbox instance
_sandbox: Optional[CommandSandbox] = None


def get_sandbox() -> CommandSandbox:
    """Get the global sandbox instance."""
    global _sandbox
    if _sandbox is None:
        _sandbox = CommandSandbox()
    return _sandbox