# AI Image Creation Platform

English | [简体中文](README.zh-CN.md)

A full-stack AI image creation project organized as a monorepo. It supports text-to-image generation and reference-image editing, with PostgreSQL tracking task state, private Amazon S3 storage, and OpenAI vision and image-generation models.

This release is an engineering-focused, demo-ready MVP with automated tests, CI, containers, database migrations, health checks, and structured request logs.

## Features

- Generate 1024 × 1024 images from text prompts.
- Edit JPEG, PNG, or WebP reference images.
- Upload reference images directly from the browser to private S3 with presigned POST forms.
- Persist `pending`, `completed`, and `failed` task states.
- Browse paginated history, download results, and soft-delete records.
- Manage PostgreSQL schema changes with Alembic.
- Trace requests with request IDs and JSON logs.
- Start the web app, API, and PostgreSQL with Docker Compose.

## Architecture

```text
Browser (React)
  │
  ├─ Request presigned POST ─────────► FastAPI ─────► Amazon S3 signing
  ├─ Upload reference directly ──────► Private Amazon S3
  └─ Create generation task ─────────► FastAPI
                                         ├─► PostgreSQL task state
                                         ├─► OpenAI vision/image generation
                                         └─► Amazon S3 generated output
```

Image upload bytes do not pass through FastAPI. The backend handles temporary authorization, validation, workflow orchestration, task persistence, and OpenAI access.

See the [architecture notes](docs/architecture.zh-CN.md) for design decisions and production-readiness boundaries.

## Stack

- API: Python 3.14, FastAPI, SQLAlchemy Async, psycopg, Alembic, boto3, OpenAI SDK.
- Web: React 19, TypeScript, Vite, Radix UI.
- Quality: Pytest, Ruff, Vitest, ESLint, GitHub Actions.
- Infrastructure: PostgreSQL, private Amazon S3, Docker Compose.

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
.venv/bin/python -m ruff check apps/api
.venv/bin/python -m pytest apps/api/tests -q

# Web
pnpm lint
pnpm test
pnpm build
```

API tests mock S3 and OpenAI, so they require no cloud credentials and incur no model cost. GitHub Actions runs the same checks for pull requests and pushes to `main`.

## Observability

Every API response contains `X-Request-ID`. The API emits one JSON log entry per request with the request ID, method, path, status code, and duration. `/health` is a process liveness probe, while `/health/database` verifies PostgreSQL readiness.

## Current boundaries

- Image generation runs inside a long-lived HTTP request; there is no background queue yet.
- Authentication, RBAC, and tenant isolation are not implemented.
- Rate limiting, content moderation, and model-cost quotas are not implemented.
- The project does not currently provide RAG or vector retrieval.
- Docker Compose targets local demonstration, not highly available production deployment.
