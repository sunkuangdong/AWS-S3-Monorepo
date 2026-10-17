"""Validate tracked evaluation datasets without calling external services."""

import argparse
import json
from collections import Counter
from pathlib import Path

from evals.dataset import dataset_sha256, load_cases

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = PROJECT_ROOT / "evals/datasets/workflow_smoke_v1.jsonl"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET,
    )
    args = parser.parse_args()
    path = args.dataset.resolve()
    cases = load_cases(path)
    result = {
        "valid": True,
        "path": str(path.relative_to(PROJECT_ROOT)),
        "case_count": len(cases),
        "sha256": dataset_sha256(path),
        "categories": dict(sorted(Counter(case.category for case in cases).items())),
        "generation_types": dict(
            sorted(Counter(case.generation_type for case in cases).items())
        ),
        "failure_points": dict(
            sorted(Counter(case.failure_point or "none" for case in cases).items())
        ),
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
