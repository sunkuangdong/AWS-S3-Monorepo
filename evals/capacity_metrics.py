"""Bounded cgroup and PostgreSQL metrics for the capacity-only application."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

CGROUP_ROOT = Path("/sys/fs/cgroup")


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


def read_cgroup_v2_metrics(root: Path = CGROUP_ROOT) -> dict[str, int | float | None]:
    """Read privacy-safe container resource counters from cgroup v2."""
    cpu_stat = _read_text(root / "cpu.stat")
    values: dict[str, int] = {}
    if cpu_stat:
        for line in cpu_stat.splitlines():
            parts = line.split()
            if len(parts) == 2:
                try:
                    values[parts[0]] = int(parts[1])
                except ValueError:
                    continue

    cpu_limit_cores: float | None = None
    cpu_max = _read_text(root / "cpu.max")
    if cpu_max:
        quota, _, period = cpu_max.partition(" ")
        if quota != "max":
            try:
                cpu_limit_cores = int(quota) / int(period)
            except (ValueError, ZeroDivisionError):
                cpu_limit_cores = None

    return {
        "cpu_usage_usec": values.get("usage_usec"),
        "cpu_user_usec": values.get("user_usec"),
        "cpu_system_usec": values.get("system_usec"),
        "cpu_throttled_usec": values.get("throttled_usec"),
        "cpu_limit_cores": cpu_limit_cores,
        "memory_current_bytes": _read_int(root / "memory.current"),
        "memory_peak_bytes": _read_int(root / "memory.peak"),
        "memory_limit_bytes": _read_int(root / "memory.max"),
    }


async def collect_capacity_metrics(
    engine: AsyncEngine,
    *,
    application_name: str = "capacity-api",
) -> dict[str, Any]:
    """Combine container counters with run-scoped PostgreSQL connection state."""
    pool = engine.sync_engine.pool
    async with engine.connect() as connection:
        result = await connection.execute(
            text(
                """
                SELECT
                    COUNT(*) FILTER (
                        WHERE pid <> pg_backend_pid()
                    ) AS total_connections,
                    COUNT(*) FILTER (
                        WHERE pid <> pg_backend_pid() AND state = 'active'
                    ) AS active_connections,
                    COUNT(*) FILTER (
                        WHERE pid <> pg_backend_pid() AND state = 'idle'
                    ) AS idle_connections
                FROM pg_stat_activity
                WHERE datname = current_database()
                  AND application_name = :application_name
                """
            ),
            {"application_name": application_name},
        )
        row = result.mappings().one()
        checked_out = max(0, int(pool.checkedout()) - 1)
        database = {
            "total_connections": int(row["total_connections"]),
            "active_connections": int(row["active_connections"]),
            "idle_connections": int(row["idle_connections"]),
            "pool_size": int(pool.size()),
            "pool_checked_out": checked_out,
            "pool_overflow": max(0, int(pool.overflow())),
        }
    return {
        "container": read_cgroup_v2_metrics(),
        "postgresql": database,
    }
