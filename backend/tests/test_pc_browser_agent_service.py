from __future__ import annotations

import asyncio
from pathlib import Path


class FakeElement:
    def __init__(self, ref: str, tag: str = "button", text: str | None = None, attrs: dict[str, str] | None = None):
        self.ref = ref
        self.tag = tag
        self.text = text
        self.attrs = attrs or {}


class FakeBrowser:
    def __init__(self, snapshots: list[list[FakeElement]] | None = None, url: str = "https://example.test/dashboard") -> None:
        self.snapshots = snapshots or [[FakeElement("@e1", text="提交")]]
        self.calls: list[tuple] = []
        self.screenshot_count = 0
        self._url = url

    def get_title(self, session=None):
        return "PC AutoExecute"

    def get_url(self, session=None):
        return self._url

    def snapshot(self, interactive_only=True, session=None):
        index = min(len(self.calls), len(self.snapshots) - 1)
        return self.snapshots[index]

    def click(self, element_ref, session=None, new_tab=False):
        self.calls.append(("click", element_ref, session, new_tab))

    def fill(self, element_ref, text, session=None):
        self.calls.append(("fill", element_ref, text, session))

    def press(self, key, session=None):
        self.calls.append(("press", key, session))

    def scroll(self, direction, amount=300, session=None):
        self.calls.append(("scroll", direction, amount, session))

    def wait_for_text(self, text, timeout_ms=25000, session=None):
        self.calls.append(("wait_for_text", text, timeout_ms, session))

    def screenshot(self, path, full_page=False, session=None):
        self.screenshot_count += 1
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(b"png")
        self.calls.append(("screenshot", str(path), full_page, session))
        return Path(path)


async def test_pc_agent_pauses_for_login_or_captcha_without_calling_model(tmp_path: Path) -> None:
    from app.services.pc_browser_agent_service import PCBrowserAgentService

    browser = FakeBrowser([[FakeElement("@e1", tag="input", text=None, attrs={"type": "password"})]], url="https://example.test/login")
    model_called = False

    def decide(context):
        nonlocal model_called
        model_called = True
        return {"action": "finish", "message": "done"}

    service = PCBrowserAgentService(browser=browser, decision_provider=decide, artifact_root=tmp_path)

    events = []
    async for event in service.iter_task_events(task="登录后进入后台", session="pc"):
        events.append(event)
        # If need_user event, auto-resume to avoid hanging
        if event.get("event") == "need_user":
            from app.services.pc_browser_agent_service import _agent_sessions
            run_id = event.get("run_id")
            session_obj = _agent_sessions.get(run_id)
            if session_obj:
                session_obj.need_user_event.set()

    assert not model_called
    need_user_events = [e for e in events if e.get("event") == "need_user"]
    assert len(need_user_events) >= 1
    assert "手动" in need_user_events[0]["message"] or "登录" in need_user_events[0]["message"]


async def test_pc_agent_executes_ai_action_and_captures_screenshot(tmp_path: Path) -> None:
    from app.services.pc_browser_agent_service import PCBrowserAgentService

    browser = FakeBrowser()
    decisions = iter(
        [
            {"action": "click", "target": "@e1", "reason": "点击提交"},
            {"action": "finish", "message": "完成"},
        ]
    )
    service = PCBrowserAgentService(browser=browser, decision_provider=lambda context: next(decisions), artifact_root=tmp_path)

    events = []
    async for event in service.iter_task_events(task="点击提交按钮", session="pc", max_steps=3):
        events.append(event)

    assert ("click", "@e1", "pc", False) in browser.calls
    assert browser.screenshot_count == 1
    assert any(event.get("event") == "step" and event.get("screenshot_url") for event in events)
    assert events[-1]["event"] == "result"
    assert events[-1]["run_result"] == "passed"


async def test_pc_agent_fill_and_wait_actions(tmp_path: Path) -> None:
    from app.services.pc_browser_agent_service import PCBrowserAgentService

    browser = FakeBrowser()
    decisions = iter(
        [
            {"action": "fill", "target": "@e1", "text": "测试用户", "reason": "填写名称"},
            {"action": "wait_text", "text": "保存成功", "reason": "等待保存结果"},
            {"action": "finish", "message": "完成"},
        ]
    )
    service = PCBrowserAgentService(browser=browser, decision_provider=lambda context: next(decisions), artifact_root=tmp_path)

    async for _event in service.iter_task_events(task="填写并保存", session="pc", max_steps=4):
        pass

    assert ("fill", "@e1", "测试用户", "pc") in browser.calls
    assert ("wait_for_text", "保存成功", 25000, "pc") in browser.calls
    assert browser.screenshot_count == 2


def test_pc_agent_parses_json_object_from_markdown_response() -> None:
    from app.services.pc_browser_agent_service import parse_decision_json

    payload = parse_decision_json(
        """
        ```json
        {"action":"click","target":"@e2","reason":"打开详情"}
        ```
        """
    )

    assert payload == {"action": "click", "target": "@e2", "reason": "打开详情"}


async def test_pc_agent_returns_error_event_when_decision_fails(tmp_path: Path) -> None:
    from app.services.pc_browser_agent_service import PCBrowserAgentService

    def decide(context):
        raise RuntimeError("bad model response")

    service = PCBrowserAgentService(browser=FakeBrowser(), decision_provider=decide, artifact_root=tmp_path)

    events = []
    async for event in service.iter_task_events(task="执行任务", session="pc"):
        events.append(event)

    assert events[-2]["event"] == "error"
    assert "bad model response" in events[-2]["message"]
    assert events[-1]["event"] == "result"
    assert events[-1]["run_result"] == "failed"


def test_manual_auth_message_with_login_url() -> None:
    from app.services.pc_browser_agent_service import PCBrowserAgentService

    # URL path matching
    assert PCBrowserAgentService._manual_auth_message({"url": "https://example.com/login"}, current_url="https://example.com/login") is not None
    assert PCBrowserAgentService._manual_auth_message({"url": "https://example.com/auth"}, current_url="https://example.com/auth/callback") is not None

    # Domain matching
    assert PCBrowserAgentService._manual_auth_message({"url": ""}, current_url="https://accounts.google.com/o/oauth2") is not None

    # No trigger for normal page
    assert PCBrowserAgentService._manual_auth_message({"url": "https://example.com/home"}, current_url="https://example.com/home") is None

    # Keyword matching still works
    assert PCBrowserAgentService._manual_auth_message({"url": "", "title": "", "elements": [{"text": "请输入验证码", "attrs": {}}]}, current_url="https://example.com/home") is not None


def test_claude_code_decision_provider_build_prompt():
    """测试 prompt 构建格式。"""
    from app.services.claude_code_decision_provider import ClaudeCodeDecisionProvider

    context = {
        "task": "检查页面标题",
        "step": 1,
        "url": "https://example.com",
        "title": "Example Domain",
        "elements": [{"ref": "@e1", "tag": "button", "text": "More", "attrs": {}}],
        "history": [],
    }
    provider = ClaudeCodeDecisionProvider()
    prompt = provider._build_prompt(context)
    assert "检查页面标题" in prompt
    assert "https://example.com" in prompt
    assert "Example Domain" in prompt
    assert '"action":"click"' in prompt
    assert '"action":"need_user"' in prompt
    assert '"action":"finish"' in prompt


def test_claude_code_decision_provider_build_command():
    """测试 CLI 命令构建。"""
    from app.services.claude_code_decision_provider import ClaudeCodeDecisionProvider

    provider = ClaudeCodeDecisionProvider(model="sonnet", api_key="sk-test")
    cmd = provider._build_command("test prompt")
    assert cmd[0] == "claude"
    assert "-p" in cmd
    assert "test prompt" in cmd
    assert "--model" in cmd
    assert "sonnet" in cmd
    assert "--output-format" in cmd


def test_claude_code_is_available():
    """测试 CLI 可用性检测（不依赖 claude 是否安装）。"""
    from app.services.claude_code_decision_provider import ClaudeCodeDecisionProvider

    # 只验证方法不抛异常
    result = ClaudeCodeDecisionProvider.is_available()
    assert isinstance(result, bool)


def test_resolve_decision_provider_default():
    """默认 provider 返回 PCAgentModelService.decide。"""
    from app.services.pc_browser_agent_service import PCBrowserAgentService

    provider = PCBrowserAgentService._resolve_decision_provider("default", None)
    assert callable(provider)


def test_resolve_decision_provider_claude_code():
    """claude_code provider 返回 ClaudeCodeDecisionProvider.decide。"""
    from app.services.pc_browser_agent_service import PCBrowserAgentService

    provider = PCBrowserAgentService._resolve_decision_provider("claude_code", "sonnet")
    assert callable(provider)
