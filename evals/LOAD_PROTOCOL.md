# Deterministic Load Evaluation Protocol

Status: **CANDIDATE — MANUAL REVIEW REQUIRED**

Protocol version: `1.0.0`

## Candidate identity

- Review date: `2026-10-17`
- Machine-readable manifest: `evals/load_protocol_v1.json`
- Runner: `python -m evals.run_load`
- Dedicated application: `evals.load_app:app`
- Docker Compose profile/service: `evaluation` / `load-api`
- Freeze tag: pending a clean, accepted reproduction run

The manifest is the machine-readable source of truth for the candidate. The
runner rejects parameter, safety, acceptance-gate, or deterministic-latency
drift. Exploratory runs must use `--allow-protocol-deviation`; their config is
explicitly marked non-compliant and they cannot be used as frozen v1 evidence.

## Purpose

This protocol measures the FastAPI orchestration and real PostgreSQL path under
controlled concurrency while replacing OpenAI and S3 with deterministic,
network-free stubs. It answers whether the local workflow remains correct and
how its throughput and POST latency scale from concurrency 1 through 16.

It does **not** measure OpenAI or S3 capacity, production network latency,
multi-worker scaling, maximum system capacity, or a production SLO.

## Locked environment and workload

- one Uvicorn worker;
- one `load-api` container connected to the real local PostgreSQL service;
- OpenAI, S3, and Langfuse network activity disabled;
- text-to-image requests at 1024 by 1024;
- deterministic delays: storage `0 ms`, unused vision `50 ms`, image generation
  `250 ms`;
- concurrency tiers `1, 4, 8, 16` in ascending order;
- five warm-up requests followed by 40 measured requests per tier;
- 30-second HTTP timeout; and
- unique run IDs so database verification only counts records from the current
  run.

The planned clean run therefore contains 20 warm-up records and 160 measured
records, for 180 completed PostgreSQL records in total.

## Measurement method

For each tier the runner first completes its warm-up batch. It then starts the
40 measured POST requests under an asyncio semaphore and records the time from
request start until the API response is received. Database readback happens
after the POST batch and is excluded from both POST latency and throughput.

The report includes request success, PostgreSQL consistency, throughput in
requests per second, nearest-rank P50/P95 latency, speedup relative to
concurrency 1, scaling efficiency, and maximum observed in-flight requests.
The protocol deliberately has no fixed RPS or latency pass threshold: v1 is a
reproducible baseline, not a production capacity promise.

## Acceptance gates

A protocol-compliant run passes only when:

1. the health, database, and isolated-load preflight checks pass;
2. all 20 warm-ups complete;
3. all 160 measured requests execute and complete;
4. there are no HTTP 5xx responses;
5. API readback proves all 180 run-scoped records exist in PostgreSQL as
   `completed` with an output reference;
6. no run-scoped record remains `pending`;
7. deterministic stub call counts exactly match the workload;
8. no cloud calls occur;
9. no tier stops early; and
10. the aggregate `overall` gate is true.

## Privacy and cost

The runner uses synthetic run-scoped prompts. Evidence contains request IDs,
generation IDs, status, bounded latency, concurrency, and aggregate stub call
counts. It does not retain prompts, presigned URLs, object keys, credentials,
or image bytes. Because all paid providers are replaced by local stubs, the
expected model and storage cost is `$0.00`.

## Candidate reproduction

Build and start the dedicated service from a committed, clean worktree:

```bash
docker compose --profile evaluation up -d --build load-api

.venv/bin/python -m evals.run_load --validate-only

.venv/bin/python -m evals.run_load \
  --concurrencies 1,4,8,16 \
  --requests-per-tier 40 \
  --warmup-requests 5 \
  --timeout-seconds 30 \
  --fail-on-gate
```

Inspect the newest result without exposing request payloads:

```bash
RESULT_DIR=$(find evals/results -mindepth 1 -maxdepth 1 -type d \
  -name '*_load_v1' | sort | tail -1)

jq '{
  protocol_version,
  protocol_status,
  protocol_compliant,
  git_commit,
  git_worktree_dirty,
  concurrencies,
  requests_per_tier,
  warmup_requests_per_tier,
  stub_delays_ms
}' "$RESULT_DIR/config.json"

jq '{
  measured_count,
  warmup_count,
  cloud_calls,
  cost_usd,
  tiers,
  database,
  errors,
  acceptance_gates
}' "$RESULT_DIR/summary.json"
```

Before freezing, manually confirm that `protocol_compliant` is `true`,
`git_worktree_dirty` is `false`, the count is 160 measured plus 20 warm-up,
all 180 records are completed, cost is zero, and `acceptance_gates.overall` is
`true`. Only then should aggregate evidence be tracked and its digest, baseline
commit, and Git tag be added to the manifest.

## Exploratory capacity runs

Higher concurrency is a separate experiment and must not replace frozen v1
evidence. For example:

```bash
.venv/bin/python -m evals.run_load \
  --concurrencies 1,4,8,16,32,64 \
  --requests-per-tier 40 \
  --warmup-requests 5 \
  --timeout-seconds 30 \
  --allow-protocol-deviation
```

Such a run should also collect container CPU and memory plus PostgreSQL active
connections before making any capacity or bottleneck claim.
