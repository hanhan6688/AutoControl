from app.automation.core.models import (
    ActionSpec,
    ActionType,
    AssertionSpec,
    AssertionType,
    Locator,
    LocatorType,
    Step,
    WaitConditionType,
    WaitSpec,
)
from app.automation.recording.codegen import generate_step_code, generate_script


class TestGenerateStepCode:
    def test_tap_resource_id(self):
        step = Step(
            id="s1",
            title="登录",
            action=ActionSpec(
                type=ActionType.TAP,
                locator=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/login"),
            ),
        )
        assert 'resource_id="com.demo:id/login"' in generate_step_code(step)

    def test_tap_text(self):
        step = Step(
            id="s2",
            title="确定",
            action=ActionSpec(
                type=ActionType.TAP,
                locator=Locator(type=LocatorType.TEXT, value="确定"),
            ),
        )
        assert 'text="确定"' in generate_step_code(step)

    def test_tap_fallback_coords(self):
        step = Step(
            id="s3",
            title="点击",
            action=ActionSpec(
                type=ActionType.TAP,
                locator=Locator(type=LocatorType.RESOURCE_ID, value="btn"),
                params={"fallback_x": 541, "fallback_y": 1768},
            ),
        )
        code = generate_step_code(step)
        assert "fallback=(541, 1768)" in code

    def test_tap_coordinate_only(self):
        step = Step(
            id="s4",
            title="点击",
            action=ActionSpec(type=ActionType.TAP, params={"x": 540, "y": 960}),
        )
        assert "auto_execute.click(540, 960)" in generate_step_code(step)

    def test_input_action(self):
        step = Step(
            id="s5",
            title="输入",
            action=ActionSpec(
                type=ActionType.INPUT,
                locator=Locator(type=LocatorType.RESOURCE_ID, value="edit"),
                params={"text": "hello"},
            ),
        )
        assert 'text="hello"' in generate_step_code(step)

    def test_swipe_action(self):
        step = Step(
            id="s6",
            title="滑动",
            action=ActionSpec(
                type=ActionType.SWIPE,
                params={
                    "start_x": 100,
                    "start_y": 500,
                    "end_x": 100,
                    "end_y": 200,
                    "duration_ms": 300,
                },
            ),
        )
        assert (
            "auto_execute.swipe(100, 500, 100, 200, duration=300)"
            in generate_step_code(step)
        )

    def test_launch(self):
        step = Step(
            id="s7",
            title="启动",
            action=ActionSpec(
                type=ActionType.LAUNCH,
                params={"app_id": "com.demo.app"},
            ),
        )
        assert 'auto_execute.launch("com.demo.app")' in generate_step_code(step)

    def test_back_key(self):
        step = Step(
            id="s8",
            title="返回",
            action=ActionSpec(
                type=ActionType.PRESS_KEY,
                params={"key": "back"},
            ),
        )
        assert "auto_execute.back()" in generate_step_code(step)

    def test_home_key(self):
        step = Step(
            id="s9",
            title="主页",
            action=ActionSpec(
                type=ActionType.PRESS_KEY,
                params={"key": "home"},
            ),
        )
        assert "auto_execute.home()" in generate_step_code(step)

    def test_long_press(self):
        step = Step(
            id="s10",
            title="长按",
            action=ActionSpec(
                type=ActionType.LONG_PRESS,
                params={"x": 540, "y": 960, "duration_ms": 1000},
            ),
        )
        assert (
            "auto_execute.long_press(540, 960, duration=1000)"
            in generate_step_code(step)
        )


class TestGenerateStepCodeWithWait:
    def test_before_wait(self):
        step = Step(
            id="s11",
            title="点击",
            action=ActionSpec(
                type=ActionType.TAP,
                locator=Locator(type=LocatorType.RESOURCE_ID, value="login"),
            ),
            before_wait=WaitSpec(
                type=WaitConditionType.VISIBLE,
                locator=Locator(type=LocatorType.RESOURCE_ID, value="login"),
                timeout=10.0,
            ),
        )
        code = generate_step_code(step)
        assert "auto_execute.wait_for_element" in code
        assert "auto_execute.click" in code


class TestGenerateStepCodeWithAssertion:
    def test_exists_assertion(self):
        step = Step(
            id="s12",
            title="检查",
            action=ActionSpec(
                type=ActionType.TAP,
                locator=Locator(type=LocatorType.RESOURCE_ID, value="login"),
            ),
            assertions=[
                AssertionSpec(
                    type=AssertionType.EXISTS,
                    locator=Locator(type=LocatorType.RESOURCE_ID, value="home"),
                )
            ],
        )
        assert "auto_execute.assert_element" in generate_step_code(step)


class TestGenerateScript:
    def test_multiple_steps(self):
        steps = [
            Step(
                id="s1",
                title="启动",
                action=ActionSpec(
                    type=ActionType.LAUNCH,
                    params={"app_id": "com.demo.app"},
                ),
            ),
            Step(
                id="s2",
                title="点击",
                action=ActionSpec(
                    type=ActionType.TAP,
                    locator=Locator(type=LocatorType.RESOURCE_ID, value="login"),
                ),
            ),
        ]
        script = generate_script(steps)
        assert "# s1: 启动" in script
        assert "# s2: 点击" in script
        assert "auto_execute.launch" in script
        assert "auto_execute.click" in script
