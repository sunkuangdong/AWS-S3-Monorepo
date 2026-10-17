import json

import httpx
from evals.live_smoke import build_live_summary, load_live_cases
from evals.run_live_smoke import DEFAULT_DATASET, _run_case


def _successful_run(case_id: str, generation_type: str, cost: float) -> dict:
    return {
        "case_id": case_id,
        "generation_type": generation_type,
        "api_completed": True,
        "database_verified": True,
        "s3_verified": True,
        "trace_complete": True,
        "privacy_safe": True,
        "cost_measured": True,
        "total_cost_usd": cost,
        "latency_ms": 1_000.0,
    }


def test_live_smoke_dataset_contains_four_balanced_safe_cases() -> None:
    cases = load_live_cases(DEFAULT_DATASET)

    assert len(cases) == 4
    assert sum(case.generation_type == "text_to_image" for case in cases) == 2
    assert sum(case.generation_type == "image_to_image" for case in cases) == 2
    assert len({case.case_id for case in cases}) == 4


def test_live_smoke_summary_passes_complete_budgeted_run() -> None:
    runs = [
        _successful_run("live-smoke-001", "text_to_image", 0.006),
        _successful_run("live-smoke-002", "text_to_image", 0.006),
        _successful_run("live-smoke-003", "image_to_image", 0.064),
        _successful_run("live-smoke-004", "image_to_image", 0.064),
    ]

    summary = build_live_summary(
        runs,
        planned_case_count=4,
        maximum_cost_usd=0.30,
        stopped_reason=None,
    )

    assert summary["cost_usd"]["total"] == 0.14
    assert summary["acceptance_gates"]["overall"] is True


def test_live_smoke_summary_rejects_unmetered_partial_run() -> None:
    run = _successful_run("live-smoke-001", "text_to_image", 0.006)
    run["cost_measured"] = False
    run["total_cost_usd"] = None

    summary = build_live_summary(
        [run],
        planned_case_count=4,
        maximum_cost_usd=0.30,
        stopped_reason="cost_not_measured",
    )

    assert summary["acceptance_gates"]["all_cases_executed"] is False
    assert summary["acceptance_gates"]["all_costs_are_measured"] is False
    assert summary["acceptance_gates"]["overall"] is False


class _FakeClient:
    def post(self, path: str, **_: object) -> httpx.Response:
        assert path == "/api/v1/images/generations"
        return httpx.Response(
            201,
            json={
                "id": "00000000-0000-0000-0000-000000000001",
                "status": "completed",
                "generation_type": "text_to_image",
                "output_object_key": "generations/private.png",
            },
            request=httpx.Request("POST", "http://localhost:8000" + path),
        )

    def get(self, path: str, **_: object) -> httpx.Response:
        if path.endswith("/download"):
            payload = {"download_url": "https://private.invalid/signed"}
            status_code = 200
            headers = {}
            content = None
        elif path.startswith("/api/v1/images/generations/"):
            payload = {
                "id": "00000000-0000-0000-0000-000000000001",
                "status": "completed",
                "generation_type": "text_to_image",
                "output_object_key": "generations/private.png",
            }
            status_code = 200
            headers = {}
            content = None
        else:
            payload = None
            status_code = 206
            headers = {"content-type": "image/png"}
            content = b"x"
        return httpx.Response(
            status_code,
            json=payload,
            headers=headers,
            content=content,
            request=httpx.Request("GET", str(path)),
        )


class _FakeTraceReader:
    def collect(self, **_: object) -> dict:
        return {
            "trace_found": True,
            "trace_complete": True,
            "privacy_safe": True,
            "cost_measured": True,
            "total_cost_usd": 0.006,
            "trace_id": "safe-trace-id",
            "observation_count": 5,
            "model_names": ["test-image-model"],
        }


def test_live_case_artifact_omits_prompt_keys_urls_and_image_bytes() -> None:
    case = load_live_cases(DEFAULT_DATASET)[0]

    result = _run_case(
        client=_FakeClient(),  # type: ignore[arg-type]
        trace_reader=_FakeTraceReader(),  # type: ignore[arg-type]
        case=case,
        reference_object_key="uploads/private.png",
        run_id="live-test",
    )

    serialized = json.dumps(result)
    assert result["api_completed"] is True
    assert result["database_verified"] is True
    assert result["s3_verified"] is True
    assert case.prompt not in serialized
    assert "uploads/private.png" not in serialized
    assert "generations/private.png" not in serialized
    assert "https://private.invalid" not in serialized
