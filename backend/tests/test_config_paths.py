from pathlib import Path


def test_relative_sqlite_database_url_resolves_under_backend_dir() -> None:
    from app.config import Settings

    settings = Settings(database_url="sqlite:///./data/test.db")

    expected_path = (settings.backend_dir / "data" / "test.db").as_posix()
    assert settings.resolved_database_url == f"sqlite:///{expected_path}"


def test_runtime_owned_paths_are_under_backend_dir() -> None:
    from app.config import Settings

    settings = Settings()

    assert settings.static_dir == settings.backend_dir / "static"
    assert settings.uploads_dir == settings.static_dir / "uploads"
    assert settings.scripts_dir == settings.backend_dir / "scripts"


def test_tool_paths_are_under_runtime_tools_dir() -> None:
    from app.config import Settings

    settings = Settings()

    assert settings.minicap_dir == settings.tools_dir / "minicap"
