"""Tests for LocatorResolver."""

from unittest.mock import MagicMock

from app.automation.core.driver import DeviceDriver, ElementRef
from app.automation.core.models import Locator, LocatorChain, LocatorType
from app.automation.locators.resolver import LocatorResolver, ResolveResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_driver(find_results: dict) -> MagicMock:
    """Create a mock DeviceDriver whose *find_element* returns canned results.

    Parameter
    ---------
    find_results : dict
        Mapping from ``"{locator_type}:{locator_value}"`` to an ``ElementRef``.
        Keys not present in the dict will receive ``ElementRef(found=False)``.
    """
    driver = MagicMock(spec=DeviceDriver)

    def fake_find(locator_type: str, locator_value: str, timeout: float = 5.0) -> ElementRef:
        key = f"{locator_type}:{locator_value}"
        return find_results.get(
            key,
            ElementRef(
                found=False,
                locator_type=locator_type,
                locator_value=locator_value,
            ),
        )

    driver.find_element = MagicMock(side_effect=fake_find)
    return driver


# ---------------------------------------------------------------------------
# Primary only
# ---------------------------------------------------------------------------


class TestLocatorResolverPrimaryOnly:
    def test_primary_found(self):
        driver = _make_driver(
            {
                "resource_id:com.demo:id/btn": ElementRef(
                    found=True,
                    locator_type="resource_id",
                    locator_value="com.demo:id/btn",
                    center=(100, 200),
                )
            }
        )
        chain = LocatorChain(
            primary=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/btn")
        )
        result = LocatorResolver(driver).resolve(chain)

        assert result.found is True
        assert result.resolved_locator.type == LocatorType.RESOURCE_ID
        assert result.attempted_count == 1

    def test_primary_not_found_no_fallbacks(self):
        driver = _make_driver({})
        chain = LocatorChain(
            primary=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/missing")
        )
        result = LocatorResolver(driver).resolve(chain)

        assert result.found is False
        assert result.attempted_count == 1

    def test_resolve_result_fields_present_when_found(self):
        driver = _make_driver(
            {
                "resource_id:com.demo:id/btn": ElementRef(
                    found=True,
                    locator_type="resource_id",
                    locator_value="com.demo:id/btn",
                    center=(100, 200),
                )
            }
        )
        chain = LocatorChain(
            primary=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/btn")
        )
        result = LocatorResolver(driver).resolve(chain)

        assert isinstance(result, ResolveResult)
        assert result.resolved_locator is not None
        assert result.element_ref is not None
        assert result.element_ref.center == (100, 200)

    def test_resolve_result_fields_when_missing(self):
        driver = _make_driver({})
        chain = LocatorChain(
            primary=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/missing")
        )
        result = LocatorResolver(driver).resolve(chain)

        assert result.resolved_locator is None
        assert result.element_ref is None
        assert result.coordinates is None


# ---------------------------------------------------------------------------
# With fallbacks
# ---------------------------------------------------------------------------


class TestLocatorResolverWithFallbacks:
    def test_primary_fails_first_fallback_succeeds(self):
        driver = _make_driver(
            {
                "text:登录": ElementRef(
                    found=True,
                    locator_type="text",
                    locator_value="登录",
                    center=(150, 800),
                )
            }
        )
        chain = LocatorChain(
            primary=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/login"),
            fallbacks=[
                Locator(type=LocatorType.TEXT, value="登录"),
                Locator(type=LocatorType.XPATH, value="//*[@text='登录']"),
            ],
        )
        result = LocatorResolver(driver).resolve(chain)

        assert result.found is True
        assert result.resolved_locator.type == LocatorType.TEXT
        assert result.attempted_count == 2

    def test_all_fail(self):
        driver = _make_driver({})
        chain = LocatorChain(
            primary=Locator(type=LocatorType.RESOURCE_ID, value="x"),
            fallbacks=[Locator(type=LocatorType.TEXT, value="y")],
        )
        result = LocatorResolver(driver).resolve(chain)

        assert result.found is False
        assert result.attempted_count == 2

    def test_multiple_fallbacks_second_succeeds(self):
        driver = _make_driver(
            {
                "xpath://*[@text='submit']": ElementRef(
                    found=True,
                    locator_type="xpath",
                    locator_value="//*[@text='submit']",
                )
            }
        )
        chain = LocatorChain(
            primary=Locator(type=LocatorType.RESOURCE_ID, value="btn1"),
            fallbacks=[
                Locator(type=LocatorType.TEXT, value="Submit"),
                Locator(type=LocatorType.XPATH, value="//*[@text='submit']"),
                Locator(type=LocatorType.CONTENT_DESC, value="submit button"),
            ],
        )
        result = LocatorResolver(driver).resolve(chain)

        assert result.found is True
        assert result.resolved_locator.type == LocatorType.XPATH
        assert result.attempted_count == 3

    def test_primary_succeeds_skips_fallbacks(self):
        driver = _make_driver(
            {
                "resource_id:com.demo:id/btn": ElementRef(
                    found=True,
                    locator_type="resource_id",
                    locator_value="com.demo:id/btn",
                    center=(100, 200),
                )
            }
        )
        chain = LocatorChain(
            primary=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/btn"),
            fallbacks=[
                Locator(type=LocatorType.TEXT, value="fallback_text"),
            ],
        )
        result = LocatorResolver(driver).resolve(chain)

        assert result.found is True
        assert result.resolved_locator.type == LocatorType.RESOURCE_ID
        assert result.attempted_count == 1


# ---------------------------------------------------------------------------
# Coordinate ratio
# ---------------------------------------------------------------------------


class TestLocatorResolverCoordinateRatio:
    def test_coordinate_ratio_resolves(self):
        driver = _make_driver({})
        driver.screen_size.return_value = (1080, 2400)  # width, height

        chain = LocatorChain(
            primary=Locator(type=LocatorType.RESOURCE_ID, value="x"),
            fallbacks=[
                Locator(type=LocatorType.COORDINATE_RATIO, value="", x=0.5, y=0.8)
            ],
        )
        result = LocatorResolver(driver).resolve(chain)

        assert result.found is True
        assert result.coordinates == (540, 1920)
        assert result.attempted_count == 2

    def test_coordinate_ratio_as_primary(self):
        driver = _make_driver({})
        driver.screen_size.return_value = (720, 1280)

        chain = LocatorChain(
            primary=Locator(
                type=LocatorType.COORDINATE_RATIO, value="", x=0.25, y=0.5
            )
        )
        result = LocatorResolver(driver).resolve(chain)

        assert result.found is True
        assert result.coordinates == (180, 640)
        assert result.attempted_count == 1

    def test_coordinate_ratio_with_none_x_y_returns_not_found(self):
        driver = _make_driver({})
        driver.screen_size.return_value = (1080, 2400)

        chain = LocatorChain(
            primary=Locator(type=LocatorType.COORDINATE_RATIO, value="")
        )
        result = LocatorResolver(driver).resolve(chain)

        assert result.found is False
        assert result.attempted_count == 1
