from typing import Any

import httpx
import pytest
from evals.capacity_v3_protocol import (
    CAPACITY_V3_IMPLEMENTATION_BASELINE_COMMIT,
    CAPACITY_V3_PROTOCOL_STATUS,
    CAPACITY_V3_PROTOCOL_VERSION,
    validate_capacity_v3_protocol,
)
from evals.run_capacity_v3 import capacity_v3_preflight

from app.core.config import integer_environment_variable


def _status() -> dict[str, Any]:
    delays = {"storage": 0, "vision": 50, "image_generation": 250}
    return {
        "capacity_v3_test": True,
        "protocol_version": "3.0.0",
        "protocol_status": "frozen",
        "cloud_calls_enabled": False,
        "langfuse_tracing_enabled": False,
        "real_postgresql_enabled": True,
        "database_pool": {
            "pool_size": 20,
            "max_overflow": 20,
            "timeout_seconds": 30,
        },
        "stubs": {
            name: {
                "provider": "stub",
                "network_enabled": False,
                "delay_ms": delay,
                "calls": {},
            }
            for name, delay in delays.items()
        },
    }


def test_integer_environment_variable_validates_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TEST_POOL_SIZE", raising=False)
    assert integer_environment_variable("TEST_POOL_SIZE", 5, minimum=1) == 5
    monkeypatch.setenv("TEST_POOL_SIZE", "20")
    assert integer_environment_variable("TEST_POOL_SIZE", 5, minimum=1) == 20
    monkeypatch.setenv("TEST_POOL_SIZE", "0")
    with pytest.raises(RuntimeError, match="大于或等于 1"):
        integer_environment_variable("TEST_POOL_SIZE", 5, minimum=1)


@pytest.mark.anyio
async def test_capacity_v3_preflight_proves_single_variable_pool_change() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path in {"/health", "/health/database"}:
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/capacity-v3-test/status":
            return httpx.Response(200, json=_status())
        if request.url.path == "/capacity-v3-test/metrics":
            return httpx.Response(
                200,
                json={
                    "container": {
                        "cpu_usage_usec": 100,
                        "memory_current_bytes": 1000,
                    },
                    "postgresql": {
                        "active_connections": 0,
                        "pool_size": 20,
                    },
                },
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:8004",
        transport=httpx.MockTransport(handler),
    ) as client:
        preflight = await capacity_v3_preflight(client)

    manifest = validate_capacity_v3_protocol(
        mode="pilot",
        concurrencies=[64, 96],
        requests_per_tier=1000,
        warmup_requests_per_tier=64,
        timeout_seconds=30.0,
        sample_interval_seconds=0.05,
        preflight_result=preflight,
    )
    assert preflight["database_pool"] == {
        "pool_size": 20,
        "max_overflow": 20,
        "timeout_seconds": 30,
    }
    assert manifest["optimization"]["single_variable"] == (
        "sqlalchemy_connection_pool_capacity"
    )
    assert manifest["protocol_version"] == CAPACITY_V3_PROTOCOL_VERSION == "3.0.0"
    assert manifest["status"] == CAPACITY_V3_PROTOCOL_STATUS == "frozen"
    assert manifest["freeze"] == {
        "git_tag": "capacity-eval-v3.0.0",
        "implementation_baseline_commit": (
            CAPACITY_V3_IMPLEMENTATION_BASELINE_COMMIT
        ),
        "evidence_path": "evals/evidence/capacity_v3_validation_summary.json",
        "evidence_sha256": (
            "1e3abdb016cc62637eb93e9c0c527e4903ca7e803b5c4d7b645f39cf636b7cd8"
        ),
    }


def test_capacity_v3_protocol_locks_pilot_and_full_modes() -> None:
    pilot = validate_capacity_v3_protocol(
        mode="pilot",
        concurrencies=[64, 96],
        requests_per_tier=1000,
        warmup_requests_per_tier=64,
        timeout_seconds=30.0,
        sample_interval_seconds=0.05,
    )
    full = validate_capacity_v3_protocol(
        mode="full",
        concurrencies=[64, 96, 128, 192, 256],
        requests_per_tier=1000,
        warmup_requests_per_tier=64,
        timeout_seconds=30.0,
        sample_interval_seconds=0.05,
    )
    assert pilot["protocol_version"] == full["protocol_version"] == "3.0.0"
    with pytest.raises(ValueError, match="pilot parameters do not match"):
        validate_capacity_v3_protocol(
            mode="pilot",
            concurrencies=[64],
            requests_per_tier=1000,
            warmup_requests_per_tier=64,
            timeout_seconds=30.0,
            sample_interval_seconds=0.05,
        )
