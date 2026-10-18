# Capacity v3 Connection-Pool Optimization Experiment

Status: **CANDIDATE**

Protocol version: `3.0.0`

## Hypothesis

Capacity v2 repeatedly identified concurrency 96 as the first saturation
candidate while the SQLAlchemy pool reached its default ceiling of 15 total
connections. CPU, memory, PostgreSQL active queries, and HTTP 5xx did not reach
corresponding ceilings. Capacity v3 tests whether increasing only the
evaluation service's SQLAlchemy connection-pool capacity reduces queueing.

This is a hypothesis, not a proven root cause. The experiment must reject the
hypothesis if throughput, P95 latency, or reliability do not improve across
repeated runs.

## Single controlled change

| Setting | Frozen v2 | Candidate v3 |
| --- | ---: | ---: |
| SQLAlchemy `pool_size` | 5 | 20 |
| SQLAlchemy `max_overflow` | 10 | 20 |
| Pool timeout | 30 s | 30 s |
| Uvicorn workers | 1 | 1 |
| Image stub latency | 250 ms | 250 ms |
| PostgreSQL | Real local service | Real local service |
| Cloud calls | Disabled | Disabled |

Production and frozen v1/v2 retain their existing defaults. Only the isolated
`capacity-v3-api` service receives the larger pool settings.

## Modes

- `pilot`: concurrency 64 and 96, with 64 warm-ups and 1,000 measured requests
  per tier. This is the step-8 directional check.
- `full`: concurrency 64, 96, 128, 192, and 256 with the same per-tier counts.
  This is reserved for step 9 after a successful pilot.

Both modes use one verification-read retry only. Measured generation POSTs are
never retried. A formal request failure safely stops later tiers.

## Run the pilot

```bash
docker compose --profile capacity-v3 up -d --build --wait capacity-v3-api

.venv/bin/python -m evals.run_capacity_v3 \
  --mode pilot \
  --validate-only

.venv/bin/python -m evals.run_capacity_v3 \
  --mode pilot \
  --fail-on-gate
```

## Decision rule

Proceed to the full phase only when the pilot completes both tiers with 100%
API and database success and shows directionally better concurrency-96
throughput or P95 latency than the frozen v2 primary run. One pilot is not
enough to claim durable improvement; step 9 requires repeated full validation.

## Limits

This local, network-free experiment cannot establish production capacity or
cloud-provider behavior. A larger database pool may shift pressure to
PostgreSQL and can be harmful in multi-worker deployments, where total possible
connections multiply by worker count.
