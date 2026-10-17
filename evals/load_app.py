"""FastAPI application for real-PostgreSQL, network-free load evaluation."""

from __future__ import annotations

import os

# This must be set before importing the production application and observability code.
os.environ["LANGFUSE_TRACING_ENABLED"] = "false"

from app.api.router import api_router
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

from evals.load_protocol import LOAD_PROTOCOL_STATUS, LOAD_PROTOCOL_VERSION
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
    delay_ms=_non_negative_delay("LOAD_STUB_STORAGE_DELAY_MS", 0),
)
vision_stub = DeterministicVisionStub(
    delay_ms=_non_negative_delay("LOAD_STUB_VISION_DELAY_MS", 50),
)
image_generation_stub = DeterministicImageGenerationStub(
    delay_ms=_non_negative_delay("LOAD_STUB_IMAGE_DELAY_MS", 250),
)

app = FastAPI(
    title="AI Image API - Load Evaluation",
    version=f"{LOAD_PROTOCOL_VERSION}-{LOAD_PROTOCOL_STATUS}",
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


@app.get("/load-test/status", include_in_schema=False)
def load_test_status() -> dict[str, object]:
    """Expose a bounded preflight signal proving that cloud clients are disabled."""
    return {
        "load_test": True,
        "protocol_version": LOAD_PROTOCOL_VERSION,
        "protocol_status": LOAD_PROTOCOL_STATUS,
        "cloud_calls_enabled": False,
        "langfuse_tracing_enabled": False,
        "real_postgresql_enabled": True,
        "reference_object_key": DeterministicStorageStub.REFERENCE_OBJECT_KEY,
        "stubs": {
            "storage": storage_stub.snapshot(),
            "vision": vision_stub.snapshot(),
            "image_generation": image_generation_stub.snapshot(),
        },
    }
