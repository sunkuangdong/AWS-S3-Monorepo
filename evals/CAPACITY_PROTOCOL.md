# Frozen Exploratory Capacity Evaluation Protocol

Status: **FROZEN**

Protocol version: `1.0.0`

## Frozen identity

- Frozen on: `2026-10-17`
- Canonical Git tag: `capacity-eval-v1.0.0`
- Passing implementation baseline: `28edd96acf4848e349f3d4d5d1eccc15218ff7c7`
- Machine-readable manifest: `evals/capacity_protocol_v1.json`
- Privacy-safe aggregate evidence: `evals/evidence/capacity_v1_summary.json`
- Source result: `evals/results/20261018T004025Z_capacity_v1`
- Runner: `python -m evals.run_capacity`
- Dedicated application: `evals.capacity_app:app`
- Docker Compose profile/service: `capacity` / `capacity-api`

The tag is the canonical source snapshot and the manifest is the
machine-readable source of truth. The runner rejects parameter, safety,
acceptance-gate, resource-sampling, or deterministic-latency drift. Changes to
the workload, environment, metrics, heuristics, or gates require a new protocol
version and tag.

## Purpose and frozen claim

This protocol extends frozen Load v1 through concurrency 64 while collecting
API-container CPU and memory plus PostgreSQL connection and SQLAlchemy pool
activity. The frozen evidence establishes a tested local lower bound of 64
concurrent clients and an observed 165.047 requests per second with 100% API
success and database consistency. It does not claim that 64 clients or 165.047
requests per second is the maximum capacity.

## Locked environment and workload

- one Uvicorn worker;
- one `capacity-api` container connected to the real local PostgreSQL service;
- OpenAI, S3, and Langfuse network activity disabled;
- text-to-image requests at 1024 by 1024;
- deterministic delays: storage `0 ms`, unused vision `50 ms`, image generation
  `250 ms`;
- concurrency tiers `1, 4, 8, 16, 32, 64` in ascending order;
- five warm-up requests followed by 200 measured requests per tier;
- 30-second HTTP timeout;
- 100 ms resource-sampling interval; and
- unique run IDs so database verification only counts current-run records.

The compliant run contains 30 warm-up records and 1,200 measured records, for
1,230 completed PostgreSQL records in total.

## Measurement method

Each tier completes its warm-up batch before the measured POST batch. The
runner records request latency and throughput only for
`POST /api/v1/images/generations`; database readback is performed afterward and
excluded. During the measured window, a separate client samples cgroup v2 CPU
and memory counters plus PostgreSQL and SQLAlchemy pool activity every 100 ms.

The report uses nearest-rank P50/P95 latency and calculates speedup and scaling
efficiency relative to concurrency 1. Resource sampling has bounded observer
overhead. Short PostgreSQL operations may occur between samples, especially at
high tiers with short elapsed times.

## Saturation heuristics

The first tier is marked as a candidate when at least one condition occurs:

1. marginal throughput gain is below 20%;
2. P95 latency grows by more than 50%;
3. scaling efficiency falls below 50%; or
4. a request fails.

These signals require interpretation and are not correctness acceptance gates.
The frozen run observed no candidate through concurrency 64. At concurrency 64,
P95 growth from the preceding tier was 49.4%, just below the configured signal.

## Acceptance gates

A protocol-compliant run passes only when:

1. health, database, isolated-capacity, and resource preflight checks pass;
2. all 30 warm-ups and 1,200 measured requests execute and complete;
3. no HTTP 5xx or transport errors occur;
4. API readback proves all 1,230 run-scoped PostgreSQL records are complete;
5. no run-scoped record remains pending;
6. deterministic stub calls exactly match the workload;
7. no cloud calls occur and the run is not stopped early;
8. every tier has usable CPU and memory samples;
9. resource monitoring reports no errors; and
10. the aggregate `overall` gate is true.

## Privacy and cost

The runner uses synthetic run-scoped prompts. Tracked evidence excludes prompts,
request IDs, generation IDs, object keys, presigned URLs, credentials, image
bytes, and host identifiers. Because paid providers are replaced by local
stubs, expected and measured cloud cost is `$0.00`.

## Reproduction

Build and start the dedicated service from a committed, clean worktree:

```bash
docker compose --profile capacity up -d --build --wait capacity-api

.venv/bin/python -m evals.run_capacity --validate-only

.venv/bin/python -m evals.run_capacity \
  --concurrencies 1,4,8,16,32,64 \
  --requests-per-tier 200 \
  --warmup-requests 5 \
  --timeout-seconds 30 \
  --sample-interval-seconds 0.1 \
  --fail-on-gate
```

A conforming reproduction must record a clean worktree, 1,200 measured and 30
warm-up requests, all 1,230 database records as completed, resource measurements
for every tier, no monitoring errors, zero cloud calls, zero cloud cost, and an
aggregate passing gate.

## Interpretation limits

This protocol measures one local FastAPI worker, local Docker Desktop, real
PostgreSQL, and deterministic provider stubs. It cannot establish OpenAI or S3
capacity, production network latency, multi-worker or multi-host scaling,
production availability, maximum system capacity, or an SLO. Higher concurrency
must use a separately versioned experiment and cannot replace this evidence.
