"""AI step runner for PC AutoExecute, backed by agent-browser."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.config import settings
from app.services.pc_browser_service import PCBrowserService
from app.utils import utc_iso


# 登录页特征 URL 路径
_LOGIN_PATH_PATTERNS = [
    "/login", "/signin", "/sign-in", "/auth",
    "/oauth", "/sso", "/authenticate",
]

# 登录页特征域名
_LOGIN_DOMAIN_PATTERNS = [
    "accounts.google.com",
    "login.microsoftonline.com",
    "auth0.com",
    "signin.aws.amazon.com",
]


class PCAgentRunSession:
    """管理单次 Agent 运行的状态，用于暂停/恢复。"""

    def __init__(self, run_id: str):
        self.run_id = run_id
        self.need_user_event = asyncio.Event()
        self.cancelled = False


# 全局 session 注册表
_agent_sessions: dict[str, PCAgentRunSession] = {}


DecisionProvider = Callable[[dict[str, Any]], dict[str, Any]]


def parse_decision_json(content: str) -> dict[str, Any]:
    """Parse a JSON object from model output."""
    cleaned = content.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.S | re.I)
    if fenced:
        cleaned = fenced.group(1)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.S)
        if not match:
            raise
        payload = json.loads(match.group(0))
    if not isinstance(payload, dict):
        raise ValueError("PC agent decision must be a JSON object")
    return payload


class PCBrowserAgentService:
    """Run one PC test task as an observe-decide-act loop."""

    def __init__(
        self,
        browser: PCBrowserService | None = None,
        decision_provider: DecisionProvider | None = None,
        artifact_root: Path | None = None,
        provider: str = "default",
        model: str | None = None,
    ) -> None:
        self.browser = browser or PCBrowserService()
        if decision_provider is None:
            decision_provider = self._resolve_decision_provider(provider, model)
        self.decision_provider = decision_provider
        self.artifact_root = artifact_root or settings.uploads_dir / "pc-agent"

    @staticmethod
    def _resolve_decision_provider(provider: str, model: str | None) -> DecisionProvider:
        """根据 provider 类型选择决策 provider。"""
        if provider == "claude_code":
            from app.services.claude_code_decision_provider import ClaudeCodeDecisionProvider
            from app.services.model_provider_service import ModelProviderService

            config = ModelProviderService().pc_agent_config()
            return ClaudeCodeDecisionProvider(
                model=model or config.model or "sonnet",
                api_key=config.api_key or None,
            ).decide
        # 默认：现有 PCAgentModelService
        from app.services.pc_agent_model_service import PCAgentModelService
        return PCAgentModelService().decide

    async def iter_task_events(
        self,
        *,
        task: str,
        session: str | None = None,
        max_steps: int = 8,
    ) -> AsyncIterator[dict[str, Any]]:
        run_id = uuid.uuid4().hex[:10]
        session_name = session or "pc-autoexecute"
        max_steps = max(1, min(max_steps, 30))

        # 创建可暂停的运行会话
        agent_session = PCAgentRunSession(run_id)
        _agent_sessions[run_id] = agent_session

        # 在数据库中创建运行记录
        db_run = _create_db_run(run_id=run_id, session=session_name, task=task, max_steps=max_steps)

        try:
            yield self._event("start", "agent", "PC Agent 开始执行。", run_id=run_id, session=session_name, task=task)

            history: list[dict[str, Any]] = []
            for step in range(1, max_steps + 1):
                context = self._build_context(task=task, session=session_name, history=history, step=step)
                yield self._event(
                    "log",
                    "observe",
                    f"读取页面：{context['title'] or '-'} / {context['url'] or '-'}",
                    run_id=run_id,
                    step=step,
                    url=context["url"],
                    title=context["title"],
                )

                manual_message = self._manual_auth_message(context, current_url=context.get("url", ""))
                if manual_message:
                    screenshot = self._capture_step_screenshot(run_id=run_id, step=step, session=session_name)
                    _update_db_run(run_id, run_result="need_user", result_note=manual_message, steps_completed=step - 1, action_trace=history)
                    yield self._event(
                        "need_user",
                        "manual",
                        manual_message,
                        run_id=run_id,
                        step=step,
                        screenshot_url=screenshot["url"],
                    )
                    # 暂停等待用户操作
                    await agent_session.need_user_event.wait()
                    agent_session.need_user_event.clear()
                    if agent_session.cancelled:
                        _finish_db_run(db_run, run_result="cancelled", result_note="用户取消了执行")
                        yield self._event("error", "manual", "用户取消了执行", run_id=run_id, step=step)
                        return
                    yield self._event("log", "manual", "用户已完成登录，继续执行", run_id=run_id, step=step)
                    continue

                try:
                    decision = self._decide(context)
                except Exception as exc:
                    _finish_db_run(db_run, run_result="failed", result_note=f"PC Agent 决策失败：{exc}", steps_completed=step - 1, action_trace=history)
                    yield self._event(
                        "error",
                        "agent",
                        f"PC Agent 决策失败：{exc}",
                        run_id=run_id,
                        step=step,
                        run_result="failed",
                    )
                    yield self._event("result", "result", f"PC Agent 决策失败：{exc}", run_id=run_id, run_result="failed", history=history)
                    return
                action = str(decision.get("action") or "").strip().lower()
                reason = str(decision.get("reason") or decision.get("message") or action or "执行下一步")

                if action in {"need_user", "manual", "pause"}:
                    message = str(decision.get("message") or "需要你在内嵌浏览器里手动处理后再继续。")
                    screenshot = self._capture_step_screenshot(run_id=run_id, step=step, session=session_name)
                    _update_db_run(run_id, run_result="need_user", result_note=message, steps_completed=step - 1, action_trace=history)
                    yield self._event("need_user", "manual", message, run_id=run_id, step=step, decision=decision, screenshot_url=screenshot["url"])
                    # 暂停等待用户操作
                    await agent_session.need_user_event.wait()
                    agent_session.need_user_event.clear()
                    if agent_session.cancelled:
                        _finish_db_run(db_run, run_result="cancelled", result_note="用户取消了执行")
                        yield self._event("error", "manual", "用户取消了执行", run_id=run_id, step=step)
                        return
                    yield self._event("log", "manual", "用户已完成登录，继续执行", run_id=run_id, step=step)
                    continue

                if action in {"finish", "done", "success"}:
                    message = str(decision.get("message") or "PC Agent 已判断任务完成。")
                    _finish_db_run(db_run, run_result="passed", result_note=message, steps_completed=step - 1, action_trace=history)
                    yield self._event("result", "result", message, run_id=run_id, run_result="passed", history=history)
                    return

                try:
                    self._execute_action(decision, session=session_name)
                    screenshot = self._capture_step_screenshot(run_id=run_id, step=step, session=session_name)
                except Exception as exc:
                    _finish_db_run(db_run, run_result="failed", result_note=f"PC Agent 执行失败：{exc}", steps_completed=step - 1, action_trace=history)
                    yield self._event(
                        "error",
                        "execution",
                        f"PC Agent 执行动作失败：{exc}",
                        run_id=run_id,
                        step=step,
                        decision=decision,
                        run_result="failed",
                    )
                    yield self._event("result", "result", f"PC Agent 执行失败：{exc}", run_id=run_id, run_result="failed", history=history)
                    return

                step_event = self._event(
                    "step",
                    "execution",
                    reason,
                    run_id=run_id,
                    step=step,
                    action=action,
                    decision=decision,
                    screenshot_path=screenshot["path"],
                    screenshot_url=screenshot["url"],
                )
                history.append(step_event)
                _update_db_run(run_id, steps_completed=step, action_trace=history)
                yield step_event

            _update_db_run(run_id, run_result="need_user", result_note=f"PC Agent 已达到最大步数 {max_steps}，请检查页面后继续或调整任务。", steps_completed=max_steps, action_trace=history)
            yield self._event(
                "need_user",
                "manual",
                f"PC Agent 已达到最大步数 {max_steps}，请检查页面后继续或调整任务。",
                run_id=run_id,
                step=max_steps,
            )
        finally:
            _agent_sessions.pop(run_id, None)

    def _build_context(self, *, task: str, session: str, history: list[dict[str, Any]], step: int) -> dict[str, Any]:
        title = self.browser.get_title(session=session)
        url = self.browser.get_url(session=session)
        elements = self.browser.snapshot(interactive_only=True, session=session)
        return {
            "task": task,
            "session": session,
            "step": step,
            "title": title,
            "url": url,
            "elements": [
                {
                    "ref": item.ref,
                    "tag": item.tag,
                    "text": item.text,
                    "attrs": item.attrs,
                }
                for item in elements
            ],
            "history": history[-8:],
        }

    def _decide(self, context: dict[str, Any]) -> dict[str, Any]:
        return self.decision_provider(context)

    @staticmethod
    def _manual_auth_message(context: dict[str, Any], current_url: str = "") -> str | None:
        page_text = " ".join(
            [
                str(context.get("url") or ""),
                str(context.get("title") or ""),
                " ".join(str(item.get("text") or "") for item in context.get("elements", [])),
                " ".join(
                    " ".join(str(value) for value in item.get("attrs", {}).values())
                    for item in context.get("elements", [])
                ),
            ]
        ).lower()
        sensitive_markers = ("type password", "password", "验证码", "captcha", "扫码", "二次验证", "2fa", "otp")
        if any(marker in page_text for marker in sensitive_markers):
            return "检测到登录、密码、验证码或二次验证页面，请你在内嵌浏览器里手动完成，完成后点击继续执行。"

        # URL 路径和域名匹配
        if current_url:
            parsed = urlparse(current_url)
            path_lower = parsed.path.lower()
            host_lower = parsed.hostname.lower() if parsed.hostname else ""

            for pattern in _LOGIN_PATH_PATTERNS:
                if pattern in path_lower:
                    return f"检测到登录页面 (URL路径: {path_lower})"

            for domain in _LOGIN_DOMAIN_PATTERNS:
                if domain in host_lower:
                    return f"检测到第三方登录 (域名: {host_lower})"

        return None

    def _execute_action(self, decision: dict[str, Any], *, session: str) -> None:
        action = str(decision.get("action") or "").strip().lower()
        if action == "click":
            self.browser.click(str(decision["target"]), session=session, new_tab=bool(decision.get("new_tab", False)))
            return
        if action == "fill":
            self.browser.fill(str(decision["target"]), str(decision.get("text") or ""), session=session)
            return
        if action in {"press", "key"}:
            self.browser.press(str(decision.get("key") or "Enter"), session=session)
            return
        if action == "scroll":
            self.browser.scroll(
                str(decision.get("direction") or "down"),
                int(decision.get("amount") or 500),
                session=session,
            )
            return
        if action == "wait_text":
            self.browser.wait_for_text(str(decision.get("text") or ""), timeout_ms=int(decision.get("timeout_ms") or 25000), session=session)
            return
        raise ValueError(f"unsupported PC agent action: {action}")

    def _capture_step_screenshot(self, *, run_id: str, step: int, session: str) -> dict[str, str]:
        screenshots_dir = self.artifact_root / "screenshots"
        path = (screenshots_dir / f"step_{step:03d}.png").resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.browser.screenshot(path=path, session=session)
        relative = Path("screenshots") / f"step_{step:03d}.png"
        if self.artifact_root == settings.uploads_dir / "pc-agent":
            return {"path": str(path), "url": f"/static/uploads/{relative.as_posix()}"}
        return {"path": str(path), "url": str(path)}

    @staticmethod
    def _event(event: str, phase: str, message: str, **extra: Any) -> dict[str, Any]:
        return {
            "event": event,
            "type": event,
            "phase": phase,
            "timestamp": utc_iso(),
            "message": message,
            **extra,
        }


# ── DB persistence helpers ────────────────────────────────────────────────────


def _create_db_run(*, run_id: str, session: str, task: str, max_steps: int) -> int | None:
    """在数据库中创建 PC Agent 运行记录，返回记录 id。"""
    try:
        from app.database import SessionLocal
        from app.models import PCAgentRun

        db = SessionLocal()
        try:
            record = PCAgentRun(
                run_id=run_id,
                session=session,
                task=task,
                max_steps=max_steps,
                run_result="running",
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            return record.id
        except Exception:
            db.rollback()
            return None
        finally:
            db.close()
    except Exception:
        return None


def _update_db_run(
    run_id: str,
    *,
    run_result: str | None = None,
    result_note: str | None = None,
    steps_completed: int | None = None,
    action_trace: list[dict[str, Any]] | None = None,
) -> None:
    """更新 PC Agent 运行记录的中间状态。"""
    try:
        from app.database import SessionLocal
        from app.models import PCAgentRun

        db = SessionLocal()
        try:
            record = db.query(PCAgentRun).filter(PCAgentRun.run_id == run_id).first()
            if not record:
                return
            if run_result is not None:
                record.run_result = run_result
            if result_note is not None:
                record.result_note = result_note
            if steps_completed is not None:
                record.steps_completed = steps_completed
            if action_trace is not None:
                # 只保留最近 200 条，避免 JSON 过大
                record.action_trace = action_trace[-200:]
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()
    except Exception:
        pass


def _finish_db_run(
    db_run_id: int | None,
    *,
    run_result: str,
    result_note: str = "",
    steps_completed: int | None = None,
    action_trace: list[dict[str, Any]] | None = None,
) -> None:
    """标记 PC Agent 运行记录为完成状态。"""
    if db_run_id is None:
        return
    try:
        from app.database import SessionLocal
        from app.models import PCAgentRun

        db = SessionLocal()
        try:
            record = db.query(PCAgentRun).filter(PCAgentRun.id == db_run_id).first()
            if not record:
                return
            record.run_result = run_result
            record.result_note = result_note
            record.ended_at = datetime.now(timezone.utc)
            if record.started_at:
                delta = record.ended_at - record.started_at
                record.duration_ms = int(delta.total_seconds() * 1000)
            if steps_completed is not None:
                record.steps_completed = steps_completed
            if action_trace is not None:
                record.action_trace = action_trace[-200:]
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()
    except Exception:
        pass
