"""Validate frozen live smoke inputs and redacted evidence without cloud calls."""

from __future__ import annotations

import json

from evals.live_smoke import (
    FROZEN_LIVE_MANIFEST,
    PROJECT_ROOT,
    load_frozen_live_manifest,
    validate_frozen_live_protocol,
)


def main() -> int:
    manifest = load_frozen_live_manifest()
    dataset_path = PROJECT_ROOT / manifest["dataset"]["path"]
    validate_frozen_live_protocol(
        dataset_path,
        maximum_cost_usd=manifest["runner"]["maximum_cost_usd"],
        timeout_seconds=manifest["runner"]["timeout_seconds"],
        trace_wait_seconds=manifest["runner"]["trace_wait_seconds"],
    )
    evidence_path = PROJECT_ROOT / manifest["evidence"]["path"]
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    result = {
        "valid": True,
        "protocol": {
            "version": manifest["protocol_version"],
            "status": manifest["status"],
            "frozen_date": manifest["frozen_date"],
            "git_tag": manifest["git_tag"],
            "implementation_baseline_commit": manifest[
                "implementation_baseline_commit"
            ],
        },
        "manifest": str(FROZEN_LIVE_MANIFEST.relative_to(PROJECT_ROOT)),
        "dataset": manifest["dataset"],
        "evidence": {
            "path": manifest["evidence"]["path"],
            "sha256": manifest["evidence"]["sha256"],
            "run_count": evidence["result"]["run_count"],
            "overall_passed": evidence["result"]["overall_passed"],
            "total_cost_usd": evidence["cost_usd"]["total"],
            "privacy_scan": evidence["privacy"]["artifact_scan"],
        },
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
