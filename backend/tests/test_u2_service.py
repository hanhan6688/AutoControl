from __future__ import annotations


def test_click_selector_uses_xpath_target(monkeypatch) -> None:
    from app.services import u2_service

    calls: list[tuple[str, object]] = []

    class FakeXPathTarget:
        def wait(self, timeout: float) -> bool:
            calls.append(("wait", timeout))
            return True

        def click(self) -> None:
            calls.append(("click", None))

    class FakeDevice:
        def xpath(self, value: str) -> FakeXPathTarget:
            calls.append(("xpath", value))
            return FakeXPathTarget()

        def __call__(self, **kwargs):
            calls.append(("selector", kwargs))
            return FakeXPathTarget()

    monkeypatch.setattr(u2_service, "get_device", lambda udid: FakeDevice())

    assert u2_service.click_selector("device-1", xpath='//android.widget.EditText[@text="账号"]', timeout=1.5)
    assert calls == [
        ("xpath", '//android.widget.EditText[@text="账号"]'),
        ("wait", 1.5),
        ("click", None),
    ]


def test_click_selector_maps_android_locator_fields(monkeypatch) -> None:
    from app.services import u2_service

    calls: list[tuple[str, object]] = []

    class FakeTarget:
        def wait(self, timeout: float) -> bool:
            calls.append(("wait", timeout))
            return True

        def click(self) -> None:
            calls.append(("click", None))

    class FakeDevice:
        def __call__(self, **kwargs):
            calls.append(("selector", kwargs))
            return FakeTarget()

    monkeypatch.setattr(u2_service, "get_device", lambda udid: FakeDevice())

    assert u2_service.click_selector(
        "device-1",
        resource_id="com.example:id/search",
        text="搜索",
        content_desc="搜索框",
        class_name="android.widget.EditText",
        package="com.example",
        timeout=2,
    )
    assert calls == [
        (
            "selector",
            {
                "resourceId": "com.example:id/search",
                "text": "搜索",
                "description": "搜索框",
                "className": "android.widget.EditText",
                "packageName": "com.example",
            },
        ),
        ("wait", 2),
        ("click", None),
    ]


def test_input_selector_sets_text_on_target(monkeypatch) -> None:
    from app.services import u2_service

    calls: list[tuple[str, object]] = []

    class FakeTarget:
        def wait(self, timeout: float) -> bool:
            calls.append(("wait", timeout))
            return True

        def clear_text(self) -> None:
            calls.append(("clear_text", None))

        def set_text(self, value: str) -> None:
            calls.append(("set_text", value))

    class FakeDevice:
        def __call__(self, **kwargs):
            calls.append(("selector", kwargs))
            return FakeTarget()

    monkeypatch.setattr(u2_service, "get_device", lambda udid: FakeDevice())

    assert u2_service.input_selector(
        "device-1",
        "13530926521",
        resource_id="com.example:id/phone",
        clear=True,
        timeout=3,
    )
    assert calls == [
        ("selector", {"resourceId": "com.example:id/phone"}),
        ("wait", 3),
        ("clear_text", None),
        ("set_text", "13530926521"),
    ]
