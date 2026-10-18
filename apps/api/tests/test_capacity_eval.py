from pathlib import Path
from typing import Any

import httpx
import pytest
from evals.capacity_metrics import read_cgroup_v2_metrics
from evals.capacity_protocol import validate_capacity_protocol
from evals.capacity_scoring import build_capacity_summary
from evals.run_capacity import capacity_preflight


def _write(path: Path, value: str) -> None:
    path.write_text(value, encoding="utf-8")


def test_cgroup_v2_metrics_are_parsed_without_host_identifiers(tmp_path: Path) -> None:
    _write(
        tmp_path / "cpu.stat",
        "usage_usec 12345\nuser_usec 10000\nsystem_usec 2345\n"
        "throttled_usec 99\n",
    )
    _write(tmp_path / "cpu.max", "200000 100000\n")
    _write(tmp_path / "memory.current", "104857600\n")
    _write(tmp_path / "memory.peak", "125829120\n")
    _write(tmp_path / "memory.max", "max\n")

    metrics = read_cgroup_v2_metrics(tmp_path)

    assert metrics == {
        "cpu_usage_usec": 12345,
        "cpu_user_usec": 10000,
        "cpu_system_usec": 2345,
        "cpu_throttled_usec": 99,
        "cpu_limit_cores": 2.0,
        "memory_current_bytes": 104857600,
        "memory_peak_bytes": 125829120,
        "memory_limit_bytes": None,
    }


def _capacity_status() -> dict[str, Any]:
    delays = {"storage": 0, "vision": 50, "image_generation": 250}
    return {
        "capacity_test": True,
        "protocol_version": "1.0.0",
        "protocol_status": "exploratory",
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
async def test_capacity_preflight_requires_metrics_and_cloud_isolation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path in {"/health", "/health/database"}:
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/capacity-test/status":
            return httpx.Response(200, json=_capacity_status())
        if request.url.path == "/capacity-test/metrics":
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
        base_url="http://127.0.0.1:8002",
        transport=httpx.MockTransport(handler),
    ) as client:
        result = await capacity_preflight(client)

    manifest = validate_capacity_protocol(
        concurrencies=[1, 4, 8, 16, 32, 64],
        requests_per_tier=200,
        warmup_requests_per_tier=5,
        timeout_seconds=30.0,
        sample_interval_seconds=0.1,
        preflight_result=result,
    )
    assert result["resource_metrics_available"] is True
    assert manifest["status"] == "exploratory"


def test_capacity_scoring_identifies_first_saturation_signal() -> None:
    load_summary = {
        "tiers": [
            {
                "concurrency": 1,
                "throughput_rps": 4.0,
                "success_rate": 1.0,
                "scaling_efficiency": 1.0,
                "latency_ms": {"p95_nearest_rank": 250.0},
            },
            {
                "concurrency": 4,
                "throughput_rps": 15.0,
                "success_rate": 1.0,
                "scaling_efficiency": 0.938,
                "latency_ms": {"p95_nearest_rank": 270.0},
            },
            {
                "concurrency": 8,
                "throughput_rps": 16.0,
                "success_rate": 1.0,
                "scaling_efficiency": 0.5,
                "latency_ms": {"p95_nearest_rank": 500.0},
            },
        ],
        "acceptance_gates": {"preflight_passed": True, "overall": True},
    }
    resource_tiers = [
        {
            "concurrency": concurrency,
            "sample_count": 3,
            "sample_error_count": 0,
            "api_container": {
                "average_cpu_percent": 50.0,
                "maximum_memory_current_bytes": 1000,
            },
        }
        for concurrency in (1, 4, 8)
    ]

    summary = build_capacity_summary(
        load_summary=load_summary,
        resource_tiers=resource_tiers,
        saturation_signals={
            "maximum_marginal_throughput_gain": 0.2,
            "minimum_p95_latency_growth": 0.5,
            "maximum_scaling_efficiency": 0.5,
        },
    )

    assert summary["saturation_analysis"]["first_candidate"] == {
        "concurrency": 8,
        "signals": [
            "throughput_gain_below_20_percent",
            "p95_growth_above_50_percent",
        ],
    }
    assert summary["acceptance_gates"]["overall"] is True
