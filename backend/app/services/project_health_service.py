from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import settings
from app.services.model_provider_service import ModelProviderService


@dataclass(frozen=True)
class PathHealth:
    path: str
    exists: bool
    kind: str

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "exists": self.exists, "kind": self.kind}


class ProjectHealthService:
    """Read-only project health snapshot for operational troubleshooting."""

    def snapshot(self) -> dict[str, Any]:
        pc_agent = ModelProviderService().pc_agent_config()
        agent_browser_path = settings.resolved_agent_browser_path
        autoglm_root = settings.open_autoglm_root
        backend_dir = settings.backend_dir
        reports_dir = settings.static_dir / "reports"
        uploads_dir = settings.uploads_dir

        return {
            "status": "ok",
            "runtime": {
                "python": sys.executable,
                "backend_dir": str(backend_dir),
                "runtime_root": str(settings.runtime_root),
                "database": self._database_summary(),
            },
            "tools": {
                "agent_browser": {
                    "path": agent_browser_path,
                    "available": shutil.which(agent_browser_path) is not None,
                },
                "open_autoglm": self._path_health(autoglm_root).to_dict(),
                "open_autoglm_main": self._path_health(autoglm_root / "main.py").to_dict(),
                "adb": {
                    "path": settings.resolved_adb_path,
                    "available": shutil.which(settings.resolved_adb_path) is not None,
                },
                "ios": {
                    "path": settings.resolved_ios_path,
                    "available": shutil.which(settings.resolved_ios_path) is not None,
                },
                "hdc": {
                    "path": settings.resolved_hdc_path,
                    "available": shutil.which(settings.resolved_hdc_path) is not None,
                },
            },
            "models": {
                "pc_agent": pc_agent.public_dict(),
                "autoglm": {
                    "base_url": settings.autoglm_base_url,
                    "model": settings.autoglm_model,
                    "configured": bool(settings.autoglm_base_url and settings.autoglm_model and settings.autoglm_api_key and settings.autoglm_api_key != "EMPTY"),
                },
            },
            "artifacts": {
                "reports": self._dir_summary(reports_dir),
                "uploads": self._dir_summary(uploads_dir),
            },
        }

    @staticmethod
    def _database_summary() -> dict[str, Any]:
        url = settings.resolved_database_url
        if url.startswith("sqlite:///"):
            path = Path(url.removeprefix("sqlite:///"))
            return {
                "type": "sqlite",
                "path": str(path),
                "exists": path.exists() if str(path) != ":memory:" else True,
            }
        return {
            "type": url.split(":", 1)[0],
            "configured": bool(url),
        }

    @staticmethod
    def _path_health(path: Path) -> PathHealth:
        kind = "missing"
        if path.is_file():
            kind = "file"
        elif path.is_dir():
            kind = "directory"
        return PathHealth(path=str(path), exists=path.exists(), kind=kind)

    @staticmethod
    def _dir_summary(path: Path) -> dict[str, Any]:
        total_bytes = 0
        file_count = 0
        if path.exists():
            for item in path.rglob("*"):
                if item.is_file():
                    file_count += 1
                    total_bytes += item.stat().st_size
        return {
            "path": str(path),
            "exists": path.exists(),
            "file_count": file_count,
            "total_bytes": total_bytes,
            "total_mb": round(total_bytes / 1024 / 1024, 2),
        }
