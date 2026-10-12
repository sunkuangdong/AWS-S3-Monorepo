# 项目演示脚本

这份脚本用于 5～8 分钟的面试或内部技术展示。演示重点是业务闭环和工程决策，不是逐个介绍框架。

## 演示前准备

```bash
docker compose up --build
```

确认以下地址可访问：

- <http://localhost:5173>
- <http://localhost:8000/docs>
- <http://localhost:8000/health/database>

提前准备一张不超过 10 MB 的 JPEG、PNG 或 WebP 参考图。

## 1. 用一句话说明项目

> 这是一个支持文生图和参考图编辑的全栈 AI 图片平台，浏览器直传私有 S3，FastAPI 编排 OpenAI，PostgreSQL 跟踪任务生命周期。

## 2. 展示文字生成

1. 输入一条有主体、场景、光线和风格的提示词；
2. 点击“生成图片”；
3. 展示生成结果；
4. 打开历史页面，说明任务已经持久化，而不是只保存在浏览器内存中。

建议讲清楚：任务在外部调用前先保存为 `pending`，成功变为 `completed`，外部调用异常则记录为 `failed`。

## 3. 展示参考图编辑

1. 上传准备好的参考图；
2. 输入明确的编辑要求；
3. 生成并对比输入与输出。

建议讲清楚：浏览器使用预签名 POST 直传 S3；后端通过视觉模型分析参考图，再组合编辑提示词调用图片编辑模型。

## 4. 展示历史管理

在历史页面依次展示：

- 分页查询；
- 临时签名地址预览；
- 下载图片；
- 软删除记录。

说明数据库保存 object key，而不是长期公开 URL；每次读取时生成短期访问地址。

## 5. 展示工程质量

```bash
.venv/bin/python -m ruff check apps/api
.venv/bin/python -m pytest apps/api/tests -q
pnpm lint
pnpm test
pnpm build
```

随后展示 `.github/workflows/ci.yml`，说明这些检查也会在 Pull Request 中自动执行。

## 6. 展示可观测性

```bash
curl -i -H 'X-Request-ID: interview-demo-001' \
  http://localhost:8000/health
```

指出响应头中的 `X-Request-ID`，再从 API JSON 日志中找到同一个 ID、响应状态和耗时。

## 7. 主动说明边界

> 当前版本定位是工程化 MVP。生产化下一步会把长耗时生成迁移到任务队列，并增加幂等重试、认证授权、租户隔离、Metrics/Trace、成本治理和内容安全。多模态素材检索会在业务需要后通过 pgvector 和 OpenCLIP 引入。

主动说明边界可以体现技术判断，避免把本地演示环境包装成已经通过生产验证的系统。
