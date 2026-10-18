# Project Evaluation Report

**Report date:** 2026-10-18  
**Scope:** Workflow Smoke, Live Smoke, Load v1, and Capacity v1-v3  
**System under test:** FastAPI image-generation workflow with PostgreSQL state, S3 objects, OpenAI image services, and Langfuse observability

## Executive summary

The evaluation program progressed from deterministic workflow correctness to a
paid live integration check, then to reproducible local load and capacity
experiments. The evidence supports the following bounded conclusions:

- All 12 Workflow Smoke scenarios matched their reviewed expectations. Normal
  paths completed, injected external failures were contained, invalid input was
  rejected, database-completion failure was compensated, and no orphan output
  or unexpected pending record remained.
- All four paid Live Smoke cases completed across PostgreSQL, S3, OpenAI, and
  Langfuse. Database consistency, S3 retrieval, trace completeness, trace
  privacy, and cost measurement were all 100%. Total measured model cost was
  **$0.1404404**, within the **$0.30** cap.
- Load v1 completed 160 measured requests with 100% API success and database
  consistency. At concurrency 16, one local worker reached **42.144 RPS** with
  **346.008 ms P95** latency.
- Capacity v1 completed 1,200 measured requests without failures through
  concurrency 64, reaching **165.047 RPS** with **511.634 ms P95** latency.
- Capacity v2 identified concurrency 96 as the first repeatable performance
  knee and retained concurrency 64 as the performance-safe operating point.
- Capacity v3 increased only SQLAlchemy pool capacity. Across three validation
  runs, concurrency 96 improved from one fully successful v2 run out of three
  to three out of three; median throughput increased **14.9%** and median P95
  fell **22.4%**. The performance knee remained at 96, while reproduced request
  failures moved to concurrency 128.

The defensible local recommendation is therefore **concurrency 64 for
performance-sensitive operation**. Concurrency 96 was repeatedly correct in
v3 but had materially higher tail latency; it is a reliability result, not a
production SLO.

## Evidence boundary

The evaluation layers intentionally answer different questions and their
numbers are not interchangeable.

| Layer | Environment and workload | Primary result | Latency / throughput | Measured model cost |
| --- | --- | --- | --- | --- |
| Workflow Smoke | 12 deterministic offline scenarios, concurrency 4 | 100% scenario expectations and state consistency | 100.380 ms P95; harness latency only | $0 |
| Live Smoke | 4 real PostgreSQL/S3/OpenAI/Langfuse requests | 4/4 end-to-end success; all six quality rates 100% | 32.235 s P50; 72.524 s P95 | $0.1404404 |
| Load v1 | 160 measured requests, real PostgreSQL, deterministic provider stubs, c1-c16 | 100% API success and DB consistency | 42.144 RPS and 346.008 ms P95 at c16 | $0 |
| Capacity v1 | 1,200 measured requests, same local boundary, c1-c64 | 100% through c64; no saturation observed within range | 165.047 RPS and 511.634 ms P95 at c64 | $0 |
| Capacity v2 | 3 breakpoint runs; c64 and c96 repeated | c64 fully reliable; c96 first repeatable performance knee and failures in 2/3 runs | Primary c96: 68.018 RPS, 4,690.003 ms P95, 99.8% success | $0 |
| Capacity v3 | 3 validation runs; 11,000 measured requests | c64/c96 100%; c128 failures in 2/3 runs | c96 median: 80.569 RPS, 3,375.503 ms P95 | $0 |

Primary evidence:

- [Workflow v1 aggregate](evidence/workflow_v1_summary.json)
- [Live Smoke v1 aggregate](evidence/live_smoke_v1_summary.json)
- [Load v1 aggregate](evidence/load_v1_summary.json)
- [Capacity v1 aggregate](evidence/capacity_v1_summary.json)
- [Capacity v2 aggregate](evidence/capacity_v2_summary.json)
- [Capacity v3 validation aggregate](evidence/capacity_v3_validation_summary.json)

## Workflow correctness and failure containment

Workflow Smoke exercised two normal paths, seven externally injected failure
paths, one post-commit response failure, one database-completion failure, and
one validation rejection. A raw completion ratio would be misleading because
most cases were designed to fail at a controlled boundary. The harness instead
checked each scenario against its expected outcome and terminal state.

All acceptance gates passed:

- scenario expectation rate: 100%;
- normal-path task success: 100%;
- external-failure containment: 100%;
- validation rejection: 100%;
- database-failure recovery: 100%;
- terminal-state consistency: 100%;
- orphan outputs: 0;
- unexpected pending records: 0.

The post-commit response-failure case deliberately returned a request failure
after the completed state had already committed. The database correctly
retained the completed record, demonstrating that response delivery failure
does not roll back an already durable result.

This result is governed by [EVALUATION_PROTOCOL.md](EVALUATION_PROTOCOL.md) and
the `workflow-eval-v1.0.0` Git tag. The tracked Workflow aggregate was produced
retrospectively from the clean frozen-tag run and does not change the frozen
dataset, protocol, manifest, source result, or tag.

## Live integration, privacy, and cost

Live Smoke executed two text-to-image and two image-to-image cases against the
real integration chain. All four cases produced distinct database generations
and Langfuse traces, and all generated S3 outputs were retrievable.

| Generation type | Cases | Mean latency | Total cost | Mean cost per case |
| --- | ---: | ---: | ---: | ---: |
| Text-to-image | 2 | 27.722 s | $0.0119750 | $0.0059875 |
| Image-to-image | 2 | 65.886 s | $0.1284654 | $0.0642327 |
| **All live cases** | **4** | **46.804 s** | **$0.1404404** | **$0.0351101** |

The run consumed 46.8% of its $0.30 safety cap. Langfuse cost was measured for
every case, while trace input and output remained absent. The tracked aggregate
also omits prompts, image descriptions, object keys, presigned URLs,
credentials, image bytes, and operational identifiers.

This is an integration smoke, not an availability or capacity test. Four
requests are enough to verify the chain and cost instrumentation, but not to
estimate a production success rate or latency SLO. The live source run also
recorded a dirty worktree; its evidence was subsequently reviewed, privacy
scanned, hashed, and frozen at `live-smoke-v1.0.0`, but the dirty-source fact
remains a provenance limitation. See
[LIVE_SMOKE_PROTOCOL.md](LIVE_SMOKE_PROTOCOL.md).

## Deterministic load baseline

Load v1 isolated application and database behavior with one Uvicorn worker,
real PostgreSQL, and fixed network-free provider stubs. It measured 160
requests after 20 warmups.

| Concurrency | Success | Throughput | P95 latency | Scaling efficiency |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 100% | 3.707 RPS | 274.261 ms | 100.0% |
| 4 | 100% | 14.440 RPS | 288.386 ms | 97.4% |
| 8 | 100% | 26.695 RPS | 314.978 ms | 90.0% |
| 16 | 100% | 42.144 RPS | 346.008 ms | 71.1% |

All 180 warmup and measured records were found in PostgreSQL with completed
status. There were no server errors, transport errors, duplicate request IDs,
or duplicate generation IDs. The result freezes a reproducible baseline under
[LOAD_PROTOCOL.md](LOAD_PROTOCOL.md) and `load-eval-v1.0.0`.

## Capacity boundary and optimization

### Capacity v1: establish a lower bound

Capacity v1 expanded the same deterministic setup to concurrency 64. All 1,200
measured requests and 30 warmups completed consistently. Throughput increased
to 165.047 RPS at c64 and no formal saturation signal appeared within the
tested range. This established c64 as a tested local lower bound, not a maximum.

### Capacity v2: locate the first repeatable knee

Capacity v2 increased sample size to 1,000 requests per tier and repeated the
experiment three times. Every run identified c96 as the first performance
saturation candidate. At c96, throughput fell, P95 latency rose into seconds,
and two of the three runs contained request failures. The primary run recorded
99.8% success, 68.018 RPS, 4,690.003 ms P95, and two transport errors. The safe
stop prevented higher tiers from being treated as evidence from that run.

The bounded v1/v2 interpretation is documented in
[CAPACITY_V1_V2_COMPARISON.md](CAPACITY_V1_V2_COMPARISON.md).

### Capacity v3: test one pool-capacity hypothesis

Capacity v3 changed one variable: SQLAlchemy `pool_size` / `max_overflow`
increased from `5/10` to `20/20`. Business logic, one-worker topology, provider
stub latency, workload size, and measured POST retry policy stayed unchanged.

At c96, the larger pool produced the following repeated-median changes:

| Metric | Capacity v2 | Capacity v3 | Change |
| --- | ---: | ---: | ---: |
| Fully successful runs | 1/3 | 3/3 | +2 runs |
| Success rate | 99.9% | 100% | +0.1 pp |
| Throughput | 70.147 RPS | 80.569 RPS | +14.9% |
| P95 latency | 4,352.453 ms | 3,375.503 ms | -22.4% |

The optimization improved c96 reliability and medians but did not remove the
knee. Pool checked-out connections reached 38-39 with overflow reaching 20,
and c96 P95 remained roughly 3.4 seconds. At c128, 2,993 of 3,000 requests
succeeded; seven transport failures occurred across two of three runs.
Therefore:

- recommended performance-safe tier: **c64**;
- highest repeatedly fully reliable v3 tier: **c96**;
- first repeated performance saturation candidate: **c96**;
- first reproduced request-failure tier: **c128**.

The detailed controlled comparison is in
[CAPACITY_V2_V3_COMPARISON.md](CAPACITY_V2_V3_COMPARISON.md).

## Cost summary

The total measured model cost represented by this report is **$0.1404404**, all
from Live Smoke. Workflow Smoke, Load v1, and Capacity v1-v3 intentionally
disabled cloud calls and Langfuse and therefore recorded **$0 model cost**.

This total does not include local hardware, Docker, PostgreSQL, S3 storage,
network transfer, developer time, or unrelated historical API usage. It should
be described as measured evaluation model spend, not total cost of ownership.

## Failure boundaries

| Boundary | Evidence | Defensible interpretation |
| --- | --- | --- |
| Workflow/provider failure | 7 injected external failures and 1 post-commit response failure contained; no orphan output or pending record | Compensation and terminal-state invariants worked for the reviewed failure matrix |
| Database completion failure | Injected case recovered with a consistent terminal state | Recovery logic passed one deterministic scenario; not a database-availability benchmark |
| Real integration | 4/4 live cases passed | The end-to-end chain and privacy-safe cost tracing worked in a small smoke sample |
| Local load through c16 | 160/160 measured requests succeeded | One worker and PostgreSQL handled the frozen deterministic load profile |
| Local capacity through c64 | Repeatedly 100% successful | c64 is the recommended performance-safe tested tier |
| Performance saturation | c96 identified in all v2 and v3 validation runs | Tail latency and throughput degradation begin before correctness necessarily fails |
| Request failure | v3 c128 failed in 2/3 runs | c128 is the first reproduced failure tier under the v3 local setup |

## Reproducibility and provenance

| Evaluation | Frozen Git tag | Tracked aggregate |
| --- | --- | --- |
| Workflow Smoke v1 | `workflow-eval-v1.0.0` | [workflow_v1_summary.json](evidence/workflow_v1_summary.json) |
| Live Smoke v1 | `live-smoke-v1.0.0` | [live_smoke_v1_summary.json](evidence/live_smoke_v1_summary.json) |
| Load v1 | `load-eval-v1.0.0` | [load_v1_summary.json](evidence/load_v1_summary.json) |
| Capacity v1 | `capacity-eval-v1.0.0` | [capacity_v1_summary.json](evidence/capacity_v1_summary.json) |
| Capacity v2 | `capacity-eval-v2.0.0` | [capacity_v2_summary.json](evidence/capacity_v2_summary.json) |
| Capacity v3 | `capacity-eval-v3.0.0` | [capacity_v3_validation_summary.json](evidence/capacity_v3_validation_summary.json) |

Tracked aggregates are privacy-safe and raw results remain untracked. The
capacity artifacts omit prompts, request and generation IDs, object keys,
presigned URLs, credentials, image bytes, and host identifiers.

## Limitations

- Load and capacity figures come from local Docker, one Uvicorn worker, real
  PostgreSQL, and deterministic 250 ms image-provider stubs. They do not
  measure OpenAI or S3 capacity and must not be presented as production RPS.
- The live sample contains only four requests and cannot establish production
  availability, percentile stability, or an SLO.
- Capacity experiments are burst tests, not long-duration soak tests; they do
  not measure memory leaks, connection aging, autoscaling, or multi-host
  behavior.
- Capacity v3 c192 and c256 each ran only once, so neither supports a repeated
  reliability claim.
- P95 uses nearest-rank percentiles and is sensitive to sample size and local
  machine scheduling.
- The live evidence's dirty source worktree limits exact source-state
  reproducibility even though the reviewed aggregate and protocol were frozen.

## Conclusion

The project now has evidence for workflow compensation, real service
integration, privacy-safe cost tracing, deterministic load scaling, capacity
breakpoint discovery, and single-variable optimization validation. The
strongest engineering result is not a raw maximum-RPS claim: it is the measured
movement of the repeated request-failure boundary from c96 in v2 to c128 in v3,
while retaining c64 as the performance-safe recommendation and transparently
reporting the remaining c96 tail-latency knee.
