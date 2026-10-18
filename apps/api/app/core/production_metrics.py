"""Privacy-safe resource snapshot for an authorized capacity operator."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

CGROUP_ROOT = Path("/sys/fs/cgroup")
_sample_lock = asyncio.Lock()
_previous_cpu_usage_usec: int | None = None
_previous_sample_time: float | None = None


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None


def _read_int(path: Path) -> int | None:
    value = _read_text(path)
    if value is None or value == "max":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _cpu_snapshot(root: Path) -> tuple[int, float]:
    stat = _read_text(root / "cpu.stat")
    cpu_max = _read_text(root / "cpu.max")
    if stat is None or cpu_max is None:
        raise RuntimeError("cgroup CPU metrics are unavailable")
    values: dict[str, int] = {}
    for line in stat.splitlines():
        parts = line.split()
        if len(parts) == 2:
            try:
                values[parts[0]] = int(parts[1])
            except ValueError:
                continue
    usage = values.get("usage_usec")
    if usage is None:
        raise RuntimeError("cgroup CPU usage is unavailable")
    quota_text, _, period_text = cpu_max.partition(" ")
    if quota_text == "max":
        cores = float(os.cpu_count() or 1)
    else:
        try:
            cores = int(quota_text) / int(period_text)
        except (ValueError, ZeroDivisionError) as error:
            raise RuntimeError("cgroup CPU limit is invalid") from error
    if cores <= 0:
        raise RuntimeError("cgroup CPU limit is invalid")
    return usage, cores


def _memory_percent(root: Path) -> float:
    current = _read_int(root / "memory.current")
    limit = _read_int(root / "memory.max")
    if current is None or limit is None or limit <= 0:
        raise RuntimeError("bounded cgroup memory metrics are unavailable")
    return min(100.0, current / limit * 100)


async def collect_production_metrics(
    engine: AsyncEngine,
    *,
    cgroup_root: Path = CGROUP_ROOT,
) -> dict[str, float]:
    """Return only the numeric contract consumed by the capacity runner."""
    global _previous_cpu_usage_usec, _previous_sample_time

    async with _sample_lock:
        now = time.monotonic()
        usage_usec, cpu_limit_cores = _cpu_snapshot(cgroup_root)
        if _previous_cpu_usage_usec is None or _previous_sample_time is None:
            cpu_percent = 0.0
        else:
            usage_seconds = max(0, usage_usec - _previous_cpu_usage_usec) / 1_000_000
            wall_seconds = max(0.000001, now - _previous_sample_time)
            cpu_percent = min(
                100.0,
                usage_seconds / wall_seconds / cpu_limit_cores * 100,
            )
        _previous_cpu_usage_usec = usage_usec
        _previous_sample_time = now
        memory_percent = _memory_percent(cgroup_root)

    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text(
                    """
                    SELECT
                        COUNT(*) FILTER (
                            WHERE datname = current_database()
                              AND state = 'active'
                        ) AS active_connections,
                        current_setting('max_connections')::integer
                            AS max_connections
                    FROM pg_stat_activity
                    """
                )
            )
        ).mappings().one()
    return {
        "cpu_percent": round(cpu_percent, 3),
        "memory_percent": round(memory_percent, 3),
        "database_active_connections": float(row["active_connections"]),
        "database_max_connections": float(row["max_connections"]),
    }
