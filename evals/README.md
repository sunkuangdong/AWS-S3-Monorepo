# Offline workflow evaluation

The evaluation harness executes the real `ImageService` orchestration against deterministic in-memory implementations of PostgreSQL, S3, OpenAI Vision, and OpenAI Images. It produces reproducible workflow and failure-compensation evidence without cloud calls or fees.

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
