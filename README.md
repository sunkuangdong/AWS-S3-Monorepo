# AI Image Analysis Platform

[简体中文](README.zh-CN.md) | English

A learning-oriented, full-stack image analysis application built as a monorepo. The React frontend uploads images directly to a private Amazon S3 bucket with a presigned POST. The FastAPI backend then creates a temporary read URL and sends the image to an OpenAI vision-capable model for analysis.

> Current scope: image understanding only. The application does not generate or edit images yet.

## Features

- Select and preview JPEG, PNG, or WebP images in the browser.
- Upload files directly from React to a private S3 bucket.
- Keep AWS and OpenAI credentials on the backend.
- Restrict uploads by MIME type, size, expiration time, and generated object key.
- Analyze private S3 images with the OpenAI Responses API.
- Display progress, errors, analysis text, and the resulting S3 object key.
- Keep frontend and backend code in one pnpm/Python monorepo.

## Architecture

```text
Browser (React)
  │
  ├─ 1. Request a presigned POST ────────► FastAPI
  │                                         │
  │                                         └─► Amazon S3 signing
  │
  ├─ 2. Upload the image directly ───────► Private Amazon S3 bucket
  │
  └─ 3. Submit object_key ───────────────► FastAPI
                                            │
                                            ├─► Create a temporary S3 read URL
                                            └─► OpenAI vision model
                                                     │
                                                     └─► Text description
```

The image bytes do not pass through FastAPI during browser upload. FastAPI handles configuration, temporary authorization, validation, orchestration, and OpenAI access.

## Technology Stack

### Backend

- Python 3.14
- FastAPI and Uvicorn
- Boto3 for Amazon S3
- OpenAI Python SDK and the Responses API
- Pydantic
- python-dotenv

### Frontend

- React 19
- TypeScript
- Vite
- pnpm workspace

### Cloud services

- Private Amazon S3 bucket
- AWS IAM user with least-privilege object permissions
- OpenAI API

## Project Structure

```text
.
├── apps/
│   ├── api/
│   │   ├── app/
│   │   │   ├── api/             # FastAPI routes
│   │   │   ├── clients/         # S3 and OpenAI adapters
│   │   │   ├── core/            # Configuration and exceptions
│   │   │   ├── schemas/         # Pydantic request/response models
│   │   │   ├── services/        # Application workflows
│   │   │   ├── dependencies.py  # Cached dependency construction
│   │   │   └── main.py          # FastAPI application entry point
│   │   ├── .env                 # Backend secrets; never commit
│   │   └── pyproject.toml
│   └── web/
│       ├── src/
│       │   ├── api/             # Browser API and S3 requests
│       │   ├── types/           # Shared frontend data shapes
│       │   └── App.tsx
│       ├── .env                 # Public Vite configuration
│       └── package.json
├── .venv/                       # Shared Python virtual environment
├── package.json                 # Root frontend scripts
└── pnpm-workspace.yaml
```

## Prerequisites

- Python `3.14.x`
- Node.js `22.22.0` or newer
- pnpm `10.33.0` or a compatible version
- An AWS account with a private S3 bucket
- An IAM access key that can upload and read objects in that bucket
- An OpenAI API key with access to a vision-capable model

The IAM identity used by the backend needs, at minimum, permissions equivalent to:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject"
      ],
      "Resource": "arn:aws:s3:::YOUR_BUCKET/uploads/*"
    }
  ]
}
```

## Installation

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e "./apps/api[dev]"

corepack enable
pnpm install
```

If you use `nvm`, select the project Node.js version before running pnpm:

```bash
nvm use 22
```

## Environment Variables

### Backend: `apps/api/.env`

```dotenv
AWS_ACCESS_KEY_ID=your_iam_access_key_id
AWS_SECRET_ACCESS_KEY=your_iam_secret_access_key
AWS_DEFAULT_REGION=us-east-1
S3_BUCKET=your_private_bucket_name

OPENAI_API_KEY=your_openai_api_key
MODEL_NAME=your_vision_capable_model

S3_PRESIGNED_URL_EXPIRES=600
MAX_UPLOAD_BYTES=10485760
FRONTEND_ORIGIN=http://localhost:5173
```

### Frontend: `apps/web/.env`

```dotenv
VITE_API_BASE_URL=http://localhost:8000
```

Only variables prefixed with `VITE_` are exposed to browser code. Never put AWS secrets or an OpenAI API key in the frontend environment file.

## S3 CORS

The browser uploads directly to S3, so the bucket needs a CORS rule for the frontend origin:

```json
[
  {
    "AllowedHeaders": ["*"],
    "AllowedMethods": ["POST", "GET"],
    "AllowedOrigins": ["http://localhost:5173"],
    "ExposeHeaders": ["ETag"],
    "MaxAgeSeconds": 3000
  }
]
```

Keep the bucket private. CORS controls browser cross-origin behavior; it does not replace IAM permissions or make objects public.

## Running Locally

Open two terminals at the repository root.

### Terminal 1: FastAPI

```bash
.venv/bin/python -m uvicorn app.main:app \
  --app-dir apps/api \
  --reload \
  --reload-dir apps/api \
  --port 8000
```

Useful backend URLs:

- Health check: <http://127.0.0.1:8000/health>
- OpenAPI documentation: <http://127.0.0.1:8000/docs>

### Terminal 2: React

```bash
nvm use 22
pnpm dev
```

Open <http://localhost:5173>. Use `localhost` rather than `127.0.0.1` so the browser origin matches the configured CORS rules.

## API Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Check whether the API process is running. |
| `POST` | `/api/v1/images/presign-upload` | Create a temporary S3 presigned POST. |
| `POST` | `/api/v1/images/analyze` | Analyze an uploaded S3 image with OpenAI. |

Example presign request:

```json
{
  "file_name": "dog.jpg",
  "content_type": "image/jpeg"
}
```

Example analysis request:

```json
{
  "object_key": "uploads/generated-object-name.jpg",
  "prompt": "Describe the main objects, setting, and colors in this image."
}
```

## Development Commands

```bash
# Frontend development server
pnpm dev

# Frontend production build
pnpm build

# Frontend lint
pnpm lint

# Backend lint
.venv/bin/python -m ruff check apps/api
```

## Security Notes

- Do not commit `.env` files or access keys.
- Do not use root-user AWS access keys in application code.
- Keep the S3 bucket private and grant only the required object actions.
- Presigned URLs and forms are temporary credentials; keep their expiration short.
- The backend only accepts object keys below `uploads/`.
- Add authentication, authorization, rate limiting, malware scanning, and persistent metadata before treating this as a production file service.

## Current Limitations

- Image analysis only; image generation and editing are not implemented.
- No user authentication or tenant isolation.
- No PostgreSQL metadata persistence yet.
- No automated test suite yet.
- Generated object keys are returned to the browser for learning and debugging.

