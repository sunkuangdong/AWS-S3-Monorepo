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

## Pilot result

The clean pilot at `20261018T012504Z` passed every acceptance gate with 2,000
measured requests and 128 warm-ups. At concurrency 64, v3 remained close to the
frozen v2 baseline: throughput changed by -2.2% and P95 by +6.8%. At concurrency
96, API and database success reached 100%, throughput improved from 68.018 to
155.791 RPS (+129%), and P95 fell from 4,690.003 to 2,038.004 ms (-56.5%).

The decision rule is satisfied, so v3 may proceed to step-9 full validation.
The 96 tier still had 16.5% less throughput and 213.1% higher P95 than the v3
64 tier. The larger pool is therefore an important contributor, but it does not
eliminate the scaling knee. The tracked pilot aggregate is
`evals/evidence/capacity_v3_pilot_summary.json`.

## Full repeated validation

Step 9 executed three clean full-mode runs from implementation commit
`e02511c91102d7138cc436e8d97c01de90d65b97`. All runs used the same one-worker
service, real PostgreSQL, deterministic provider stubs, and `20 + 20`
SQLAlchemy pool configuration. Across the three runs, 11,000 measured requests
and 704 executed warm-ups incurred no cloud calls and no cost.

Concurrency 64 and 96 completed 3,000/3,000 measured requests with matching
database state. Every run identified 96 as the first performance-saturation
candidate. Relative to the three frozen v2 runs, the concurrency-96 median
throughput increased from 70.147 to 80.569 RPS (+14.9%), median P95 decreased
from 4,352.453 to 3,375.503 ms (-22.4%), and fully successful runs increased
from one of three to three of three.

The optimization did not remove the scaling knee. The pool reached 38--39
checked-out connections and its overflow ceiling of 20 at concurrency 96 in
all three runs. Two runs reproduced formal transport failures at concurrency
128; the other reached concurrency 256 before two such failures. The full-run
correctness gate is therefore intentionally false after safe stopping, just as
an overload-search protocol should preserve failures rather than retry or hide
them.

The evidence supports a repeated correctness lower bound of 96, but 64 remains
the recommended performance-safe tier because P95 still rises sharply at 96.
The reviewed candidate aggregate is
`evals/evidence/capacity_v3_validation_summary.json`. Freezing and tagging this
result are reserved for step 10.

## Limits

This local, network-free experiment cannot establish production capacity or
cloud-provider behavior. A larger database pool may shift pressure to
PostgreSQL and can be harmful in multi-worker deployments, where total possible
connections multiply by worker count.
