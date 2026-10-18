from pathlib import Path

import pytest

from app.core.production_metrics import _cpu_snapshot, _memory_percent


def _write(path: Path, value: str) -> None:
    path.write_text(value, encoding="utf-8")


def test_cgroup_snapshot_reports_bounded_capacity_inputs(tmp_path: Path) -> None:
    _write(tmp_path / "cpu.stat", "usage_usec 2000000\n")
    _write(tmp_path / "cpu.max", "200000 100000\n")
    _write(tmp_path / "memory.current", "250\n")
    _write(tmp_path / "memory.max", "1000\n")

    assert _cpu_snapshot(tmp_path) == (2_000_000, 2.0)
    assert _memory_percent(tmp_path) == 25.0


def test_unbounded_memory_is_rejected(tmp_path: Path) -> None:
    _write(tmp_path / "memory.current", "250\n")
    _write(tmp_path / "memory.max", "max\n")

    with pytest.raises(RuntimeError, match="bounded cgroup memory"):
        _memory_percent(tmp_path)
