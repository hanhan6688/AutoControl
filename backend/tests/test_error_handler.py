from __future__ import annotations

import pytest
import asyncio
from fastapi import HTTPException


def test_handle_service_errors_maps_sync_exception() -> None:
    from app.error_handler import handle_service_errors

    class ServiceError(RuntimeError):
        pass

    @handle_service_errors({ServiceError: 502})
    def endpoint() -> None:
        raise ServiceError("service unavailable")

    with pytest.raises(HTTPException) as exc_info:
        endpoint()

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == "service unavailable"


def test_handle_service_errors_maps_async_exception() -> None:
    from app.error_handler import handle_service_errors

    class ServiceError(RuntimeError):
        pass

    @handle_service_errors({ServiceError: 400})
    async def endpoint() -> None:
        raise ServiceError("bad service input")

    async def run_endpoint() -> None:
        await endpoint()

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(run_endpoint())

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "bad service input"
