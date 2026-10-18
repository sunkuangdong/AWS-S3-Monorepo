from typing import Any

import httpx
import pytest
from evals.capacity_v2_protocol import (
    CAPACITY_V2_PROTOCOL_STATUS,
    CAPACITY_V2_PROTOCOL_VERSION,
    REQUIRED_ACCEPTANCE_GATES,
    validate_capacity_v2_protocol,
)
from evals.capacity_v2_scoring import build_capacity_v2_summary
from evals.run_capacity_v2 import (
    _capacity_v2_stub_calls_match,
    _retry_verification_transport_failures,
    _scan_capacity_v2_records,
    capacity_v2_preflight,
)


def _capacity_v2_status() -> dict[str, Any]:
    delays = {"storage": 0, "vision": 50, "image_generation": 250}
    return {
        "capacity_v2_test": True,
        "protocol_version": "2.0.0",
        "protocol_status": "candidate",
        "cloud_calls_enabled": False,
        "langfuse_tracing_enabled": False,
        "real_postgresql_enabled": True,
        "stubs": {
            name: {
                "provider": "stub",
                "network_enabled": False,
                "delay_ms": delays[name],
                "calls": {},
            }
            for name in delays
        },
    }


@pytest.mark.anyio
async def test_capacity_v2_preflight_locks_identity_and_cloud_isolation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path in {"/health", "/health/database"}:
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/capacity-v2-test/status":
            return httpx.Response(200, json=_capacity_v2_status())
        if request.url.path == "/capacity-v2-test/metrics":
            return httpx.Response(
                200,
                json={
                    "container": {
                        "cpu_usage_usec": 100,
                        "memory_current_bytes": 1000,
                    },
                    "postgresql": {
                        "active_connections": 0,
                        "pool_checked_out": 0,
                    },
                },
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:8003",
        transport=httpx.MockTransport(handler),
    ) as client:
        result = await capacity_v2_preflight(client)

    manifest = validate_capacity_v2_protocol(
        concurrencies=[64, 96, 128, 192, 256],
        requests_per_tier=1000,
        warmup_requests_per_tier=64,
        timeout_seconds=30.0,
        sample_interval_seconds=0.05,
        preflight_result=result,
    )
    assert result["resource_metrics_available"] is True
    assert manifest["protocol_version"] == CAPACITY_V2_PROTOCOL_VERSION == "2.0.0"
    assert manifest["status"] == CAPACITY_V2_PROTOCOL_STATUS == "candidate"
    assert manifest["required_acceptance_gates"] == list(
        REQUIRED_ACCEPTANCE_GATES
    )


def test_capacity_v2_protocol_rejects_parameter_drift() -> None:
    with pytest.raises(ValueError, match="concurrencies does not match"):
        validate_capacity_v2_protocol(
            concurrencies=[64, 128, 256],
            requests_per_tier=1000,
            warmup_requests_per_tier=64,
            timeout_seconds=30.0,
            sample_interval_seconds=0.05,
        )


@pytest.mark.anyio
async def test_capacity_v2_retries_only_verification_transport_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/images/generations/generation-1"
        return httpx.Response(
            200,
            json={
                "id": "generation-1",
                "status": "completed",
                "output_object_key": "private-key",
                "output_url": "private-url",
            },
        )

    runs = [
        {
            "request_id": "request-1",
            "api_completed": True,
            "generation_id": "generation-1",
            "database_verified": False,
            "verification_error_type": "RemoteProtocolError",
        },
        {
            "request_id": "request-2",
            "api_completed": True,
            "generation_id": "generation-2",
            "database_verified": False,
            "verification_error_type": "DatabaseStateMismatch",
        },
    ]
    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:8003",
        transport=httpx.MockTransport(handler),
    ) as client:
        result, retry_summary = await _retry_verification_transport_failures(
            client,
            runs,
        )

    assert retry_summary == {"attempted": 1, "recovered": 1}
    assert result[0]["database_verified"] is True
    assert result[1] == runs[1]


@pytest.mark.anyio
async def test_capacity_v2_scans_only_run_scoped_private_records() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/capacity-v2-test/records"
        assert request.url.params["run_id"] == "capacity-v2-20261018T010000Z-deadbeef"
        return httpx.Response(
            200,
            json={
                "run_id": request.url.params["run_id"],
                "records": [
                    {
                        "id": "generation-1",
                        "status": "completed",
                        "generation_type": "text_to_image",
                        "output_present": True,
                    }
                ],
            },
        )

    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:8003",
        transport=httpx.MockTransport(handler),
    ) as client:
        records = await _scan_capacity_v2_records(
            client,
            run_id="capacity-v2-20261018T010000Z-deadbeef",
        )

    assert records == [
        {
            "id": "generation-1",
            "status": "completed",
            "generation_type": "text_to_image",
            "output_present": True,
        }
    ]


def test_capacity_v2_stub_counts_allow_one_presign_per_readback_retry() -> None:
    delta = {
        "image_generation": {"generate_image": 10},
        "vision": {},
        "storage": {
            "upload_generated_image": 10,
            "create_presigned_download_url": 21,
        },
    }
    assert _capacity_v2_stub_calls_match(
        delta,
        expected_request_count=10,
        verification_retry_attempts=1,
    )
    delta["storage"]["create_presigned_download_url"] = 22
    assert not _capacity_v2_stub_calls_match(
        delta,
        expected_request_count=10,
        verification_retry_attempts=1,
    )


def _tier(concurrency: int, throughput: float, p95: float) -> dict[str, Any]:
    return {
        "concurrency": concurrency,
        "request_count": 1000,
        "throughput_rps": throughput,
        "success_rate": 1.0,
        "speedup_vs_concurrency_1": 1.0,
        "scaling_efficiency": 1.0,
        "latency_ms": {"p95_nearest_rank": p95},
    }


def test_capacity_v2_scoring_finds_normalized_scaling_knee() -> None:
    load_summary = {
        "tiers": [
            _tier(64, 160.0, 300.0),
            _tier(96, 220.0, 305.0),
            _tier(128, 230.0, 310.0),
            {
                **_tier(192, 0.0, 0.0),
                "request_count": 0,
                "success_rate": None,
            },
        ],
        "acceptance_gates": {"preflight_passed": True, "overall": True},
    }
    resource_tiers = [
        {
            "concurrency": concurrency,
            "sample_count": 5,
            "sample_error_count": 0,
            "api_container": {
                "average_cpu_percent": 50.0,
                "maximum_memory_current_bytes": 1000,
            },
        }
        for concurrency in (64, 96, 128)
    ]

    summary = build_capacity_v2_summary(
        load_summary=load_summary,
        resource_tiers=resource_tiers,
        baseline_concurrency=64,
        saturation_signals={
            "maximum_marginal_scaling_efficiency": 0.5,
            "minimum_p95_latency_growth": 0.5,
            "maximum_scaling_efficiency": 0.5,
        },
    )

    assert summary["saturation_analysis"]["first_candidate"] == {
        "concurrency": 128,
        "signals": ["marginal_scaling_efficiency_below_50_percent"],
    }
    assert summary["tiers"][0]["speedup_vs_baseline"] == 1.0
    assert summary["tiers"][2]["marginal_scaling_efficiency"] == 0.136
    assert summary["tiers"][3]["executed"] is False
    assert summary["tiers"][3]["saturation_signals"] == []
    assert len(summary["saturation_analysis"]["all_candidates"]) == 1
    assert summary["acceptance_gates"]["overall"] is True
