"""Network-free FastAPI application with capacity-only resource endpoints."""

from __future__ import annotations

import os

os.environ["LANGFUSE_TRACING_ENABLED"] = "false"

from app.api.router import api_router
from app.db.session import engine
from app.dependencies import (
    get_openai_image_generation_client,
    get_openai_vision_client,
    get_s3_storage_client,
)
from app.main import (
    database_health_check,
    health_check,
    lifespan,
    request_observability,
)
from fastapi import FastAPI

from evals.capacity_metrics import collect_capacity_metrics
from evals.capacity_protocol import (
    CAPACITY_PROTOCOL_STATUS,
    CAPACITY_PROTOCOL_VERSION,
)
from evals.load_stubs import (
    DeterministicImageGenerationStub,
    DeterministicStorageStub,
    DeterministicVisionStub,
)


def _non_negative_delay(name: str, default: int) -> int:
    raw_value = os.getenv(name, str(default))
    try:
        value = int(raw_value)
    except ValueError as error:
        raise RuntimeError(f"{name} must be an integer") from error
    if value < 0:
        raise RuntimeError(f"{name} must be non-negative")
    return value


storage_stub = DeterministicStorageStub(
    delay_ms=_non_negative_delay("CAPACITY_STUB_STORAGE_DELAY_MS", 0),
)
vision_stub = DeterministicVisionStub(
    delay_ms=_non_negative_delay("CAPACITY_STUB_VISION_DELAY_MS", 50),
)
image_generation_stub = DeterministicImageGenerationStub(
    delay_ms=_non_negative_delay("CAPACITY_STUB_IMAGE_DELAY_MS", 250),
)

app = FastAPI(
    title="AI Image API - Capacity Experiment",
    version=f"{CAPACITY_PROTOCOL_VERSION}-{CAPACITY_PROTOCOL_STATUS}",
    lifespan=lifespan,
)
app.middleware("http")(request_observability)
app.include_router(api_router)
app.add_api_route(
    "/health",
    health_check,
    methods=["GET"],
    response_model=dict[str, str],
    tags=["system"],
)
app.add_api_route(
    "/health/database",
    database_health_check,
    methods=["GET"],
    response_model=dict[str, str],
    tags=["system"],
)

app.dependency_overrides[get_s3_storage_client] = lambda: storage_stub
app.dependency_overrides[get_openai_vision_client] = lambda: vision_stub
app.dependency_overrides[get_openai_image_generation_client] = (
    lambda: image_generation_stub
)


@app.get("/capacity-test/status", include_in_schema=False)
def capacity_test_status() -> dict[str, object]:
    return {
        "capacity_test": True,
        "protocol_version": CAPACITY_PROTOCOL_VERSION,
        "protocol_status": CAPACITY_PROTOCOL_STATUS,
        "cloud_calls_enabled": False,
        "langfuse_tracing_enabled": False,
        "real_postgresql_enabled": True,
        "stubs": {
            "storage": storage_stub.snapshot(),
            "vision": vision_stub.snapshot(),
            "image_generation": image_generation_stub.snapshot(),
        },
    }


@app.get("/capacity-test/metrics", include_in_schema=False)
async def capacity_test_metrics() -> dict[str, object]:
    return await collect_capacity_metrics(engine)
