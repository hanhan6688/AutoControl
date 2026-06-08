"""Tests for IOSDriver — delegates to wda_service."""

from unittest.mock import MagicMock, patch

from app.automation.core.driver import DeviceDriver, ElementRef
from app.automation.drivers.ios_driver import IOSDriver, _map_locator


# ── _map_locator ─────────────────────────────────────────────────────────────


class TestMapLocator:
    def test_maps_class_name(self):
        assert _map_locator("class_name", "XCUIElementTypeButton") == {
            "class_name": "XCUIElementTypeButton"
        }

    def test_maps_resource_id_to_accessibility_id(self):
        assert _map_locator("resource_id", "btn_login") == {
            "accessibility_id": "btn_login"
        }

    def test_maps_text_to_name(self):
        assert _map_locator("text", "Login") == {"name": "Login"}

    def test_maps_xpath(self):
        assert _map_locator("xpath", "//XCUIElementTypeButton") == {
            "xpath": "//XCUIElementTypeButton"
        }

    def test_maps_content_desc_to_accessibility_id(self):
        assert _map_locator("content_desc", "login button") == {
            "accessibility_id": "login button"
        }

    def test_unknown_type_falls_back_to_name(self):
        assert _map_locator("unknown_type", "some_value") == {
            "name": "some_value"
        }


# ── Init ─────────────────────────────────────────────────────────────────────


class TestIOSDriverInit:
    def test_platform_is_ios(self):
        driver = IOSDriver(udid="abc123", wda_url="http://localhost:8100")
        assert driver.platform == "ios"

    def test_udid_stored(self):
        driver = IOSDriver(udid="abc123", wda_url="http://localhost:8100")
        assert driver.udid == "abc123"

    def test_wda_url_stored(self):
        driver = IOSDriver(udid="abc123", wda_url="http://localhost:8100")
        assert driver.wda_url == "http://localhost:8100"

    def test_implements_device_driver_protocol(self):
        assert issubclass(IOSDriver, DeviceDriver)


# ── App lifecycle ────────────────────────────────────────────────────────────


class TestIOSDriverLaunch:
    @patch("app.automation.drivers.ios_driver.wda_service")
    def test_launch_calls_wda(self, mock_wda):
        driver = IOSDriver(udid="abc123", wda_url="http://localhost:8100")
        driver.launch("com.demo.app")
        mock_wda.launch_app.assert_called_once_with(
            "abc123", "com.demo.app", wda_url="http://localhost:8100"
        )


class TestIOSDriverStopApp:
    def test_stop_app_is_noop(self):
        driver = IOSDriver(udid="abc123", wda_url="http://localhost:8100")
        # Should not raise
        driver.stop_app("com.demo.app")


# ── Touch / gesture ──────────────────────────────────────────────────────────


class TestIOSDriverTap:
    @patch("app.automation.drivers.ios_driver.wda_service")
    def test_tap_calls_wda(self, mock_wda):
        driver = IOSDriver(udid="abc123", wda_url="http://localhost:8100")
        driver.tap(100, 200)
        mock_wda.click.assert_called_once_with(
            "abc123", 100, 200, wda_url="http://localhost:8100"
        )


class TestIOSDriverLongPress:
    @patch("app.automation.drivers.ios_driver.wda_service")
    def test_long_press_calls_tap_hold(self, mock_wda):
        mock_client = MagicMock()
        mock_wda.get_client.return_value = mock_client
        driver = IOSDriver(udid="abc123", wda_url="http://localhost:8100")
        driver.long_press(100, 200, duration_ms=1500)
        mock_client.tap_hold.assert_called_once_with(100, 200, 1.5)

    @patch("app.automation.drivers.ios_driver.wda_service")
    def test_long_press_default_duration(self, mock_wda):
        mock_client = MagicMock()
        mock_wda.get_client.return_value = mock_client
        driver = IOSDriver(udid="abc123", wda_url="http://localhost:8100")
        driver.long_press(100, 200)
        mock_client.tap_hold.assert_called_once_with(100, 200, 1.0)


class TestIOSDriverSwipe:
    @patch("app.automation.drivers.ios_driver.wda_service")
    def test_swipe_calls_wda(self, mock_wda):
        driver = IOSDriver(udid="abc123", wda_url="http://localhost:8100")
        driver.swipe(100, 200, 300, 400, duration_ms=500)
        mock_wda.swipe.assert_called_once_with(
            "abc123", 100, 200, 300, 400, duration=0.5, wda_url="http://localhost:8100"
        )

    @patch("app.automation.drivers.ios_driver.wda_service")
    def test_swipe_default_duration(self, mock_wda):
        driver = IOSDriver(udid="abc123", wda_url="http://localhost:8100")
        driver.swipe(0, 0, 100, 100)
        mock_wda.swipe.assert_called_once_with(
            "abc123", 0, 0, 100, 100, duration=0.3, wda_url="http://localhost:8100"
        )


# ── Input ────────────────────────────────────────────────────────────────────


class TestIOSDriverInputText:
    @patch("app.automation.drivers.ios_driver.wda_service")
    def test_input_text_calls_type_keys(self, mock_wda):
        mock_client = MagicMock()
        mock_wda.get_client.return_value = mock_client
        driver = IOSDriver(udid="abc123", wda_url="http://localhost:8100")
        driver.input_text("hello world")
        mock_client.type_keys.assert_called_once_with("hello world")


class TestIOSDriverPressKey:
    @patch("app.automation.drivers.ios_driver.wda_service")
    def test_press_key_home(self, mock_wda):
        mock_client = MagicMock()
        mock_wda.get_client.return_value = mock_client
        driver = IOSDriver(udid="abc123", wda_url="http://localhost:8100")
        driver.press_key("home")
        mock_client.home.assert_called_once()

    @patch("app.automation.drivers.ios_driver.wda_service")
    def test_press_key_home_is_case_insensitive(self, mock_wda):
        mock_client = MagicMock()
        mock_wda.get_client.return_value = mock_client
        driver = IOSDriver(udid="abc123", wda_url="http://localhost:8100")
        driver.press_key("HOME")
        mock_client.home.assert_called_once()

    @patch("app.automation.drivers.ios_driver.wda_service")
    def test_press_key_back_swipes_from_left_edge(self, mock_wda):
        mock_client = MagicMock()
        mock_size = MagicMock()
        mock_size.width = 390
        mock_size.height = 844
        mock_client.window_size.return_value = mock_size
        mock_wda.get_client.return_value = mock_client
        driver = IOSDriver(udid="abc123", wda_url="http://localhost:8100")
        driver.press_key("back")
        mock_client.window_size.assert_called_once()
        mock_client.swipe.assert_called_once_with(10, 422, 195, 422, 0.3)

    @patch("app.automation.drivers.ios_driver.wda_service")
    def test_press_key_unknown_logs_warning(self, mock_wda):
        mock_client = MagicMock()
        mock_wda.get_client.return_value = mock_client
        driver = IOSDriver(udid="abc123", wda_url="http://localhost:8100")
        # Should not raise and should not call home/swipe
        driver.press_key("volume_up")
        mock_client.home.assert_not_called()
        mock_client.swipe.assert_not_called()


# ── Screen / hierarchy ───────────────────────────────────────────────────────


class TestIOSDriverScreenshot:
    @patch("app.automation.drivers.ios_driver.wda_service")
    def test_screenshot_calls_wda(self, mock_wda):
        mock_wda.screenshot.return_value = b"png_data"
        driver = IOSDriver(udid="abc123", wda_url="http://localhost:8100")
        result = driver.screenshot()
        assert result == b"png_data"
        mock_wda.screenshot.assert_called_once_with(
            "abc123", "http://localhost:8100"
        )


class TestIOSDriverDumpSource:
    @patch("app.automation.drivers.ios_driver.wda_service")
    def test_dump_source_calls_wda(self, mock_wda):
        mock_wda.dump_source.return_value = "<AppiumAUT><element /></AppiumAUT>"
        driver = IOSDriver(udid="abc123", wda_url="http://localhost:8100")
        result = driver.dump_source()
        assert result == "<AppiumAUT><element /></AppiumAUT>"
        mock_wda.dump_source.assert_called_once_with(
            "abc123", "http://localhost:8100"
        )


# ── Device info ──────────────────────────────────────────────────────────────


class TestIOSDriverCurrentApp:
    @patch("app.automation.drivers.ios_driver.wda_service")
    def test_returns_bundle_id(self, mock_wda):
        mock_client = MagicMock()
        mock_client.session_info.return_value = {"bundleId": "com.demo.app"}
        mock_wda.get_client.return_value = mock_client
        driver = IOSDriver(udid="abc123", wda_url="http://localhost:8100")
        result = driver.current_app()
        assert result == {"bundle_id": "com.demo.app"}
        mock_client.session_info.assert_called_once()

    @patch("app.automation.drivers.ios_driver.wda_service")
    def test_returns_empty_when_no_bundle_id(self, mock_wda):
        mock_client = MagicMock()
        mock_client.session_info.return_value = {}
        mock_wda.get_client.return_value = mock_client
        driver = IOSDriver(udid="abc123", wda_url="http://localhost:8100")
        result = driver.current_app()
        assert result == {"bundle_id": ""}


class TestIOSDriverScreenSize:
    @patch("app.automation.drivers.ios_driver.wda_service")
    def test_returns_width_and_height(self, mock_wda):
        mock_client = MagicMock()
        mock_size = MagicMock()
        mock_size.width = 390
        mock_size.height = 844
        mock_client.window_size.return_value = mock_size
        mock_wda.get_client.return_value = mock_client
        driver = IOSDriver(udid="abc123", wda_url="http://localhost:8100")
        result = driver.screen_size()
        assert result == (390, 844)
        mock_client.window_size.assert_called_once()


# ── Element search ───────────────────────────────────────────────────────────


class TestIOSDriverFindElement:
    @patch("app.automation.drivers.ios_driver.wda_service")
    def test_find_element_found_with_bounds(self, mock_wda):
        mock_client = MagicMock()
        mock_el = MagicMock()
        mock_el.exists = True
        mock_el.bounds = {"x": 50, "y": 100, "width": 200, "height": 50}
        mock_client.find_element.return_value = mock_el
        mock_wda.get_client.return_value = mock_client
        driver = IOSDriver(udid="abc123", wda_url="http://localhost:8100")
        result = driver.find_element("text", "Login", timeout=10.0)
        mock_client.find_element.assert_called_once_with(name="Login")
        assert isinstance(result, ElementRef)
        assert result.found is True
        assert result.locator_type == "text"
        assert result.locator_value == "Login"
        assert result.bounds == {"x": 50, "y": 100, "width": 200, "height": 50}
        assert result.center == (150, 125)

    @patch("app.automation.drivers.ios_driver.wda_service")
    def test_find_element_not_found(self, mock_wda):
        mock_client = MagicMock()
        mock_el = MagicMock()
        mock_el.exists = False
        mock_client.find_element.return_value = mock_el
        mock_wda.get_client.return_value = mock_client
        driver = IOSDriver(udid="abc123", wda_url="http://localhost:8100")
        result = driver.find_element("class_name", "XCUIElementTypeButton", timeout=5.0)
        mock_client.find_element.assert_called_once_with(
            class_name="XCUIElementTypeButton"
        )
        assert isinstance(result, ElementRef)
        assert result.found is False
        assert result.locator_type == "class_name"
        assert result.locator_value == "XCUIElementTypeButton"
        assert result.bounds is None
        assert result.center is None

    @patch("app.automation.drivers.ios_driver.wda_service")
    def test_find_element_uses_xpath_locator(self, mock_wda):
        mock_client = MagicMock()
        mock_el = MagicMock()
        mock_el.exists = False
        mock_client.find_element.return_value = mock_el
        mock_wda.get_client.return_value = mock_client
        driver = IOSDriver(udid="abc123", wda_url="http://localhost:8100")
        driver.find_element("xpath", "//XCUIElementTypeButton[@label='OK']")
        mock_client.find_element.assert_called_once_with(
            xpath="//XCUIElementTypeButton[@label='OK']"
        )

    @patch("app.automation.drivers.ios_driver.wda_service")
    def test_find_element_uses_resource_id_as_accessibility_id(self, mock_wda):
        mock_client = MagicMock()
        mock_el = MagicMock()
        mock_el.exists = False
        mock_client.find_element.return_value = mock_el
        mock_wda.get_client.return_value = mock_client
        driver = IOSDriver(udid="abc123", wda_url="http://localhost:8100")
        driver.find_element("resource_id", "com.demo:id/btn_login")
        mock_client.find_element.assert_called_once_with(
            accessibility_id="com.demo:id/btn_login"
        )

    @patch("app.automation.drivers.ios_driver.wda_service")
    def test_find_element_non_existent_object(self, mock_wda):
        """Element without .exists attribute falls back to bool(element)."""
        mock_client = MagicMock()
        # A MagicMock without .exists configured — hasattr check fails,
        # but bool(MagicMock()) is True, so found should be True.
        mock_el = MagicMock(spec=[])  # spec=[] prevents auto-creation of attributes
        mock_el.bounds = {"x": 0, "y": 0, "width": 100, "height": 50}
        # Delete the 'exists' attribute so hasattr returns False
        del mock_el.exists
        mock_client.find_element.return_value = mock_el
        mock_wda.get_client.return_value = mock_client
        driver = IOSDriver(udid="abc123", wda_url="http://localhost:8100")
        result = driver.find_element("text", "Something")
        assert result.found is True
        assert result.center == (50, 25)


class TestIOSDriverElementExists:
    @patch.object(IOSDriver, "find_element")
    def test_element_exists_returns_true_when_found(self, mock_find):
        mock_find.return_value = ElementRef(
            found=True, locator_type="text", locator_value="Login"
        )
        driver = IOSDriver(udid="abc123", wda_url="http://localhost:8100")
        assert driver.element_exists("text", "Login") is True
        mock_find.assert_called_once_with("text", "Login", timeout=5.0)

    @patch.object(IOSDriver, "find_element")
    def test_element_exists_returns_false_when_not_found(self, mock_find):
        mock_find.return_value = ElementRef(
            found=False, locator_type="text", locator_value="Login"
        )
        driver = IOSDriver(udid="abc123", wda_url="http://localhost:8100")
        assert driver.element_exists("text", "Login") is False
        mock_find.assert_called_once_with("text", "Login", timeout=5.0)

    @patch.object(IOSDriver, "find_element")
    def test_element_exists_passes_custom_timeout(self, mock_find):
        mock_find.return_value = ElementRef(
            found=False, locator_type="text", locator_value="Login"
        )
        driver = IOSDriver(udid="abc123", wda_url="http://localhost:8100")
        driver.element_exists("text", "Login", timeout=15.0)
        mock_find.assert_called_once_with("text", "Login", timeout=15.0)
