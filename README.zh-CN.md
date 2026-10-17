# AI 图片创作平台

简体中文 | [English](README.md)

一个采用 monorepo 结构的全栈 AI 图片创作项目。它支持文字生成图片和基于参考图编辑图片，并通过 PostgreSQL 管理任务状态、Amazon S3 保存私有图片、OpenAI 提供视觉理解与图片生成能力。

当前版本定位为可稳定演示的工程化 MVP：包含自动化测试、CI、容器化、数据库迁移、健康检查和结构化请求日志。

## 功能

- 使用文字直接生成 1024 × 1024 图片；
- 上传 JPEG、PNG 或 WebP 参考图后进行图片编辑；
- 浏览器通过预签名 POST 直接上传到私有 S3；
- 保存 `pending`、`completed`、`failed` 任务状态；
- 数据库完成提交失败时删除已上传输出，并将任务补偿为 `failed`；
- 分页查看历史记录，下载结果并软删除记录；
- 通过 Alembic 管理 PostgreSQL 模式变更；
- 使用请求 ID 和 JSON 日志跟踪请求；
- 使用 Docker Compose 一键启动 Web、API 和 PostgreSQL。

## 架构

```text
浏览器（React）
  │
  ├─ 申请预签名 POST ──────────────► FastAPI ─────► Amazon S3 签名
  ├─ 直接上传参考图 ───────────────► 私有 Amazon S3
  └─ 创建生成任务 ─────────────────► FastAPI
                                        ├─► PostgreSQL 任务状态
                                        ├─► OpenAI 视觉理解/图片生成
                                        └─► Amazon S3 保存生成结果
```

图片二进制不会经过 FastAPI 上传接口。后端负责临时授权、输入验证、业务编排、状态持久化以及 OpenAI 访问。

更完整的设计与取舍见 [架构说明](docs/architecture.zh-CN.md)；面试或内部演示可使用 [5～8 分钟演示脚本](docs/demo.zh-CN.md)。

## 技术栈

### 后端

- Python 3.14、FastAPI、Uvicorn；
- SQLAlchemy Async、psycopg、Alembic；
- Boto3、OpenAI Python SDK；
- Pytest、Ruff。

### 前端

- React 19、TypeScript、Vite；
- Radix UI；
- Vitest、ESLint；
- pnpm workspace。

### 基础设施

- PostgreSQL；
- 私有 Amazon S3 Bucket；
- Docker Compose；
- GitHub Actions。

## 项目结构

```text
.
├── .github/workflows/ci.yml       # 持续集成
├── apps/
│   ├── api/
│   │   ├── alembic/               # 数据库迁移
│   │   ├── app/
│   │   │   ├── api/               # FastAPI 路由
│   │   │   ├── clients/           # S3 与 OpenAI 适配器
│   │   │   ├── core/              # 配置、异常和日志
│   │   │   ├── db/                # 数据库会话
│   │   │   ├── models/            # SQLAlchemy 模型
│   │   │   ├── repositories/      # 数据访问
│   │   │   ├── schemas/           # Pydantic 模型
│   │   │   └── services/          # 业务编排
│   │   ├── tests/                  # 后端测试
│   │   └── Dockerfile
│   └── web/
│       ├── src/
│       │   ├── api/                # HTTP 与 S3 请求
│       │   ├── components/         # UI 组件
│       │   ├── viewmodels/         # 页面状态与命令
│       │   └── views/              # 页面
│       └── Dockerfile
├── docs/architecture.zh-CN.md
├── compose.yaml
└── pnpm-workspace.yaml
```

## 快速启动：Docker Compose

前置条件：Docker，以及可用的 AWS、S3 和 OpenAI 凭证。

```bash
cp apps/api/.env.example apps/api/.env
cp apps/web/.env.example apps/web/.env
```

填写 `apps/api/.env` 中的 AWS、S3 和 OpenAI 配置，然后执行：

```bash
docker compose up --build
```

后端 IAM 身份需要应用目录的对象级 `s3:GetObject`、`s3:PutObject` 权限，以及针对 `generations/*` 的 `s3:DeleteObject` 权限，以便在工作流失败时执行补偿删除。应用工作流不需要 `s3:ListBucket`。

容器会等待 PostgreSQL 就绪、执行 Alembic 迁移并启动服务：

- Web：<http://localhost:5173>
- API 文档：<http://localhost:8000/docs>
- API 存活检查：<http://localhost:8000/health>
- 数据库就绪检查：<http://localhost:8000/health/database>

停止服务：

```bash
docker compose down
```

数据库保存在命名卷 `postgres-data` 中，普通 `docker compose down` 不会删除数据。

## 本地开发

### 环境要求

- Python 3.14.x；
- Node.js 22.22.0 或更高版本；
- pnpm 10.33.0；
- PostgreSQL；
- 私有 S3 Bucket 和 OpenAI API Key。

### 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e "./apps/api[dev]"

corepack enable
pnpm install
```

### 配置

```bash
cp apps/api/.env.example apps/api/.env
cp apps/web/.env.example apps/web/.env
```

核心后端配置：

```dotenv
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_DEFAULT_REGION=us-east-1
S3_BUCKET=...
OPENAI_API_KEY=...
MODEL_NAME=...
IMAGE_GENERATION_MODEL=...
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/ai_image
```

不要把 AWS 或 OpenAI 密钥放入 `apps/web/.env`。所有 `VITE_` 变量都会进入浏览器构建产物。

### 数据库迁移

```bash
cd apps/api
../../.venv/bin/python -m alembic upgrade head
cd ../..
```

### 启动

终端一：

```bash
.venv/bin/python -m uvicorn app.main:app \
  --app-dir apps/api \
  --reload \
  --reload-dir apps/api \
  --port 8000
```

终端二：

```bash
pnpm dev
```

## API

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/health` | API 存活检查 |
| `GET` | `/health/database` | PostgreSQL 就绪检查 |
| `POST` | `/api/v1/images/presign-upload` | 创建 S3 预签名上传表单 |
| `POST` | `/api/v1/images/analyze` | 分析已上传图片 |
| `POST` | `/api/v1/images/generations` | 创建图片生成任务 |
| `GET` | `/api/v1/images/generations` | 分页查询生成历史 |
| `GET` | `/api/v1/images/generations/{id}` | 查询单条记录 |
| `GET` | `/api/v1/images/generations/{id}/download` | 获取临时下载地址 |
| `DELETE` | `/api/v1/images/generations/{id}` | 软删除记录 |

## 质量检查

```bash
# 后端
.venv/bin/python -m ruff check apps/api evals
.venv/bin/python -m pytest apps/api/tests -q

# 前端
pnpm lint
pnpm test
pnpm build
```

后端测试会 Mock S3 和 OpenAI，不需要真实凭证，也不会产生模型费用。GitHub Actions 会在 Pull Request 和 `main` 分支推送时执行相同检查。

## 离线工作流评估

确定性评估运行器会执行真实的 `ImageService` 编排逻辑，但用内存实现替代 PostgreSQL、S3、OpenAI Vision 和 OpenAI Images。它在不访问云服务、不产生费用的前提下，测量正常路径完成率、注入故障收敛率、数据库与对象状态一致性、孤儿输出和并发执行情况。

```bash
.venv/bin/python -m evals.validation
.venv/bin/python -m evals.run_workflow \
  --dataset evals/datasets/workflow_smoke_v1.jsonl \
  --concurrency 4
```

证据文件会写入已被 Git 忽略的 `evals/results/` 目录。指标定义和验收规则见 [`evals/EVALUATION_PROTOCOL.md`](evals/EVALUATION_PROTOCOL.md)。Mock 服务延迟不能当作生产环境延迟。

## 可观测性

API 为每个响应添加 `X-Request-ID`，并输出单行 JSON 请求日志：

```json
{"timestamp":"2026-10-12T18:00:00+00:00","level":"INFO","logger":"app.main","message":"request_completed","request_id":"...","method":"GET","path":"/health","status_code":200,"duration_ms":0.42}
```

调用方可以传入不超过 128 个字符的 `X-Request-ID`，用于串联客户端与服务端日志。

启用 Langfuse 后，每次图片工作流会生成一条根 Trace，并在其下记录 PostgreSQL、S3、OpenAI 视觉分析和图片生成步骤。模型 Observation 会记录模型名与 Token 用量，便于按工作流分析延迟、错误、用量以及配置后的模型费用。

```dotenv
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://us.cloud.langfuse.com
LANGFUSE_TRACING_ENABLED=true
LANGFUSE_ENVIRONMENT=local-evaluation
```

为保护敏感数据，Trace 不上传 Prompt、模型生成的描述、预签名 URL、S3 Object Key 或图片内容；只记录状态、模型、尺寸、字节数、Token 用量和数据库 ID 等有限的运行元数据。测试或敏感环境可设置 `LANGFUSE_TRACING_ENABLED=false` 完全关闭 Trace。

Langfuse 已内置 `gpt-4.1-mini` 的价格。项目使用的图片模型按文本输入、图片输入和图片输出 Token 分别计费，可先预览、再应用仓库中经过审计的自定义价格配置：

```bash
.venv/bin/python apps/api/scripts/configure_langfuse_model.py
.venv/bin/python apps/api/scripts/configure_langfuse_model.py --apply
```

## S3 CORS

浏览器需要直接上传参考图，因此 Bucket 应允许前端来源：

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

CORS 不会公开私有对象，也不能代替 IAM 权限控制。

## 当前边界

- 图片生成在一次 HTTP 请求内执行，尚未引入后台任务队列；
- 尚未实现用户登录、RBAC 和多租户隔离；
- 尚未实现限流、内容安全审核和模型费用配额；
- 当前没有 RAG 或向量检索能力；
- Docker Compose 面向本地演示，不代表高可用生产部署。

这些边界及后续生产化顺序记录在[架构说明](docs/architecture.zh-CN.md#生产化演进)中。
