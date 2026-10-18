import json
import os
from pathlib import Path

import pytest
from evals.production_capacity import (
    StageSpec,
    build_summary,
    load_cases,
    parse_stage,
    resource_summary,
)
from evals.run_production_capacity import (
    DEFAULT_DATASET,
    ProductionCapacityError,
    _enforce_resource_metrics_preflight,
    _load_default_environment,
    _metrics_payload,
    _sanitize_run,
    _validated_url,
)


def _successful_run(sequence: int) -> dict:
    return {
        "sequence": sequence,
        "api_completed": True,
        "database_verified": True,
        "database_record_found": True,
        "s3_verified": True,
        "trace_complete": True,
        "privacy_safe": True,
        "model_compliant": True,
        "cost_measured": True,
        "total_cost_usd": 0.04,
        "api_latency_ms": 1_000.0,
    }


def test_explicit_target_environment_overrides_local_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "S3_BUCKET=default-development-bucket\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("S3_BUCKET", "isolated-capacity-bucket")

    _load_default_environment(env_file)

    assert os.environ["S3_BUCKET"] == "isolated-capacity-bucket"


def test_required_resource_metrics_fail_preflight_when_unavailable() -> None:
    with pytest.raises(ProductionCapacityError) as raised:
        _enforce_resource_metrics_preflight(
            None,
            required=True,
            error_type="UnexpectedHTTPStatus",
        )

    assert raised.value.stage == "resource_metrics"
    assert raised.value.error_type == "UnexpectedHTTPStatus"


def test_dataset_and_stage_parser_cover_both_workflows() -> None:
    cases = load_cases(DEFAULT_DATASET)
    assert {case.generation_type for case in cases} == {
        "text_to_image",
        "image_to_image",
    }

    ramp = parse_stage("ramp:0.5-2:4")
    assert ramp == StageSpec("ramp", 0.5, 2.0, 4)
    assert ramp.rates() == [0.5, 1.0, 1.5, 2.0]
    assert parse_stage("steady:3:2").rates() == [3.0, 3.0]


@pytest.mark.parametrize(
    "value",
    ["unknown:1:2", "ramp:2-1:2", "steady:0:2", "steady:1:0"],
)
def test_stage_parser_rejects_unsafe_values(value: str) -> None:
    with pytest.raises(ValueError):
        parse_stage(value)


def test_summary_passes_only_complete_observed_run() -> None:
    runs = [_successful_run(1), _successful_run(2)]
    resources = resource_summary(
        [
            {
                "cpu_percent": 45.0,
                "memory_percent": 50.0,
                "database_active_connections": 20.0,
                "database_max_connections": 100.0,
            }
        ]
    )
    summary = build_summary(
        runs,
        stages=[],
        planned_count=2,
        maximum_cost_usd=0.10,
        minimum_success_rate=0.99,
        database_scan={
            "missing_count": 0,
            "duplicate_count": 0,
            "unexpected_pending_count": 0,
        },
        orphan_scan={"available": True, "orphan_output_count": 0},
        resources=resources,
        maximum_cpu_percent=80,
        maximum_memory_percent=80,
        maximum_database_connection_percent=80,
        stopped_reason=None,
    )

    assert summary["cost_usd"]["total"] == 0.08
    assert summary["acceptance_gates"]["overall"] is True


def test_missing_resource_metrics_prevent_production_claim() -> None:
    summary = build_summary(
        [_successful_run(1)],
        stages=[],
        planned_count=1,
        maximum_cost_usd=0.10,
        minimum_success_rate=0.99,
        database_scan={
            "missing_count": 0,
            "duplicate_count": 0,
            "unexpected_pending_count": 0,
        },
        orphan_scan={"available": True, "orphan_output_count": 0},
        resources=resource_summary([]),
        maximum_cpu_percent=80,
        maximum_memory_percent=80,
        maximum_database_connection_percent=80,
        stopped_reason=None,
    )

    assert summary["acceptance_gates"]["resource_metrics_available"] is False
    assert summary["acceptance_gates"]["overall"] is False


def test_target_url_requires_exact_host_and_remote_https() -> None:
    assert (
        _validated_url(
            "https://api.example.com",
            expected_host="api.example.com",
            name="API",
        )
        == "https://api.example.com"
    )
    with pytest.raises(ValueError, match="HTTPS"):
        _validated_url(
            "http://api.example.com",
            expected_host="api.example.com",
            name="API",
        )
    with pytest.raises(ValueError, match="expected-api-host"):
        _validated_url(
            "https://wrong.example.com",
            expected_host="api.example.com",
            name="API",
        )


def test_metrics_contract_is_bounded_numeric_data() -> None:
    assert _metrics_payload(
        {
            "cpu_percent": 10,
            "memory_percent": 20,
            "database_active_connections": 3,
            "database_max_connections": 100,
            "ignored_secret": "not copied",
        }
    ) == {
        "cpu_percent": 10.0,
        "memory_percent": 20.0,
        "database_active_connections": 3.0,
        "database_max_connections": 100.0,
    }


def test_persisted_run_omits_private_values() -> None:
    run = {
        "sequence": 1,
        "api_completed": True,
        "_tracking_token": "private-token",
        "_generation_id": "private-generation-id",
        "_output_object_key": "generations/private.png",
    }
    serialized = json.dumps(_sanitize_run(run))
    assert "private" not in serialized
    assert "sequence" in serialized
