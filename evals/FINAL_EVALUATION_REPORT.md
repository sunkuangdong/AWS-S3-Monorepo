# Project Evaluation Report

**Date:** 2026-10-18

**Scope:** Workflow Smoke, Live Smoke, Load v1, Capacity v1-v3

This report summarizes the project's measured reliability, performance, and
cost. Reproduction commands and expected outputs are in the
[manual verification guide](MANUAL_VERIFICATION_GUIDE.md).

## Results

| Evaluation | Workload | Result | Performance | Cost |
| --- | --- | --- | --- | ---: |
| Workflow Smoke | 12 deterministic scenarios | 100% expected outcomes and state consistency; 0 orphan outputs | 100.380 ms P95 harness latency | $0 |
| Live Smoke | 4 real PostgreSQL/S3/OpenAI/Langfuse workflows | 4/4 passed; database, S3, trace, privacy, and cost checks all 100% | 32.235 s P50; 72.524 s P95 | $0.1404404 |
| Load v1 | 160 measured requests, c1-c16 | 100% API and database consistency | 42.144 RPS; 346.008 ms P95 at c16 | $0 |
| Capacity v1 | 1,200 measured requests, c1-c64 | 100% through c64 | 165.047 RPS; 511.634 ms P95 at c64 | $0 |
| Capacity v2 | 3 repeated breakpoint runs | c96 was the first repeatable performance knee; failures in 2/3 runs | 70.147 RPS median; 4,352.453 ms median P95 at c96 | $0 |
| Capacity v3 | 3 runs; 11,000 measured requests | c64/c96 100%; failures reproduced at c128 | 80.569 RPS median; 3,375.503 ms median P95 at c96 | $0 |

## Capacity optimization

Capacity v3 changed one variable: the isolated evaluation service's SQLAlchemy
pool increased from `pool_size=5, max_overflow=10` to `20, 20`. Business logic,
worker count, workload, and provider-stub latency were unchanged.

| c96 metric | v2 | v3 | Change |
| --- | ---: | ---: | ---: |
| Fully successful runs | 1/3 | 3/3 | +2 runs |
| Median throughput | 70.147 RPS | 80.569 RPS | +14.9% |
| Median P95 | 4,352.453 ms | 3,375.503 ms | -22.4% |
| First reproduced request-failure tier | c96 | c128 | +32 clients |

The pool change improved c96 reliability and latency but did not remove its
performance knee. The defensible local recommendation is:

- performance-safe tier: **c64**;
- highest repeatedly fully reliable v3 tier: **c96**;
- first repeated performance knee: **c96**;
- first reproduced request-failure tier: **c128**.

## Reliability and cost boundary

- Seven injected provider failures and one post-commit response failure were
  contained without orphan outputs or unexpected pending records.
- The injected database-completion failure reached a consistent terminal state.
- All four live cases completed across the real PostgreSQL, S3, OpenAI, and
  Langfuse chain.
- Measured evaluation model spend was **$0.1404404**, entirely from Live Smoke;
  deterministic Workflow, Load, and Capacity runs made no cloud calls.
- Cost excludes local hardware, PostgreSQL, S3 storage and transfer, and
  unrelated historical API usage.

## Evidence

| Evaluation | Evidence | Frozen tag |
| --- | --- | --- |
| Workflow v1 | [JSON](evidence/workflow_v1_summary.json) | `workflow-eval-v1.0.0` |
| Live v1 | [JSON](evidence/live_smoke_v1_summary.json) | `live-smoke-v1.0.0` |
| Load v1 | [JSON](evidence/load_v1_summary.json) | `load-eval-v1.0.0` |
| Capacity v1 | [JSON](evidence/capacity_v1_summary.json) | `capacity-eval-v1.0.0` |
| Capacity v2 | [JSON](evidence/capacity_v2_summary.json) | `capacity-eval-v2.0.0` |
| Capacity v3 | [JSON](evidence/capacity_v3_validation_summary.json) | `capacity-eval-v3.0.0` |

See [CAPACITY_V2_V3_COMPARISON.md](CAPACITY_V2_V3_COMPARISON.md) for the
controlled comparison. Tracked evidence is privacy-safe; raw result directories
remain untracked.

## Limits

- Load and Capacity use one local Uvicorn worker, real PostgreSQL, and a
  deterministic 250 ms provider stub. Their RPS is not production OpenAI/S3
  capacity or a production SLO.
- Live Smoke has four cases, which verifies integration but cannot establish
  production availability or stable latency percentiles.
- Capacity tests are bursts, not long soak tests; multi-worker, multi-host,
  autoscaling, and connection-aging behavior remain unmeasured.
- Capacity v3 c192 and c256 ran only once and do not support repeatability
  claims.
- The Live Smoke source run recorded a dirty worktree. Its reviewed aggregate
  was privacy-scanned, hashed, and frozen, but exact source-state
  reproducibility remains limited.
