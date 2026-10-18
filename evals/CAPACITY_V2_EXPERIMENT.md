# Frozen Capacity v2 Breakpoint Evaluation Protocol

Status: **FROZEN**

Protocol version: `2.0.0`

## Frozen identity

- Frozen on: `2026-10-17`
- Canonical Git tag: `capacity-eval-v2.0.0`
- Measured implementation baseline: `24b087bf3bb3443ee98daf46328d560cb004efb7`
- Machine-readable manifest: `evals/capacity_protocol_v2.json`
- Privacy-safe aggregate evidence: `evals/evidence/capacity_v2_summary.json`
- Primary source result: `evals/results/20261018T011246Z_capacity_v2`
- Comparison report: `evals/CAPACITY_V1_V2_COMPARISON.md`

The tag is the canonical frozen source snapshot. The measured implementation
baseline identifies the exact clean commit used by the primary result; the
freeze commit adds only tracked evidence, documentation, identity checks, and
frozen metadata.

The primary run intentionally has an aggregate correctness gate of `false`:
the protocol safely stopped after two formal POST transport failures at
concurrency 96. Freeze success means the experiment produced a valid baseline
and reproducible breakpoint, not that all planned tiers passed.

## Purpose

Capacity v2 searches for a local scaling knee beyond the frozen v1 range. It
starts at the previously tested concurrency-64 boundary and continues through
96, 128, 192, and 256 while collecting denser resource samples. It has its own
manifest, application, Compose service, port, runner, and result suffix, so it
cannot overwrite frozen Capacity v1 evidence.

## Locked workload

- concurrency tiers: `64, 96, 128, 192, 256`;
- 64 warm-up and 1,000 measured requests per tier;
- one Uvicorn worker;
- real PostgreSQL with `application_name=capacity-v2-api`;
- one retry for verification-read transport failures only; measured POSTs are
  never retried;
- final database validation uses a run-scoped, privacy-safe query instead of a
  historical full-table scan;
- deterministic 250 ms image-provider stub;
- OpenAI, S3, and Langfuse disabled;
- 50 ms resource-sampling interval;
- 30-second per-request timeout; and
- `$0.00` expected cloud cost.

The complete experiment contains 320 warm-up and 5,000 measured records. A
tier failure stops subsequent tiers so local overload remains bounded.

## Scaling and saturation analysis

Concurrency 64 is the v2 baseline. For each later tier, the scorer calculates:

- throughput and nearest-rank P50/P95 latency;
- speedup and efficiency relative to the concurrency-64 baseline;
- marginal throughput gain;
- marginal concurrency gain; and
- marginal scaling efficiency: throughput gain divided by concurrency gain.

The first tier becomes a saturation candidate when at least one condition is
observed:

1. marginal scaling efficiency falls below 50%;
2. P95 latency grows by more than 50% from the preceding tier;
3. total scaling efficiency versus the baseline falls below 50%; or
4. a request fails.

These are diagnostic signals rather than pass/fail correctness gates. A
candidate identifies where further investigation should begin; it is not, by
itself, a production capacity rating.

## Build and preflight

```bash
docker compose --profile capacity-v2 up -d --build --wait capacity-v2-api

.venv/bin/python -m evals.run_capacity_v2 --validate-only
```

## Run

```bash
.venv/bin/python -m evals.run_capacity_v2 \
  --concurrencies 64,96,128,192,256 \
  --requests-per-tier 1000 \
  --warmup-requests 64 \
  --timeout-seconds 30 \
  --sample-interval-seconds 0.05 \
  --fail-on-gate
```

Raw results remain ignored under `evals/results/`. The reviewed, privacy-safe
aggregate is tracked at `evals/evidence/capacity_v2_summary.json`.

Capacity v2 does not replace Capacity v1 evidence. Capacity v1 establishes the
passing lower bound through 64; Capacity v2 locates the first saturation
candidate above that boundary.

## Interpretation limits

This experiment measures one local FastAPI worker, Docker Desktop, real local
PostgreSQL, and deterministic provider stubs. It does not measure OpenAI, S3,
production networking, multi-worker scaling, multi-host capacity, availability,
or an SLO. Host load and resource-sampling overhead may affect repeated runs.
