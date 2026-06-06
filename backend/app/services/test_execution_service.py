from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import base64
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from time import perf_counter
from urllib.parse import urlparse
from uuid import uuid4

from sqlalchemy.orm import Session

from app.config import settings
from app.models import ImportedTestCase, LoginAccount, TestCaseExecution
from app.services.adb_service import ADBService
from app.services import u2_service, wda_service
from app.services.device_readiness_service import AndroidDeviceReadinessService
from app.services.execution_cancel_registry import execution_cancel_registry
from app.services.harmony_service import HarmonyService
from app.services.ios_service import IOSService
from app.services.report_writer import ReportWriter
from app.services.result_assertion_service import ResultAssertionService
from app.services.model_provider_service import ModelProviderService
from app.utils import utc_iso

from app.automation.autoglm.case_planner import CasePlanner
from app.automation.autoglm.judge_service import JudgeService


from app.services.pc_browser_agent_service import PCBrowserAgentService
from app.services.pc_browser_service import PCBrowserService


class TestExecutionError(RuntimeError):
    pass


PLATFORM_TO_DEVICE_TYPE = {
    "android": "adb",
    "ios": "ios",
    "harmony": "hdc",
    "harmonyos": "hdc",
}

PLATFORM_LABELS = {
    "android": "Android",
    "ios": "iOS",
    "harmony": "HarmonyOS",
}

LEYOUJIA_LOGIN_URL = "https://itest.leyoujia.com/jjslogin/index"
LEYOUJIA_PROD_LOGIN_URL = "https://i.leyoujia.com/jjslogin/index"
LEYOUJIA_AUTH_PROFILES = {
    "test": {
        "env": "test",
        "label": "测试环境",
        "login_url": LEYOUJIA_LOGIN_URL,
        "state_file": "leyoujia-test.json",
        "hosts": {"zero-ai-test.leyoujia.com"},
    },
    "prod": {
        "env": "prod",
        "label": "生产环境",
        "login_url": LEYOUJIA_PROD_LOGIN_URL,
        "state_file": "leyoujia-prod.json",
        "hosts": {"zero-ai.leyoujia.com"},
    },
}


def _normalize_platform(platform: str | None) -> str | None:
    if not platform:
        return None
    value = platform.strip().lower()
    if value in {"android", "adb"}:
        return "android"
    if value in {"ios", "iphone", "xctest"}:
        return "ios"
    if value in {"harmony", "harmonyos", "ohos", "hdc"}:
        return "harmony"
    return None


_LOGIN_TAKEOVER_KEYWORDS = [
    "登录", "登陆", "login", "sign in", "signin",
    "验证码", "verification", "verify",
    "密码", "password", "passcode",
    "账号", "账户", "account", "username", "user",
    "手机号", "phone", "mobile",
    "授权", "authorize", "auth",
    "注册", "register", "sign up", "signup",
    "绑定", "bind",
    "认证", "authenticate",
]


def _is_login_takeover(message: str) -> bool:
    """Check if a takeover message is login/authentication related."""
    lowered = message.lower()
    return any(kw in lowered for kw in _LOGIN_TAKEOVER_KEYWORDS)


def _classify_execution_error(
    run_result: str,
    result_note: str,
    action_trace: list[dict],
) -> str | None:
    if run_result not in {"failed", "uncertain"}:
        return None

    trace_text = "\n".join(str(entry) for entry in action_trace)
    text = f"{result_note}\n{trace_text}"
    if "执行已停止" in text:
        return "cancelled"
    if "未选择设备" in text:
        return "no_device"
    if "未连接" in text or "离线" in text or "无法找到设备" in text or "设备未满足" in text:
        return "device_unavailable"
    if "断言失败" in text:
        return "assertion_failed"
    if "断言不确定" in text:
        return "assertion_uncertain"
    if "Open-AutoGLM" in text or "AUTOGLM" in text:
        return "autoglm_execution_failed"
    return "execution_failed"


class TestExecutionService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.report_writer = ReportWriter()

    def execute_case(
        self,
        case_id: int,
        device_udid: str | None = None,
        device_platform: str | None = None,
        client_run_id: str | None = None,
    ) -> TestCaseExecution:
        execution_id: int | None = None
        for event in self.iter_case_events(
            case_id,
            device_udid=device_udid,
            device_platform=device_platform,
            client_run_id=client_run_id,
        ):
            if event.get("event") == "result":
                execution_id = event.get("execution_id")

        if execution_id is None:
            raise TestExecutionError("用例执行未产生结果")
        execution = self.db.get(TestCaseExecution, execution_id)
        if execution is None:
            raise TestExecutionError("用例执行结果不存在")
        return execution

    def execute_plan(
        self,
        plan_id: int,
        device_udid: str | None = None,
        device_platform: str | None = None,
        client_run_id: str | None = None,
    ) -> list[TestCaseExecution]:
        cases = (
            self.db.query(ImportedTestCase)
            .filter(ImportedTestCase.plan_id == plan_id)
            .order_by(ImportedTestCase.sequence)
            .all()
        )
        if not cases:
            raise TestExecutionError("测试计划不存在或没有用例")

        executions: list[TestCaseExecution] = []
        for case in cases:
            executions.append(
                self.execute_case(
                    case.id,
                    device_udid=device_udid,
                    device_platform=device_platform,
                    client_run_id=client_run_id,
                )
            )
        return executions

    def iter_plan_events(
        self,
        plan_id: int,
        device_udid: str | None = None,
        device_platform: str | None = None,
        client_run_id: str | None = None,
    ) -> Iterator[dict]:
        cases = (
            self.db.query(ImportedTestCase)
            .filter(ImportedTestCase.plan_id == plan_id)
            .order_by(ImportedTestCase.sequence)
            .all()
        )
        if not cases:
            raise TestExecutionError("测试计划不存在或没有用例")

        started = datetime.utcnow()
        report_dir = self._make_report_group_dir(plan_id=plan_id)
        report_folder_url = self._report_url_for_path(report_dir)
        results: list[dict] = []

        yield {
            "event": "batch_start",
            "phase": "batch",
            "timestamp": utc_iso(),
            "plan_id": plan_id,
            "total_cases": len(cases),
            "message": f"开始批量执行 {len(cases)} 条用例。",
            "report_folder_url": report_folder_url,
        }

        for index, case in enumerate(cases, start=1):
            if execution_cancel_registry.is_cancelled(client_run_id):
                break
            yield {
                "event": "case_start",
                "phase": "batch",
                "timestamp": utc_iso(),
                "plan_id": plan_id,
                "case_id": case.id,
                "case_name": case.case_name,
                "case_index": index,
                "total_cases": len(cases),
                "message": f"开始执行第 {index}/{len(cases)} 条：{case.case_name}",
                "report_folder_url": report_folder_url,
            }
            for event in self.iter_case_events(
                case.id,
                device_udid=device_udid,
                device_platform=device_platform,
                report_dir=report_dir,
                client_run_id=client_run_id,
            ):
                event.setdefault("plan_id", plan_id)
                event.setdefault("case_id", case.id)
                event.setdefault("case_index", index)
                event.setdefault("total_cases", len(cases))
                event.setdefault("report_folder_url", report_folder_url)
                if event.get("event") == "result":
                    results.append(event)
                yield event

        ended = datetime.utcnow()
        summary_url = self._save_plan_run_summary(
            plan_id=plan_id,
            report_dir=report_dir,
            results=results,
            started_at=started,
            ended_at=ended,
        )
        yield {
            "event": "batch_result",
            "phase": "report",
            "timestamp": utc_iso(),
            "plan_id": plan_id,
            "total_cases": len(cases),
            "passed": sum(1 for item in results if item.get("run_result") == "passed"),
            "failed": sum(1 for item in results if item.get("run_result") == "failed"),
            "message": f"批量执行完成，报告目录：{report_folder_url}",
            "summary_url": summary_url,
            "report_folder_url": report_folder_url,
        }
        execution_cancel_registry.cleanup(client_run_id)

    def iter_case_events(
        self,
        case_id: int,
        device_udid: str | None = None,
        device_platform: str | None = None,
        report_dir: Path | None = None,
        client_run_id: str | None = None,
    ) -> Iterator[dict]:
        case = self.db.get(ImportedTestCase, case_id)
        if not case:
            raise TestExecutionError("测试用例不存在")

        started = datetime.utcnow()
        timer = perf_counter()
        run_index = case.run_count + 1
        action_trace: list[dict] = [
            {
                "type": "plan",
                "phase": "plan",
                "timestamp": utc_iso(),
                "case_id": case.id,
                "goal": case.case_name,
                "precondition": case.precondition,
                "steps": case.steps,
                "expected_result": case.expected_result,
            }
        ]
        target_kind = self._infer_target_kind(case)
        is_web_case = target_kind == "web"
        if report_dir is None:
            report_dir = self._make_report_group_dir(case_id=case.id)
        final_result = "failed"
        result_note = ""
        autoglm_configured = False
        case_trace_id: str | None = None

        def emit(event_type: str, phase: str, message: str, **extra: object) -> dict:
            event = {
                "event": event_type,
                "type": event_type,
                "phase": phase,
                "timestamp": utc_iso(),
                "case_id": case.id,
                "message": message,
                "client_run_id": client_run_id,
                **extra,
            }
            action_trace.append(event)
            return event

        yield emit(
            "log",
            "plan",
            f"用例已解析，目标类型：{target_kind}",
            type="case_task_plan",
            target_kind=target_kind,
            is_web_case=is_web_case,
        )

        # Web 类型用例路由到 agent-browser 执行器
        if is_web_case:
            yield from self._run_web_case_events(
                case=case,
                report_dir=report_dir,
                emit=emit,
                client_run_id=client_run_id,
                action_trace=action_trace,
                started=started,
                timer=timer,
                run_index=run_index,
            )
            return

        # ── Mobile: resolve device & run AutoGLM ─────────────────────
        platform, device_error, device_warnings = self._resolve_device(device_udid, device_platform)

        if execution_cancel_registry.is_cancelled(client_run_id):
            result_note = "执行已停止。"
            yield emit("error", "device_check", result_note, error_category="cancelled")
        elif device_error:
            result_note = device_error
            yield emit("error", "device_check", device_error, error_category="device_unavailable")
        elif platform is None:
            result_note = "未能解析设备平台，请选择在线设备后重试。"
            yield emit("error", "device_check", result_note, error_category="device_unavailable")
        else:
            # Emit non-blocking readiness warnings
            for warning in device_warnings:
                yield emit("log", "device_check", warning)

            yield emit(
                "log", "device_check",
                f"{PLATFORM_LABELS[platform]} 设备 {device_udid} 在线，准备调用 Open-AutoGLM。",
                device_udid=device_udid, device_platform=platform,
            )

            root_error = self._validate_open_autoglm_root()
            if root_error:
                result_note = root_error
                yield emit("error", "device_check", root_error, error_category="autoglm_config")
            else:
                login_accounts = self._get_autoglm_login_accounts()
                # Build structured CaseTaskPlan for checkpoint-based execution
                case_planner = CasePlanner()
                task_plan = case_planner.build(
                    case_id=case.id,
                    target_app=case.target_app or "未知应用",
                    platform=platform,
                    launch_app_id="",
                    preconditions=[case.precondition] if case.precondition else [],
                    steps=[s.get("step", s) if isinstance(s, dict) else str(s) for s in (case.steps or [])],
                    expected_result=case.expected_result or "",
                )
                yield emit(
                    "log",
                    "plan",
                    f"已生成 CaseTaskPlan，包含 {len(task_plan.checkpoints)} 个 checkpoint。",
                    type="case_task_plan",
                    case_task_plan=task_plan.to_dict(),
                )
                # Use PromptBuilder to generate scoped prompt per checkpoint
                unified_prompt = self._build_unified_prompt(case, target_kind, platform, login_accounts=login_accounts)
                autoglm_configured = True

                yield emit("log", "execution", "发送统一测试任务给 AutoGLM。", target_kind=target_kind)
                case_trace_id = uuid4().hex
                execution_code = yield from self._run_autoglm_phase(
                    phase="execution",
                    prompt=unified_prompt,
                    platform=platform,
                    device_udid=device_udid,
                    report_dir=report_dir,
                    emit=emit,
                    client_run_id=client_run_id,
                    trace_id=case_trace_id,
                    login_accounts=login_accounts,
                )

                if execution_cancel_registry.is_cancelled(client_run_id):
                    result_note = "执行已停止。"
                    yield emit("error", "execution", result_note, error_category="cancelled")
                elif execution_code == 0:
                    yield emit("log", "execution", "AutoGLM 执行完成，准备截取终态屏幕并断言结果。", returncode=execution_code)
                    screenshot = None
                    if not execution_cancel_registry.is_cancelled(client_run_id):
                        screenshot = self._capture_final_screenshot(report_dir, platform, device_udid)
                        if screenshot.get("url"):
                            yield emit(
                                "log",
                                "report",
                                f"终态截图已保存：{screenshot['url']}",
                                type="final_screenshot",
                                screenshot_url=screenshot["url"],
                                screenshot_path=screenshot["path"],
                                screenshot_at=screenshot["created_at"],
                            )
                        else:
                            yield emit(
                                "error",
                                "report",
                                f"终态截图保存失败：{screenshot.get('error') or '未知错误'}",
                                error_category="screenshot_failed",
                            )

                    if not execution_cancel_registry.is_cancelled(client_run_id):
                        assertion = ResultAssertionService().assert_result(
                            case=case,
                            action_trace=action_trace,
                            final_screenshot=screenshot,
                        )
                        # Supplement with JudgeService checkpoint-based verdict
                        judge = JudgeService()
                        checkpoints_passed = sum(1 for a in action_trace if a.get("type") == "action_executed" and a.get("success") is True)
                        current_app_info = ""
                        if device_udid and platform == "android":
                            current_app_info = self._get_current_app_package(device_udid)
                        judge_result = judge.determine(
                            checkpoints_passed=checkpoints_passed,
                            total_checkpoints=len(task_plan.checkpoints),
                            final_app=current_app_info,
                            expected_app=task_plan.launch_app_id or current_app_info,
                        )
                        assertion["judge_verdict"] = judge_result.verdict
                        assertion["judge_confidence"] = judge_result.confidence
                        assertion["judge_reason"] = judge_result.reason
                        assertion["checkpoints_total"] = len(task_plan.checkpoints)
                        assertion["checkpoints_passed"] = checkpoints_passed
                        yield emit(
                            "log",
                            "assertion",
                            f"JudgeService 判定：{judge_result.verdict}（置信度 {judge_result.confidence:.2f}）：{judge_result.reason}",
                            type="judge_verdict",
                            judge_verdict=judge_result.verdict,
                            judge_confidence=judge_result.confidence,
                            judge_reason=judge_result.reason,
                        )
                        verdict = assertion.get("verdict")
                        if verdict == "passed":
                            final_result = "passed"
                            result_note = f"断言通过：{assertion.get('reason')}"
                            yield emit(
                                "log",
                                "assertion",
                                result_note,
                                type="result_assertion",
                                assertion=assertion,
                            )
                        elif verdict == "failed":
                            final_result = "failed"
                            result_note = f"断言失败：{assertion.get('reason')}"
                            yield emit(
                                "error",
                                "assertion",
                                result_note,
                                type="result_assertion",
                                error_category="assertion_failed",
                                assertion=assertion,
                            )
                        else:
                            final_result = "uncertain"
                            result_note = f"断言不确定：{assertion.get('reason')}"
                            yield emit(
                                "error",
                                "assertion",
                                result_note,
                                type="result_assertion",
                                error_category="assertion_uncertain",
                                assertion=assertion,
                            )
                else:
                    result_note = f"测试执行失败，Open-AutoGLM 返回码：{execution_code}"
                    yield emit("error", "execution", result_note, returncode=execution_code)

                    if not execution_cancel_registry.is_cancelled(client_run_id):
                        screenshot = self._capture_final_screenshot(report_dir, platform, device_udid)
                        if screenshot.get("url"):
                            yield emit(
                                "log",
                                "report",
                                f"终态截图已保存：{screenshot['url']}",
                                type="final_screenshot",
                                screenshot_url=screenshot["url"],
                                screenshot_path=screenshot["path"],
                                screenshot_at=screenshot["created_at"],
                            )
                        else:
                            yield emit(
                                "error",
                                "report",
                                f"终态截图保存失败：{screenshot.get('error') or '未知错误'}",
                                error_category="screenshot_failed",
                            )

        if not result_note:
            result_note = "用例执行结束，但没有拿到明确结果。"

        duration_ms = max(1, int((perf_counter() - timer) * 1000))
        if execution_cancel_registry.is_cancelled(client_run_id):
            final_result = "failed"
            result_note = "执行已停止。"

        assertion_result = self._latest_assertion_result(action_trace)
        error_category = _classify_execution_error(final_result, result_note, action_trace)
        execution = TestCaseExecution(
            plan_id=case.plan_id,
            case_id=case.id,
            run_index=run_index,
            device_udid=device_udid,
            run_result=final_result,
            result_note=result_note,
            autoglm_configured=autoglm_configured,
            action_trace=[],
            error_category=error_category,
            trace_id=case_trace_id,
            started_at=started,
            ended_at=datetime.utcnow(),
            duration_ms=duration_ms,
        )
        self.db.add(execution)

        case.run_count = run_index
        case.latest_result = final_result
        case.latest_result_note = result_note
        self.db.commit()
        self.db.refresh(execution)

        log_url = self._save_execution_log_file(
            execution_id=execution.id,
            action_trace=action_trace,
            report_dir=report_dir,
        )
        log_event = emit(
            "log",
            "report",
            f"完整执行日志已外置保存：{log_url}",
            type="external_log",
            log_url=log_url,
            log_event_count=len(action_trace),
        )
        report_url = self._save_execution_report(
            execution=execution,
            case=case,
            target_kind=target_kind,
            device_platform=platform,
            started_at=started,
            ended_at=execution.ended_at or datetime.utcnow(),
            duration_ms=duration_ms,
            report_dir=report_dir,
            logs=action_trace,
            external_log_url=log_url,
        )
        report_event = emit(
            "log",
            "report",
            f"执行 JSON 报告已保存：{report_url}",
            report_url=report_url,
            report_folder_url=self._report_url_for_path(report_dir),
        )
        execution.action_trace = self._build_slim_action_trace(action_trace, log_url)
        self.db.commit()
        self.db.refresh(execution)

        yield log_event
        yield report_event
        yield {
            "event": "result",
            "phase": "report",
            "timestamp": utc_iso(),
            "execution_id": execution.id,
            "case_id": execution.case_id,
            "run_result": execution.run_result,
            "result_note": execution.result_note,
            "error_category": execution.error_category,
            "assertion_result": assertion_result,
            "report_url": report_url,
            "log_url": log_url,
            "report_folder_url": self._report_url_for_path(report_dir),
            "duration_ms": execution.duration_ms,
        }
        execution_cancel_registry.cleanup(client_run_id)

    def iter_case_event_lines(
        self,
        case_id: int,
        device_udid: str | None = None,
        device_platform: str | None = None,
        client_run_id: str | None = None,
    ) -> Iterator[str]:
        for event in self.iter_case_events(
            case_id,
            device_udid=device_udid,
            device_platform=device_platform,
            client_run_id=client_run_id,
        ):
            yield json.dumps(event, ensure_ascii=False, default=str) + "\n"

    def iter_plan_event_lines(
        self,
        plan_id: int,
        device_udid: str | None = None,
        device_platform: str | None = None,
        client_run_id: str | None = None,
    ) -> Iterator[str]:
        for event in self.iter_plan_events(
            plan_id,
            device_udid=device_udid,
            device_platform=device_platform,
            client_run_id=client_run_id,
        ):
            yield json.dumps(event, ensure_ascii=False, default=str) + "\n"

    def _run_autoglm_phase(
        self,
        phase: str,
        prompt: str,
        platform: str,
        device_udid: str,
        report_dir: Path | None,
        emit,
        client_run_id: str | None = None,
        trace_id: str | None = None,
        login_accounts: list[dict[str, str]] | None = None,
    ) -> Iterator[dict]:
        if execution_cancel_registry.is_cancelled(client_run_id):
            yield emit("error", phase, "执行已停止。", error_category="cancelled")
            return 130

        screenshots_dir = report_dir / "screenshots" if report_dir else None
        command = self._build_autoglm_command(platform, device_udid, prompt, screenshot_dir=screenshots_dir)
        display_command = self._redacted_command(command)
        yield emit("log", phase, f"启动 Open-AutoGLM：{' '.join(display_command)}", command=display_command, trace_id=trace_id)
        terminal_log_path = self._make_autoglm_terminal_log_path(report_dir, phase) if report_dir else None
        terminal_log_file = None
        if terminal_log_path is not None:
            terminal_log_file = terminal_log_path.open("w", encoding="utf-8")
            terminal_log_file.write(f"[command] {' '.join(display_command)}\n")

        try:
            process = subprocess.Popen(
                command,
                cwd=str(settings.open_autoglm_root),
                env=self._autoglm_env(
                    platform,
                    device_udid,
                    takeover_mode="wait" if client_run_id else "fail",
                ),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except OSError as exc:
            if terminal_log_file is not None:
                terminal_log_file.write(f"[error] failed to start Open-AutoGLM: {exc}\n")
                terminal_log_file.close()
                yield self._emit_autoglm_terminal_log_event(emit, terminal_log_path)
            yield emit("error", phase, f"无法启动 Open-AutoGLM：{exc}", error_category="autoglm_start_failed")
            return 127

        execution_cancel_registry.register_process(client_run_id, process)
        assert process.stdout is not None
        assert process.stderr is not None
        autoglm_step = 0
        in_action_block = False
        action_block_lines: list[str] = []
        # Buffered action info waiting for its STEP_SCREENSHOT_SAVED line.
        # AutoGLM prints 🎯 → JSON → ===== → STEP_SCREENSHOT_SAVED, so the
        # screenshot arrives just after the action block ends.  We buffer the
        # parsed action and emit the merged event when the screenshot line
        # arrives (or immediately if no screenshot_dir was requested).
        pending_action: dict[str, object] | None = None
        action_marker_re = re.compile(r"🎯\s*(?:执行动作|Action)\s*:", re.IGNORECASE)
        action_block_end_re = re.compile(r"^=+\s*$")
        screenshot_saved_re = re.compile(r"^STEP_SCREENSHOT_SAVED:(.+)$")
        try:
            for raw_line in process.stdout:
                if execution_cancel_registry.is_cancelled(client_run_id):
                    if process.poll() is None:
                        process.kill()
                    yield emit("error", phase, "执行已停止。", error_category="cancelled")
                    return 130
                message = raw_line.rstrip("\n")
                if terminal_log_file is not None:
                    terminal_log_file.write(f"[stdout] {message}\n")
                if not message:
                    continue
                if message.startswith("MANUAL_TAKEOVER_REQUIRED:"):
                    takeover_message = message.split(":", 1)[1].strip() or "AutoGLM 请求人工接管。"
                    # Auto-respond with login credentials when takeover is login-related
                    if login_accounts and _is_login_takeover(takeover_message):
                        credential_str = "; ".join(
                            f"{a['login_id']} / {a['password']}"
                            for a in login_accounts
                        )
                        yield emit(
                            "log",
                            phase,
                            f"检测到登录接管请求，自动提供账号信息：{credential_str}",
                            type="autoglm_auto_login",
                            login_accounts_used=len(login_accounts),
                        )
                        try:
                            process.stdin.write("\n")
                            process.stdin.flush()
                        except (BrokenPipeError, OSError):
                            pass
                        continue
                    yield emit(
                        "need_user",
                        phase,
                        takeover_message,
                        type="manual_takeover_required",
                        error_category="manual_takeover_required",
                    )
                    continue
                # AutoGLM saved a step screenshot — merge it into the pending
                # action_executed event and emit.
                ss_match = screenshot_saved_re.match(message)
                if ss_match and screenshots_dir is not None:
                    filename = ss_match.group(1)
                    saved_path = screenshots_dir / filename
                    ss_info: dict[str, str] | None = None
                    if saved_path.exists():
                        ss_info = {
                            "url": self._artifact_url_for_path(saved_path),
                            "path": str(saved_path),
                            "created_at": utc_iso(),
                        }
                    # Emit the pending action with the screenshot merged in.
                    if pending_action is not None:
                        event_extra = pending_action
                        pending_action = None
                        if ss_info:
                            event_extra["screenshot_url"] = ss_info["url"]
                            event_extra["screenshot_path"] = ss_info["path"]
                            event_extra["screenshot_at"] = ss_info["created_at"]
                        yield emit(
                            "log",
                            phase,
                            event_extra.pop("_summary"),
                            type="action_executed",
                            **event_extra,
                        )
                    continue
                # Step boundary detection.
                # AutoGLM verbose output (zh/en) is:
                #   ==================================================
                #   💭 思考过程:           / 💭 Thinking:
                #   --------------------------------------------------
                #   <thinking text>
                #   🎯 执行动作:           / 🎯 Action:
                #   { <pretty-printed JSON> }
                #   ==================================================
                # The 🎯 marker reliably delimits one agent step. There is no
                # explicit step number in the verbose output, so we count them
                # ourselves and buffer everything between 🎯 and the closing
                # '=====' so we can extract the action JSON.
                if not in_action_block:
                    if action_marker_re.search(message):
                        # If a previous action is still pending (no screenshot
                        # arrived), emit it now before starting the next step.
                        if pending_action is not None:
                            yield emit(
                                "log",
                                phase,
                                pending_action.pop("_summary"),
                                type="action_executed",
                                **pending_action,
                            )
                            pending_action = None
                        autoglm_step += 1
                        in_action_block = True
                        action_block_lines = [message]
                    else:
                        yield emit("log", phase, message, stream="stdout", autoglm_step=autoglm_step or None)
                else:
                    action_block_lines.append(message)
                    if action_block_end_re.match(message):
                        # End of the action block. Parse the JSON and buffer
                        # the action info. If screenshot_dir is set, we wait
                        # for STEP_SCREENSHOT_SAVED to merge the screenshot;
                        # otherwise we emit immediately.
                        in_action_block = False
                        action_info = self._parse_autoglm_action_block(action_block_lines)
                        event_extra: dict[str, object] = {
                            "step": autoglm_step,
                            "action_type": action_info["action_type"],
                            "success": action_info["success"],
                            "action_params": action_info["params"],
                            "stream": "stdout",
                            "autoglm_step": autoglm_step,
                            "_summary": action_info["summary"],
                        }
                        if screenshots_dir is not None:
                            # Defer emission until STEP_SCREENSHOT_SAVED arrives.
                            pending_action = event_extra
                        else:
                            # No screenshot saving — emit immediately.
                            yield emit(
                                "log",
                                phase,
                                action_info["summary"],
                                type="action_executed",
                                **event_extra,
                            )
                        action_block_lines = []
            # End of stdout loop — flush any pending action that never got
            # its STEP_SCREENSHOT_SAVED line (e.g. process crashed mid-step).
            if pending_action is not None:
                yield emit(
                    "log",
                    phase,
                    pending_action.pop("_summary"),
                    type="action_executed",
                    **pending_action,
                )
                pending_action = None

            # Always read stderr for diagnostics (warnings may appear even on exit 0)
            stderr_output = process.stderr.read().strip()
            returncode = process.wait()
            if stderr_output and terminal_log_file is not None:
                for line in stderr_output.splitlines():
                    terminal_log_file.write(f"[stderr] {line}\n")
            if stderr_output:
                if returncode != 0:
                    yield emit("error", phase, f"AutoGLM stderr: {stderr_output[:500]}", error_category="autoglm_stderr", returncode=returncode)
                else:
                    yield emit("log", phase, f"AutoGLM stderr (diagnostic): {stderr_output[:300]}", stream="stderr")

            if terminal_log_file is not None:
                terminal_log_file.close()
                yield self._emit_autoglm_terminal_log_event(emit, terminal_log_path)
            return returncode
        finally:
            if terminal_log_file is not None and not terminal_log_file.closed:
                terminal_log_file.close()
            execution_cancel_registry.unregister_process(client_run_id, process)

    def _emit_autoglm_terminal_log_event(self, emit, terminal_log_path: Path) -> dict:
        return emit(
            "log",
            "report",
            f"AutoGLM 终端日志已保存：{self._artifact_url_for_path(terminal_log_path)}",
            type="autoglm_terminal_log",
            terminal_log_url=self._artifact_url_for_path(terminal_log_path),
            terminal_log_path=str(terminal_log_path),
        )

    def _make_autoglm_terminal_log_path(self, report_dir: Path, phase: str) -> Path:
        report_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
        safe_phase = re.sub(r"[^a-zA-Z0-9_-]+", "_", phase).strip("_") or "execution"
        return report_dir / f"autoglm_terminal_{safe_phase}_{timestamp}.log"

    @staticmethod
    def _parse_autoglm_action_block(block_lines: list[str]) -> dict[str, object]:
        """Parse the buffered stdout block between the 🎯 marker and the
        closing '=====' separator. AutoGLM prints a pretty-printed action JSON
        inside this block. We extract:
            - action_type : "Tap" / "Type" / "Swipe" / "LongPress" / "Launch" /
                            "Back" / "Home" / "Wait" / "finish" / "unknown"
            - params       : dict of action parameters
            - success      : True for do(), success status for finish()
            - message      : human readable summary line
        """
        joined = "\n".join(block_lines)
        json_match = re.search(r"\{[\s\S]*\}", joined)
        if not json_match:
            return {
                "action_type": "unknown",
                "success": True,
                "message": joined[:200],
                "params": {},
                "summary": joined[:200],
            }
        try:
            action_dict = json.loads(json_match.group(0))
        except (ValueError, TypeError):
            return {
                "action_type": "unknown",
                "success": True,
                "message": joined[:200],
                "params": {},
                "summary": joined[:200],
            }

        if not isinstance(action_dict, dict):
            return {
                "action_type": "unknown",
                "success": True,
                "message": joined[:200],
                "params": {},
                "summary": joined[:200],
            }

        meta = action_dict.get("_metadata")
        if meta == "finish":
            message_text = str(action_dict.get("message") or "").strip()
            return {
                "action_type": "finish",
                "success": True,
                "message": message_text or "任务已完成",
                "params": {k: v for k, v in action_dict.items() if k != "_metadata"},
                "summary": f"finish({message_text})" if message_text else "finish()",
            }
        if meta == "do":
            action_type = str(action_dict.get("action") or "Do")
            params = {
                k: v for k, v in action_dict.items()
                if k not in ("_metadata", "action")
            }
            return {
                "action_type": action_type,
                "success": True,
                "message": f"{action_type}({params})",
                "params": params,
                "summary": f"{action_type}({params})",
            }
        # Fallback: best-effort
        return {
            "action_type": str(action_dict.get("action") or "unknown"),
            "success": True,
            "message": joined[:200],
            "params": {k: v for k, v in action_dict.items() if k != "_metadata"},
            "summary": joined[:200],
        }

    def _build_autoglm_command(self, platform: str, device_udid: str, prompt: str, screenshot_dir: Path | None = None) -> list[str]:
        device_type = PLATFORM_TO_DEVICE_TYPE[platform]
        command = [
            settings.resolved_python_path,
            "-u",
            "main.py",
            "--device-type",
            device_type,
            "--device-id",
            device_udid,
            "--base-url",
            os.environ.get("PHONE_AGENT_BASE_URL") or settings.autoglm_base_url,
            "--model",
            os.environ.get("PHONE_AGENT_MODEL") or settings.autoglm_model,
            "--max-steps",
            str(int(os.environ.get("PHONE_AGENT_MAX_STEPS") or settings.autoglm_max_steps)),
            "--lang",
            os.environ.get("PHONE_AGENT_LANG") or settings.autoglm_lang,
            "--skip-system-check",
            "--skip-model-check",
            "--quiet",
        ]
        if platform == "ios":
            command.extend(["--wda-url", os.environ.get("PHONE_AGENT_WDA_URL") or settings.autoglm_wda_url])
        if screenshot_dir is not None:
            screenshot_dir.mkdir(parents=True, exist_ok=True)
            command.extend(["--screenshot-dir", str(screenshot_dir)])
        command.append(prompt)
        return command

    def _autoglm_env(self, platform: str, device_udid: str, takeover_mode: str | None = None) -> dict[str, str]:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PHONE_AGENT_DEVICE_TYPE"] = PLATFORM_TO_DEVICE_TYPE[platform]
        env["PHONE_AGENT_DEVICE_ID"] = device_udid
        env["PHONE_AGENT_BASE_URL"] = env.get("PHONE_AGENT_BASE_URL") or settings.autoglm_base_url
        env["PHONE_AGENT_MODEL"] = env.get("PHONE_AGENT_MODEL") or settings.autoglm_model
        env["PHONE_AGENT_API_KEY"] = env.get("PHONE_AGENT_API_KEY") or settings.autoglm_api_key or "EMPTY"
        env["PHONE_AGENT_MAX_STEPS"] = env.get("PHONE_AGENT_MAX_STEPS") or str(settings.autoglm_max_steps)
        env["PHONE_AGENT_LANG"] = env.get("PHONE_AGENT_LANG") or settings.autoglm_lang
        env["PHONE_AGENT_WDA_URL"] = env.get("PHONE_AGENT_WDA_URL") or settings.autoglm_wda_url
        env["PHONE_AGENT_TAKEOVER_MODE"] = env.get("PHONE_AGENT_TAKEOVER_MODE") or takeover_mode or "fail"

        path_parts = []
        for executable in (settings.resolved_adb_path, settings.resolved_ios_path, settings.resolved_hdc_path):
            exe_path = Path(executable)
            if exe_path.is_absolute() and exe_path.exists():
                path_parts.append(str(exe_path.parent))
        path_parts.append(str(settings.open_autoglm_root))
        env["PATH"] = os.pathsep.join(path_parts + [env.get("PATH", "")])
        return env

    @staticmethod
    def _redacted_command(command: list[str]) -> list[str]:
        redacted = list(command)
        for index, item in enumerate(redacted):
            if item == "--apikey" and index + 1 < len(redacted):
                redacted[index + 1] = "***"
        return redacted

    # ------------------------------------------------------------------
    # Device resolution — consolidates all device checks into one call.
    # Returns (platform, error_message, warnings). Only hard failures
    # (ADB broken, device not found, adb_shell_unavailable) block execution.
    # Everything else (keyboard, screenshot, dumpsys) is a warning.
    # ------------------------------------------------------------------
    def _resolve_device(
        self,
        device_udid: str | None,
        device_platform: str | None,
    ) -> tuple[str, str | None, list[str]]:
        platform = _normalize_platform(device_platform)
        warnings: list[str] = []

        if not device_udid:
            return ("", "未选择设备，请在左侧设备面板选择在线设备后重试。", [])

        # Auto-detect platform from connected devices when not provided
        if platform is None:
            platform = self._infer_platform_from_connected_devices(device_udid)
        if platform is None:
            return (
                "",
                f"无法识别设备 {device_udid} 的平台类型。"
                f"请确认设备已通过 USB 数据线连接且 adb devices 能看到该设备。",
                [],
            )

        # Tool check (adb / hdc / go-ios)
        tool_error = self._validate_platform_executable(platform)
        if tool_error:
            return (platform, tool_error, [])

        # Device-list check
        try:
            devices = self._list_devices(platform)
        except Exception as exc:
            return (platform, f"{PLATFORM_LABELS[platform]} 设备检测失败：{exc}", [])

        matched = [d for d in devices if getattr(d, "udid", None) == device_udid]
        if not matched:
            return (
                platform,
                f"无法找到设备 {device_udid}，请确认 {PLATFORM_LABELS[platform]} 已连接并在线。",
                [],
            )
        if getattr(matched[0], "status", "") != "online":
            return (
                platform,
                f"设备 {device_udid} 当前状态为 {getattr(matched[0], 'status', 'unknown')}，不是在线状态。",
                [],
            )

        # Android readiness: only adb_shell_unavailable blocks execution;
        # other issues (keyboard, screenshot, dumpsys) are warnings.
        if platform == "android":
            readiness = AndroidDeviceReadinessService().check(device_udid)
            for issue in readiness.issues:
                if issue.code == "adb_shell_unavailable":
                    return (platform, f"设备 {device_udid} ADB shell 无响应：{issue.message}", [])
                warnings.append(f"设备就绪提醒：{issue.message}")

        return (platform, None, warnings)

    def _validate_device(self, device_udid: str, platform: str) -> str | None:
        """Legacy wrapper — kept for tests. Prefer _resolve_device."""
        _, error, _ = self._resolve_device(device_udid, platform)
        return error

    def _validate_platform_executable(self, platform: str) -> str | None:
        executable = {
            "android": settings.resolved_adb_path,
            "ios": settings.resolved_ios_path,
            "harmony": settings.resolved_hdc_path,
        }[platform]
        if shutil.which(executable) is None:
            return f"{PLATFORM_LABELS[platform]} 执行工具未配置或不可用：{executable}"
        return None

    @staticmethod
    def _list_devices(platform: str) -> list[object]:
        if platform == "android":
            return list(ADBService().list_devices())
        if platform == "ios":
            return list(IOSService().list_devices())
        return list(HarmonyService().list_devices())

    def _infer_platform_from_connected_devices(self, device_udid: str) -> str | None:
        for platform in ("android", "ios", "harmony"):
            try:
                if any(getattr(device, "udid", None) == device_udid for device in self._list_devices(platform)):
                    return platform
            except Exception:
                continue
        return None

    @staticmethod
    def _validate_open_autoglm_root() -> str | None:
        main_path = settings.open_autoglm_root / "main.py"
        if not main_path.exists():
            return f"Open-AutoGLM 入口不存在：{main_path}"
        return None

    @staticmethod
    def _infer_target_kind(case: ImportedTestCase) -> str:
        target_app = (case.target_app or "").strip()
        if target_app == "微信小程序":
            return "mini_program"
        # Check text hints for web/mini_program regardless of target_app
        text = " ".join(
            [
                case.target_app or "",
                case.precondition or "",
                case.case_name or "",
                " ".join(case.steps or []),
            ]
        ).lower()
        if "小程序" in text or "微信" in text:
            return "mini_program"
        if "web" in text or "h5" in text or "网页" in text or "浏览器" in text or "https://" in text or "http://" in text:
            return "web"
        return "app"

    def _run_web_case_events(
        self,
        case: ImportedTestCase,
        report_dir: Path,
        emit,
        client_run_id: str | None,
        action_trace: list[dict],
        started: datetime,
        timer: float,
        run_index: int,
    ) -> Iterator[dict]:
        """执行 Web 类型用例，使用 agent-browser 执行器"""
        yield emit(
            "log",
            "device_check",
            "检测到 Web 类型用例，使用 agent-browser 执行器。",
            executor="agent-browser",
            target_kind="web",
        )
        pc_agent_config = ModelProviderService().pc_agent_config()
        yield emit(
            "log",
            "agent",
            f"PC Agent 模型：{pc_agent_config.provider} / {pc_agent_config.model or '未配置'}",
            type="pc_agent_model",
            provider=pc_agent_config.provider,
            model=pc_agent_config.model,
            configured=pc_agent_config.configured,
        )

        # 检查 agent-browser 是否可用
        browser_service = PCBrowserService()
        agent_browser_path = settings.resolved_agent_browser_path
        if not shutil.which(agent_browser_path):
            result_note = f"agent-browser 未配置或不可用：{agent_browser_path}"
            yield emit("error", "device_check", result_note, error_category="agent_browser_config")
            self._finalize_execution(
                case=case,
                action_trace=action_trace,
                report_dir=report_dir,
                started=started,
                timer=timer,
                run_index=run_index,
                final_result="failed",
                result_note=result_note,
                client_run_id=client_run_id,
            )
            return

        # 构建执行任务 — use case name as fallback goal
        execution_goal = case.case_name
        target_url = self._extract_target_url(case)
        session_name = self._web_session_name(case=case, client_run_id=client_run_id, run_index=run_index)
        if target_url:
            auth_result = self._prepare_web_auth_state_if_needed(
                target_url=target_url,
                browser_service=browser_service,
                session_name=session_name,
                emit=emit,
                case=case,
                action_trace=action_trace,
                report_dir=report_dir,
                started=started,
                timer=timer,
                run_index=run_index,
                client_run_id=client_run_id,
            )
            if auth_result:
                yield auth_result
                return
            yield emit("log", "precondition", f"打开目标 URL：{target_url}", url=target_url)
            try:
                session = browser_service.open(target_url, session=session_name, headed=True)
                yield emit(
                    "log",
                    "precondition",
                    f"浏览器已打开：{session.title}",
                    session_id=session.session_id,
                    url=session.url,
                )
            except Exception as exc:
                result_note = f"打开浏览器失败：{exc}"
                yield emit("error", "precondition", result_note, error_category="browser_open_failed")
                self._finalize_execution(
                    case=case,
                    action_trace=action_trace,
                    report_dir=report_dir,
                    started=started,
                    timer=timer,
                    run_index=run_index,
                    final_result="failed",
                    result_note=result_note,
                    client_run_id=client_run_id,
                )
                return

        # 使用 PCBrowserAgentService 执行任务
        agent_service = PCBrowserAgentService(browser=browser_service, artifact_root=report_dir)
        max_steps = settings.autoglm_max_steps or 15

        try:
            agent_result = None
            for event in agent_service.iter_task_events(task=execution_goal, session=session_name, max_steps=max_steps):
                if execution_cancel_registry.is_cancelled(client_run_id):
                    yield emit("error", "execution", "执行已停止。", error_category="cancelled")
                    browser_service.close(session=session_name)
                    self._finalize_execution(
                        case=case,
                        action_trace=action_trace,
                        report_dir=report_dir,
                        started=started,
                        timer=timer,
                        run_index=run_index,
                        final_result="failed",
                        result_note="执行已停止。",
                        client_run_id=client_run_id,
                    )
                    return

                action_trace.append(event)
                yield event

                if event.get("event") == "result":
                    agent_result = event

            if agent_result:
                final_result = agent_result.get("run_result", "failed")
                result_note = agent_result.get("message", "Web 用例执行完成")
            else:
                final_result = "failed"
                result_note = "Web 用例执行未产生结果"

        except Exception as exc:
            final_result = "failed"
            result_note = f"Web 用例执行失败：{exc}"
            yield emit("error", "execution", result_note, error_category="web_execution_failed")
        finally:
            browser_service.close(session=session_name)

        # 保存终态截图
        screenshot = None
        if not execution_cancel_registry.is_cancelled(client_run_id):
            screenshot = self._capture_web_final_screenshot(report_dir, browser_service, session=session_name)
            if screenshot.get("url"):
                yield emit(
                    "log",
                    "report",
                    f"终态截图已保存：{screenshot['url']}",
                    type="final_screenshot",
                    screenshot_url=screenshot["url"],
                    screenshot_path=screenshot["path"],
                    screenshot_at=screenshot["created_at"],
                )

        # 断言结果
        assertion = ResultAssertionService().assert_result(
            case=case,
            action_trace=action_trace,
            final_screenshot=screenshot,
        )
        verdict = assertion.get("verdict")
        if verdict == "passed":
            final_result = "passed"
            result_note = f"断言通过：{assertion.get('reason')}"
            yield emit("log", "assertion", result_note, type="result_assertion", assertion=assertion)
        elif verdict == "failed":
            final_result = "failed"
            result_note = f"断言失败：{assertion.get('reason')}"
            yield emit("error", "assertion", result_note, type="result_assertion", error_category="assertion_failed", assertion=assertion)
        else:
            final_result = "uncertain"
            result_note = f"断言不确定：{assertion.get('reason')}"
            yield emit("error", "assertion", result_note, type="result_assertion", error_category="assertion_uncertain", assertion=assertion)

        # 保存执行结果并 yield 最终事件
        execution = self._finalize_execution(
            case=case,
            action_trace=action_trace,
            report_dir=report_dir,
            started=started,
            timer=timer,
            run_index=run_index,
            final_result=final_result,
            result_note=result_note,
            client_run_id=client_run_id,
        )

        # Yield 最终结果事件
        assertion_result = self._latest_assertion_result(action_trace)
        yield {
            "event": "result",
            "phase": "report",
            "timestamp": utc_iso(),
            "execution_id": execution.id,
            "case_id": execution.case_id,
            "run_result": execution.run_result,
            "result_note": execution.result_note,
            "error_category": execution.error_category,
            "assertion_result": assertion_result,
            "report_url": getattr(execution, "_report_url", ""),
            "log_url": getattr(execution, "_log_url", ""),
            "report_folder_url": self._report_url_for_path(report_dir),
            "duration_ms": execution.duration_ms,
        }
        execution_cancel_registry.cleanup(client_run_id)

    @staticmethod
    def _web_session_name(*, case: ImportedTestCase, client_run_id: str | None, run_index: int) -> str:
        suffix = client_run_id or f"case-{case.id}-{run_index}"
        return f"web-{suffix}"

    def _prepare_web_auth_state_if_needed(
        self,
        *,
        target_url: str,
        browser_service: PCBrowserService,
        session_name: str,
        emit,
        case: ImportedTestCase,
        action_trace: list[dict],
        report_dir: Path,
        started: datetime,
        timer: float,
        run_index: int,
        client_run_id: str | None,
    ) -> dict | None:
        auth_profile = self._leyoujia_auth_profile_for_url(target_url)
        if not auth_profile:
            return None

        state_path = self._leyoujia_auth_state_path(auth_profile)
        if state_path.exists():
            try:
                browser_service.load_state(state_path, session=session_name)
                emit(
                    "log",
                    "precondition",
                    f"已加载 Leyoujia {auth_profile['label']}登录态。",
                    type="web_auth_state_loaded",
                    login_url=auth_profile["login_url"],
                    auth_env=auth_profile["env"],
                    state_path=str(state_path),
                )
                return None
            except Exception as exc:
                emit(
                    "error",
                    "precondition",
                    f"Leyoujia 登录态加载失败：{exc}",
                    type="web_auth_state_load_failed",
                    error_category="web_auth_state_load_failed",
                    login_url=auth_profile["login_url"],
                    auth_env=auth_profile["env"],
                )

        message = (
            f"检测到 Leyoujia {auth_profile['label']}需要登录态。请先在 PC AutoExecute 选择"
            f"“{auth_profile['label']}”，点击“打开登录页”，手动完成扫码/登录后点击“保存登录态”，"
            "再重新执行该 Web 用例。"
        )
        emit(
            "need_user",
            "precondition",
            message,
            type="manual_auth_required",
            error_category="manual_auth_required",
            login_url=auth_profile["login_url"],
            auth_env=auth_profile["env"],
            target_url=target_url,
            state_path=str(state_path),
        )
        execution = self._finalize_execution(
            case=case,
            action_trace=action_trace,
            report_dir=report_dir,
            started=started,
            timer=timer,
            run_index=run_index,
            final_result="failed",
            result_note=message,
            client_run_id=client_run_id,
        )
        return {
            "event": "result",
            "phase": "report",
            "timestamp": utc_iso(),
            "execution_id": execution.id,
            "case_id": execution.case_id,
            "run_result": execution.run_result,
            "result_note": execution.result_note,
            "error_category": execution.error_category,
            "report_url": getattr(execution, "_report_url", ""),
            "log_url": getattr(execution, "_log_url", ""),
            "report_folder_url": self._report_url_for_path(report_dir),
            "duration_ms": execution.duration_ms,
        }

    @staticmethod
    def _leyoujia_auth_profile_for_url(target_url: str) -> dict[str, object] | None:
        host = (urlparse(target_url).hostname or "").lower()
        for profile in LEYOUJIA_AUTH_PROFILES.values():
            if host in profile["hosts"]:
                return profile
        return None

    @staticmethod
    def _leyoujia_auth_state_path(profile: dict[str, object] | None = None) -> Path:
        item = profile or LEYOUJIA_AUTH_PROFILES["test"]
        return (settings.backend_dir / ".pc_auth" / str(item["state_file"])).resolve()

    @staticmethod
    def _extract_target_url(case: ImportedTestCase) -> str | None:
        """从用例中提取目标 URL"""
        import re

        texts = [
            case.precondition or "",
            case.case_name or "",
            " ".join(case.steps or []),
            case.target_app or "",
        ]
        combined = " ".join(texts)

        # 匹配常见 URL 模式
        url_pattern = r"https?://[^\s<>\"]+"
        match = re.search(url_pattern, combined)
        if match:
            return match.group(0)

        # 检查 target_app 是否是 URL
        if case.target_app and case.target_app.startswith(("http://", "https://")):
            return case.target_app

        return None

    def _capture_web_final_screenshot(self, report_dir: Path, browser_service: PCBrowserService, session: str | None = None) -> dict[str, str]:
        """截取 Web 终态屏幕"""
        screenshots_dir = report_dir / "screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        created_at = utc_iso()
        stem = f"final_web_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}"
        target_path = screenshots_dir / f"{stem}.png"

        try:
            browser_service.screenshot(target_path, full_page=False, session=session)
            if target_path.exists() and target_path.stat().st_size > 0:
                return {
                    "url": self._report_url_for_path(target_path),
                    "path": str(target_path),
                    "created_at": created_at,
                }
        except Exception:
            pass

        return {"error": "Web 截图失败", "created_at": created_at}

    def _finalize_execution(
        self,
        case: ImportedTestCase,
        action_trace: list[dict],
        report_dir: Path,
        started: datetime,
        timer: float,
        run_index: int,
        final_result: str,
        result_note: str,
        client_run_id: str | None,
    ) -> TestCaseExecution:
        """保存执行结果到数据库"""
        duration_ms = max(1, int((perf_counter() - timer) * 1000))
        if execution_cancel_registry.is_cancelled(client_run_id):
            final_result = "failed"
            result_note = "执行已停止。"

        assertion_result = self._latest_assertion_result(action_trace)
        error_category = _classify_execution_error(final_result, result_note, action_trace)
        execution = TestCaseExecution(
            plan_id=case.plan_id,
            case_id=case.id,
            run_index=run_index,
            device_udid=None,
            run_result=final_result,
            result_note=result_note,
            autoglm_configured=False,
            action_trace=[],
            error_category=error_category,
            started_at=started,
            ended_at=datetime.utcnow(),
            duration_ms=duration_ms,
        )
        self.db.add(execution)

        case.run_count = run_index
        case.latest_result = final_result
        case.latest_result_note = result_note
        self.db.commit()
        self.db.refresh(execution)

        log_url = self._save_execution_log_file(
            execution_id=execution.id,
            action_trace=action_trace,
            report_dir=report_dir,
        )
        report_url = self._save_execution_report(
            execution=execution,
            case=case,
            target_kind="web",
            device_platform="web",
            started_at=started,
            ended_at=execution.ended_at or datetime.utcnow(),
            duration_ms=duration_ms,
            report_dir=report_dir,
            logs=action_trace,
            external_log_url=log_url,
        )

        execution.action_trace = self._build_slim_action_trace(action_trace, log_url)
        self.db.commit()
        self.db.refresh(execution)

        # Store URLs for later access
        execution._log_url = log_url
        execution._report_url = report_url

        return execution

    def _get_autoglm_login_accounts(self) -> list[dict[str, str]]:
        """Query LoginAccount records where use_for_autoglm=True.

        Returns a list of dicts with keys: platform, label, login_id, password.
        The password is returned in plain text for injection into the prompt.
        """
        accounts = (
            self.db.query(LoginAccount)
            .filter(LoginAccount.use_for_autoglm == True)
            .order_by(LoginAccount.platform, LoginAccount.label)
            .all()
        )
        return [
            {
                "platform": a.platform,
                "label": a.label,
                "login_id": a.login_id,
                "password": a.password,
            }
            for a in accounts
        ]

    @staticmethod
    def _build_unified_prompt(
        case: ImportedTestCase,
        target_kind: str,
        platform: str,
        login_accounts: list[dict[str, str]] | None = None,
    ) -> str:
        """Build a unified prompt for AutoGLM from the case object.

        The prompt is composed of four and only four fields:
            1. 目标应用 (target_app)
            2. *前置条件 (precondition)
            3. *用例步骤 (steps)
            4. *预期结果 (expected_result)

        If login_accounts are provided, appends login credential instructions
        so AutoGLM can handle login screens autonomously.

        The three starred fields are required at the API/UI layer. This keeps
        the prompt minimal and lets the case author focus on the actual test.
        """
        target_app = (case.target_app or "").strip() or "根据用例内容判断"
        precondition = (case.precondition or "").strip()
        expected_result = (case.expected_result or "").strip()
        steps = case.steps or []

        # 微信小程序导航前置指令
        is_mini_program = (
            "小程序" in target_app
            or "小程序" in (case.test_module or "")
            or "小程序" in (case.system_name or "")
        )
        nav_prefix = ""
        if is_mini_program:
            raw_name = (case.test_module or "").strip() or (case.system_name or "").strip()
            mini_program_name = raw_name.replace("微信", "").replace("小程序", "").strip() or "该小程序"
            nav_prefix = f"进入微信，从微信主页面从下面的发现-小程序进去找{mini_program_name}；"

        # 步骤文本
        step_lines: list[str] = []
        for s in steps:
            text = s.get("step", s) if isinstance(s, dict) else str(s)
            text = (text or "").strip()
            if text:
                step_lines.append(f"  {len(step_lines) + 1}. {text}")
        steps_block = "\n".join(step_lines) if step_lines else "  (无)"

        # 拼接 prompt —— 只使用目标应用 + 三个必填字段
        lines = [
            f"目标应用：{target_app}",
            "",
            "前置条件：",
            f"  {precondition or '(无)'}",
            "",
            "用例步骤：",
            steps_block,
            "",
            "预期结果：",
            f"  {expected_result or '(无)'}",
        ]

        if nav_prefix:
            lines.insert(0, f"导航提示：{nav_prefix}")

        # ── Append login credentials for AutoGLM ──────────────────────
        if login_accounts:
            lines.append("")
            lines.append("可用登录账号（如果遇到登录页面，请优先使用以下信息登录）：")
            for idx, acct in enumerate(login_accounts, start=1):
                lines.append(f"  {idx}. 平台:{acct['platform']} 账号:{acct['login_id']} 密码:{acct['password']}")

        return "\n".join(lines).rstrip() + "\n"

    @staticmethod
    def _target_kind_label(target_kind: str) -> str:
        return {
            "mini_program": "小程序",
            "web": "Web/H5",
            "app": "APP",
        }.get(target_kind, target_kind)

    @staticmethod
    def _latest_assertion_result(action_trace: list[dict]) -> dict | None:
        return ReportWriter.latest_assertion_result(action_trace)

    @staticmethod
    def _get_current_app_package(device_udid: str) -> str:
        """Get the current foreground app package name for JudgeService."""
        if not device_udid:
            return ""
        try:
            result = ADBService().current_app(device_udid)
            if result:
                return result.get("package_name", "")
        except Exception:
            pass
        return ""

    def _build_slim_action_trace(self, action_trace: list[dict], log_url: str) -> list[dict]:
        return self.report_writer.build_slim_action_trace(action_trace, log_url)

    def _save_execution_log_file(self, execution_id: int, action_trace: list[dict], report_dir: Path) -> str:
        return self.report_writer.save_execution_log_file(execution_id, action_trace, report_dir)

    @staticmethod
    def load_external_action_trace(action_trace: list[dict]) -> list[dict]:
        return ReportWriter().load_external_action_trace(action_trace)

    @staticmethod
    def _extract_page_hint(case: ImportedTestCase) -> str:
        text = " ".join([case.precondition or "", case.case_name or "", " ".join(case.steps or [])])
        for marker in ("进入", "打开", "到达"):
            index = text.find(marker)
            if index >= 0:
                snippet = text[index:index + 28].strip(" ，,。；;")
                if snippet:
                    return f"并{snippet}"
        return "并进入测试起点页面"

    def _artifact_url_for_path(self, path: Path) -> str:
        try:
            return self._report_url_for_path(path)
        except ValueError:
            return path.name

    def _capture_final_screenshot(self, report_dir: Path, platform: str, device_udid: str) -> dict[str, str]:
        stem = f"final_screen_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}"
        return self._capture_device_screenshot(report_dir, platform, device_udid, stem)

    def _capture_device_screenshot(self, report_dir: Path, platform: str, device_udid: str, stem: str) -> dict[str, str]:
        screenshots_dir = report_dir / "screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        created_at = utc_iso()
        try:
            if platform == "android":
                target_path = screenshots_dir / f"{stem}.png"
                if settings.u2_enabled:
                    try:
                        png = u2_service.screenshot(device_udid)
                        target_path.write_bytes(png)
                    except Exception:
                        result = subprocess.run(
                            [settings.resolved_adb_path, "-s", device_udid, "exec-out", "screencap", "-p"],
                            capture_output=True,
                            timeout=settings.screenshot_timeout_seconds,
                            check=False,
                        )
                        if result.returncode != 0:
                            error = result.stderr.decode("utf-8", errors="ignore").strip()
                            raise TestExecutionError(error or "adb screencap failed")
                        if not result.stdout:
                            raise TestExecutionError("adb screencap returned empty content")
                        target_path.write_bytes(result.stdout)
                else:
                    result = subprocess.run(
                        [settings.resolved_adb_path, "-s", device_udid, "exec-out", "screencap", "-p"],
                        capture_output=True,
                        timeout=settings.screenshot_timeout_seconds,
                        check=False,
                    )
                    if result.returncode != 0:
                        error = result.stderr.decode("utf-8", errors="ignore").strip()
                        raise TestExecutionError(error or "adb screencap failed")
                    if not result.stdout:
                        raise TestExecutionError("adb screencap returned empty content")
                    target_path.write_bytes(result.stdout)
            elif platform == "harmony":
                target_path = screenshots_dir / f"{stem}.jpeg"
                remote_path = f"/data/local/tmp/{stem}.jpeg"
                capture = subprocess.run(
                    [settings.resolved_hdc_path, "-t", device_udid, "shell", "screenshot", remote_path],
                    capture_output=True,
                    text=True,
                    timeout=settings.screenshot_timeout_seconds,
                    check=False,
                )
                output = f"{capture.stdout}\n{capture.stderr}".lower()
                if capture.returncode != 0 or "fail" in output or "error" in output or "not found" in output:
                    capture = subprocess.run(
                        [settings.resolved_hdc_path, "-t", device_udid, "shell", "snapshot_display", "-f", remote_path],
                        capture_output=True,
                        text=True,
                        timeout=settings.screenshot_timeout_seconds,
                        check=False,
                    )
                if capture.returncode != 0:
                    raise TestExecutionError(capture.stderr.strip() or capture.stdout.strip() or "hdc screenshot failed")
                recv = subprocess.run(
                    [settings.resolved_hdc_path, "-t", device_udid, "file", "recv", remote_path, str(target_path)],
                    capture_output=True,
                    text=True,
                    timeout=settings.screenshot_timeout_seconds,
                    check=False,
                )
                subprocess.run(
                    [settings.resolved_hdc_path, "-t", device_udid, "shell", "rm", "-f", remote_path],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                if recv.returncode != 0:
                    raise TestExecutionError(recv.stderr.strip() or recv.stdout.strip() or "hdc file recv failed")
                if not target_path.exists() or target_path.stat().st_size == 0:
                    raise TestExecutionError("hdc screenshot returned empty content")
            else:
                target_path = screenshots_dir / f"{stem}.png"
                if not self._capture_ios_screenshot(target_path, device_udid):
                    raise TestExecutionError("iOS screenshot failed")

            return {
                "url": self._artifact_url_for_path(target_path),
                "path": str(target_path),
                "created_at": created_at,
            }
        except Exception as exc:
            return {"error": str(exc), "created_at": created_at}

    @staticmethod
    def _capture_ios_screenshot(target_path: Path, device_udid: str) -> bool:
        if settings.wda_enabled:
            try:
                png = wda_service.screenshot(device_udid or "ios-default")
                target_path.write_bytes(png)
                return target_path.exists() and target_path.stat().st_size > 0
            except Exception:
                pass

        command = ["idevicescreenshot"]
        if device_udid:
            command.extend(["-u", device_udid])
        command.append(str(target_path))
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=settings.screenshot_timeout_seconds, check=False)
            return result.returncode == 0 and target_path.exists() and target_path.stat().st_size > 0
        except Exception:
            return False

    def _save_execution_report(
        self,
        execution: TestCaseExecution,
        case: ImportedTestCase,
        target_kind: str,
        device_platform: str | None,
        started_at: datetime,
        ended_at: datetime,
        duration_ms: int,
        report_dir: Path | None = None,
        logs: list[dict] | None = None,
        external_log_url: str | None = None,
    ) -> str:
        return self.report_writer.save_execution_report(
            execution=execution,
            case=case,
            target_kind=target_kind,
            device_platform=device_platform,
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=duration_ms,
            report_dir=report_dir,
            logs=logs,
            external_log_url=external_log_url,
        )

    def _save_plan_run_summary(
        self,
        plan_id: int,
        report_dir: Path,
        results: list[dict],
        started_at: datetime,
        ended_at: datetime,
    ) -> str:
        return self.report_writer.save_plan_run_summary(
            plan_id=plan_id,
            report_dir=report_dir,
            results=results,
            started_at=started_at,
            ended_at=ended_at,
        )

    def _make_report_group_dir(self, plan_id: int | None = None, case_id: int | None = None) -> Path:
        return self.report_writer.make_report_group_dir(plan_id=plan_id, case_id=case_id)

    def _report_url_for_path(self, path: Path) -> str:
        return self.report_writer.report_url_for_path(path)
