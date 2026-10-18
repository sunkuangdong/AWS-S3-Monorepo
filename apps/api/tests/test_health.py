from fastapi.testclient import TestClient

import app.main as main_module
from app.main import app


def test_health_check_returns_request_id() -> None:
    with TestClient(app) as client:
        response = client.get(
            "/health",
            headers={"X-Request-ID": "demo-request-123"},
        )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-ID"] == "demo-request-123"


def test_health_check_replaces_oversized_request_id() -> None:
    with TestClient(app) as client:
        response = client.get(
            "/health",
            headers={"X-Request-ID": "x" * 129},
        )

    assert response.status_code == 200
    assert len(response.headers["X-Request-ID"]) == 32


def test_capacity_metrics_are_disabled_without_operator_secret(
    monkeypatch,
) -> None:
    monkeypatch.delenv("CAPACITY_METRICS_AUTHORIZATION", raising=False)
    with TestClient(app) as client:
        response = client.get("/internal/capacity-metrics")

    assert response.status_code == 404


def test_capacity_metrics_require_exact_authorization(monkeypatch) -> None:
    monkeypatch.setenv("CAPACITY_METRICS_AUTHORIZATION", "Bearer operator-secret")

    async def fake_metrics(_engine) -> dict[str, float]:
        return {
            "cpu_percent": 12.0,
            "memory_percent": 34.0,
            "database_active_connections": 5.0,
            "database_max_connections": 100.0,
        }

    monkeypatch.setattr(main_module, "collect_production_metrics", fake_metrics)
    with TestClient(app) as client:
        rejected = client.get(
            "/internal/capacity-metrics",
            headers={"Authorization": "Bearer wrong"},
        )
        accepted = client.get(
            "/internal/capacity-metrics",
            headers={"Authorization": "Bearer operator-secret"},
        )

    assert rejected.status_code == 401
    assert accepted.status_code == 200
    assert accepted.json()["cpu_percent"] == 12.0
