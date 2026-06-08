from __future__ import annotations

from fastapi.testclient import TestClient


def test_project_health_endpoint_returns_operational_snapshot() -> None:
    from app.main import create_app

    client = TestClient(create_app())
    response = client.get("/api/diagnostic/project-health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert "runtime" in payload
    assert "tools" in payload
    assert "models" in payload
    assert "artifacts" in payload
    assert "pc_agent" in payload["models"]


def test_artifact_cleanup_endpoint_defaults_to_dry_run() -> None:
    from app.main import create_app

    client = TestClient(create_app())
    response = client.post("/api/diagnostic/artifacts/cleanup", json={"max_age_days": 30})

    assert response.status_code == 200
    payload = response.json()
    assert payload["dry_run"] is True
    assert "candidate_count" in payload


def test_image_library_api_is_not_registered() -> None:
    from app.main import create_app

    client = TestClient(create_app())
    response = client.get("/api/image-library")

    assert response.status_code == 404
