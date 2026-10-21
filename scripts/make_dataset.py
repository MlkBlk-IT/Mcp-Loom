"""Build a synthetic dataset for the Loom benchmark.

Rules set by the owner:
  * prompts are OURS (written here, varied, randomized with a fixed seed)
  * NO tool calling — the content is plain assistant prose / code / config / logs
  * three size classes: small / medium / large

Why synthetic instead of the machine's real logs: a benchmark must be reproducible
and shareable. Real logs contain secrets, machine-specific paths, and (as we found)
sparse NUL padding that makes the numbers meaningless.

Every sample is a plausible "context payload" an agent would want to externalize:
a code review, a config dump, an incident report, a doc, a session transcript.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

SEED = 20261021
OUT = Path(__file__).resolve().parents[1] / "dataset"

# --- prompt pool: OUR prompts, no tool calling ------------------------------

PROMPTS = {
    "code_review": [
        "Review the Python module below and flag correctness issues, API misuse, and race conditions.",
        "Audit this async code for resource leaks and cancellation bugs. Be concrete.",
        "Find the security flaws in this handler. Ignore style.",
        "Explain what breaks if I change the retry policy to exponential backoff.",
    ],
    "config": [
        "Summarize this deployment configuration and flag the values that differ from staging.",
        "Rewrite this YAML manifest so it is valid for Kubernetes 1.29.",
        "Which settings in this config would break a cold start on a 2-core machine?",
    ],
    "incident": [
        "Write the incident timeline from these raw service logs.",
        "Diagnose the root cause of this repeated timeout and propose a fix.",
        "Turn these alerts into a customer-facing status update.",
    ],
    "doc": [
        "Document the public API of this package for the README.",
        "Write an onboarding guide for new contributors to this repository.",
        "Summarize this design doc for the engineering all-hands.",
    ],
    "analysis": [
        "Compare these three approaches and recommend one, with trade-offs.",
        "What are the hidden costs of this architecture at 10x scale?",
        "Break down this dataset's characteristics and its implications for modeling.",
    ],
    "session": [
        "Continue this conversation from where it left off, keeping the tone.",
        "Summarize the decisions made in this thread and list the open questions.",
        "Rewrite this exchange more concisely without losing any commitment.",
    ],
    "migration": [
        "Write the step-by-step migration plan from v2 to v3 of this schema.",
        "Give me the rollback procedure for this database migration.",
        "List every breaking change between these two API versions.",
    ],
}

# --- building blocks ---------------------------------------------------------

CODE_TEMPLATES = [
    '''class {name}Client:
    """{doc}"""

    def __init__(self, base_url: str = "{base_url}", timeout: float = {timeout}) -> None:
        self._base_url = base_url
        self._timeout = timeout
        self._session = httpx.Client(timeout=timeout)

    async def fetch_{verb}(self, {arg}: str) -> dict:
        url = f"{{self._base_url}}/{path}/{arg}"
        for attempt in range({retries}):
            try:
                resp = await self._session.get(url)
                resp.raise_for_status()
                return resp.json()
            except httpx.TimeoutException:
                if attempt == {retries} - 1:
                    raise
                await asyncio.sleep(0.{delay} * (2 ** attempt))
        raise RuntimeError("unreachable")

    def close(self) -> None:
        self._session.close()
''',
    '''def process_{name}(records: list[dict], *, batch_size: int = {batch}) -> Iterator[dict]:
    """{doc}"""
    buffer: list[dict] = []
    for record in records:
        if record.get("status") not in {statuses}:
            continue
        buffer.append(record)
        if len(buffer) >= batch_size:
            yield from _flush(buffer)
            buffer = []
    if buffer:
        yield from _flush(buffer)
''',
    '''export async function {name}Route(req: Request, res: Response) {{
  const limit = {limit};
  const cursor = req.query.get("cursor") ?? null;
  const rows = await db.query(
    "SELECT id, payload FROM items WHERE tenant = $1 ORDER BY id LIMIT $2",
    [req.user.tenantId, limit],
  );
  return res.json({{ data: rows, nextCursor: rows.at(-1)?.id ?? null }});
}}
''',
    '''def _validate_{name}(payload: Mapping[str, Any]) -> None:
    errors: list[str] = []
    if "{required}" not in payload:
        errors.append("missing required field '{required}'")
    value = payload.get("{field}")
    if value is not None and not isinstance(value, {vtype}):
        errors.append(f"expected {vtype}, got {{type(value).__name__}}")
    if len(errors) > {maxerr}:
        raise ValidationError("; ".join(errors[:{maxerr}]))
''',
]

CONFIG_TEMPLATES = [
    """# generated by config-gen v{ver}
service:
  name: {svc}
  replicas: {replicas}
  port: {port}
  resources:
    limits:
      cpu: "{cpu}m"
      memory: {mem}Mi
    requests:
      cpu: "{reqcpu}m"
      memory: {reqmem}Mi
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: {surge}
      maxUnavailable: {unavail}
  env:
    LOG_LEVEL: {loglevel}
    DATABASE_URL: postgres://{svc}:${{DB_PASSWORD}}@db-{port}.internal:5432/{svc}
    FEATURE_FLAGS: "beta_{feat}=on,legacy_{feat}=off"
  probes:
    liveness:
      httpGet: {{path: /healthz, port: {port}}}
      initialDelaySeconds: {delay}
      periodSeconds: {period}
    readiness:
      httpGet: {{path: /ready, port: {port}}}
      periodSeconds: {period}
""",
    """[server]
host = {host}
port = {port}
workers = {replicas}
graceful_shutdown_timeout = {timeout}s
max_request_size = {maxreq}

[database]
url = postgres://{svc}@localhost:5432/{svc}
pool_size = {pool}
pool_timeout = {timeout}
statement_timeout = {stmt}ms
sslmode = require

[cache]
backend = redis
addr = {host}:6379
ttl = {ttl}s
maxmemory = {mem}mb

[logging]
level = {loglevel}
format = json
sample_rate = {sample}
""",
]

LOG_TEMPLATES = [
    """{ts} INFO  [{reqid}] {svc}.handler received request method={method} path={path} trace={trace}
{ts} DEBUG [{reqid}] cache lookup key={key} hit={hit} latency={lat}ms
{ts} INFO  [{reqid}] {svc}.db query took {lat}ms rows={rows} sql="SELECT * FROM items WHERE tenant_id = $1 LIMIT $2"
{ts} WARN  [{reqid}] {svc}.pool connection reused after {lat}ms
{ts} ERROR [{reqid}] {svc}.upstream timeout after {timeout}ms upstream=svc-{up}
{ts} INFO  [{reqid}] {svc}.handler completed status={status} duration={lat}ms
""",
    """{ts} [ERROR] com.{pkg}.{cls} - Failed to process {verb}
{ts} [WARN]  com.{pkg}.{cls} - Retry {n} of {retries} for {res}
{ts} [INFO]  com.{pkg}.{cls} - Connection pool exhausted, waiting {lat}ms
{ts} [DEBUG] com.{pkg}.{cls} - Executing statement: SELECT count(*) FROM {tbl} WHERE status = ?
{ts} [ERROR] com.{pkg}.{cls} - java.lang.IllegalStateException: Cannot invoke "String.length()" because "v" is null
\tat com.{pkg}.{cls}.transform({cls}.java:{line})
\tat com.{pkg}.{cls}.process({cls}.java:{line2})
""",
]

DOC_TEMPLATES = [
    """# {title}

## Overview

{title} provides {what}. It is used by {n} internal services and is available on the
internal registry as `{pkg}`.

## Installation

```bash
pip install {pkg}=={ver}
```

## Usage

```python
from {mod} import {cls}

client = {cls}(base_url="{base_url}")
result = client.fetch_{verb}("{arg}")
```

## Configuration

| Option | Default | Description |
|---|---|---|
| `base_url` | `{base_url}` | Service endpoint |
| `timeout` | `{timeout}` | Request timeout in seconds |
| `retries` | `{retries}` | Number of retry attempts |

## Notes

- Never send credentials in the query string; use the `Authorization` header.
- The `port` must be `{port}` in staging and `{port2}` in production.
- Migration from v1 to v2 is **not** reversible; take a snapshot first.
""",
]

INCIDENT_TEMPLATES = [
    """# Incident {id}: {title}

**Severity:** {sev} · **Started:** {ts} · **Resolved:** {ts2} · **Duration:** {dur}

## Summary

Between {ts} and {ts2}, requests to `{svc}` on port `{port}` failed with HTTP {status}.
The on-call engineer was paged after {delay} minutes.

## Impact

- {n} users affected (~{pct}% of traffic)
- {rps} requests per second were rejected
- Estimated revenue impact: ${rev}

## Timeline

| Time | Event |
|---|---|
| {ts} | Alert fired: `HighErrorRate` on `{svc}` |
| {ts} | On-call acknowledged the page |
| {ts} | Root cause identified: {cause} |
| {ts} | Mitigation applied: {mitigation} |
| {ts} | Recovery confirmed, alerts silenced |

## Root cause

{cause}

The deploy at {ts} increased the connection pool from {pool} to {pool2}, which
exceeded the database limit of {maxconn}.

## Action items

- [ ] {act1} (owner: {owner})
- [ ] {act2} (owner: {owner2})
""",
]

TRANSCRIPT_TEMPLATES = [
    """User: {ask}
Assistant: {reply1}
User: {ask2}
Assistant: {reply2}
User: {ask3}
Assistant: {reply3}

[decision] We will use {choice} for the {topic} implementation.
[commitment] The {topic} migration must ship before {deadline}.
[open] Nobody has confirmed whether {topic} works on the legacy path.
""",
]

WORDS = (
    "service handler request response latency timeout error warning retry pool "
    "connection database query migration schema deploy rollback feature flag "
    "latency throughput saturation backpressure circuit breaker idempotency"
).split()

NAMES = ["Invoice", "Order", "User", "Tenant", "Payment", "Shipment", "Catalog", "Session"]
VERBS = ["order", "user", "tenant", "payment", "shipment", "catalog", "session"]


def _rand_words(rng: random.Random, n: int) -> str:
    return " ".join(rng.choice(WORDS) for _ in range(n))


def _fill(template: str, rng: random.Random) -> str:
    """Fill a template with plausible randomized values."""
    subs = {
        "name": rng.choice(NAMES),
        "cls": rng.choice(NAMES),
        "pkg": rng.choice(["core", "billing", "orders", "platform"]),
        "mod": "loom_sdk",
        "svc": rng.choice(["billing-api", "orders-svc", "catalog-api", "gateway"]),
        "doc": _rand_words(rng, 6).capitalize(),
        "base_url": f"https://{rng.choice(['api', 'internal', 'edge'])}.example.com/v{rng.randint(1, 4)}",
        "timeout": rng.choice([5, 10, 15, 30, 60]),
        "retries": rng.randint(2, 5),
        "delay": rng.randint(1, 9),
        "arg": rng.choice(["id", "ref", "uuid", "slug"]),
        "path": rng.choice(["orders", "users", "items"]),
        "batch": rng.choice([50, 100, 500, 1000]),
        "statuses": repr({"ok", "paid", "shipped"}),
        "required": rng.choice(["id", "amount", "currency", "customer_id"]),
        "field": rng.choice(["email", "name", "total", "currency"]),
        "vtype": rng.choice(["str", "int", "dict", "list"]),
        "maxerr": rng.choice([3, 5, 10]),
        "limit": rng.choice([20, 50, 100]),
        "ver": f"{rng.randint(0, 9)}.{rng.randint(0, 20)}.{rng.randint(0, 9)}",
        "replicas": rng.randint(1, 12),
        "port": rng.choice([8000, 8080, 8443, 3000, 5000]),
        "port2": rng.choice([9000, 9090, 7000]),
        "cpu": rng.choice([100, 250, 500, 1000]),
        "reqcpu": rng.choice([50, 100, 250]),
        "mem": rng.choice([256, 512, 1024, 2048]),
        "reqmem": rng.choice([128, 256, 512]),
        "surge": rng.choice([1, 2, 3]),
        "unavail": rng.choice([0, 1, 2]),
        "loglevel": rng.choice(["debug", "info", "warn", "error"]),
        "feat": rng.choice(["search", "checkout", "export"]),
        "delay2": rng.randint(5, 60),
        "period": rng.randint(5, 30),
        "host": rng.choice(["127.0.0.1", "0.0.0.0", "10.0.0.5"]),
        "maxreq": rng.choice(["10M", "50M", "1G"]),
        "pool": rng.choice([5, 10, 20, 50]),
        "stmt": rng.choice([1000, 5000, 30000]),
        "ttl": rng.choice([30, 60, 300, 900]),
        "sample": rng.choice(["0.1", "0.5", "1.0"]),
        "reqid": f"{rng.randint(0x1000, 0xffff):04x}",
        "ts": f"2026-10-{rng.randint(10, 21)}T{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:{rng.randint(0, 59):02d}.{rng.randint(0, 999):03d}Z",
        "method": rng.choice(["GET", "POST", "PUT", "DELETE"]),
        "path2": rng.choice(["/v1/items", "/v2/orders", "/healthz"]),
        "trace": f"{rng.randint(0x100000, 0xffffff):06x}",
        "key": f"cache:{rng.randint(1000, 9999)}",
        "hit": rng.choice(["true", "false"]),
        "lat": rng.randint(1, 900),
        "rows": rng.randint(0, 5000),
        "status": rng.choice([500, 502, 503, 504]),
        "up": rng.randint(1, 5),
        "verb": rng.choice(["create", "update", "delete", "get"]),
        "n": rng.randint(2, 9),
        "tbl": rng.choice(["items", "orders", "sessions", "payments"]),
        "line": rng.randint(40, 400),
        "line2": rng.randint(40, 400),
        "title": rng.choice([
            "Payments service migration", "Order ingestion rewrite", "Tenant isolation",
            "Catalog indexing", "Session store consolidation", "Shipment tracking",
        ]),
        "what": _rand_words(rng, 10),
        "id": f"INC-{rng.randint(1000, 9999)}",
        "sev": rng.choice(["SEV1", "SEV2", "SEV3"]),
        "ts2": f"2026-10-{rng.randint(10, 21)}T{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:00Z",
        "dur": rng.choice(["12 minutes", "45 minutes", "2 hours", "4 hours"]),
        "pct": rng.choice([2, 5, 11, 23, 47]),
        "rps": rng.choice([120, 450, 1200, 3800]),
        "rev": rng.choice([1200, 5400, 23000, 98000]),
        "cause": rng.choice([
            "a connection pool misconfiguration exhausted the database connections",
            "an unbounded retry loop amplified load during a partial outage",
            "a schema migration locked a hot table for longer than the timeout",
        ]),
        "mitigation": rng.choice([
            "rolled back the deploy and raised the pool limit",
            "disabled the feature flag and scaled the service up",
            "terminated the stuck queries and shed load",
        ]),
        "maxconn": rng.choice([50, 100, 200]),
        "pool2": rng.choice([60, 120, 250]),
        "act1": "Add a pool-size alert below 70% saturation",
        "act2": "Add a load test that reproduces the saturation point",
        "owner": rng.choice(["platform", "payments", "sre", "orders"]),
        "owner2": rng.choice(["platform", "payments", "sre", "orders"]),
        "ask": rng.choice([
            "How do I migrate the schema without downtime?",
            "What is the safest order for these two deploys?",
            "Why does the pool exhaust only under load?",
        ]),
        "ask2": rng.choice(["Can we do it in one step?", "What is the rollback?"]),
        "ask3": rng.choice(["And what about the legacy path?", "Who owns that?"]),
        "reply1": _rand_words(rng, 40),
        "reply2": _rand_words(rng, 50),
        "reply3": _rand_words(rng, 35),
        "choice": rng.choice(["a strangler fig", "a blue/green cutover", "an expand-contract migration"]),
        "topic": rng.choice(["billing", "orders", "catalog", "sessions"]),
        "deadline": rng.choice(["2026-11-15", "Q1 2027", "end of the quarter"]),
    }
    out = template
    for k, v in subs.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def build_sample(rng: random.Random, kind: str, target_chars: int) -> str:
    """Build one sample of a given kind, roughly `target_chars` long."""
    pools = {
        "code_review": CODE_TEMPLATES,
        "config": CONFIG_TEMPLATES,
        "incident": INCIDENT_TEMPLATES,
        "doc": DOC_TEMPLATES,
        "analysis": DOC_TEMPLATES,
        "session": TRANSCRIPT_TEMPLATES,
        "migration": INCIDENT_TEMPLATES,
    }
    template = rng.choice(pools[kind])
    parts = [_fill(template, rng)]
    while sum(len(p) for p in parts) < target_chars:
        t = rng.choice(pools[kind])
        parts.append(_fill(t, rng))
        parts.append(f"\n### section {len(parts)}\n\n{_rand_words(rng, rng.randint(40, 220))}\n")
    return "\n".join(parts)


SIZES = [
    ("small", 4_000, 12_000),
    ("medium", 60_000, 180_000),
    ("large", 500_000, 1_200_000),
]


def main() -> None:
    rng = random.Random(SEED)
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = []

    for size_name, lo, hi in SIZES:
        kinds = list(PROMPTS)
        for i, kind in enumerate(kinds):
            target = rng.randint(lo, hi)
            content = build_sample(rng, kind, target)
            name = f"{size_name}_{i:02d}_{kind}.txt"
            path = OUT / name
            path.write_text(content, encoding="utf-8")
            manifest.append(
                {
                    "file": name,
                    "size": size_name,
                    "kind": kind,
                    "prompt": PROMPTS[kind][rng.randrange(len(PROMPTS[kind]))],
                    "chars": len(content),
                    "lines": content.count("\n") + 1,
                }
            )
            print(f"{name:38s} {len(content):>10,} chars  {content.count(chr(10)) + 1:>7,} lines")

    (OUT / "manifest.json").write_text(
        json.dumps({"seed": SEED, "samples": manifest}, indent=2), encoding="utf-8"
    )
    print(f"\n{len(manifest)} samples -> {OUT}")
    print("total chars:", f"{sum(m['chars'] for m in manifest):,}")


if __name__ == "__main__":
    main()
