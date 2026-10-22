"""Profiles — how aggressive Loom is allowed to be.

strict (default) : move only, never summarize. Zero loss.
balanced         : move + aggressive anchoring, still lossless.
aggressive       : enables lossy summarization — opt-in, always reported.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Profile:
    name: str
    max_anchor_chars: int
    allow_lossy: bool
    keep_invariants: bool
    description: str


PROFILES: dict[str, Profile] = {
    "strict": Profile(
        name="strict",
        max_anchor_chars=6000,
        allow_lossy=False,
        keep_invariants=True,
        description="Move-only. Zero loss. Default.",
    ),
    "balanced": Profile(
        name="balanced",
        max_anchor_chars=3000,
        allow_lossy=False,
        keep_invariants=True,
        description="Move + tighter anchors. Still lossless.",
    ),
    "lean": Profile(
        name="lean",
        max_anchor_chars=1500,
        allow_lossy=False,
        keep_invariants=True,
        description="Move + minimal anchor. Still lossless.",
    ),
    "aggressive": Profile(
        name="aggressive",
        max_anchor_chars=1200,
        allow_lossy=True,
        keep_invariants=True,
        description="May summarize. Lossy — opt-in, reported every time.",
    ),
}

import os

_ACTIVE: Profile = PROFILES[os.environ.get("LOOM_PROFILE", "strict")]


def get_profile() -> Profile:
    return _ACTIVE


def set_profile(mode: str) -> dict:
    global _ACTIVE
    if mode not in PROFILES:
        return {
            "ok": False,
            "error": f"unknown profile {mode!r}. Valid: {sorted(PROFILES)}",
            "active": _ACTIVE.name,
        }
    _ACTIVE = PROFILES[mode]
    return {
        "ok": True,
        "active": _ACTIVE.name,
        "allow_lossy": _ACTIVE.allow_lossy,
        "description": _ACTIVE.description,
    }
