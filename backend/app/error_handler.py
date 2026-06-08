from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from functools import wraps
from typing import Any, TypeVar, cast

from fastapi import HTTPException

F = TypeVar("F", bound=Callable[..., Any])


def handle_service_errors(error_statuses: Mapping[type[Exception], int]) -> Callable[[F], F]:
    """Map known service exceptions to FastAPI HTTP responses.

    Args:
        error_statuses: Mapping of exception types to HTTP status codes.
                       Example: {ADBError: 502, UIElementError: 400}
    """

    def status_for(exc: Exception) -> int | None:
        for error_type, status_code in error_statuses.items():
            if isinstance(exc, error_type):
                return status_code
        return None

    def decorator(func: F) -> F:
        if inspect.iscoroutinefunction(func):

            @wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                try:
                    return await func(*args, **kwargs)
                except HTTPException:
                    raise
                except Exception as exc:
                    status_code = status_for(exc)
                    if status_code is None:
                        raise
                    raise HTTPException(status_code=status_code, detail=str(exc)) from exc

            return cast(F, async_wrapper)

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except HTTPException:
                raise
            except Exception as exc:
                status_code = status_for(exc)
                if status_code is None:
                    raise
                raise HTTPException(status_code=status_code, detail=str(exc)) from exc

        return cast(F, sync_wrapper)

    return decorator


# Lazy import to avoid circular dependencies
def get_device_error_handler():
    """Get device error handler with lazy imports."""
    from app.services.adb_service import ADBError
    from app.services.harmony_service import HarmonyError
    from app.services.ios_service import IOSError
    from app.services.scrcpy_service import ScrcpyError
    from app.services.screen_stream_service import ScreenStreamError
    from app.services.ui_element_service import UIElementError
    from app.services.visual_action_service import VisualActionError

    return handle_service_errors({
        ADBError: 502,
        IOSError: 502,
        HarmonyError: 502,
        ScrcpyError: 502,
        ScreenStreamError: 502,
        UIElementError: 500,
        VisualActionError: 500,
    })
