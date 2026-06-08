"""LocatorResolver — resolves a LocatorChain by trying primary then each fallback."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.automation.core.driver import DeviceDriver, ElementRef
from app.automation.core.models import Locator, LocatorChain, LocatorType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResolveResult:
    """Outcome of a locator resolution attempt."""

    found: bool
    resolved_locator: Locator | None = None
    element_ref: ElementRef | None = None
    attempted_count: int = 0
    coordinates: tuple[int, int] | None = None


class LocatorResolver:
    """Resolves a LocatorChain by trying the primary locator first, then each
    fallback in order until one succeeds or the list is exhausted."""

    def __init__(self, driver: DeviceDriver) -> None:
        self._driver = driver

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(self, chain: LocatorChain, timeout: float = 5.0) -> ResolveResult:
        """Try every locator in *chain* and return the first that succeeds."""
        attempted = 0

        for locator in chain.all_locators():
            attempted += 1

            if locator.type == LocatorType.COORDINATE_RATIO:
                result = self._resolve_coordinate(locator)
                if result.found:
                    return ResolveResult(
                        found=True,
                        resolved_locator=locator,
                        attempted_count=attempted,
                        coordinates=result.coordinates,
                    )
            else:
                ref = self._driver.find_element(
                    locator.type.value, locator.value, timeout=timeout
                )
                if ref.found:
                    return ResolveResult(
                        found=True,
                        resolved_locator=locator,
                        element_ref=ref,
                        attempted_count=attempted,
                    )
                logger.debug(
                    "Locator %s=%s not found", locator.type.value, locator.value
                )

        return ResolveResult(found=False, attempted_count=attempted)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_coordinate(self, locator: Locator) -> _CoordResult:
        if locator.x is None or locator.y is None:
            return _CoordResult(found=False)
        width, height = self._driver.screen_size()
        px = int(locator.x * width)
        py = int(locator.y * height)
        return _CoordResult(found=True, coordinates=(px, py))


@dataclass(frozen=True)
class _CoordResult:
    """Internal helper — not part of the public API."""

    found: bool = False
    coordinates: tuple[int, int] | None = None
