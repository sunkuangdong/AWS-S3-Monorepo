# Manual Verification Guide

This guide connects the project's headline metrics to tracked evidence and
shows how to reproduce each evaluation layer safely. It does not replace the
frozen protocols or the [project-level evaluation report](FINAL_EVALUATION_REPORT.md).

## Verification levels

Use the least expensive level that answers the question:

1. **Evidence audit:** read tracked, privacy-safe JSON and verify frozen
   identities. No services, cloud calls, or model cost.
2. **Offline reproduction:** rerun Workflow, Load, or Capacity with local
   deterministic substitutes. No OpenAI, S3, or Langfuse calls.
3. **Live reproduction:** rerun four real PostgreSQL/S3/OpenAI/Langfuse cases.
   This requires credentials and incurs model cost.

Raw run directories under `evals/results/` are intentionally ignored. Do not
commit prompts, object keys, presigned URLs, credentials, images, generation
IDs, request IDs, or trace IDs.

## Evidence index

| Claim | Canonical evidence | Fields to inspect | Frozen tag |
| --- | --- | --- | --- |
| 12/12 workflow scenarios matched; 100% state consistency; no orphan output | [`workflow_v1_summary.json`](evidence/workflow_v1_summary.json) | `result`, `outcome_counts`, `latency_ms` | `workflow-eval-v1.0.0` |
| 4/4 live workflows passed; measured model cost was $0.1404404 | [`live_smoke_v1_summary.json`](evidence/live_smoke_v1_summary.json) | `result`, `cost_usd`, `latency_ms`, `generation_types` | `live-smoke-v1.0.0` |
| Load v1 reached 42.144 RPS and 346.008 ms P95 at c16 | [`load_v1_summary.json`](evidence/load_v1_summary.json) | `result`, `tiers`, `database` | `load-eval-v1.0.0` |
| Capacity v1 reached 165.047 RPS and 511.634 ms P95 at c64 | [`capacity_v1_summary.json`](evidence/capacity_v1_summary.json) | `result`, `tiers`, `saturation_analysis` | `capacity-eval-v1.0.0` |
| Capacity v2 found the first repeatable performance knee at c96 | [`capacity_v2_summary.json`](evidence/capacity_v2_summary.json) | `result`, `repeatability` | `capacity-eval-v2.0.0` |
| Capacity v3 improved c96 throughput 14.9%, reduced P95 22.4%, and reproduced failures at c128 | [`capacity_v3_validation_summary.json`](evidence/capacity_v3_validation_summary.json) | `single_variable_change`, `aggregate`, `comparison_to_frozen_v2_repeated_medians`, `conclusion` | `capacity-eval-v3.0.0` |

Inspect all résumé-relevant fields without opening raw results:

```bash
jq '{result, outcome_counts, latency_ms}' \
  evals/evidence/workflow_v1_summary.json

jq '{result, cost_usd, latency_ms, generation_types}' \
  evals/evidence/live_smoke_v1_summary.json

jq '{result, tiers, database}' \
  evals/evidence/load_v1_summary.json

jq '{result, tiers, saturation_analysis}' \
  evals/evidence/capacity_v1_summary.json

jq '{result, repeatability}' \
  evals/evidence/capacity_v2_summary.json

jq '{
  single_variable_change,
  aggregate,
  comparison_to_frozen_v2_repeated_medians,
  conclusion
}' evals/evidence/capacity_v3_validation_summary.json
```

The narrative interpretation and limitations are in
[`FINAL_EVALUATION_REPORT.md`](FINAL_EVALUATION_REPORT.md). The controlled
optimization analysis is in
[`CAPACITY_V2_V3_COMPARISON.md`](CAPACITY_V2_V3_COMPARISON.md).

## 1. Free static and quality checks

Run from the repository root. A clean worktree is required before producing
new evidence intended for comparison.

```bash
git status -sb
git show --no-patch --decorate project-eval-v1.0.0

source .venv/bin/activate

python -m ruff check apps/api evals
python -m pytest apps/api/tests -q

pnpm lint
pnpm test
pnpm build

python -m evals.validation
python -m evals.live_validation
```

Expected results:

- the worktree is clean;
- 54 API tests and 3 web tests pass;
- Ruff, ESLint, and the production web build pass;
- Workflow and Live manifests, datasets, hashes, and tracked evidence validate;
- no command makes a paid model call.

## 2. Offline Workflow Smoke

This run uses deterministic in-memory dependencies and costs `$0`.

```bash
python -m evals.run_workflow \
  --dataset evals/datasets/workflow_smoke_v1.jsonl \
  --concurrency 4 \
  --fail-on-gate

RESULT_DIR=$(find evals/results -mindepth 1 -maxdepth 1 -type d \
  -name '*_workflow_smoke_v1' | sort | tail -1)

jq '{
  run_count,
  cloud_calls,
  score,
  latency_ms,
  concurrency,
  acceptance_gates
}' "$RESULT_DIR/summary.json"
```

Expected gates:

- `run_count: 12`;
- `cloud_calls: false`;
- every rate under `score` is `1.0`;
- `orphan_output_count: 0` and `unexpected_pending_count: 0`;
- `acceptance_gates.overall: true`.

Offline latency is harness latency, not production API latency.

## 3. Frozen Load v1

This run uses one Uvicorn worker, real local PostgreSQL, and deterministic
provider substitutes. It inserts 180 run-scoped database records and costs
`$0`.

```bash
docker compose --profile evaluation up -d --build --wait load-api

python -m evals.run_load --validate-only

python -m evals.run_load \
  --concurrencies 1,4,8,16 \
  --requests-per-tier 40 \
  --warmup-requests 5 \
  --timeout-seconds 30 \
  --fail-on-gate

RESULT_DIR=$(find evals/results -mindepth 1 -maxdepth 1 -type d \
  -name '*_load_v1' | sort | tail -1)

jq '{
  measured_count,
  warmup_count,
  cloud_calls,
  cost_usd,
  tiers,
  database,
  errors,
  acceptance_gates
}' "$RESULT_DIR/summary.json"
```

A protocol-compliant reproduction has 160 measured requests, 20 warmups, 180
completed database records, no server or transport errors, no cloud calls, zero
cost, and `acceptance_gates.overall: true`. Throughput may vary with host load;
compare correctness first and performance second.

## 4. Frozen Capacity v1

Capacity v1 is a larger local run. Close unrelated CPU- or disk-intensive
applications before testing.

```bash
docker compose --profile capacity up -d --build --wait capacity-api

python -m evals.run_capacity --validate-only

python -m evals.run_capacity \
  --concurrencies 1,4,8,16,32,64 \
  --requests-per-tier 200 \
  --warmup-requests 5 \
  --timeout-seconds 30 \
  --sample-interval-seconds 0.1 \
  --fail-on-gate
```

Expected correctness evidence is 1,200 measured requests plus 30 warmups, 100%
API and database consistency, resource samples at every tier, no cloud calls,
and zero cost. The frozen 165.047 RPS result is a local deterministic baseline,
not a production or cloud-provider capacity promise.

## 5. Capacity v3 optimization reproduction

Capacity v3 changes only the isolated evaluation service's SQLAlchemy pool
capacity from `5 + 10` to `20 + 20`.

```bash
docker compose --profile capacity-v3 up -d --build --wait capacity-v3-api

python -m evals.run_capacity_v3 \
  --mode full \
  --fail-on-gate
```

For a repeatability comparison, run the full command three times under similar
host conditions and keep each result directory. Do not retry measured POST
failures. The command may exit non-zero after safely recording overload; that
is a valid capacity observation when the service stays healthy and partial
results are preserved.

Compare the new runs with the frozen aggregate rather than selecting only the
best run:

```bash
jq '{
  aggregate,
  repeated_tiers,
  comparison_to_frozen_v2_repeated_medians,
  conclusion
}' evals/evidence/capacity_v3_validation_summary.json
```

The frozen evidence supports c64 as the performance-safe tier, c96 as the
highest repeatedly fully reliable tier and first performance knee, and c128 as
the first reproduced request-failure tier.

## 6. Paid Live Smoke

Only run this section when `apps/api/.env` contains valid AWS, S3, OpenAI, and
Langfuse configuration and the API uses `LANGFUSE_TRACING_ENABLED=true`. The
reference image must already exist under `uploads/` in the configured private
bucket.

Start the real API and database:

```bash
docker compose up -d --build --wait database api
```

Supply the reference object only at runtime. Never commit the real value:

```bash
export LIVE_SMOKE_REFERENCE_OBJECT_KEY='uploads/your-existing-reference.png'
```

Run the free preflight first. It verifies API/database health, S3 `HeadObject`,
Langfuse authentication, the frozen dataset, and the cost ceiling without a
model call:

```bash
python -m evals.run_live_smoke --validate-only
```

Only after preflight passes, explicitly authorize the four paid cases:

```bash
python -m evals.run_live_smoke \
  --confirm-cloud-spend \
  --maximum-cost-usd 0.30 \
  --fail-on-gate
```

Inspect the aggregate result:

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

A passing run executes all four cases, retrieves every S3 output, finds every
Langfuse trace, leaves trace input/output empty, measures every cost, remains
within the configured stop threshold, and reports
`acceptance_gates.overall: true`. Provider prices can change, so confirm current
pricing and account balance before authorizing paid calls.

## 7. Draft production-capacity evaluation

This is not a rerun of the local Stub benchmark. Read
[`PRODUCTION_CAPACITY_PROTOCOL.md`](PRODUCTION_CAPACITY_PROTOCOL.md) first. A
human must approve the exact target, deployment identity, isolated data scope,
provider quota, cost cap, arrival rates, duration, and resource thresholds.

The protected metrics endpoint is disabled unless the target API has a long
random complete authorization value in `CAPACITY_METRICS_AUTHORIZATION`. Give
the same value to the runner without putting it on the command line:

```bash
export PRODUCTION_CAPACITY_METRICS_AUTHORIZATION='Bearer ...'
export LIVE_SMOKE_REFERENCE_OBJECT_KEY='uploads/your-existing-reference.png'
```

Run the no-model-call preflight first:

```bash
python -m evals.run_production_capacity \
  --api-base-url https://api.example.com \
  --expected-api-host api.example.com \
  --target-environment-label production-canary \
  --metrics-url https://api.example.com/internal/capacity-metrics \
  --validate-only
```

Do not run the paid command until every preflight check passes and an operator
is watching the production dashboards. Start with the four-request pilot shown
in the production protocol. The runner automates request scheduling, safe stop
conditions, PostgreSQL record scanning, S3 retrieval and orphan checks,
Langfuse trace/cost validation, and JSON/Markdown reporting.

After a run, a human still needs to confirm that no real user was affected,
the deployment and provider quotas match the recorded configuration, alerts
behaved as expected, synthetic objects can be cleaned safely, and the result
is repeated at least three times before making a capacity claim.

### 7.1 Rehearse data isolation locally

This rehearsal uses a dedicated Compose project, PostgreSQL volume, API port,
S3 bucket, OpenAI project key, and Langfuse environment. It proves isolation
and integration only; it is not a production-capacity result because the local
compute and network are not production-equivalent.

First create the external isolated resources described in
`PRODUCTION_CAPACITY_PROTOCOL.md`. Then create the untracked environment file:

```bash
cp apps/api/.env.capacity.example apps/api/.env.capacity
chmod 600 apps/api/.env.capacity
```

Fill every `replace_with_...` value. The S3 identity must be able to list the
test bucket and read/write only its `uploads/` and `generations/` objects. The
OpenAI key must belong to a separate capacity-test project. Do not reuse the
development or production key.

Start only the isolated database and API:

```bash
docker compose \
  -f compose.production-capacity.local.yaml \
  up -d --build --wait

docker compose \
  -f compose.production-capacity.local.yaml \
  ps
```

Load the same external credentials into the runner process without printing
them, then set the two in-memory-only values:

```bash
set -a
source apps/api/.env.capacity
set +a

export LIVE_SMOKE_REFERENCE_OBJECT_KEY='uploads/your-capacity-reference.png'
export PRODUCTION_CAPACITY_METRICS_AUTHORIZATION="$CAPACITY_METRICS_AUTHORIZATION"
```

Verify the isolated target without a model call:

```bash
python -m evals.run_production_capacity \
  --api-base-url http://localhost:8100 \
  --expected-api-host localhost \
  --target-environment-label production-capacity-local-rehearsal \
  --metrics-url http://localhost:8100/internal/capacity-metrics \
  --validate-only
```

The preflight must report `paid_model_calls: 0`, successful database/S3/
Langfuse/resource-metric checks, and no access error. Stop this stack with:

```bash
docker compose \
  -f compose.production-capacity.local.yaml \
  down
```

Do not add `--volumes` unless the isolated database has been reviewed and may
be permanently deleted.

## Interview-safe evidence capture

Use these artifacts in a portfolio or interview:

- the root README's measured-results table;
- [`FINAL_EVALUATION_REPORT.md`](FINAL_EVALUATION_REPORT.md);
- the six aggregate JSON files listed above;
- the frozen Git tags and protocol manifests;
- a Langfuse screenshot showing the workflow tree, model, latency, usage, and
  cost with input/output empty.

Do not publish raw result directories or screenshots containing prompts,
object keys, presigned URLs, credentials, image contents, request IDs,
generation IDs, or trace IDs.
