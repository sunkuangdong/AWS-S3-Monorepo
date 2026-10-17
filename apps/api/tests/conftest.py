import os

import pytest

_TEST_ENVIRONMENT = {
    "AWS_DEFAULT_REGION": "us-east-1",
    "S3_BUCKET": "test-image-bucket",
    "OPENAI_API_KEY": "test-openai-key",
    "MODEL_NAME": "test-vision-model",
    "IMAGE_GENERATION_MODEL": "test-image-model",
    "DATABASE_URL": "postgresql+psycopg://postgres:postgres@localhost:5432/test_db",
    "FRONTEND_ORIGIN": "http://localhost:5173",
    "LANGFUSE_TRACING_ENABLED": "false",
}

for name, value in _TEST_ENVIRONMENT.items():
    os.environ.setdefault(name, value)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
