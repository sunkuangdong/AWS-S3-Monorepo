from typing import Any

import httpx
import pytest
from evals.load_protocol import (
    LOAD_PROTOCOL_STATUS,
    LOAD_PROTOCOL_VERSION,
    REQUIRED_ACCEPTANCE_GATES,
    validate_load_protocol,
)
from evals.load_scoring import build_load_summary
from evals.run_load import parse_concurrencies, preflight, validate_local_base_url


def _stub_status() -> dict[str, Any]:
    delays = {
        "storage": 0,
        "vision": 50,
        "image_generation": 250,
    }
    return {
        "load_test": True,
        "protocol_version": "1.0.0",
        "protocol_status": "frozen",
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
            for name in ("storage", "vision", "image_generation")
        },
    }


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:8001",
        "http://example.com:8001",
        "http://user:password@localhost:8001",
        "http://localhost:8001/api",
        "http://localhost",
    ],
)
def test_load_runner_rejects_non_loopback_or_ambiguous_urls(url: str) -> None:
    with pytest.raises(ValueError):
        validate_local_base_url(url)


def test_load_runner_accepts_ordered_positive_concurrency_tiers() -> None:
    assert validate_local_base_url("http://127.0.0.1:8001") == (
        "http://127.0.0.1:8001"
    )
    assert parse_concurrencies("1,4,8,16") == [1, 4, 8, 16]


def test_load_protocol_locks_frozen_parameters_evidence_and_gates() -> None:
    manifest = validate_load_protocol(
        concurrencies=[1, 4, 8, 16],
        requests_per_tier=40,
        warmup_requests_per_tier=5,
        timeout_seconds=30.0,
    )

    assert manifest["protocol_version"] == LOAD_PROTOCOL_VERSION == "1.0.0"
    assert manifest["status"] == LOAD_PROTOCOL_STATUS == "frozen"
    assert manifest["freeze"] == {
        "git_tag": "load-eval-v1.0.0",
        "implementation_baseline_commit": (
            "0d917ef6cfb1304b37fff37df153e918ad8134f5"
        ),
        "evidence_path": "evals/evidence/load_v1_summary.json",
        "evidence_sha256": (
            "8449d2daa3d56d3f070cb7ce65360965e32f56a7b09e88c33442fc7e84175841"
        ),
    }
    assert manifest["required_acceptance_gates"] == list(
        REQUIRED_ACCEPTANCE_GATES
    )


def test_load_protocol_rejects_parameter_drift_unless_exploratory() -> None:
    with pytest.raises(ValueError, match="concurrencies does not match"):
        validate_load_protocol(
            concurrencies=[1, 4, 8, 16, 32],
            requests_per_tier=40,
            warmup_requests_per_tier=5,
            timeout_seconds=30.0,
        )

    manifest = validate_load_protocol(
        concurrencies=[1, 4, 8, 16, 32],
        requests_per_tier=40,
        warmup_requests_per_tier=5,
        timeout_seconds=30.0,
        allow_parameter_deviation=True,
    )
    assert manifest["protocol_version"] == "1.0.0"


@pytest.mark.anyio
async def test_preflight_requires_real_database_and_network_free_stubs() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/health/database":
            return httpx.Response(200, json={"database": "reachable"})
        if request.url.path == "/load-test/status":
            return httpx.Response(200, json=_stub_status())
        return httpx.Response(404)

    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:8001",
        transport=httpx.MockTransport(handler),
    ) as client:
        result = await preflight(client)

    assert result["passed"] is True
    assert result["cloud_calls_enabled"] is False
    assert result["checks"] == {
        "/health": 200,
        "/health/database": 200,
    }
    manifest = validate_load_protocol(
        concurrencies=[1, 4, 8, 16],
        requests_per_tier=40,
        warmup_requests_per_tier=5,
        timeout_seconds=30.0,
        preflight_result=result,
    )
    assert manifest["stub_delays_ms"]["image_generation"] == 250


def _run(phase: str, concurrency: int, number: int) -> dict[str, Any]:
    return {
        "phase": phase,
        "concurrency": concurrency,
        "request_number": number,
        "status_code": 201,
        "api_completed": True,
        "database_verified": True,
        "latency_ms": 100.0 + number,
        "error_type": None,
    }


def test_load_summary_passes_only_complete_consistent_workload() -> None:
    runs = [
        _run(phase, concurrency, number)
        for concurrency in (1, 4)
        for phase, count in (("warmup", 1), ("measured", 2))
        for number in range(1, count + 1)
    ]
    database_records = [
        {
            "id": f"generation-{index}",
            "status": "completed",
            "generation_type": "text_to_image",
            "output_present": True,
        }
        for index in range(6)
    ]

    summary = build_load_summary(
        runs=runs,
        tier_timings=[
            {"concurrency": 1, "elapsed_seconds": 0.4, "max_in_flight": 1},
            {"concurrency": 4, "elapsed_seconds": 0.1, "max_in_flight": 2},
        ],
        concurrencies=[1, 4],
        requests_per_tier=2,
        warmup_requests_per_tier=1,
        database_records=database_records,
        preflight_passed=True,
        cloud_calls_enabled=False,
        stub_calls_match_workload=True,
        stopped_reason=None,
    )

    assert summary["acceptance_gates"]["overall"] is True
    assert list(summary["acceptance_gates"]) == list(REQUIRED_ACCEPTANCE_GATES)
    assert summary["cost_usd"] == 0.0
    assert summary["tiers"][0]["throughput_rps"] == 5.0
    assert summary["tiers"][1]["throughput_rps"] == 20.0
    assert summary["tiers"][1]["scaling_efficiency"] == 1.0


def test_load_summary_rejects_pending_database_record() -> None:
    run = _run("measured", 1, 1)
    summary = build_load_summary(
        runs=[run],
        tier_timings=[
            {"concurrency": 1, "elapsed_seconds": 0.2, "max_in_flight": 1}
        ],
        concurrencies=[1],
        requests_per_tier=1,
        warmup_requests_per_tier=0,
        database_records=[
            {
                "id": "generation-1",
                "status": "pending",
                "generation_type": "text_to_image",
                "output_present": False,
            }
        ],
        preflight_passed=True,
        cloud_calls_enabled=False,
        stub_calls_match_workload=True,
        stopped_reason=None,
    )

    assert summary["acceptance_gates"]["database_state_consistent"] is False
    assert summary["acceptance_gates"]["no_unexpected_pending_records"] is False
    assert summary["acceptance_gates"]["all_load_records_completed"] is False
    assert summary["acceptance_gates"]["overall"] is False
