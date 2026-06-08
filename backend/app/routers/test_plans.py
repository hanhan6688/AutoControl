from __future__ import annotations

import tempfile
from html import escape
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.error_handler import handle_service_errors
from app.models import ImportedTestCase, TestCaseExecution, TestCaseFolder, TestPlanProject
from app.schemas import (
    ALLOWED_TARGET_APPS,
    BatchRunResponse,
    ImportedTestCaseBatchUpdateRequest,
    ImportedTestCaseCreateRequest,
    ImportedTestCaseResponse,
    ImportResultResponse,
    MessageResponse,
    RequirementAnalysisResponse,
    SkippedRowResponse,
    TestCaseExecutionResponse,
    TestCaseRunRequest,
    TestPlanListItem,
    TestPlanProjectResponse,
)
from app.services.execution_cancel_registry import execution_cancel_registry
from app.services.requirement_analysis_service import RequirementAnalysisError, RequirementAnalysisService
from app.services.report_writer import ReportWriter
from app.services.test_execution_service import TestExecutionError, TestExecutionService
from app.services.test_plan_import_service import TestPlanImportError, TestPlanImportService
from app.utils import utc_iso

router = APIRouter(prefix="/api/test-plans", tags=["test-plans"])

# Error handlers
handle_import_errors = handle_service_errors({TestPlanImportError: 400})
handle_execution_errors = handle_service_errors({TestExecutionError: 404})
handle_req_analysis_errors = handle_service_errors({RequirementAnalysisError: 400})


@router.get("", response_model=list[TestPlanListItem])
def list_test_plans(db: Session = Depends(get_db)) -> list[TestPlanProject]:
    return db.query(TestPlanProject).order_by(TestPlanProject.imported_at.desc()).all()


@router.get("/{plan_id}", response_model=TestPlanProjectResponse)
def get_test_plan(plan_id: int, db: Session = Depends(get_db)) -> TestPlanProject:
    plan = (
        db.query(TestPlanProject)
        .options(selectinload(TestPlanProject.cases), selectinload(TestPlanProject.folders))
        .filter(TestPlanProject.id == plan_id)
        .first()
    )
    if not plan:
        raise HTTPException(status_code=404, detail="测试计划不存在")
    # Populate folder_name for each case
    for case in plan.cases:
        case.folder_name = case.folder.name if case.folder else None
    return plan


@router.delete("/{plan_id}", response_model=MessageResponse)
def delete_test_plan(plan_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    plan = db.get(TestPlanProject, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="测试计划不存在")
    db.delete(plan)
    db.commit()
    return {"message": "测试计划已删除"}


@router.post("/import", response_model=ImportResultResponse)
async def import_test_plan(
    project_name: str = Form(...),
    file: UploadFile = File(...),
    check_duplicates: bool = Form(True),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """导入AutoGLM文件，返回详细的导入结果"""
    suffix = Path(file.filename or "test-cases.xlsx").suffix or ".xlsx"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
        temp_path = Path(temp_file.name)
        temp_file.write(await file.read())

    try:
        result = TestPlanImportService(db).import_file(
            temp_path,
            project_name=project_name,
            source_filename=file.filename,
            check_duplicates=check_duplicates,
        )

        # 构建响应
        return {
            "id": result.plan.id,
            "name": result.plan.name,
            "source_filename": result.plan.source_filename,
            "total_cases": result.plan.total_cases,
            "imported_at": result.plan.imported_at,
            "cases": [
                ImportedTestCaseResponse.model_validate(case) for case in result.plan.cases
            ],
            "import_summary": result.to_summary(),
            "skipped_rows": [
                SkippedRowResponse(
                    row_number=row.row_number,
                    reason=row.reason,
                    raw_data=row.raw_data,
                )
                for row in result.skipped_rows[:50]  # 最多返回50条跳过记录
            ],
        }
    except TestPlanImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        temp_path.unlink(missing_ok=True)


@router.post("/generate-from-requirement", response_model=RequirementAnalysisResponse)
async def generate_from_requirement(
    project_name: str = Form(..., description="项目名称"),
    target_app: str = Form(..., description="目标应用"),
    file: UploadFile = File(..., description="需求文档（支持 txt/pdf/docx/xlsx/csv）"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """上传产品需求文档，AI 自动生成测试用例并填入系统。"""
    if target_app not in ALLOWED_TARGET_APPS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的目标应用: {target_app}，可选值: {', '.join(ALLOWED_TARGET_APPS)}",
        )

    suffix = Path(file.filename or "unknown").suffix.lower()
    supported = {".txt", ".pdf", ".docx", ".xlsx", ".xlsm", ".csv"}
    if suffix not in supported:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文档格式: {suffix}，支持: {', '.join(sorted(supported))}",
        )

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read())
        temp_path = Path(tmp.name)

    try:
        result = RequirementAnalysisService(db).analyze_requirement(
            file_path=temp_path,
            project_name=project_name,
            target_app=target_app,
            source_filename=file.filename,
        )

        # Reload cases with proper ordering
        cases = (
            db.query(ImportedTestCase)
            .filter(ImportedTestCase.plan_id == result.plan.id)
            .order_by(ImportedTestCase.sequence)
            .all()
        )

        return {
            "id": result.plan.id,
            "name": result.plan.name,
            "source_filename": result.plan.source_filename,
            "total_cases": result.plan.total_cases,
            "imported_at": result.plan.imported_at,
            "cases": [ImportedTestCaseResponse.model_validate(case) for case in cases],
            "generation_summary": {
                "raw_text_length": result.raw_text_length,
                "initial_case_count": result.initial_case_count,
                "refined_case_count": result.refined_case_count,
                "final_case_count": result.generated_count,
            },
        }
    except RequirementAnalysisError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        temp_path.unlink(missing_ok=True)


@router.post("/{plan_id}/cases", response_model=ImportedTestCaseResponse)
def create_manual_test_case(
    plan_id: int,
    payload: ImportedTestCaseCreateRequest,
    db: Session = Depends(get_db),
) -> ImportedTestCase:
    plan = db.get(TestPlanProject, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="测试计划不存在")

    next_sequence = (
        db.query(func.max(ImportedTestCase.sequence))
        .filter(ImportedTestCase.plan_id == plan_id)
        .scalar()
        or 0
    ) + 1

    case = ImportedTestCase(
        plan_id=plan_id,
        folder_id=payload.folder_id if payload.folder_id else None,
        sequence=next_sequence,
        system_name=payload.system_name.strip() if payload.system_name else None,
        module=payload.module.strip() if payload.module else None,
        case_name=payload.case_name,
        precondition=payload.precondition.strip() if payload.precondition else None,
        steps=payload.steps,
        expected_result=payload.expected_result,
        requirement_id=payload.requirement_id.strip() if payload.requirement_id else None,
        case_type=payload.case_type.strip() if payload.case_type else None,
        priority=payload.priority.strip() if payload.priority else None,
        target_app=payload.target_app.strip() if payload.target_app else None,
        test_module=payload.test_module.strip() if payload.test_module else None,
        run_count=0,
        latest_result="pending",
        latest_result_note="",
    )
    db.add(case)
    plan.total_cases = next_sequence
    db.commit()
    db.refresh(case)
    return case


@router.delete("/cases/{case_id}", response_model=MessageResponse)
def delete_test_case(case_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    case = db.get(ImportedTestCase, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="测试用例不存在")
    plan = db.get(TestPlanProject, case.plan_id)
    db.delete(case)
    if plan:
        plan.total_cases = max(0, plan.total_cases - 1)
    db.commit()
    return {"message": "测试用例已删除"}


@router.post("/{plan_id}/cases/batch-update")
def batch_update_cases(
    plan_id: int,
    payload: ImportedTestCaseBatchUpdateRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Batch update system_name, module, target_app, test_module for selected cases.
    Empty string '' means clear the field (set to None).
    """
    cases = (
        db.query(ImportedTestCase)
        .filter(ImportedTestCase.plan_id == plan_id, ImportedTestCase.id.in_(payload.case_ids))
        .all()
    )
    if not cases:
        raise HTTPException(status_code=404, detail="未找到匹配的用例")
    updates = payload.model_dump(exclude={"case_ids"}, exclude_none=True)
    # Convert empty strings to None for database storage
    for key, value in list(updates.items()):
        if isinstance(value, str):
            value = value.strip()
        if value == "":
            updates[key] = None
        else:
            updates[key] = value
    for case in cases:
        for key, value in updates.items():
            setattr(case, key, value)
    db.commit()
    return {"updated": len(cases)}


@router.post("/cases/{case_id}/run", response_model=TestCaseExecutionResponse)
@handle_execution_errors
def run_test_case(
    case_id: int,
    payload: TestCaseRunRequest | None = None,
    db: Session = Depends(get_db),
) -> TestCaseExecutionResponse:
    return TestExecutionService(db).execute_case(
        case_id,
        device_udid=(payload.device_udid if payload else None),
        device_platform=(payload.device_platform if payload else None),
        client_run_id=(payload.client_run_id if payload else None),
    )


@router.post("/cases/{case_id}/run/stream")
@handle_execution_errors
def stream_test_case_run(
    case_id: int,
    payload: TestCaseRunRequest | None = None,
    db: Session = Depends(get_db),
) -> StreamingResponse:
    stream = TestExecutionService(db).iter_case_event_lines(
        case_id,
        device_udid=(payload.device_udid if payload else None),
        device_platform=(payload.device_platform if payload else None),
        client_run_id=(payload.client_run_id if payload else None),
    )
    return StreamingResponse(stream, media_type="application/x-ndjson")


@router.post("/{plan_id}/run", response_model=BatchRunResponse)
@handle_execution_errors
def run_test_plan(
    plan_id: int,
    payload: TestCaseRunRequest | None = None,
    db: Session = Depends(get_db),
) -> BatchRunResponse:
    executions = TestExecutionService(db).execute_plan(
        plan_id,
        device_udid=(payload.device_udid if payload else None),
        device_platform=(payload.device_platform if payload else None),
        client_run_id=(payload.client_run_id if payload else None),
    )

    return BatchRunResponse(
        plan_id=plan_id,
        total_cases=len(executions),
        executions=[TestCaseExecutionResponse.model_validate(execution) for execution in executions],
    )


@router.post("/{plan_id}/run/stream")
@handle_execution_errors
def stream_test_plan_run(
    plan_id: int,
    payload: TestCaseRunRequest | None = None,
    db: Session = Depends(get_db),
) -> StreamingResponse:
    stream = TestExecutionService(db).iter_plan_event_lines(
        plan_id,
        device_udid=(payload.device_udid if payload else None),
        device_platform=(payload.device_platform if payload else None),
        client_run_id=(payload.client_run_id if payload else None),
    )
    return StreamingResponse(stream, media_type="application/x-ndjson")


@router.post("/runs/{client_run_id}/cancel")
def cancel_test_run(client_run_id: str) -> dict[str, object]:
    killed_process = execution_cancel_registry.cancel(client_run_id)
    return {
        "client_run_id": client_run_id,
        "cancelled": True,
        "killed_process": killed_process,
    }


@router.post("/runs/{client_run_id}/resume")
def resume_test_run(client_run_id: str) -> dict[str, object]:
    resumed = execution_cancel_registry.send_input(client_run_id, "\n")
    if not resumed:
        raise HTTPException(status_code=404, detail="没有找到可继续的执行进程")
    return {
        "client_run_id": client_run_id,
        "resumed": True,
    }


@router.get("/{plan_id}/report")
def get_test_plan_report(
    plan_id: int,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get comprehensive test plan report with error statistics."""
    plan = db.get(TestPlanProject, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="测试计划不存在")

    # Get all executions for this plan
    executions = (
        db.query(TestCaseExecution)
        .filter(TestCaseExecution.plan_id == plan_id)
        .order_by(TestCaseExecution.run_index)
        .all()
    )

    # Calculate statistics
    total_cases = len(plan.cases)
    total_runs = len(executions)
    passed_count = sum(1 for e in executions if e.run_result == "passed")
    failed_count = sum(1 for e in executions if e.run_result == "failed")
    uncertain_count = sum(1 for e in executions if e.run_result == "uncertain")

    # Error category breakdown
    error_categories: dict[str, int] = {}
    assertion_by_execution: dict[int, dict[str, Any] | None] = {}
    review_required_count = 0
    for execution in executions:
        if execution.error_category:
            error_categories[execution.error_category] = error_categories.get(execution.error_category, 0) + 1
        assertion = TestExecutionService._latest_assertion_result(
            TestExecutionService.load_external_action_trace(execution.action_trace or [])
        )
        assertion_by_execution[execution.id] = assertion
        if assertion and assertion.get("review_required"):
            review_required_count += 1

    # Build case results
    case_results: list[dict[str, Any]] = []
    for case in plan.cases:
        case_executions = [e for e in executions if e.case_id == case.id]
        latest_execution = case_executions[-1] if case_executions else None

        case_results.append({
            "case_id": case.id,
            "sequence": case.sequence,
            "case_name": case.case_name,
            "target_app": case.target_app,
            "test_module": case.test_module,
            "run_count": case.run_count,
            "latest_result": case.latest_result,
            "latest_result_note": case.latest_result_note,
            "latest_error_category": latest_execution.error_category if latest_execution else None,
            "latest_duration_ms": latest_execution.duration_ms if latest_execution else None,
            "latest_execution_id": latest_execution.id if latest_execution else None,
            "latest_assertion": assertion_by_execution.get(latest_execution.id) if latest_execution else None,
        })

    return {
        "plan_id": plan.id,
        "plan_name": plan.name,
        "source_filename": plan.source_filename,
        "imported_at": plan.imported_at.isoformat(),
        "summary": {
            "total_cases": total_cases,
            "total_runs": total_runs,
            "passed": passed_count,
            "failed": failed_count,
            "uncertain": uncertain_count,
            "review_required": review_required_count,
            "pass_rate": round(passed_count / total_runs * 100, 2) if total_runs > 0 else 0,
            "error_categories": error_categories,
        },
        "cases": case_results,
        "generated_at": utc_iso(),
    }


@router.get("/executions/{execution_id}/report")
def get_execution_detail_report(
    execution_id: int,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get detailed report for a single test execution."""
    execution = db.get(TestCaseExecution, execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="执行记录不存在")

    case = db.get(ImportedTestCase, execution.case_id)

    action_trace = TestExecutionService.load_external_action_trace(execution.action_trace or [])

    # Extract screenshots from action_trace
    screenshots: list[dict[str, Any]] = []
    action_summary: list[dict[str, Any]] = []
    error_details: list[dict[str, Any]] = []
    autoglm_terminal_logs: list[dict[str, Any]] = []
    assertion_result: dict[str, Any] | None = None
    case_task_plan: dict[str, Any] | None = None

    # Build a screenshot lookup by step number for matching with actions.
    # Keep the FIRST screenshot per step (from the STEP_SCREENSHOT_SAVED
    # mechanism) so multiple emits don't shadow each other.
    screenshot_by_step: dict[int, dict[str, Any]] = {}
    for entry in action_trace:
        if entry.get("type") == "step_screenshot":
            step_num = entry.get("step")
            if step_num is None:
                continue
            screenshot_by_step.setdefault(step_num, {
                "url": entry.get("screenshot_url"),
                "current_app": entry.get("current_app"),
                "timestamp": entry.get("timestamp"),
            })

    for entry in action_trace:
        if entry.get("type") in {"step_screenshot", "final_screenshot"}:
            screenshots.append({
                "step": entry.get("step"),
                "url": entry.get("screenshot_url"),
                "current_app": entry.get("current_app"),
                "timestamp": entry.get("timestamp"),
                "kind": "final" if entry.get("type") == "final_screenshot" else "step",
            })
        elif entry.get("type") == "action_executed":
            step_num = entry.get("step")
            # Get matching screenshot for this action
            screenshot_info = screenshot_by_step.get(step_num, {})
            action_summary.append({
                "step": step_num,
                "action_type": entry.get("action_type"),
                "success": entry.get("success"),
                "message": entry.get("message"),
                "timestamp": entry.get("timestamp"),
                "screenshot_url": screenshot_info.get("url"),
                "current_app": screenshot_info.get("current_app"),
                "action_params": entry.get("action_params"),
            })
        elif entry.get("type") == "error":
            error_details.append({
                "error": entry.get("error"),
                "exception_type": entry.get("exception_type"),
            })
        elif entry.get("type") == "result_assertion":
            assertion = entry.get("assertion")
            assertion_result = assertion if isinstance(assertion, dict) else None
        elif entry.get("type") == "case_task_plan":
            task_plan = entry.get("task_plan")
            case_task_plan = task_plan if isinstance(task_plan, dict) else None
        elif entry.get("type") == "error_summary":
            error_details.append({
                "category": entry.get("category"),
                "details": entry.get("details"),
            })
        elif entry.get("type") == "autoglm_terminal_log":
            autoglm_terminal_logs.append({
                "url": entry.get("terminal_log_url"),
                "path": entry.get("terminal_log_path"),
                "timestamp": entry.get("timestamp"),
            })

    # Stable sort by step number so the UI shows 步骤 1 → 2 → 3 … in order
    # regardless of any event reordering inside action_trace.
    def _step_key(item: dict[str, Any]) -> tuple[int, int]:
        step_val = item.get("step")
        if isinstance(step_val, int):
            # step_screenshot entries come before final_screenshot
            return (0, step_val) if item.get("kind") == "step" else (1, 0)
        return (2, 0)

    action_summary.sort(key=lambda a: (a.get("step") if isinstance(a.get("step"), int) else 10**9))
    screenshots.sort(key=_step_key)

    return {
        "execution_id": execution.id,
        "case_id": execution.case_id,
        "case_name": case.case_name if case else None,
        "run_index": execution.run_index,
        "device_udid": execution.device_udid,
        "trace_id": execution.trace_id,
        "result": execution.run_result,
        "result_note": execution.result_note,
        "error_category": execution.error_category,
        "assertion_result": assertion_result,
        "case_task_plan": case_task_plan,
        "duration_ms": execution.duration_ms,
        "started_at": execution.started_at.isoformat() if execution.started_at else None,
        "ended_at": execution.ended_at.isoformat() if execution.ended_at else None,
        "screenshots": screenshots,
        "action_summary": action_summary,
        "error_details": error_details,
        "autoglm_terminal_logs": autoglm_terminal_logs,
        "full_trace": action_trace,
    }


@router.get("/executions/{execution_id}/detail")
def get_execution_detail(
    execution_id: int,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return get_execution_detail_report(execution_id, db)


@router.get("/executions/{execution_id}/export")
def export_execution_detail_report(
    execution_id: int,
    format: str = "json",
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Export a single test execution report as JSON or HTML."""
    report = get_execution_detail_report(execution_id, db)

    if format == "html":
        html_content = _generate_execution_html_report(report)
        return JSONResponse(
            content={"html": html_content, "filename": f"execution_report_{execution_id}.html"},
        )

    if format != "json":
        raise HTTPException(status_code=400, detail="仅支持 json 或 html 格式")

    return JSONResponse(
        content={"report": report, "filename": f"execution_report_{execution_id}.json"},
    )


@router.get("/{plan_id}/export")
def export_test_plan_report(
    plan_id: int,
    format: str = "json",
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Export test plan report as JSON or HTML."""
    report = get_test_plan_report(plan_id, db)

    if format == "html":
        html_content = _generate_html_report(report)
        return JSONResponse(
            content={"html": html_content, "filename": f"test_report_{plan_id}.html"},
        )

    if format != "json":
        raise HTTPException(status_code=400, detail="仅支持 json 或 html 格式")

    return JSONResponse(
        content={"report": report, "filename": f"test_report_{plan_id}.json"},
    )


def _generate_html_report(report: dict[str, Any]) -> str:
    """Generate HTML report from report data."""
    summary = report.get("summary", {})
    cases = report.get("cases", [])

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>测试报告 - {report.get("plan_name", "Unknown")}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 40px; background: #f5f5f5; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
        h1 {{ color: #333; border-bottom: 2px solid #409eff; padding-bottom: 10px; }}
        h2 {{ color: #666; margin-top: 30px; }}
        .summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 20px; margin: 20px 0; }}
        .stat {{ background: #f8f9fa; padding: 20px; border-radius: 8px; text-align: center; }}
        .stat-value {{ font-size: 32px; font-weight: bold; color: #409eff; }}
        .stat-label {{ color: #666; margin-top: 5px; }}
        .passed {{ color: #67c23a; }}
        .failed {{ color: #f56c6c; }}
        .uncertain {{ color: #e6a23c; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #eee; }}
        th {{ background: #f8f9fa; font-weight: 600; }}
        .tag {{ padding: 4px 8px; border-radius: 4px; font-size: 12px; }}
        .tag-pass {{ background: #e1f3d8; color: #67c23a; }}
        .tag-fail {{ background: #fde2e2; color: #f56c6c; }}
        .tag-uncertain {{ background: #fdf6ec; color: #e6a23c; }}
        .tag-pending {{ background: #e9e9eb; color: #909399; }}
        .error-category {{ color: #f56c6c; font-size: 12px; }}
        .footer {{ margin-top: 40px; text-align: center; color: #999; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>测试报告</h1>
        <p><strong>项目：</strong>{report.get("plan_name", "Unknown")}</p>
        <p><strong>生成时间：</strong>{report.get("generated_at", "Unknown")}</p>

        <h2>执行统计</h2>
        <div class="summary">
            <div class="stat">
                <div class="stat-value">{summary.get("total_cases", 0)}</div>
                <div class="stat-label">用例总数</div>
            </div>
            <div class="stat">
                <div class="stat-value">{summary.get("total_runs", 0)}</div>
                <div class="stat-label">执行次数</div>
            </div>
            <div class="stat">
                <div class="stat-value passed">{summary.get("passed", 0)}</div>
                <div class="stat-label">通过</div>
            </div>
            <div class="stat">
                <div class="stat-value failed">{summary.get("failed", 0)}</div>
                <div class="stat-label">失败</div>
            </div>
            <div class="stat">
                <div class="stat-value uncertain">{summary.get("uncertain", 0)}</div>
                <div class="stat-label">待确认</div>
            </div>
            <div class="stat">
                <div class="stat-value uncertain">{summary.get("review_required", 0)}</div>
                <div class="stat-label">需人工复核</div>
            </div>
            <div class="stat">
                <div class="stat-value">{summary.get("pass_rate", 0)}%</div>
                <div class="stat-label">通过率</div>
            </div>
        </div>

        <h2>错误分类</h2>
        <div class="summary">
"""

    error_categories = summary.get("error_categories", {})
    for category, count in error_categories.items():
        html += f"""            <div class="stat">
                <div class="stat-value failed">{count}</div>
                <div class="stat-label">{escape(str(category))}</div>
            </div>
"""

    html += """        </div>

        <h2>用例详情</h2>
        <table>
            <thead>
                <tr>
                    <th>序号</th>
                    <th>用例名称</th>
                    <th>测试模块</th>
                    <th>执行次数</th>
                    <th>最新结果</th>
                    <th>错误类型</th>
                    <th>结果说明</th>
                </tr>
            </thead>
            <tbody>
"""

    for case in cases:
        latest_assertion = case.get("latest_assertion") or {}
        assertion_brief = ""
        if latest_assertion:
            confidence = latest_assertion.get("confidence")
            confidence_text = f"{round(float(confidence) * 100)}%" if isinstance(confidence, (int, float)) else "-"
            assertion_brief = f"{latest_assertion.get('verdict', '-')}/{confidence_text}"
        result_class = (
            "tag-pass"
            if case.get("latest_result") == "passed"
            else ("tag-fail" if case.get("latest_result") == "failed" else ("tag-uncertain" if case.get("latest_result") == "uncertain" else "tag-pending"))
        )
        html += f"""                <tr>
                    <td>{case.get("sequence", "")}</td>
                    <td>{escape(str(case.get("case_name", "")))}</td>
                    <td>{escape(str(case.get("test_module", "") or ""))}</td>
                    <td>{case.get("run_count", 0)}</td>
                    <td><span class="tag {result_class}">{case.get("latest_result", "pending")}</span></td>
                    <td class="error-category">{escape(str(case.get("latest_error_category", "") or ""))}</td>
                    <td>{escape(str(case.get("latest_result_note", "") or "")[:100])}<br>{escape(assertion_brief)}</td>
                </tr>
"""

    html += f"""            </tbody>
        </table>

        <div class="footer">
            <p>Generated by Mobile-AI-TestOps</p>
        </div>
    </div>
</body>
</html>"""

    return html


def _generate_execution_html_report(report: dict[str, Any]) -> str:
    """Generate HTML report for a single execution."""
    actions = report.get("action_summary", [])
    errors = report.get("error_details", [])
    assertion_html = ReportWriter._render_assertion_section(report.get("assertion_result") or {})
    task_plan_html = ReportWriter._render_task_plan_section(report.get("case_task_plan") or {})

    action_rows = ""
    for action in actions:
        status_class = "passed" if action.get("success") else "failed"
        action_rows += f"""                <tr>
                    <td>{action.get("step", "")}</td>
                    <td>{escape(str(action.get("action_type", "") or ""))}</td>
                    <td><span class="{status_class}">{'成功' if action.get("success") else '失败'}</span></td>
                    <td>{escape(str(action.get("message", "") or ""))}</td>
                </tr>
"""

    if not action_rows:
        action_rows = """                <tr><td colspan="4">暂无执行步骤</td></tr>
"""

    error_blocks = ""
    for item in errors:
        error_blocks += f"""            <pre>{escape(str(item.get("error") or item.get("details") or item))}</pre>
"""
    if not error_blocks:
        error_blocks = "            <p>无错误详情</p>\n"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>单用例执行报告 - {escape(str(report.get("case_name") or report.get("execution_id")))}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 40px; background: #f5f7fa; color: #303133; }}
        .container {{ max-width: 1000px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
        h1 {{ margin-top: 0; border-bottom: 2px solid #409eff; padding-bottom: 12px; }}
        .meta {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin: 20px 0; }}
        .meta div {{ background: #f5f7fa; border-radius: 6px; padding: 12px; }}
        .label {{ display: block; color: #909399; font-size: 12px; margin-bottom: 4px; }}
        .passed {{ color: #67c23a; font-weight: 600; }}
        .failed {{ color: #f56c6c; font-weight: 600; }}
        .uncertain {{ color: #e6a23c; font-weight: 600; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 16px; }}
        th, td {{ padding: 10px 12px; border-bottom: 1px solid #ebeef5; text-align: left; vertical-align: top; }}
        th {{ background: #f5f7fa; }}
        pre {{ white-space: pre-wrap; word-break: break-word; background: #fff5f5; border-radius: 6px; padding: 12px; }}
        .note {{ background: #fdf6ec; border-radius: 6px; padding: 12px; }}
        .section {{ margin-top: 24px; padding-top: 8px; }}
        .assertion-box {{ border: 1px solid #ebeef5; border-left: 4px solid #909399; border-radius: 8px; padding: 16px; background: #fff; }}
        .assertion-box.assertion-passed {{ border-left-color: #67c23a; }}
        .assertion-box.assertion-failed {{ border-left-color: #f56c6c; }}
        .assertion-box.assertion-uncertain {{ border-left-color: #e6a23c; }}
        .assertion-meta {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 10px 0; }}
        .pill {{ display: inline-block; padding: 4px 8px; border-radius: 4px; background: #f5f7fa; color: #606266; font-size: 12px; }}
        .evidence-list {{ margin: 8px 0 0; padding-left: 20px; }}
        .task-plan {{ background: #f8f9fa; border-radius: 8px; padding: 16px; }}
        .footer {{ margin-top: 32px; color: #909399; font-size: 12px; text-align: center; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>单用例执行报告</h1>
        <div class="meta">
            <div><span class="label">用例</span>{escape(str(report.get("case_name") or "-"))}</div>
            <div><span class="label">结果</span><span class="{'passed' if report.get("result") == "passed" else 'failed'}">{escape(str(report.get("result") or "-"))}</span></div>
            <div><span class="label">设备</span>{escape(str(report.get("device_udid") or "-"))}</div>
            <div><span class="label">耗时</span>{report.get("duration_ms") or "-"} ms</div>
            <div><span class="label">开始时间</span>{escape(str(report.get("started_at") or "-"))}</div>
            <div><span class="label">结束时间</span>{escape(str(report.get("ended_at") or "-"))}</div>
        </div>
        <h2>结果说明</h2>
        <div class="note">{escape(str(report.get("result_note") or "-"))}</div>
        {assertion_html}
        {task_plan_html}
        <h2>执行步骤</h2>
        <table>
            <thead><tr><th>步骤</th><th>动作</th><th>状态</th><th>说明</th></tr></thead>
            <tbody>
{action_rows}            </tbody>
        </table>
        <h2>错误详情</h2>
{error_blocks}
        <div class="footer">Generated by Mobile-AI-TestOps</div>
    </div>
</body>
</html>"""
