# Exploratory Capacity Experiment

Status: **EXPLORATORY**

Protocol version: `1.0.0`

## Purpose

This experiment extends the frozen Load v1 baseline through concurrency 32 and
64 while collecting API-container CPU and memory plus PostgreSQL connection and
SQLAlchemy pool activity. It is deliberately separate from frozen Load v1 and
must not overwrite its manifest, evidence, tag, or claims.

## Locked experiment parameters

- concurrency tiers: `1, 4, 8, 16, 32, 64`;
- 5 warm-up and 200 measured requests per tier;
- one Uvicorn worker;
- real PostgreSQL with `application_name=capacity-api`;
- deterministic 250 ms image provider stub;
- OpenAI, S3, and Langfuse disabled;
- 100 ms resource sampling interval; and
- `$0.00` expected cloud cost.

The API resource sampler reads cgroup v2 counters from inside the dedicated
container. PostgreSQL samples count only connections labeled `capacity-api` and
exclude the sampler's own backend. Sampling is bounded but creates observer
overhead, so small differences should not be overinterpreted.

## Saturation signals

The report marks the first tier where at least one heuristic occurs:

1. marginal throughput gain is below 20%;
2. P95 latency grows by more than 50%;
3. scaling efficiency falls below 50%; or
4. a request fails.

These are analysis signals, not pass/fail gates. Correctness, isolation,
database consistency, and resource-metric collection remain acceptance gates.

## Build and preflight

```bash
docker compose --profile capacity up -d --build --wait capacity-api

.venv/bin/python -m evals.run_capacity --validate-only
```

## Run

```bash
.venv/bin/python -m evals.run_capacity \
  --concurrencies 1,4,8,16,32,64 \
  --requests-per-tier 200 \
  --warmup-requests 5 \
  --timeout-seconds 30 \
  --sample-interval-seconds 0.1 \
  --fail-on-gate
```

The experiment should take roughly one to two minutes on the original local
environment. Raw results remain ignored under `evals/results/`.

## Interpretation limits

This experiment measures a single local FastAPI worker, local Docker Desktop,
real PostgreSQL, and deterministic provider stubs. It cannot establish real
OpenAI/S3 throughput, multi-host capacity, production availability, or an SLO.
Any resume claim must state the tested concurrency, synthetic provider latency,
single-worker scope, and observed rather than theoretical throughput.
