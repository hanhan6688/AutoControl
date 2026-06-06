from __future__ import annotations

import json
import re
import base64
import mimetypes
from pathlib import Path
from typing import Any

from openai import OpenAI

from app.config import settings
from app.models import ImportedTestCase
from app.automation.autoglm.judge_service import JudgeService


VALID_VERDICTS = {"passed", "failed", "uncertain"}


class ResultAssertionService:
    """Judge whether a completed AutoGLM run satisfies the test expectation."""

    def assert_result(
        self,
        case: ImportedTestCase,
        action_trace: list[dict],
        final_screenshot: dict[str, Any] | None = None,
        task_plan: dict[str, Any] | None = None,
        checkpoints_passed: int | None = None,
        total_checkpoints: int | None = None,
        final_app: str = "",
        expected_app: str = "",
    ) -> dict[str, Any]:
        # Derive task_plan from case if not provided (backward compat)
        if task_plan is None:
            task_plan = self._task_plan_from_case(case)
        fallback = self._fallback_assertion(case, task_plan, action_trace, final_screenshot)

        # Supplement with JudgeService when checkpoint data is available
        if checkpoints_passed is not None and total_checkpoints is not None and total_checkpoints > 0:
            judge = JudgeService()
            judge_result = judge.determine(
                checkpoints_passed=checkpoints_passed,
                total_checkpoints=total_checkpoints,
                final_app=final_app,
                expected_app=expected_app or final_app,
            )
            fallback["judge_verdict"] = judge_result.verdict
            fallback["judge_confidence"] = judge_result.confidence
            fallback["judge_reason"] = judge_result.reason
            # If JudgeService is more confident than fallback, prefer its verdict
            if judge_result.confidence > fallback.get("confidence", 0):
                fallback["verdict"] = judge_result.verdict
                fallback["confidence"] = judge_result.confidence
                fallback["reason"] = f"[JudgeService] {judge_result.reason}"

        if not self._is_ai_enabled():
            return fallback

        try:
            ai_assertion = self._assert_with_ai(case, task_plan, action_trace, final_screenshot)
        except Exception as exc:
            fallback["assertion_error"] = str(exc)
            return fallback

        return self._merge_assertion(fallback, ai_assertion)

    def _is_ai_enabled(self) -> bool:
        api_key = self._api_key()
        return bool(settings.result_assertion_enabled and api_key and api_key != "EMPTY")

    def _assert_with_ai(
        self,
        case: ImportedTestCase,
        task_plan: dict[str, Any],
        action_trace: list[dict],
        final_screenshot: dict[str, Any] | None,
    ) -> dict[str, Any]:
        client = OpenAI(
            base_url=self._base_url(),
            api_key=self._api_key(),
            timeout=settings.result_assertion_timeout_seconds,
        )
        response = client.chat.completions.create(
            model=self._model(),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是移动端测试结果裁判，只判断测试结果是否符合预期。"
                        "你不能操作手机，不能把 AutoGLM 执行完成等同于测试通过。"
                        "只输出 JSON。"
                    ),
                },
                {
                    "role": "user",
                    "content": self._assertion_user_content(case, task_plan, action_trace, final_screenshot),
                },
            ],
            temperature=0.0,
            max_tokens=800,
            stream=False,
        )
        content = response.choices[0].message.content or ""
        payload = self._parse_json_object(content)
        payload["source"] = "ai"
        return self._with_review_fields(payload)

    def _assertion_user_content(
        self,
        case: ImportedTestCase,
        task_plan: dict[str, Any],
        action_trace: list[dict],
        final_screenshot: dict[str, Any] | None,
    ) -> str | list[dict[str, Any]]:
        prompt = self._assertion_prompt(case, task_plan, action_trace, final_screenshot)
        image_url = self._screenshot_data_url(final_screenshot)
        if not image_url:
            return prompt
        return [
            {"type": "text", "text": prompt + "\n请优先结合终态截图做视觉判断。"},
            {"type": "image_url", "image_url": {"url": image_url}},
        ]

    def _assertion_prompt(
        self,
        case: ImportedTestCase,
        task_plan: dict[str, Any],
        action_trace: list[dict],
        final_screenshot: dict[str, Any] | None,
    ) -> str:
        logs = self._compact_logs(action_trace)
        return "\n".join(
            [
                "请判断这次移动端测试是否符合预期。",
                "必须输出 JSON 对象，字段固定为：verdict, confidence, reason, evidence, failed_expectations, review_required, review_status。",
                "verdict 只能是 passed / failed / uncertain。",
                "如果证据不足、截图不可判读、日志只说明执行完成但不能证明预期成立，verdict 必须是 uncertain，review_required 必须为 true。",
                "判断规则：AutoGLM 返回成功只代表执行完成，不代表测试通过；必须有日志、截图信息或可观察证据支持预期结果。",
                f"用例名称：{case.case_name}",
                f"前置条件：{case.precondition or '无'}",
                f"原始步骤：{json.dumps(case.steps or [], ensure_ascii=False)}",
                f"原始预期：{case.expected_result or '无'}",
                f"任务书：{json.dumps(task_plan, ensure_ascii=False)}",
                f"终态截图：{json.dumps(final_screenshot or {}, ensure_ascii=False)}",
                "执行日志摘要：",
                logs,
            ]
        )

    # ------------------------------------------------------------------
    # Derive a lightweight task_plan from the case object itself,
    # replacing the old CaseOrchestrationService.build_plan() output.
    # ------------------------------------------------------------------
    @staticmethod
    def _task_plan_from_case(case: ImportedTestCase) -> dict[str, Any]:
        # success_criteria: expected_result + last step as anchor
        last_step = ""
        if case.steps:
            steps = case.steps if isinstance(case.steps, list) else []
            if steps:
                last = steps[-1]
                last_step = last.get("step", last) if isinstance(last, dict) else str(last)

        criteria = []
        if case.expected_result:
            criteria.append(case.expected_result)
        if last_step:
            criteria.append(last_step)

        # unified_goal: a human-readable sentence combining precondition + steps
        goal_parts = []
        if case.precondition and str(case.precondition).strip():
            goal_parts.append(str(case.precondition).strip())
        if case.steps:
            step_text = "；".join(
                s.get("step", s) if isinstance(s, dict) else str(s)
                for s in case.steps
                if (s.get("step", s) if isinstance(s, dict) else str(s)).strip()
            )
            if step_text:
                goal_parts.append(step_text)
        unified_goal = "；然后".join(goal_parts) if goal_parts else case.case_name

        return {
            "source": "fallback",
            "unified_goal": unified_goal,
            "success_criteria": criteria or [case.expected_result or "任务完成"],
        }

    def _fallback_assertion(
        self,
        case: ImportedTestCase,
        task_plan: dict[str, Any],
        action_trace: list[dict],
        final_screenshot: dict[str, Any] | None,
    ) -> dict[str, Any]:
        expectation_terms = self._expectation_terms(case, task_plan)
        log_text = self._plain_log_text(action_trace)
        evidence: list[str] = []
        matched_terms: list[str] = []

        for term in expectation_terms:
            if term and term in log_text:
                matched_terms.append(term)
                evidence.append(f"日志包含预期关键词：{term}")

        failure_terms = ["失败", "无法", "未找到", "异常", "错误", "超时", "返回码：1", "returncode=1"]
        failed_expectations = [term for term in failure_terms if term in log_text]

        if failed_expectations:
            verdict = "failed"
            confidence = 0.7
            reason = "执行日志中出现失败或异常信号。"
        elif expectation_terms and matched_terms:
            verdict = "passed"
            confidence = 0.68
            reason = "执行日志中找到与预期结果匹配的关键证据。"
        elif final_screenshot and final_screenshot.get("url"):
            verdict = "uncertain"
            confidence = 0.45
            reason = "AutoGLM 执行完成并保存了终态截图，但文本日志证据不足，需要人工或视觉模型复核。"
            evidence.append(f"终态截图：{final_screenshot.get('url')}")
        else:
            verdict = "uncertain"
            confidence = 0.35
            reason = "AutoGLM 执行完成，但没有足够证据证明预期结果成立。"

        return self._with_review_fields({
            "source": "fallback",
            "verdict": verdict,
            "confidence": confidence,
            "reason": reason,
            "evidence": evidence,
            "failed_expectations": failed_expectations,
        })

    def _merge_assertion(self, fallback: dict[str, Any], ai_assertion: dict[str, Any]) -> dict[str, Any]:
        verdict = str(ai_assertion.get("verdict") or "").strip().lower()
        if verdict not in VALID_VERDICTS:
            verdict = "uncertain"
        merged = dict(fallback)
        merged["source"] = "ai"
        merged["verdict"] = verdict
        merged["confidence"] = self._safe_confidence(ai_assertion.get("confidence"), fallback["confidence"])
        for key in ("reason",):
            value = ai_assertion.get(key)
            if isinstance(value, str) and value.strip():
                merged[key] = value.strip()
        for key in ("evidence", "failed_expectations"):
            value = ai_assertion.get(key)
            if isinstance(value, list):
                merged[key] = [str(item).strip() for item in value if str(item).strip()]
        return self._with_review_fields(merged)

    @staticmethod
    def _with_review_fields(assertion: dict[str, Any]) -> dict[str, Any]:
        verdict = str(assertion.get("verdict") or "uncertain").strip().lower()
        if verdict not in VALID_VERDICTS:
            verdict = "uncertain"
        confidence = ResultAssertionService._safe_confidence(assertion.get("confidence"), 0.0)
        review_required = verdict == "uncertain" or (verdict == "failed" and confidence < 0.7)
        enriched = dict(assertion)
        enriched["verdict"] = verdict
        enriched["confidence"] = confidence
        enriched["review_required"] = bool(enriched.get("review_required", review_required))
        enriched["review_status"] = str(
            enriched.get("review_status") or ("pending" if enriched["review_required"] else "not_required")
        )
        if enriched["review_required"] and not enriched.get("review_recommendation"):
            enriched["review_recommendation"] = "请人工打开终态截图、执行日志和任务书，确认预期结果是否真实成立。"
        return enriched

    @staticmethod
    def _expectation_terms(case: ImportedTestCase, task_plan: dict[str, Any]) -> list[str]:
        candidates: list[str] = []
        if case.expected_result:
            candidates.extend(ResultAssertionService._split_terms(case.expected_result))
        for item in task_plan.get("success_criteria") or []:
            candidates.extend(ResultAssertionService._split_terms(str(item)))
        return list(dict.fromkeys(term for term in candidates if len(term) >= 2))

    @staticmethod
    def _split_terms(text: str) -> list[str]:
        normalized = re.sub(r"[，,。；;、\s]+", " ", text.strip())
        parts = [part.strip() for part in normalized.split(" ") if part.strip()]
        if len(text.strip()) <= 24:
            parts.append(text.strip())
        return parts

    @staticmethod
    def _plain_log_text(action_trace: list[dict]) -> str:
        values = []
        for item in action_trace:
            phase = item.get("phase")
            event_type = item.get("type") or item.get("event")
            if phase in {"plan", "report", "assertion"} or event_type in {"case_task_plan", "result_assertion"}:
                continue
            for key in ("message", "result_note", "run_result"):
                value = item.get(key)
                if value:
                    values.append(str(value))
        return "\n".join(values)

    @staticmethod
    def _compact_logs(action_trace: list[dict], limit: int = 12000) -> str:
        lines = []
        for item in action_trace:
            phase = item.get("phase", "-")
            event = item.get("event") or item.get("type") or "log"
            message = item.get("message") or item.get("result_note") or ""
            if message:
                lines.append(f"[{phase}/{event}] {message}")
        text = "\n".join(lines)
        return text[-limit:]

    @staticmethod
    def _parse_json_object(content: str) -> dict[str, Any]:
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", content, flags=re.S)
            if not match:
                raise
            payload = json.loads(match.group(0))
        if not isinstance(payload, dict):
            raise ValueError("assertion response is not a JSON object")
        return payload

    @staticmethod
    def _safe_confidence(value: object, default: float) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            return default
        return max(0.0, min(1.0, confidence))

    @staticmethod
    def _screenshot_data_url(final_screenshot: dict[str, Any] | None) -> str | None:
        if not final_screenshot:
            return None
        path_value = final_screenshot.get("path")
        if not path_value:
            return None
        path = Path(str(path_value))
        if not path.exists() or not path.is_file():
            return None
        try:
            data = path.read_bytes()
        except OSError:
            return None
        if not data:
            return None
        mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
        encoded = base64.b64encode(data).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    @staticmethod
    def _base_url() -> str:
        return settings.result_assertion_base_url

    @staticmethod
    def _model() -> str:
        return settings.result_assertion_model

    @staticmethod
    def _api_key() -> str:
        return settings.result_assertion_api_key
