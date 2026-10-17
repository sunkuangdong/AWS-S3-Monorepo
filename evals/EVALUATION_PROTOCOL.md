# Image Workflow Evaluation Protocol

Status: **FROZEN**

Protocol version: `1.0.0`

## Frozen identity

- Frozen on: `2026-10-17`
- Canonical Git tag: `workflow-eval-v1.0.0`
- Passing implementation baseline: `e1972c904579c960372d34053653834cf31ff362`
- Dataset SHA-256: `b17df2e5c7711fa7abd4389ca14bcfb756854d19eb4f868b1176819604d4c464`
- Machine-readable manifest: `evals/frozen_protocol_v1.json`

The tag is the canonical code snapshot. The manifest locks the dataset path, digest, ordered case IDs, runner mode, concurrency, and required gates. Any change to labels, cases, metrics, scoring, or acceptance rules must use a new protocol version and a new manifest; v1.0.0 is immutable.

## Purpose

This protocol evaluates the orchestration and persistence behavior of the image-generation workflow without sending requests to OpenAI, Amazon S3, PostgreSQL, or Langfuse. It is an offline engineering test, not an image-quality benchmark or production load test.

## Frozen inputs

Each run records the exact SHA-256 digest and case IDs of the JSONL dataset. The initial smoke dataset is `evals/datasets/workflow_smoke_v1.jsonl` and contains:

- successful text-to-image and image-to-image paths;
- failures while signing and downloading reference images;
- vision, image-generation, image-edit, and output-upload failures;
- a failure while committing the completed database state;
- a failure while creating the response URL after a successful commit;
- an invalid S3 object key rejected before persistence.

The database-completion case verifies that a failed completion commit triggers transaction rollback, compensating S3 deletion, and persistence of the task as `failed`.

## Isolation

- All dependencies are deterministic in-memory fakes.
- `LANGFUSE_TRACING_ENABLED=false` is forced by the runner.
- No cloud credentials are read by the fake dependencies.
- No prompt text, signed URL, object key from a real system, or generated image is written to results.
- Generated artifacts under `evals/results/` are ignored by Git.

## Metrics

- **Normal-path task success rate:** successful completion, a committed `completed` record, and a referenced stored output. Only normal-path cases are included.
- **External-failure containment rate:** injected provider or storage failures end in a committed `failed` record with no generated output or orphan.
- **Validation rejection rate:** invalid input is rejected before a database record or generated object exists.
- **Database failure recovery rate:** a failed `completed` commit removes the uploaded output and changes the previously committed task from `pending` to `failed` before propagating the infrastructure error.
- **State consistency rate:** committed database state and stored outputs satisfy the terminal-state invariant.
- **Orphan output count:** generated outputs that are not referenced by committed database state.
- **Unexpected pending count:** records left `pending` after a synchronous request has terminated.
- **Scenario expectation rate:** actual outcome and state exactly match the reviewed case labels. This measures regression against labels; it does not prove that the labeled behavior is desirable.
- **Latency:** wall-clock time of deterministic fake workflows. It is useful only for harness regression and concurrency checks, not production latency claims.

Deliberately injected failures are never mixed into the normal-path task success denominator.

## Acceptance gates

A release candidate passes only if:

1. every case matches its reviewed label;
2. normal paths complete successfully;
3. external failures are contained;
4. invalid inputs are rejected before side effects;
5. database completion failures are compensated;
6. every terminal state is consistent;
7. no generated output is orphaned; and
8. no synchronous request leaves an unexpected `pending` record.

The runner exits successfully by default so it can always publish diagnostic artifacts. CI uses `--fail-on-gate` to reject regressions in any acceptance gate.

## Reproduction

```bash
.venv/bin/python -m evals.validation

.venv/bin/python -m evals.run_workflow \
  --dataset evals/datasets/workflow_smoke_v1.jsonl \
  --concurrency 4 \
  --fail-on-gate
```

Inspect `summary.json`, `raw_runs.jsonl`, `config.json`, and `report.md` in the printed result directory.

## Out of scope

This protocol does not measure visual quality, prompt adherence, real provider availability, real S3 or PostgreSQL latency, maximum throughput, or production cost. Those require a separately versioned live smoke or load protocol with explicit budgets.
