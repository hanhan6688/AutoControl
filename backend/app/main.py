import logging
import os

# Set UTF-8 encoding for subprocess output on Windows
os.environ["PYTHONIOENCODING"] = "utf-8"

import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import socketio

from app.config import settings
from app.database import init_db
from app.routers import api_tests, automation, devices, diagnostic, health, login_accounts, pc_browser, scripts, test_plans, folders
from app.services.screen_socketio_service import sio as screen_sio
from app.services.xpath_health_service import xpath_health_loop


_xpath_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    global _xpath_task
    _xpath_task = asyncio.create_task(xpath_health_loop())
    logging.getLogger(__name__).info("xpath health loop started (every 20min)")
    yield
    if _xpath_task is not None:
        _xpath_task.cancel()
        _xpath_task = None


class SuppressAccessPathFilter(logging.Filter):
    def __init__(self, suppressed_paths: set[str]) -> None:
        super().__init__()
        self.suppressed_paths = suppressed_paths

    def filter(self, record: logging.LogRecord) -> bool:
        path = self._extract_path(record)
        if path is None:
            return True
        return not any(path == item or path.startswith(f"{item}?") for item in self.suppressed_paths)

    @staticmethod
    def _extract_path(record: logging.LogRecord) -> str | None:
        if len(record.args) >= 3 and isinstance(record.args[2], str):
            return record.args[2]

        message = record.getMessage()
        marker = " /"
        if marker not in message:
            return None
        path_part = message.split(marker, 1)[1].split(" HTTP/", 1)[0]
        return f"/{path_part}"


def install_access_log_filters() -> None:
    access_logger = logging.getLogger("uvicorn.access")
    if any(getattr(item, "_mobile_ai_testops_devices_filter", False) for item in access_logger.filters):
        return

    filter_item = SuppressAccessPathFilter({"/api/devices"})
    setattr(filter_item, "_mobile_ai_testops_devices_filter", True)
    access_logger.addFilter(filter_item)


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name)
    install_access_log_filters()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=settings.cors_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    settings.static_dir.mkdir(parents=True, exist_ok=True)
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=settings.static_dir), name="static")
    app.router.lifespan_context = lifespan

    app.include_router(health.router)
    app.include_router(devices.router)
    app.include_router(test_plans.router)
    app.include_router(folders.router)
    app.include_router(login_accounts.router)
    app.include_router(scripts.router)
    app.include_router(diagnostic.router)
    app.include_router(pc_browser.router)
    app.include_router(api_tests.router)
    app.include_router(automation.router)

    return app


app = create_app()

# Mount SocketIO ASGI app — all HTTP routes go to FastAPI,
# SocketIO connections go to /ws/socket.io
socket_app = socketio.ASGIApp(screen_sio, other_asgi_app=app, socketio_path="socket.io")
