from pathlib import Path

from evals.dataset import load_cases
from evals.run_workflow import DEFAULT_DATASET, execute


def test_workflow_smoke_dataset_is_valid() -> None:
    cases = load_cases(DEFAULT_DATASET)

    assert len(cases) == 12
    assert len({case.case_id for case in cases}) == len(cases)
    assert {case.category for case in cases} == {
        "normal_path",
        "external_failure",
        "database_failure",
        "post_commit_failure",
        "validation",
    }


def test_offline_workflow_runner_verifies_completion_compensation(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "workflow-results"

    summary = execute(
        dataset_path=DEFAULT_DATASET,
        output_dir=output_dir,
        concurrency=4,
    )

    assert summary["run_count"] == 12
    assert summary["cloud_calls"] is False
    assert summary["concurrency"]["max_in_flight"] == 4
    assert summary["score"] == {
        "scenario_expectation_rate": 1.0,
        "normal_path_task_success_rate": 1.0,
        "external_failure_containment_rate": 1.0,
        "validation_rejection_rate": 1.0,
        "database_failure_recovery_rate": 1.0,
        "state_consistency_rate": 1.0,
        "orphan_output_count": 0,
        "unexpected_pending_count": 0,
        "post_commit_response_failure_count": 1,
        "database_failure_case_count": 1,
    }
    assert summary["acceptance_gates"]["overall"] is True
    assert summary["acceptance_gates"]["no_orphan_outputs"] is True
    assert summary["acceptance_gates"]["no_unexpected_pending_records"] is True
    assert (output_dir / "raw_runs.jsonl").is_file()
    assert (output_dir / "summary.json").is_file()
    assert (output_dir / "config.json").is_file()
    assert (output_dir / "report.md").is_file()
