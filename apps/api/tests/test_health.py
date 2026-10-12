from fastapi.testclient import TestClient

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
