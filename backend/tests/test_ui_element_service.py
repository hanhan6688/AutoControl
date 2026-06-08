from __future__ import annotations


ANDROID_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout" package="com.tencent.mm" content-desc="" clickable="false" enabled="true" bounds="[0,0][1080,1920]">
    <node index="1" text="" resource-id="com.tencent.mm:id/container" class="android.view.ViewGroup" package="com.tencent.mm" content-desc="" clickable="false" enabled="true" bounds="[60,120][1020,1800]">
      <node index="2" text="AI找房" resource-id="com.tencent.mm:id/ai_house" class="android.widget.Button" package="com.tencent.mm" content-desc="AI找房入口" clickable="true" enabled="true" bounds="[100,200][420,300]" />
      <node index="3" text="AI找房" resource-id="" class="android.widget.TextView" package="com.tencent.mm" content-desc="" clickable="false" enabled="true" bounds="[130,220][390,280]" />
    </node>
  </node>
</hierarchy>
"""


DUPLICATE_ANDROID_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout" package="com.tencent.mm" content-desc="" clickable="false" enabled="true" bounds="[0,0][1080,1920]">
    <node index="1" text="" resource-id="" class="android.widget.RelativeLayout" package="com.tencent.mm" content-desc="" clickable="true" enabled="true" bounds="[100,100][300,220]" />
    <node index="2" text="" resource-id="" class="android.widget.RelativeLayout" package="com.tencent.mm" content-desc="" clickable="true" enabled="true" bounds="[320,100][520,220]" />
  </node>
</hierarchy>
"""


INPUT_ANDROID_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout" package="com.jjs.android.butler.test" content-desc="" clickable="false" enabled="true" bounds="[0,0][1080,2400]">
    <node index="1" text="" resource-id="com.jjs.android.butler.test:id/phone" class="android.widget.EditText" package="com.jjs.android.butler.test" content-desc="手机号" clickable="true" enabled="true" bounds="[80,320][1000,420]" />
  </node>
</hierarchy>
"""


WEBVIEW_TEXT_ANDROID_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout" package="com.jjs.android.butler.test" content-desc="" clickable="false" enabled="true" bounds="[0,0][1080,2400]">
    <node index="1" text="" resource-id="" class="android.webkit.WebView" package="com.jjs.android.butler.test" content-desc="" clickable="false" enabled="true" bounds="[0,0][1080,2400]">
      <node index="2" text="AI找房" resource-id="" class="android.widget.TextView" package="com.jjs.android.butler.test" content-desc="" clickable="true" enabled="true" bounds="[80,320][380,420]" />
    </node>
  </node>
</hierarchy>
"""


WEBVIEW_PARENT_CLICKABLE_ANDROID_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout" package="com.jjs.android.butler.test" content-desc="" clickable="false" enabled="true" bounds="[0,0][1080,2400]">
    <node index="1" text="" resource-id="" class="android.view.View" package="com.jjs.android.butler.test" content-desc="" clickable="true" enabled="true" bounds="[40,300][600,500]">
      <node index="2" text="AI找房" resource-id="" class="android.widget.TextView" package="com.jjs.android.butler.test" content-desc="" clickable="false" enabled="true" bounds="[80,330][260,390]" />
    </node>
  </node>
</hierarchy>
"""


def test_parse_android_hierarchy_builds_stable_selector() -> None:
    from app.services.ui_element_service import UIElementService

    elements = UIElementService().parse_generic_hierarchy(ANDROID_XML, platform="android")
    target = next(item for item in elements if item.resource_id == "com.tencent.mm:id/ai_house")

    assert target.text == "AI找房"
    assert target.content_desc == "AI找房入口"
    assert target.bounds.center == (260, 250)
    assert target.selector == {
        "resource_id": "com.tencent.mm:id/ai_house",
        "text": "AI找房",
        "content_desc": "AI找房入口",
        "class_name": "android.widget.Button",
        "package": "com.tencent.mm",
    }
    assert target.xpath == '//android.widget.Button[@resource-id="com.tencent.mm:id/ai_house"]'


def test_locate_point_prefers_clickable_element_over_nested_label() -> None:
    from app.services.ui_element_service import UIElementService

    result = UIElementService().locate_generic_xml(
        xml=ANDROID_XML,
        x=150,
        y=240,
        package_name="com.tencent.mm",
        platform="android",
    )

    assert result.found is True
    assert result.element is not None
    assert result.element.class_name == "android.widget.Button"
    assert "auto_execute.click(" in result.generated_code
    assert 'resource_id="com.tencent.mm:id/ai_house"' in result.generated_code
    assert "click(text=" not in result.generated_code
    assert ", text=" not in result.generated_code
    assert 'content_desc="AI找房入口"' not in result.generated_code
    assert 'ocr_text="AI找房"' in result.generated_code
    assert "fallback=(150, 240)" in result.generated_code


def test_find_element_matches_selector_without_exact_coordinates() -> None:
    from app.services.ui_element_service import UIElementService

    service = UIElementService()
    elements = service.parse_generic_hierarchy(ANDROID_XML, platform="android")
    match = service.find_element(
        elements,
        text="AI找房",
        resource_id="com.tencent.mm:id/ai_house",
        package="com.tencent.mm",
    )

    assert match is not None
    assert match.bounds.center == (260, 250)


def test_duplicate_controls_without_stable_attrs_get_unique_hierarchy_xpath() -> None:
    from app.services.ui_element_service import UIElementService

    service = UIElementService()
    elements = service.parse_generic_hierarchy(DUPLICATE_ANDROID_XML, platform="android")
    controls = [item for item in elements if item.class_name == "android.widget.RelativeLayout"]

    assert len(controls) == 2
    assert controls[0].xpath == "/hierarchy/android.widget.FrameLayout[1]/android.widget.RelativeLayout[1]"
    assert controls[1].xpath == "/hierarchy/android.widget.FrameLayout[1]/android.widget.RelativeLayout[2]"

    match = service.find_element(
        elements,
        class_name="android.widget.RelativeLayout",
        package="com.tencent.mm",
        xpath=controls[1].xpath,
    )

    assert match is not None
    assert match.bounds.center == (420, 160)


def test_locate_point_generates_replayable_xpath_for_duplicate_controls() -> None:
    from app.services.ui_element_service import UIElementService

    result = UIElementService().locate_generic_xml(
        xml=DUPLICATE_ANDROID_XML,
        x=420,
        y=160,
        package_name="com.tencent.mm",
        platform="android",
    )

    assert result.found is True
    assert result.element is not None
    assert result.element.xpath == "/hierarchy/android.widget.FrameLayout[1]/android.widget.RelativeLayout[2]"
    assert 'xpath="/hierarchy/android.widget.FrameLayout[1]/android.widget.RelativeLayout[2]"' in result.generated_code


def test_strict_xpath_mode_generates_only_xpath_without_coordinate_fallback() -> None:
    from app.services.ui_element_service import UIElementService

    result = UIElementService().locate_generic_xml(
        xml=ANDROID_XML,
        x=150,
        y=240,
        package_name="com.tencent.mm",
        strict_xpath_only=True,
        platform="android",
    )

    assert result.found is True
    assert result.element is not None
    assert result.element.xpath == '//android.widget.Button[@resource-id="com.tencent.mm:id/ai_house"]'
    assert result.element.hierarchy_xpath == (
        "/hierarchy/android.widget.FrameLayout[1]/android.view.ViewGroup[1]/android.widget.Button[1]"
    )
    assert result.generated_code == (
        'auto_execute.click(xpath="//android.widget.Button[@resource-id=\\"com.tencent.mm:id/ai_house\\"]")'
    )


def test_strict_xpath_mode_uses_text_xpath_when_resource_id_is_missing() -> None:
    from app.services.ui_element_service import UIElementService

    result = UIElementService().locate_generic_xml(
        xml=WEBVIEW_TEXT_ANDROID_XML,
        x=120,
        y=360,
        package_name="com.jjs.android.butler.test",
        strict_xpath_only=True,
        platform="android",
    )

    assert result.found is True
    assert result.element is not None
    assert result.element.hierarchy_xpath == (
        "/hierarchy/android.widget.FrameLayout[1]/android.webkit.WebView[1]/android.widget.TextView[1]"
    )
    assert result.generated_code == (
        'auto_execute.click(xpath="//android.widget.TextView[@text=\\"AI找房\\" and @package=\\"com.jjs.android.butler.test\\"]")'
    )


def test_locate_point_prefers_labeled_child_over_unlabeled_clickable_webview_parent() -> None:
    from app.services.ui_element_service import UIElementService

    result = UIElementService().locate_generic_xml(
        xml=WEBVIEW_PARENT_CLICKABLE_ANDROID_XML,
        x=120,
        y=360,
        package_name="com.jjs.android.butler.test",
        strict_xpath_only=True,
        platform="android",
    )

    assert result.found is True
    assert result.element is not None
    assert result.element.class_name == "android.widget.TextView"
    assert result.generated_code == (
        'auto_execute.click(xpath="//android.widget.TextView[@text=\\"AI找房\\" and @package=\\"com.jjs.android.butler.test\\"]")'
    )


def test_text_input_element_generates_targeted_input_code() -> None:
    from app.services.ui_element_service import UIElementService

    service = UIElementService()
    result = service.locate_generic_xml(
        xml=INPUT_ANDROID_XML,
        x=120,
        y=360,
        package_name="com.jjs.android.butler.test",
        strict_xpath_only=True,
        platform="android",
    )

    assert result.found is True
    assert result.element is not None
    assert service.is_text_input(result.element) is True
    assert service.build_input_code(result.element, "1234564") == (
        'auto_execute.input(xpath="//android.widget.EditText[@resource-id=\\"com.jjs.android.butler.test:id/phone\\"]", text="1234564")'
    )


def test_strict_xpath_mode_does_not_generate_coordinate_fallback_when_no_element_found() -> None:
    from app.services.ui_element_service import UIElementService

    result = UIElementService().locate_generic_xml(
        xml=ANDROID_XML,
        x=2000,
        y=2000,
        package_name="com.tencent.mm",
        strict_xpath_only=True,
        platform="android",
    )

    assert result.found is False
    assert result.generated_code == ""
    assert "strict XPath mode" in result.message


def test_locate_point_does_not_record_other_package_when_target_package_is_set() -> None:
    from app.services.ui_element_service import UIElementService

    keyboard_xml = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
    <hierarchy rotation="0">
      <node index="0" text="" resource-id="" class="android.widget.FrameLayout" package="com.google.android.inputmethod.latin" content-desc="" clickable="false" enabled="true" bounds="[0,1400][1080,1920]">
        <node index="1" text="A" resource-id="" class="android.inputmethodservice.KeyboardView" package="com.google.android.inputmethod.latin" content-desc="A" clickable="true" enabled="true" bounds="[20,1500][120,1620]" />
      </node>
    </hierarchy>
    """

    result = UIElementService().locate_generic_xml(
        xml=keyboard_xml,
        x=60,
        y=1560,
        package_name="com.jjs.android.butler.test",
        strict_xpath_only=True,
        platform="android",
    )

    assert result.found is False
    assert result.generated_code == ""
    assert "outside target package" in result.message


def test_find_element_matches_hierarchy_xpath_for_replay() -> None:
    from app.services.ui_element_service import UIElementService

    service = UIElementService()
    elements = service.parse_generic_hierarchy(ANDROID_XML, platform="android")
    match = service.find_element(
        elements,
        xpath="/hierarchy/android.widget.FrameLayout[1]/android.view.ViewGroup[1]/android.widget.Button[1]",
    )

    assert match is not None
    assert match.resource_id == "com.tencent.mm:id/ai_house"


def test_locate_device_point_can_reuse_recent_hierarchy_dump(monkeypatch) -> None:
    from app.services import ui_element_service
    from app.services.ui_element_service import UIElementService

    class FakeADB:
        calls = 0

        def dump_ui_hierarchy(self, udid: str) -> str:
            self.calls += 1
            return ANDROID_XML

    # Make u2 fail so the test exercises the ADB fallback path
    monkeypatch.setattr(ui_element_service.u2_service, "dump_hierarchy", lambda udid: (_ for _ in ()).throw(RuntimeError("u2 unavailable")))

    UIElementService.clear_hierarchy_cache()
    fake_adb = FakeADB()
    service = UIElementService(adb=fake_adb)

    first = service.locate_device_point(
        udid="device-1",
        x=150,
        y=240,
        package_name="com.tencent.mm",
        strict_xpath_only=True,
        cache_ttl_ms=1000,
    )
    second = service.locate_device_point(
        udid="device-1",
        x=150,
        y=240,
        package_name="com.tencent.mm",
        strict_xpath_only=True,
        cache_ttl_ms=1000,
    )

    assert first.found is True
    assert second.found is True
    assert fake_adb.calls == 1

    UIElementService.clear_hierarchy_cache()


def test_ios_locate_fetches_source_from_wda(monkeypatch) -> None:
    from app.services import ui_element_service
    from app.services.ui_element_service import UIElementService

    ios_xml = """
    <AppiumAUT>
      <XCUIElementTypeApplication type="XCUIElementTypeApplication" name="Leyoujia" label="Leyoujia" x="0" y="0" width="390" height="844">
        <XCUIElementTypeButton type="XCUIElementTypeButton" name="AI找房" label="AI找房" enabled="true" x="40" y="120" width="120" height="48" />
      </XCUIElementTypeApplication>
    </AppiumAUT>
    """

    # wda_enabled is True by default, so wda_service is used first
    monkeypatch.setattr(ui_element_service.wda_service, "dump_source", lambda udid: ios_xml)

    result = UIElementService().locate_device_point(
        udid="ios-device",
        x=80,
        y=140,
        platform="ios",
        strict_xpath_only=True,
        wda_url="http://127.0.0.1:8100",
    )

    assert result.found is True
    assert result.element is not None
    assert result.element.content_desc == "AI找房"
    assert result.generated_code == (
        'auto_execute.click(xpath="//XCUIElementTypeButton[@content-desc=\\"AI找房\\"]")'
    )


def test_ios_locate_falls_back_to_http_when_wda_fails(monkeypatch) -> None:
    from app.services import ui_element_service
    from app.services.ui_element_service import UIElementService

    ios_xml = """
    <AppiumAUT>
      <XCUIElementTypeApplication type="XCUIElementTypeApplication" name="Leyoujia" label="Leyoujia" x="0" y="0" width="390" height="844">
        <XCUIElementTypeButton type="XCUIElementTypeButton" name="AI找房" label="AI找房" enabled="true" x="40" y="120" width="120" height="48" />
      </XCUIElementTypeApplication>
    </AppiumAUT>
    """
    calls: list[str] = []

    class FakeResponse:
        status_code = 200
        text = '{"source": ' + UIElementService._py_string(ios_xml) + "}"

    def fake_get(url, timeout, verify):
        calls.append(url)
        return FakeResponse()

    # wda_service fails, so it falls back to HTTP
    monkeypatch.setattr(ui_element_service.wda_service, "dump_source", lambda udid: (_ for _ in ()).throw(RuntimeError("wda not available")))
    monkeypatch.setattr(ui_element_service.requests, "get", fake_get)

    result = UIElementService().locate_device_point(
        udid="ios-device",
        x=80,
        y=140,
        platform="ios",
        strict_xpath_only=True,
        wda_url="http://127.0.0.1:8100",
    )

    assert calls == ["http://127.0.0.1:8100/source"]
    assert result.found is True
    assert result.element is not None
    assert result.element.content_desc == "AI找房"


def test_android_locate_uses_u2_when_enabled(monkeypatch) -> None:
    from app.services import ui_element_service
    from app.services.ui_element_service import UIElementService

    u2_calls: list[str] = []

    def fake_u2_dump(udid: str) -> str:
        u2_calls.append(udid)
        return ANDROID_XML

    monkeypatch.setattr(ui_element_service.u2_service, "dump_hierarchy", fake_u2_dump)

    result = UIElementService().locate_device_point(
        udid="android-device",
        x=150,
        y=240,
        package_name="com.tencent.mm",
    )

    assert u2_calls == ["android-device"]
    assert result.found is True
    assert result.element is not None
    assert result.element.class_name == "android.widget.Button"


def test_android_locate_falls_back_to_adb_when_u2_fails(monkeypatch) -> None:
    from app.services import ui_element_service
    from app.services.ui_element_service import UIElementService

    class FakeADB:
        calls = 0

        def dump_ui_hierarchy(self, udid: str) -> str:
            self.calls += 1
            return ANDROID_XML

    monkeypatch.setattr(ui_element_service.u2_service, "dump_hierarchy", lambda udid: (_ for _ in ()).throw(RuntimeError("u2 not available")))
    monkeypatch.setattr(ui_element_service.settings, "u2_enabled", True)

    fake_adb = FakeADB()
    service = UIElementService(adb=fake_adb)

    result = service.locate_device_point(
        udid="android-device",
        x=150,
        y=240,
        package_name="com.tencent.mm",
    )

    assert fake_adb.calls == 1
    assert result.found is True
    assert result.element.class_name == "android.widget.Button"


def test_android_click_prefers_u2_selector_before_hierarchy_dump(monkeypatch) -> None:
    from app.services import ui_element_service
    from app.services.ui_element_service import UIElementService

    calls: list[dict] = []

    def fake_click_selector(udid: str, **kwargs) -> bool:
        calls.append({"udid": udid, **kwargs})
        return True

    class FakeADB:
        def dump_ui_hierarchy(self, udid: str) -> str:
            raise AssertionError("hierarchy dump should not be used when u2 selector click succeeds")

        def shell(self, udid: str, command: str) -> None:
            raise AssertionError("coordinate fallback should not be used when u2 selector click succeeds")

    monkeypatch.setattr(ui_element_service.settings, "u2_enabled", True)
    monkeypatch.setattr(ui_element_service.u2_service, "click_selector", fake_click_selector, raising=False)

    assert UIElementService(adb=FakeADB()).click(
        udid="android-device",
        resource_id="com.tencent.mm:id/ai_house",
        package="com.tencent.mm",
        timeout=2,
    )
    assert calls == [
        {
            "udid": "android-device",
            "text": None,
            "resource_id": "com.tencent.mm:id/ai_house",
            "content_desc": None,
            "class_name": None,
            "package": "com.tencent.mm",
            "xpath": None,
            "timeout": 2,
        }
    ]
