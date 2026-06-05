"""DeviceDriver protocol and ElementRef result type for the Unified Automation Engine V2."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ElementRef:
    """Result of an element search operation."""

    found: bool
    locator_type: str
    locator_value: str
    bounds: dict[str, int] | None = None
    center: tuple[int, int] | None = None
    text: str | None = None
    resource_id: str | None = None
    class_name: str | None = None
    content_desc: str | None = None
    attributes: dict[str, Any] | None = None


class DeviceDriver(ABC):
    """Abstract base class defining the device automation interface.

    Concrete implementations (AndroidDriver, IOSDriver) must provide
    platform-specific behavior for every abstract method/property below.
    """

    @property
    @abstractmethod
    def platform(self) -> str:
        """Return the platform identifier: 'android' or 'ios'."""

    @abstractmethod
    def launch(self, app_id: str) -> None:
        """Launch an application by its package identifier."""

    @abstractmethod
    def stop_app(self, app_id: str) -> None:
        """Force-stop an application by its package identifier."""

    @abstractmethod
    def tap(self, x: int, y: int) -> None:
        """Perform a tap at the given screen coordinates."""

    @abstractmethod
    def long_press(self, x: int, y: int, duration_ms: int = 1000) -> None:
        """Perform a long-press at the given coordinates for *duration_ms* milliseconds."""

    @abstractmethod
    def swipe(self, sx: int, sy: int, ex: int, ey: int, duration_ms: int = 300) -> None:
        """Swipe from (sx, sy) to (ex, ey) over *duration_ms* milliseconds."""

    @abstractmethod
    def input_text(self, text: str) -> None:
        """Type *text* into the currently focused input field."""

    @abstractmethod
    def press_key(self, key: str) -> None:
        """Press a device key (e.g. 'home', 'back', 'enter')."""

    @abstractmethod
    def screenshot(self) -> bytes:
        """Capture a screenshot and return the PNG bytes."""

    @abstractmethod
    def dump_source(self) -> str:
        """Return the raw accessibility/UI-hierarchy source as a string."""

    @abstractmethod
    def current_app(self) -> dict[str, str]:
        """Return information about the currently foregrounded application."""

    @abstractmethod
    def screen_size(self) -> tuple[int, int]:
        """Return the screen dimensions as (width, height)."""

    @abstractmethod
    def find_element(self, locator_type: str, locator_value: str, timeout: float = 10.0) -> ElementRef:
        """Search for a UI element and return an ElementRef describing the result."""

    @abstractmethod
    def element_exists(self, locator_type: str, locator_value: str, timeout: float = 5.0) -> bool:
        """Return True if the element is found within *timeout* seconds."""
