"""Python code generator -- converts Steps into auto_execute-compatible Python code."""
from __future__ import annotations

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


def generate_step_code(step: Step) -> str:
    lines = []
    if step.before_wait is not None:
        lines.append(_generate_wait(step.before_wait))
    lines.append(_generate_action(step.action))
    for assertion in step.assertions:
        lines.append(_generate_assertion(assertion))
    return "\n".join(lines)


def generate_script(steps: list[Step]) -> str:
    lines = []
    for step in steps:
        lines.append(f"# {step.id}: {step.title}")
        lines.append(generate_step_code(step))
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _locator_arg(locator: Locator) -> str:
    mapping = {
        LocatorType.RESOURCE_ID: "resource_id",
        LocatorType.TEXT: "text",
        LocatorType.CONTENT_DESC: "content_desc",
        LocatorType.CLASS_NAME: "class_name",
        LocatorType.XPATH: "xpath",
    }
    arg_name = mapping.get(locator.type)
    if arg_name:
        return f'{arg_name}="{locator.value}"'
    if locator.type == LocatorType.COORDINATE_RATIO:
        return f"coordinate_ratio=({locator.x}, {locator.y})"
    return f'locator="{locator.value}"'


def _generate_action(action: ActionSpec) -> str:
    atype = action.type
    if atype == ActionType.TAP:
        return _generate_click(action)
    if atype == ActionType.LONG_PRESS:
        return _generate_long_press(action)
    if atype == ActionType.SWIPE:
        return _generate_swipe(action)
    if atype == ActionType.INPUT:
        return _generate_input(action)
    if atype == ActionType.LAUNCH:
        return f'auto_execute.launch("{action.params.get("app_id", "")}")'
    if atype == ActionType.STOP_APP:
        return f'auto_execute.stop_app("{action.params.get("app_id", "")}")'
    if atype == ActionType.PRESS_KEY:
        key = action.params.get("key", "")
        if key.lower() == "back":
            return "auto_execute.back()"
        if key.lower() == "home":
            return "auto_execute.home()"
        return f'auto_execute.press_key("{key}")'
    return f"# unsupported action: {atype.value}"


def _generate_click(action: ActionSpec) -> str:
    if action.locator is not None:
        loc_arg = _locator_arg(action.locator)
        fx = action.params.get("fallback_x")
        fy = action.params.get("fallback_y")
        if fx is not None and fy is not None:
            return f"auto_execute.click({loc_arg}, fallback=({fx}, {fy}))"
        return f"auto_execute.click({loc_arg})"
    x = action.params.get("x", 0)
    y = action.params.get("y", 0)
    return f"auto_execute.click({x}, {y})"


def _generate_long_press(action: ActionSpec) -> str:
    x = action.params.get("x", 0)
    y = action.params.get("y", 0)
    duration = action.params.get("duration_ms", 1000)
    return f"auto_execute.long_press({x}, {y}, duration={duration})"


def _generate_swipe(action: ActionSpec) -> str:
    sx = action.params.get("start_x", 0)
    sy = action.params.get("start_y", 0)
    ex = action.params.get("end_x", 0)
    ey = action.params.get("end_y", 0)
    duration = action.params.get("duration_ms", 300)
    return f"auto_execute.swipe({sx}, {sy}, {ex}, {ey}, duration={duration})"


def _generate_input(action: ActionSpec) -> str:
    text = action.params.get("text", "")
    if action.locator is not None:
        loc_arg = _locator_arg(action.locator)
        return f'auto_execute.input({loc_arg}, text="{text}")'
    return f'auto_execute.input(text="{text}")'


def _generate_wait(wait: WaitSpec) -> str:
    if wait.locator is not None:
        loc_arg = _locator_arg(wait.locator)
        return f"auto_execute.wait_for_element({loc_arg}, timeout={int(wait.timeout)})"
    return f"auto_execute.wait(timeout={int(wait.timeout)})"


def _generate_assertion(assertion: AssertionSpec) -> str:
    if assertion.type == AssertionType.EXISTS and assertion.locator is not None:
        return f"auto_execute.assert_element({_locator_arg(assertion.locator)})"
    if assertion.type == AssertionType.TEXT_EQUALS and assertion.locator is not None:
        return f'auto_execute.assert_text_visible({_locator_arg(assertion.locator)}, expected_text="{assertion.expected or ""}")'
    if assertion.type == AssertionType.TEXT_CONTAINS and assertion.expected:
        return f'auto_execute.assert_text_visible(text="{assertion.expected}")'
    if assertion.type == AssertionType.OCR_CONTAINS and assertion.expected:
        return f'ocr.find("{assertion.expected}")'
    return f"# assertion: {assertion.type.value}"
