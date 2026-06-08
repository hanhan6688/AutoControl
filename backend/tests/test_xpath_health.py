from __future__ import annotations


def test_xpath_pipeline_android_parse_and_locate_ok() -> None:
    from app.services.xpath_health_service import check_xpath_pipeline

    result = check_xpath_pipeline()

    assert result.android_parse_ok is True
    assert result.android_locate_ok is True
    assert result.ios_parse_ok is True
    assert result.ios_locate_ok is True
    assert result.status in ("healthy", "degraded")


def test_xpath_health_endpoint_returns_result() -> None:
    from app.main import create_app
    from fastapi.testclient import TestClient

    client = TestClient(create_app())
    response = client.get("/api/diagnostic/xpath-health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] in ("healthy", "degraded", "unhealthy", "unknown")
    assert "android_parse_ok" in payload
    assert "android_locate_ok" in payload
    assert "ios_parse_ok" in payload
    assert "ios_locate_ok" in payload
    assert "duration_ms" in payload