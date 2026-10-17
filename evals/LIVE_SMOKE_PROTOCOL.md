# Live Image Workflow Smoke Protocol

Status: **FROZEN**

Protocol version: `1.0.0`

## Frozen identity

- Frozen on: `2026-10-17`
- Canonical Git tag: `live-smoke-v1.0.0`
- Passing implementation baseline: `b6b0903198c7c1c2ca64de224cf54aef484c75bc`
- Dataset SHA-256: `a3ed9c1dd51b04495fb4c72b8b8fdc9a150a9f27d5a5678067d22866f15b318c`
- Machine-readable manifest: `evals/frozen_live_protocol_v1.json`
- Privacy-safe aggregate evidence: `evals/evidence/live_smoke_v1_summary.json`

The tag is the canonical source snapshot. Live v1 locks the dataset, models, sequential execution, request timeout, trace wait, cost ceiling, and acceptance gates. Changes require a new protocol version.

## Purpose

This separately versioned paid smoke test verifies the complete FastAPI, PostgreSQL, private Amazon S3, OpenAI, and Langfuse integration. It does not change the frozen offline protocol.

## Cases and budget

`evals/datasets/live_smoke_v1.jsonl` contains two text-to-image and two image-to-image workflows. The reference S3 object key is supplied only at runtime and is never written to an artifact. The default total measured-cost ceiling is `$0.30`.

Before any paid model call, the runner verifies API and PostgreSQL health, the exact reference object with S3 `HeadObject`, and Langfuse authentication. Paid execution requires the explicit `--confirm-cloud-spend` flag. After each case, missing Langfuse cost data, a failed API workflow, or a reached cost ceiling stops later cases.

## Acceptance gates

The run passes only when all four cases execute and:

1. every API workflow completes;
2. API readback confirms a consistent PostgreSQL `completed` record;
3. every generated S3 output is retrievable as an image;
4. every Langfuse trace contains the expected workflow observations;
5. every observation keeps input and output empty;
6. each workflow uses the frozen model set;
7. every model-generation cost is measured; and
8. total measured cost remains within the configured ceiling.

## Privacy

Tracked cases use synthetic prompts. Generated evidence stores case IDs, generation IDs, request IDs, trace IDs, model names, bounded operational metrics, and costs. It does not store prompts, image descriptions, object keys, presigned URLs, credentials, or image bytes.

## Interpretation

Four paid cases provide integration evidence only. Reported runner wall-clock latency includes post-request database, S3, and Langfuse verification; it must not be presented as API latency, maximum throughput, availability, or a production service-level objective.

## Reproduction

Keep the reference key out of shell history by using an environment variable:

```bash
export LIVE_SMOKE_REFERENCE_OBJECT_KEY='uploads/your-existing-reference.png'

# Free preflight: API, PostgreSQL, S3 HeadObject, and Langfuse authentication.
.venv/bin/python -m evals.run_live_smoke --validate-only

# Four sequential paid cases, stopped on failure, missing cost, or budget limit.
.venv/bin/python -m evals.run_live_smoke \
  --confirm-cloud-spend \
  --maximum-cost-usd 0.30 \
  --fail-on-gate
```

After the paid command prints its result directory, inspect only the aggregate gates first:

```bash
RESULT_DIR=$(find evals/results -mindepth 1 -maxdepth 1 -type d \
  -name '*_live_smoke_v1' | sort | tail -1)

jq '{
  planned_case_count,
  run_count,
  stopped_reason,
  score,
  cost_usd,
  latency_ms,
  acceptance_gates
}' "$RESULT_DIR/summary.json"
```
