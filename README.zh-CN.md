# AI 图片分析平台

简体中文 | [English](README.md)

这是一个采用 monorepo 结构的全栈图片分析学习项目。React 前端通过预签名 POST 将图片直接上传到私有 Amazon S3 Bucket；FastAPI 后端随后创建临时读取地址，并把图片交给支持视觉输入的 OpenAI 模型进行分析。

> 当前范围：仅支持图片理解，暂不支持图片生成或图片编辑。

## 功能

- 在浏览器中选择并预览 JPEG、PNG 或 WebP 图片。
- React 将文件直接上传到私有 S3 Bucket。
- AWS 和 OpenAI 凭证只保存在后端。
- 通过 MIME 类型、文件大小、有效期和随机对象路径限制上传。
- 使用 OpenAI Responses API 分析私有 S3 图片。
- 显示处理进度、错误信息、分析文本和 S3 object key。
- 使用 pnpm/Python monorepo 统一管理前后端代码。

## 系统架构

```text
浏览器（React）
  │
  ├─ 1. 申请预签名 POST ───────────────► FastAPI
  │                                      │
  │                                      └─► Amazon S3 签名
  │
  ├─ 2. 直接上传图片 ──────────────────► 私有 Amazon S3 Bucket
  │
  └─ 3. 提交 object_key ───────────────► FastAPI
                                         │
                                         ├─► 创建 S3 临时读取地址
                                         └─► OpenAI 视觉模型
                                                  │
                                                  └─► 图片文字描述
```

浏览器上传时，图片二进制不会经过 FastAPI。FastAPI 负责配置管理、临时授权、数据验证、业务编排和 OpenAI 访问。

## 技术栈

### 后端

- Python 3.14
- FastAPI 和 Uvicorn
- Boto3（Amazon S3）
- OpenAI Python SDK 和 Responses API
- Pydantic
- python-dotenv

### 前端

- React 19
- TypeScript
- Vite
- pnpm workspace

### 云服务

- 私有 Amazon S3 Bucket
- 遵循最小权限原则的 AWS IAM 用户
- OpenAI API

## 项目结构

```text
.
├── apps/
│   ├── api/
│   │   ├── app/
│   │   │   ├── api/             # FastAPI 路由
│   │   │   ├── clients/         # S3 和 OpenAI 适配器
│   │   │   ├── core/            # 配置与异常
│   │   │   ├── schemas/         # Pydantic 请求/响应模型
│   │   │   ├── services/        # 应用业务流程
│   │   │   ├── dependencies.py  # 带缓存的依赖构造
│   │   │   └── main.py          # FastAPI 应用入口
│   │   ├── .env                 # 后端密钥，禁止提交
│   │   └── pyproject.toml
│   └── web/
│       ├── src/
│       │   ├── api/             # 浏览器 API 和 S3 请求
│       │   ├── types/           # 前端数据结构
│       │   └── App.tsx
│       ├── .env                 # Vite 公开配置
│       └── package.json
├── .venv/                       # 前后端工作区共用的 Python 虚拟环境
├── package.json                 # 根目录前端脚本
└── pnpm-workspace.yaml
```

## 前置条件

- Python `3.14.x`
- Node.js `22.22.0` 或更高版本
- pnpm `10.33.0` 或兼容版本
- 一个包含私有 S3 Bucket 的 AWS 账户
- 一个可以上传和读取该 Bucket 对象的 IAM Access Key
- 一个能够调用视觉模型的 OpenAI API Key

后端使用的 IAM 身份至少需要等价于以下权限：

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

## 安装依赖

在仓库根目录执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e "./apps/api[dev]"

corepack enable
pnpm install
```

如果使用 `nvm`，运行 pnpm 前先选择项目所需的 Node.js 版本：

```bash
nvm use 22
```

## 环境变量

### 后端：`apps/api/.env`

```dotenv
AWS_ACCESS_KEY_ID=你的_IAM_Access_Key_ID
AWS_SECRET_ACCESS_KEY=你的_IAM_Secret_Access_Key
AWS_DEFAULT_REGION=us-east-1
S3_BUCKET=你的私有_Bucket_名称

OPENAI_API_KEY=你的_OpenAI_API_Key
MODEL_NAME=你的账户可用的视觉模型

S3_PRESIGNED_URL_EXPIRES=600
MAX_UPLOAD_BYTES=10485760
FRONTEND_ORIGIN=http://localhost:5173
```

### 前端：`apps/web/.env`

```dotenv
VITE_API_BASE_URL=http://localhost:8000
```

只有以 `VITE_` 开头的变量才会暴露给浏览器代码。不要把 AWS Secret Key 或 OpenAI API Key 放进前端环境文件。

## S3 CORS

浏览器会直接上传到 S3，因此 Bucket 需要允许前端来源：

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

请保持 Bucket 私有。CORS 只控制浏览器的跨来源行为，不能代替 IAM 权限，也不会自动公开对象。

## 本地启动

在仓库根目录打开两个终端。

### 终端一：FastAPI

```bash
.venv/bin/python -m uvicorn app.main:app \
  --app-dir apps/api \
  --reload \
  --reload-dir apps/api \
  --port 8000
```

常用后端地址：

- 健康检查：<http://127.0.0.1:8000/health>
- OpenAPI 文档：<http://127.0.0.1:8000/docs>

### 终端二：React

```bash
nvm use 22
pnpm dev
```

打开 <http://localhost:5173>。建议使用 `localhost`，不要改成 `127.0.0.1`，这样浏览器来源才能与 CORS 配置完全一致。

## API 接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/health` | 检查 API 进程是否运行。 |
| `POST` | `/api/v1/images/presign-upload` | 创建临时 S3 预签名 POST。 |
| `POST` | `/api/v1/images/analyze` | 使用 OpenAI 分析已经上传到 S3 的图片。 |

申请上传凭证示例：

```json
{
  "file_name": "dog.jpg",
  "content_type": "image/jpeg"
}
```

图片分析请求示例：

```json
{
  "object_key": "uploads/generated-object-name.jpg",
  "prompt": "请描述图片中的主要物体、场景和颜色。"
}
```

## 开发命令

```bash
# 启动前端开发服务器
pnpm dev

# 构建前端生产版本
pnpm build

# 检查前端代码
pnpm lint

# 检查后端代码
.venv/bin/python -m ruff check apps/api
```

## 安全说明

- 禁止提交 `.env` 文件或访问密钥。
- 应用程序不要使用 AWS root user 的 Access Key。
- 保持 S3 Bucket 私有，并且只授予必需的对象操作权限。
- 预签名地址和表单属于临时凭证，应使用较短的有效期。
- 后端目前只接受 `uploads/` 目录中的 object key。
- 在作为生产文件服务之前，还需要加入登录、授权、限流、恶意文件扫描和持久化元数据。

## 当前限制

- 仅支持图片分析，尚未实现图片生成或编辑。
- 尚未实现用户登录和多租户隔离。
- 尚未使用 PostgreSQL 持久化文件元数据。
- 尚未建立自动化测试套件。
- 为方便学习和调试，接口会把生成的 object key 返回给浏览器。

