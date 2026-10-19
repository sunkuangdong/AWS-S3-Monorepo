# AI Image Creation Platform

English | [简体中文](README.zh-CN.md)

A full-stack AI image creation project organized as a monorepo. It supports text-to-image generation and reference-image editing, with PostgreSQL tracking task state, private Amazon S3 storage, and OpenAI vision and image-generation models.

This release is an engineering-focused, demo-ready MVP with automated tests,
CI, containers, database migrations, health checks, and structured request
logs. Its throughput and capacity figures come from controlled local
benchmarks, not production traffic.

## Engineering highlights

- Model the image workflow as durable `pending`, `completed`, and `failed`
  PostgreSQL states instead of treating an external model call as one opaque
  HTTP operation.
- Apply compensating actions when a generated S3 object exists but the final
  database commit fails, preventing orphaned outputs and stale pending tasks.
- Keep upload bytes out of the API process by issuing scoped presigned S3 POST
  forms to the browser.
- Trace PostgreSQL, S3, vision, and image-generation stages in Langfuse while
  deliberately excluding prompts, image contents, object keys, and signed URLs.
- Evaluate correctness and capacity with versioned datasets, manifests, Git
  tags, privacy-safe evidence, deterministic failure injection, and controlled
  single-variable experiments.

## Features

- Generate 1024 × 1024 images from text prompts.
- Edit JPEG, PNG, or WebP reference images.
- Upload reference images directly from the browser to private S3 with presigned POST forms.
- Persist `pending`, `completed`, and `failed` task states.
- Compensate failed completion commits by deleting uploaded outputs and persisting `failed`.
- Browse paginated history, download results, and soft-delete records.
- Manage PostgreSQL schema changes with Alembic.
- Trace requests with request IDs and JSON logs.
- Start the web app, API, and PostgreSQL with Docker Compose.

## Architecture

```text
Browser (React)
  ├─ request upload authorization ─────► FastAPI ─────► scoped S3 presigned POST
  ├─ upload reference bytes directly ─────────────────► private Amazon S3
  └─ create generation request ────────► ImageService orchestration
                                           │
                                           ├─ 1. persist PostgreSQL `pending`
                                           ├─ 2. load/analyze reference image
                                           │     (image-to-image only)
                                           ├─ 3. call OpenAI image generation
                                           ├─ 4. upload generated image to S3
                                           ├─ 5. commit PostgreSQL `completed`
                                           └─ 6. return temporary download URL

Failure path
  ├─ external call fails ──────────────► persist `failed`
  ├─ output exists but DB commit fails ► delete output, then persist `failed`
  └─ response delivery fails after commit
                                      ► preserve durable `completed` state

Operational evidence
  ├─ structured JSON request logs + X-Request-ID
  └─ privacy-safe Langfuse workflow spans, token usage, latency, and cost
```

Image upload bytes do not pass through FastAPI. The backend handles temporary authorization, validation, workflow orchestration, task persistence, and OpenAI access.

See the [architecture notes](docs/architecture.zh-CN.md) for design decisions and production-readiness boundaries.

## Stack

- API: Python 3.14, FastAPI, SQLAlchemy Async, psycopg, Alembic, boto3, OpenAI SDK.
- Web: React 19, TypeScript, Vite, Radix UI.
- Quality: Pytest, Ruff, Vitest, ESLint, GitHub Actions.
- Infrastructure: PostgreSQL, private Amazon S3, Docker Compose.

## Measured evaluation results

The repository includes a layered evaluation program rather than a single
happy-path demo. Workflow and load tests use deterministic substitutes; Live
Smoke alone calls the real paid services.

> **Claim boundary:** Load and Capacity results measure one local Uvicorn
> worker with real PostgreSQL and a deterministic 250 ms provider stub. They
> are reproducible engineering benchmarks, not OpenAI/S3 production capacity
> or production SLOs. Live Smoke verifies the real integration chain, but its
> four cases are too few to support availability or latency-percentile claims.

| Evaluation | Workload | Result | Latency / throughput | Cost | Evidence |
| --- | --- | --- | --- | --- | --- |
| Workflow Smoke v1 | 12 reviewed normal, validation, database, and provider-failure scenarios | 100% scenario expectations and terminal-state consistency; 0 orphan outputs | 100.380 ms P95 harness latency | $0 | [JSON](evals/evidence/workflow_v1_summary.json) |
| Live Smoke v1 | 4 real PostgreSQL/S3/OpenAI/Langfuse workflows | 4/4 API, database, S3, trace, privacy, and cost checks passed | Not used for a latency claim (`n=4`) | $0.1404404 | [JSON](evals/evidence/live_smoke_v1_summary.json) |
| Load v1 | 160 measured requests through c16 | 100% API and database consistency | 42.144 RPS; 346.008 ms P95 at c16 | $0 | [JSON](evals/evidence/load_v1_summary.json) |
| Capacity v1 | 1,200 measured requests through c64 | 100% success; no saturation observed within the tested range | 165.047 RPS; 511.634 ms P95 at c64 | $0 | [JSON](evals/evidence/capacity_v1_summary.json) |
| Capacity v2 | Three repeated breakpoint runs | c96 was the first repeatable performance knee; request failures in 2/3 runs | 70.147 RPS median; 4,352.453 ms median P95 at c96 | $0 | [JSON](evals/evidence/capacity_v2_summary.json) |
| Capacity v3 | Three validation runs; 11,000 measured requests | c64/c96: 100%; first reproduced request-failure tier: c128 | 80.569 RPS median; 3,375.503 ms median P95 at c96 | $0 | [JSON](evals/evidence/capacity_v3_validation_summary.json) |

Capacity v3 changed only the controlled evaluation service's SQLAlchemy pool
from `5 + 10` to `20 + 20`. At concurrency 96, fully successful runs improved
from **1/3 to 3/3**, median throughput increased **14.9%**, and median P95
latency decreased **22.4%**. The performance knee remained at 96, so the
recommended performance-safe local tier remains **concurrency 64**.

Read the [project-level evaluation report](evals/FINAL_EVALUATION_REPORT.md)
for metric definitions, failure boundaries, provenance, cost scope, and claim
limitations. The [v2/v3 controlled comparison](evals/CAPACITY_V2_V3_COMPARISON.md)
contains the optimization analysis. The
[manual verification guide](evals/MANUAL_VERIFICATION_GUIDE.md) maps each
headline number to evidence and gives free, offline, capacity, and paid test
procedures with expected results.

## Quick start with Docker

Prerequisites: Docker and valid AWS, S3, and OpenAI credentials.

```bash
cp apps/api/.env.example apps/api/.env
cp apps/web/.env.example apps/web/.env
```

Fill in the AWS, S3, and OpenAI values in `apps/api/.env`, then run:

```bash
docker compose up --build
```

The backend IAM principal needs object-level `s3:GetObject` and `s3:PutObject` access for the application prefixes, plus `s3:DeleteObject` on `generations/*` for failed-workflow compensation. `s3:ListBucket` is not required by the application workflow.

The API container waits for PostgreSQL, applies Alembic migrations, and starts the server.

- Web: <http://localhost:5173>
- OpenAPI: <http://localhost:8000/docs>
- Liveness: <http://localhost:8000/health>
- Database readiness: <http://localhost:8000/health/database>

Stop the stack with `docker compose down`. The `postgres-data` named volume is retained.

## Local development

Requirements:

- Python 3.14.x
- Node.js 22.22.0 or later
- pnpm 10.33.0
- PostgreSQL
- A private S3 bucket and an OpenAI API key

Install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e "./apps/api[dev]"

corepack enable
pnpm install
```

Create local configuration:

```bash
cp apps/api/.env.example apps/api/.env
cp apps/web/.env.example apps/web/.env
```

Apply migrations:

```bash
cd apps/api
../../.venv/bin/python -m alembic upgrade head
cd ../..
```

Start the API:

```bash
.venv/bin/python -m uvicorn app.main:app \
  --app-dir apps/api \
  --reload \
  --reload-dir apps/api \
  --port 8000
```

Start the web app in another terminal:

```bash
pnpm dev
```

## API surface

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | API liveness |
| `GET` | `/health/database` | PostgreSQL readiness |
| `POST` | `/api/v1/images/presign-upload` | Create a presigned S3 upload form |
| `POST` | `/api/v1/images/analyze` | Analyze an uploaded image |
| `POST` | `/api/v1/images/generations` | Create an image-generation task |
| `GET` | `/api/v1/images/generations` | List generation history |
| `GET` | `/api/v1/images/generations/{id}` | Get one generation record |
| `GET` | `/api/v1/images/generations/{id}/download` | Create a temporary download URL |
| `DELETE` | `/api/v1/images/generations/{id}` | Soft-delete a record |

## Quality checks

```bash
# API
.venv/bin/python -m ruff check apps/api evals
.venv/bin/python -m pytest apps/api/tests -q

# Web
pnpm lint
pnpm test
pnpm build
```

API tests mock S3 and OpenAI, so they require no cloud credentials and incur no model cost. GitHub Actions runs the same checks for pull requests and pushes to `main`.

## Reproduce the evaluation

The deterministic workflow harness runs the real `ImageService` orchestration against in-memory PostgreSQL, S3, OpenAI Vision, and OpenAI Images substitutes. It measures normal-path completion, injected-failure containment, database/object consistency, orphaned outputs, and concurrency without cloud calls or fees.

Evaluation protocol `1.0.0` is frozen at tag `workflow-eval-v1.0.0`; the tracked manifest locks the dataset hash, ordered case IDs, and acceptance gates.

### Workflow correctness

```bash
.venv/bin/python -m evals.validation
.venv/bin/python -m evals.run_workflow \
  --dataset evals/datasets/workflow_smoke_v1.jsonl \
  --concurrency 4
```

Generated evidence is written under ignored `evals/results/` directories. Metric definitions and acceptance rules are documented in [`evals/EVALUATION_PROTOCOL.md`](evals/EVALUATION_PROTOCOL.md). Fake-service latency is not production latency.

### Paid live integration smoke

The separately versioned live protocol verifies real PostgreSQL, S3, OpenAI,
and Langfuse under an explicit cost ceiling. Keep the reference object key out
of source control and tracked artifacts by supplying it only at runtime:

```bash
export LIVE_SMOKE_REFERENCE_OBJECT_KEY='uploads/your-existing-reference.png'

# Free preflight; this makes no model call.
.venv/bin/python -m evals.run_live_smoke --validate-only

# Explicitly authorized paid run, capped at $0.30.
.venv/bin/python -m evals.run_live_smoke \
  --confirm-cloud-spend \
  --maximum-cost-usd 0.30 \
  --fail-on-gate
```

See [`evals/LIVE_SMOKE_PROTOCOL.md`](evals/LIVE_SMOKE_PROTOCOL.md) before
running the paid command.

### Frozen deterministic load baseline

```bash
docker compose --profile evaluation up -d --build --wait load-api

.venv/bin/python -m evals.run_load --validate-only
.venv/bin/python -m evals.run_load \
  --concurrencies 1,4,8,16 \
  --requests-per-tier 40 \
  --warmup-requests 5 \
  --timeout-seconds 30 \
  --fail-on-gate
```

This profile uses one Uvicorn worker, real PostgreSQL, and deterministic local
S3/OpenAI substitutes. The canonical parameters and acceptance gates are in
[`evals/LOAD_PROTOCOL.md`](evals/LOAD_PROTOCOL.md).

### Frozen capacity baseline

```bash
docker compose --profile capacity up -d --build --wait capacity-api

.venv/bin/python -m evals.run_capacity --validate-only
.venv/bin/python -m evals.run_capacity \
  --concurrencies 1,4,8,16,32,64 \
  --requests-per-tier 200 \
  --warmup-requests 5 \
  --timeout-seconds 30 \
  --sample-interval-seconds 0.1 \
  --fail-on-gate
```

Higher-concurrency breakpoint and optimization experiments have separate
services and frozen protocols:

```bash
# Reproduce the v3 connection-pool experiment.
docker compose --profile capacity-v3 up -d --build --wait capacity-v3-api

.venv/bin/python -m evals.run_capacity_v3 \
  --mode full \
  --fail-on-gate
```

An overload-search run may return non-zero after safely preserving a measured
failure; that is a capacity observation, not automatically an infrastructure
failure. Read [`evals/CAPACITY_PROTOCOL.md`](evals/CAPACITY_PROTOCOL.md),
[`evals/CAPACITY_V2_EXPERIMENT.md`](evals/CAPACITY_V2_EXPERIMENT.md), and
[`evals/CAPACITY_V3_EXPERIMENT.md`](evals/CAPACITY_V3_EXPERIMENT.md) before
interpreting or comparing results.

## Observability

Every API response contains `X-Request-ID`. The API emits one JSON log entry per request with the request ID, method, path, status code, and duration. `/health` is a process liveness probe, while `/health/database` verifies PostgreSQL readiness.

When Langfuse is enabled, each image workflow emits a root trace with nested PostgreSQL, S3, OpenAI vision, and image-generation observations. Generations include model and token-usage metadata so latency, errors, usage, and configured model cost can be analyzed per workflow.

```dotenv
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://us.cloud.langfuse.com
LANGFUSE_TRACING_ENABLED=true
LANGFUSE_ENVIRONMENT=local-evaluation
```

The trace integration deliberately excludes prompts, generated descriptions, presigned URLs, S3 object keys, and image bytes. Only bounded operational metadata—such as status, model, dimensions, byte counts, token usage, and database IDs—is exported. Disable tracing in tests or sensitive environments with `LANGFUSE_TRACING_ENABLED=false`.

Langfuse already has managed pricing for `gpt-4.1-mini`. The project image model uses modality-specific token prices, so preview and apply its audited custom pricing definition with:

```bash
.venv/bin/python apps/api/scripts/configure_langfuse_model.py
.venv/bin/python apps/api/scripts/configure_langfuse_model.py --apply
```

## Current boundaries

- Image generation runs inside a long-lived HTTP request; there is no background queue yet.
- Authentication, RBAC, and tenant isolation are not implemented.
- Rate limiting, content moderation, and model-cost quotas are not implemented.
- The project does not currently provide RAG or vector retrieval.
- Docker Compose targets local demonstration, not highly available production deployment.
- Load and capacity figures use one local Uvicorn worker, real PostgreSQL, and
  deterministic provider stubs; they are not production OpenAI/S3 capacity or
  production SLO claims.
- Live Smoke contains four paid cases, which verifies integration behavior but
  cannot establish production availability or stable latency percentiles.
- Capacity runs are burst experiments rather than long-duration soak tests;
  multi-worker, multi-host, autoscaling, and connection-aging behavior remain
  outside the measured scope.

## Optional infrastructure design

[`infra/production-capacity`](infra/production-capacity/README.md) contains a
reviewable Terraform design for an isolated HTTPS/ECS/RDS capacity-test
environment. It is an unexecuted extension, is disabled with zero API tasks by
default, and is not part of the measured evidence above. The draft
[`Production Capacity Protocol`](evals/PRODUCTION_CAPACITY_PROTOCOL.md) keeps
any future real-dependency experiment separate from the frozen local results;
it cannot be used to relabel those results as production capacity.
