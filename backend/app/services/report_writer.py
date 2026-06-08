from __future__ import annotations

import json
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

from app.config import settings
from app.models import ImportedTestCase, TestCaseExecution
from app.utils import utc_iso


HTML_REPORT_STYLE = """
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 40px; background: #f5f5f5; }
    .container { max-width: 1200px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
    h1 { color: #333; border-bottom: 2px solid #409eff; padding-bottom: 10px; }
    h2 { color: #666; margin-top: 30px; }
    .summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 20px; margin: 20px 0; }
    .stat { background: #f8f9fa; padding: 20px; border-radius: 8px; text-align: center; }
    .stat-value { font-size: 32px; font-weight: bold; color: #409eff; }
    .stat-label { color: #666; margin-top: 5px; }
    .passed { color: #67c23a; }
    .failed { color: #f56c6c; }
    .uncertain { color: #e6a23c; }
    table { width: 100%; border-collapse: collapse; margin-top: 20px; }
    th, td { padding: 12px; text-align: left; border-bottom: 1px solid #eee; }
    th { background: #f8f9fa; font-weight: 600; }
    .tag { padding: 4px 8px; border-radius: 4px; font-size: 12px; }
    .tag-pass { background: #e1f3d8; color: #67c23a; }
    .tag-fail { background: #fde2e2; color: #f56c6c; }
    .tag-uncertain { background: #fdf6ec; color: #e6a23c; }
    .footer { margin-top: 40px; text-align: center; color: #999; font-size: 12px; }
    .note { background: #f8f9fa; padding: 15px; border-radius: 8px; margin: 20px 0; }
    .section { margin-top: 24px; padding-top: 8px; }
    .assertion-box { border: 1px solid #ebeef5; border-left: 4px solid #909399; border-radius: 8px; padding: 16px; background: #fff; }
    .assertion-box.assertion-passed { border-left-color: #67c23a; }
    .assertion-box.assertion-failed { border-left-color: #f56c6c; }
    .assertion-box.assertion-uncertain { border-left-color: #e6a23c; }
    .assertion-meta { display: flex; flex-wrap: wrap; gap: 10px; margin: 10px 0; }
    .pill { display: inline-block; padding: 4px 8px; border-radius: 4px; background: #f5f7fa; color: #606266; font-size: 12px; }
    .evidence-list { margin: 8px 0 0; padding-left: 20px; }
    .task-plan { background: #f8f9fa; border-radius: 8px; padding: 16px; }
    .task-plan pre { white-space: pre-wrap; word-break: break-word; background: white; padding: 12px; border-radius: 6px; }
    .screenshot-link { display: inline-block; margin-top: 8px; color: #409eff; }
"""


class ReportWriter:
    """Persists execution logs, JSON reports, and compact DB traces."""

    def make_report_group_dir(self, plan_id: int | None = None, case_id: int | None = None) -> Path:
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
        if plan_id is not None:
            folder_name = f"plan_{plan_id}_{timestamp}"
        elif case_id is not None:
            folder_name = f"case_{case_id}_{timestamp}"
        else:
            folder_name = f"run_{timestamp}"
        return settings.static_dir / "reports" / "runs" / folder_name

    def report_url_for_path(self, path: Path) -> str:
        relative_path = path.relative_to(settings.static_dir).as_posix()
        return f"/static/{relative_path}"

    def save_execution_log_file(self, execution_id: int, action_trace: list[dict], report_dir: Path) -> str:
        report_dir.mkdir(parents=True, exist_ok=True)
        log_path = report_dir / f"execution_{execution_id}.ndjson"
        with log_path.open("w", encoding="utf-8") as file:
            for event in action_trace:
                file.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
        return self.report_url_for_path(log_path)

    def load_external_action_trace(self, action_trace: list[dict]) -> list[dict]:
        log_url = next(
            (event.get("log_url") for event in reversed(action_trace or []) if event.get("type") == "external_log"),
            None,
        )
        if not isinstance(log_url, str) or not log_url.startswith("/static/"):
            return action_trace or []

        log_path = settings.static_dir / log_url.removeprefix("/static/")
        if not log_path.exists():
            return action_trace or []

        events: list[dict] = []
        try:
            with log_path.open("r", encoding="utf-8") as file:
                for line in file:
                    value = line.strip()
                    if not value:
                        continue
                    events.append(json.loads(value))
        except (OSError, json.JSONDecodeError):
            return action_trace or []
        return events or action_trace or []

    def build_slim_action_trace(self, action_trace: list[dict], log_url: str) -> list[dict]:
        important_types = {
            "plan",
            "case_task_plan",
            "pc_agent_model",
            "manual_auth_required",
            "manual_takeover_required",
            "web_auth_state_loaded",
            "web_auth_state_load_failed",
            "final_screenshot",
            "autoglm_terminal_log",
            "result_assertion",
            "external_log",
            "error",
            "error_summary",
        }
        slim: list[dict] = []
        for event in action_trace:
            event_type = event.get("type") or event.get("event")
            if event.get("stream") == "stdout":
                continue
            # Keep action_executed events only if they carry a screenshot
            if event_type == "action_executed" and not event.get("screenshot_url"):
                continue
            if event_type in important_types or event.get("event") in {"error", "result"} or event_type == "action_executed":
                slim.append(event)

        if not any(event.get("type") == "external_log" for event in slim):
            slim.append(
                {
                    "event": "log",
                    "type": "external_log",
                    "phase": "report",
                    "timestamp": utc_iso(),
                    "message": f"完整执行日志已外置保存：{log_url}",
                    "log_url": log_url,
                    "log_event_count": len(action_trace),
                }
            )

        return slim

    def save_execution_report(
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
        if report_dir is None:
            report_dir = self.make_report_group_dir(case_id=case.id)
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"execution_{execution.id}.json"
        logs = logs if logs is not None else (execution.action_trace or [])
        final_screenshot = next(
            (item for item in reversed(logs) if item.get("type") == "final_screenshot" and item.get("screenshot_url")),
            None,
        )
        autoglm_terminal_log = next(
            (item for item in reversed(logs) if item.get("type") == "autoglm_terminal_log" and item.get("terminal_log_url")),
            None,
        )
        task_plan = next(
            (item.get("task_plan") for item in logs if item.get("type") == "case_task_plan" and item.get("task_plan")),
            None,
        )
        report = {
            "execution_id": execution.id,
            "case_id": case.id,
            "case_name": case.case_name,
            "device_udid": execution.device_udid,
            "device_platform": device_platform,
            "target_kind": target_kind,
            "case_task_plan": task_plan,
            "phases": {
                phase: [item for item in logs if item.get("phase") == phase]
                for phase in ["plan", "device_check", "precondition", "execution", "assertion", "report"]
            },
            "logs": logs,
            "external_log_url": external_log_url,
            "autoglm_terminal_log_url": autoglm_terminal_log.get("terminal_log_url") if autoglm_terminal_log else None,
            "final_screenshot_url": final_screenshot.get("screenshot_url") if final_screenshot else None,
            "assertion_result": self.latest_assertion_result(logs),
            "final_result": execution.run_result,
            "result_note": execution.result_note,
            "error_category": execution.error_category,
            "started_at": started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
            "duration_ms": duration_ms,
        }
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

        # Also generate HTML report
        self.save_execution_html_report(report, report_dir)

        return self.report_url_for_path(report_path)

    def save_plan_run_summary(
        self,
        plan_id: int,
        report_dir: Path,
        results: list[dict],
        started_at: datetime,
        ended_at: datetime,
    ) -> str:
        report_dir.mkdir(parents=True, exist_ok=True)
        summary_path = report_dir / "summary.json"

        total = len(results)
        passed = sum(1 for item in results if item.get("run_result") == "passed")
        failed = sum(1 for item in results if item.get("run_result") == "failed")
        uncertain = total - passed - failed
        pass_rate = round(passed / max(1, total) * 100, 2)

        error_categories: dict[str, int] = {}
        review_required = 0
        for item in results:
            category = item.get("error_category")
            if category and item.get("run_result") in {"failed", "uncertain"}:
                error_categories[category] = error_categories.get(category, 0) + 1
            assertion = item.get("assertion_result")
            if isinstance(assertion, dict) and assertion.get("review_required"):
                review_required += 1

        case_report_links: list[dict] = []
        for item in results:
            case_report_links.append({
                "case_id": item.get("case_id"),
                "run_result": item.get("run_result"),
                "result_note": item.get("result_note"),
                "report_url": item.get("report_url"),
                "log_url": item.get("log_url"),
                "assertion_result": item.get("assertion_result"),
            })

        summary = {
            "plan_id": plan_id,
            "total_cases": total,
            "passed": passed,
            "failed": failed,
            "uncertain": uncertain,
            "review_required": review_required,
            "pass_rate": pass_rate,
            "error_category_statistics": error_categories,
            "case_report_links": case_report_links,
            "results": results,
            "report_folder_url": self.report_url_for_path(report_dir),
            "started_at": started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
            "duration_ms": max(1, int((ended_at - started_at).total_seconds() * 1000)),
        }
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

        # Also generate HTML report
        self.save_plan_html_report(summary, report_dir)

        return self.report_url_for_path(summary_path)

    @staticmethod
    def latest_assertion_result(action_trace: list[dict]) -> dict[str, Any] | None:
        for item in reversed(action_trace):
            if item.get("type") == "result_assertion" and isinstance(item.get("assertion"), dict):
                return item["assertion"]
        return None

    def save_execution_html_report(
        self,
        report: dict[str, Any],
        report_dir: Path,
    ) -> str:
        """Generate and save HTML report for a single execution."""
        report_dir.mkdir(parents=True, exist_ok=True)
        html_path = report_dir / "report.html"

        html = self._generate_execution_html(report)
        html_path.write_text(html, encoding="utf-8")
        return self.report_url_for_path(html_path)

    def save_plan_html_report(
        self,
        summary: dict[str, Any],
        report_dir: Path,
    ) -> str:
        """Generate and save HTML summary report for a plan run."""
        report_dir.mkdir(parents=True, exist_ok=True)
        html_path = report_dir / "summary.html"

        html = self._generate_plan_html(summary)
        html_path.write_text(html, encoding="utf-8")
        return self.report_url_for_path(html_path)

    def _generate_execution_html(self, report: dict[str, Any]) -> str:
        """Generate HTML for a single execution report."""
        phases = report.get("phases", {})
        assertion = report.get("assertion_result") or {}
        task_plan = report.get("case_task_plan") or {}

        result_class = "passed" if report.get("final_result") == "passed" else ("failed" if report.get("final_result") == "failed" else "uncertain")
        assertion_section = self._render_assertion_section(assertion)
        task_plan_section = self._render_task_plan_section(task_plan)
        screenshot_section = self._render_final_screenshot(report.get("final_screenshot_url"))
        terminal_log_section = self._render_autoglm_terminal_log(report.get("autoglm_terminal_log_url"))

        phase_sections = ""
        for phase_name, events in phases.items():
            if not events:
                continue
            phase_rows = ""
            for event in events[:20]:
                msg = escape(str(event.get("message") or event.get("result_note") or ""))[:200]
                phase_rows += f"<tr><td>{escape(str(event.get('event') or event.get('type') or '-'))}</td><td>{msg}</td></tr>"
            phase_sections += f"""
            <h3>{phase_name}</h3>
            <table><thead><tr><th>Event</th><th>Message</th></tr></thead><tbody>{phase_rows}</tbody></table>
            """

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>Execution Report - {escape(str(report.get('case_name') or report.get('execution_id')))}</title>
    <style>{HTML_REPORT_STYLE}</style>
</head>
<body>
    <div class="container">
        <h1>Execution Report</h1>
        <div class="summary">
            <div class="stat"><div class="stat-value">{escape(str(report.get('execution_id') or '-'))}</div><div class="stat-label">Execution ID</div></div>
            <div class="stat"><div class="stat-value {result_class}">{escape(str(report.get('final_result') or '-'))}</div><div class="stat-label">Result</div></div>
            <div class="stat"><div class="stat-value">{escape(str(report.get('duration_ms') or 0))}ms</div><div class="stat-label">Duration</div></div>
        </div>
        <div class="note"><strong>Case:</strong> {escape(str(report.get('case_name') or '-'))}</div>
        <div class="note"><strong>Note:</strong> {escape(str(report.get('result_note') or '-'))}</div>
        {assertion_section}
        {task_plan_section}
        {terminal_log_section}
        {screenshot_section}
        {phase_sections}
        <div class="footer"><p>Generated by Mobile-AI-TestOps</p></div>
    </div>
</body>
</html>"""

    @staticmethod
    def _render_assertion_section(assertion: dict[str, Any]) -> str:
        if not assertion:
            return ""
        verdict = str(assertion.get("verdict") or "uncertain")
        verdict_class = f"assertion-{verdict}" if verdict in {"passed", "failed", "uncertain"} else "assertion-uncertain"
        confidence = assertion.get("confidence")
        confidence_text = "-"
        if isinstance(confidence, (int, float)):
            confidence_text = f"{round(float(confidence) * 100)}%"
        evidence_html = ReportWriter._render_list(assertion.get("evidence"))
        failed_html = ReportWriter._render_list(assertion.get("failed_expectations"))
        review_required = "是" if assertion.get("review_required") else "否"
        review_status = escape(str(assertion.get("review_status") or "-"))
        recommendation = escape(str(assertion.get("review_recommendation") or ""))
        failed_block = f"<h4>未满足预期</h4>{failed_html}" if failed_html else ""
        recommendation_block = f"<p><strong>复核建议：</strong>{recommendation}</p>" if recommendation else ""
        return f"""
        <div class="section">
            <h2>AI断言结果</h2>
            <div class="assertion-box {escape(verdict_class)}">
                <div class="assertion-meta">
                    <span class="pill">verdict: {escape(verdict)}</span>
                    <span class="pill">置信度: {confidence_text}</span>
                    <span class="pill">来源: {escape(str(assertion.get('source') or '-'))}</span>
                    <span class="pill">需要复核: {review_required}</span>
                    <span class="pill">复核状态: {review_status}</span>
                </div>
                <p><strong>分析理由：</strong>{escape(str(assertion.get('reason') or '-'))}</p>
                <h4>证据列表</h4>
                {evidence_html or '<p>暂无证据</p>'}
                {failed_block}
                {recommendation_block}
            </div>
        </div>
        """

    @staticmethod
    def _render_task_plan_section(task_plan: dict[str, Any]) -> str:
        if not task_plan:
            return ""
        criteria = ReportWriter._render_list(task_plan.get("success_criteria"))
        guardrails = ReportWriter._render_list(task_plan.get("guardrails"))
        return f"""
        <div class="section">
            <h2>任务书</h2>
            <div class="task-plan">
                <p><strong>来源：</strong>{escape(str(task_plan.get('source') or '-'))}</p>
                <p><strong>编排模型：</strong>{escape(str(task_plan.get('planner_provider') or '-'))} / {escape(str(task_plan.get('planner_model') or '-'))}</p>
                <p><strong>目标类型：</strong>{escape(str(task_plan.get('target_type') or '-'))}</p>
                <p><strong>目标应用：</strong>{escape(str(task_plan.get('target_app') or '-'))}</p>
                <p><strong>统一任务：</strong>{escape(str(task_plan.get('unified_goal') or '-'))}</p>
                <h4>完成标准</h4>
                {criteria or '<p>未提供</p>'}
                <h4>执行约束</h4>
                {guardrails or '<p>未提供</p>'}
            </div>
        </div>
        """

    @staticmethod
    def _render_final_screenshot(url: object) -> str:
        if not url:
            return ""
        safe_url = escape(str(url), quote=True)
        return f"""
        <div class="section">
            <h2>终态截图</h2>
            <a class="screenshot-link" href="{safe_url}" target="_blank" rel="noreferrer">{safe_url}</a>
        </div>
        """

    @staticmethod
    def _render_autoglm_terminal_log(url: object) -> str:
        if not url:
            return ""
        safe_url = escape(str(url), quote=True)
        return f"""
        <div class="section">
            <h2>AutoGLM终端日志</h2>
            <a class="screenshot-link" href="{safe_url}" target="_blank" rel="noreferrer">{safe_url}</a>
        </div>
        """

    @staticmethod
    def _render_list(items: object) -> str:
        if not isinstance(items, list):
            return ""
        values = [str(item).strip() for item in items if str(item).strip()]
        if not values:
            return ""
        return "<ul class=\"evidence-list\">" + "".join(f"<li>{escape(item)}</li>" for item in values) + "</ul>"

    def _generate_plan_html(self, summary: dict[str, Any]) -> str:
        """Generate HTML for a plan summary report."""
        results = summary.get("results", [])
        error_stats = summary.get("error_category_statistics", {})

        case_rows = ""
        for item in results:
            result_class = "tag-pass" if item.get("run_result") == "passed" else ("tag-fail" if item.get("run_result") == "failed" else "tag-uncertain")
            assertion = item.get("assertion_result") if isinstance(item.get("assertion_result"), dict) else {}
            confidence = assertion.get("confidence") if assertion else None
            confidence_text = f"{round(float(confidence) * 100)}%" if isinstance(confidence, (int, float)) else "-"
            assertion_text = f"{assertion.get('verdict', '-')}/{confidence_text}" if assertion else "-"
            case_rows += f"""<tr>
                <td>{escape(str(item.get('case_id') or '-'))}</td>
                <td>{escape(str(item.get('result_note') or '-'))[:140]}</td>
                <td class="tag {result_class}">{escape(str(item.get('run_result') or '-'))}</td>
                <td>{escape(str(item.get('error_category') or '-'))}</td>
                <td>{escape(assertion_text)}</td>
            </tr>"""

        error_blocks = ""
        for category, count in error_stats.items():
            error_blocks += f"""<div class="stat"><div class="stat-value failed">{count}</div><div class="stat-label">{escape(str(category))}</div></div>"""

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>Plan Report - {escape(str(summary.get('plan_id') or '-'))}</title>
    <style>{HTML_REPORT_STYLE}</style>
</head>
<body>
    <div class="container">
        <h1>Plan Report</h1>
        <div class="summary">
            <div class="stat"><div class="stat-value">{summary.get('total_cases', 0)}</div><div class="stat-label">Total</div></div>
            <div class="stat"><div class="stat-value passed">{summary.get('passed', 0)}</div><div class="stat-label">Passed</div></div>
            <div class="stat"><div class="stat-value failed">{summary.get('failed', 0)}</div><div class="stat-label">Failed</div></div>
            <div class="stat"><div class="stat-value uncertain">{summary.get('uncertain', 0)}</div><div class="stat-label">Uncertain</div></div>
            <div class="stat"><div class="stat-value uncertain">{summary.get('review_required', 0)}</div><div class="stat-label">Review Required</div></div>
            <div class="stat"><div class="stat-value">{summary.get('pass_rate', 0)}%</div><div class="stat-label">Pass Rate</div></div>
        </div>
        <h2>Error Categories</h2>
        <div class="summary">{error_blocks}</div>
        <h2>Case Results</h2>
        <table><thead><tr><th>Case ID</th><th>Note</th><th>Result</th><th>Error</th><th>Assertion</th></tr></thead><tbody>{case_rows}</tbody></table>
        <div class="footer"><p>Generated by Mobile-AI-TestOps at {escape(str(summary.get('ended_at') or '-'))}</p></div>
    </div>
</body>
</html>"""
