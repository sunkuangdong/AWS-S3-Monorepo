# Offline workflow evaluation

The evaluation harness executes the real `ImageService` orchestration against deterministic in-memory implementations of PostgreSQL, S3, OpenAI Vision, and OpenAI Images. It produces reproducible workflow and failure-compensation evidence without cloud calls or fees.

The consolidated results, cost boundary, failure boundary, provenance, and
limitations across Workflow Smoke, Live Smoke, Load v1, and Capacity v1-v3 are
published in [`FINAL_EVALUATION_REPORT.md`](FINAL_EVALUATION_REPORT.md). Use
[`MANUAL_VERIFICATION_GUIDE.md`](MANUAL_VERIFICATION_GUIDE.md) to trace each
headline metric to evidence and reproduce the free, offline, capacity, or paid
test layer safely.

Draft [`PRODUCTION_CAPACITY_PROTOCOL.md`](PRODUCTION_CAPACITY_PROTOCOL.md)
defines a separate, explicitly authorized real-dependency capacity runner with
open arrival rates, budget reservation, resource cutoffs, PostgreSQL/S3 state
checks, Langfuse cost verification, and privacy-safe evidence. It must not be
confused with the frozen local Stub capacity results.

Protocol `1.0.0` is frozen at Git tag `workflow-eval-v1.0.0`. Its tracked manifest locks the 12 reviewed cases and dataset SHA-256. Changes to labels or gates require a new protocol version.

## Run

From the repository root:

```bash
.venv/bin/python -m evals.validation

.venv/bin/python -m evals.run_workflow \
  --dataset evals/datasets/workflow_smoke_v1.jsonl \
  --concurrency 4
```

The second command prints a directory under `evals/results/`. Inspect the concise fields with:

```bash
RESULT_DIR=$(find evals/results -mindepth 1 -maxdepth 1 -type d \
  -name '*_workflow_smoke_v1' | sort | tail -1)

jq '{
  run_count,
  cloud_calls,
  score,
  concurrency,
  acceptance_gates
}' "$RESULT_DIR/summary.json"
```

To list cases that violate state invariants:

```bash
jq -s '[
  .[] | select(.state_consistent == false)
  | {
      case_id,
      failure_point,
      outcome,
      db_status,
      orphan_output_count
    }
]' "$RESULT_DIR/raw_runs.jsonl"
```

`--fail-on-gate` changes the process exit code to non-zero when any acceptance gate fails. CI uses this mode to reject workflow or compensation regressions.

## Interpretation

The normal-path task success rate excludes intentionally injected failures. External failures are graded on containment, failure persistence, and absence of orphaned objects. Deterministic fake latency must not be presented as production API latency.

See [EVALUATION_PROTOCOL.md](EVALUATION_PROTOCOL.md) for metric definitions and acceptance rules.

## Paid live integration smoke

Frozen [`LIVE_SMOKE_PROTOCOL.md`](LIVE_SMOKE_PROTOCOL.md) v1.0.0 validates the real PostgreSQL, S3, OpenAI, and Langfuse chain with two text-generation and two image-edit cases. It has a separate dataset and version so it cannot alter frozen offline v1.0.0. Run its free preflight before explicitly authorizing the paid cases; generated raw artifacts remain ignored under `evals/results/`, while a privacy-safe aggregate is tracked under `evals/evidence/`.

## Deterministic load evaluation

Frozen [`LOAD_PROTOCOL.md`](LOAD_PROTOCOL.md) v1.0.0 measures the dedicated
one-worker FastAPI application and real PostgreSQL path at concurrency
`1,4,8,16`. OpenAI, S3, and Langfuse are disabled and replaced with bounded
deterministic stubs, so the run makes no paid cloud calls. The tracked
`load_protocol_v1.json` manifest locks the parameters, stub delays,
safety properties, and acceptance gates. Use `--allow-protocol-deviation` only
for clearly marked exploratory capacity runs.

Frozen [`CAPACITY_PROTOCOL.md`](CAPACITY_PROTOCOL.md) v1.0.0 defines a separate
exploratory capacity evaluation through concurrency 64. It uses its own
`capacity-api`, port 8002, manifest, runner, evidence, and result suffix. The
protocol samples cgroup CPU and memory plus PostgreSQL connection activity
without modifying frozen Load v1. Its evidence establishes a tested local lower
bound, not a maximum-capacity or production-SLO claim.

Frozen [`CAPACITY_V2_EXPERIMENT.md`](CAPACITY_V2_EXPERIMENT.md) v2.0.0 continues
from concurrency 64 through 256 using a separate `capacity-v2-api` service on
port 8003. It normalizes marginal throughput gain by the change in concurrency
to locate a scaling knee without changing frozen Capacity v1 artifacts. The
tracked evidence identifies concurrency 96 as the first reproducible saturation
candidate and retains 64 as the highest fully reliable tested tier. See
[`CAPACITY_V1_V2_COMPARISON.md`](CAPACITY_V1_V2_COMPARISON.md) for the bounded
comparison and limitations.

Frozen [`CAPACITY_V3_EXPERIMENT.md`](CAPACITY_V3_EXPERIMENT.md) v3.0.0 isolates
one optimization variable: the SQLAlchemy pool capacity of a dedicated
one-worker service on port 8004. Three full validation runs retained
concurrency 96 as the first performance knee while moving the first reproduced
request-failure tier to 128. See
[`CAPACITY_V2_V3_COMPARISON.md`](CAPACITY_V2_V3_COMPARISON.md) for the bounded
reliability, throughput, latency, and resource comparison.
