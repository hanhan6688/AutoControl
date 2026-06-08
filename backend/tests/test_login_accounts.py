from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.database import Base


def make_client(tmp_path, monkeypatch) -> TestClient:
    from app import database
    from app.main import create_app

    db_path = tmp_path / "accounts.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    database.engine = engine
    database.SessionLocal.configure(bind=engine)
    Base.metadata.create_all(bind=engine)
    return TestClient(create_app())


def test_login_account_create_list_update_and_delete(tmp_path, monkeypatch) -> None:
    client = make_client(tmp_path, monkeypatch)

    create_response = client.post(
        "/api/login-accounts",
        json={
            "platform": "微信",
            "label": "常用微信",
            "login_id": "13800138000",
            "password": "secret123",
            "note": "测试账号",
        },
    )

    assert create_response.status_code == 200
    created = create_response.json()
    assert created["platform"] == "微信"
    assert created["login_id"] == "13800138000"
    assert created["password_masked"] == "se******23"
    assert "password" not in created

    list_response = client.get("/api/login-accounts")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    update_response = client.put(
        f"/api/login-accounts/{created['id']}",
        json={
            "platform": "QQ",
            "label": "常用QQ",
            "login_id": "10001",
            "password": "",
            "note": "",
        },
    )

    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["platform"] == "QQ"
    assert updated["password_masked"] == "se******23"

    delete_response = client.delete(f"/api/login-accounts/{created['id']}")
    assert delete_response.status_code == 200
    assert client.get("/api/login-accounts").json() == []
