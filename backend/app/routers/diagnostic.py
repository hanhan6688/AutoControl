"""
Diagnostic API routes for debugging and monitoring.
"""
from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.services.artifact_cleanup_service import ArtifactCleanupService
from app.services.diagnostic_service import diagnostic
from app.services.project_health_service import ProjectHealthService
from app.services.xpath_health_service import check_xpath_pipeline

router = APIRouter(prefix="/api/diagnostic", tags=["diagnostic"])


class DiagnosticSummary(BaseModel):
    total_entries: int
    by_category: dict[str, int]
    by_level: dict[str, int]
    recent_errors: list[dict]
    execution_context: dict


class DiagnosticEntry(BaseModel):
    id: str
    timestamp: str
    category: str
    level: str
    source: str
    message: str
    details: dict
    duration_ms: int | None = None


class ArtifactCleanupRequest(BaseModel):
    max_age_days: int | None = None
    max_total_mb: int | None = None
    dry_run: bool = True


@router.get("/summary", response_model=DiagnosticSummary)
async def get_diagnostic_summary():
    """Get diagnostic summary."""
    return diagnostic.get_summary()


@router.get("/project-health")
async def get_project_health():
    """Get a read-only project health snapshot."""
    return ProjectHealthService().snapshot()


@router.post("/artifacts/cleanup")
async def cleanup_artifacts(request: ArtifactCleanupRequest):
    """Cleanup generated report/upload artifacts. Defaults to dry-run."""
    return ArtifactCleanupService().cleanup(
        max_age_days=request.max_age_days,
        max_total_mb=request.max_total_mb,
        dry_run=request.dry_run,
    )


@router.get("/entries", response_model=list[DiagnosticEntry])
async def get_diagnostic_entries(
    category: str | None = Query(None, description="Filter by category"),
    level: str | None = Query(None, description="Filter by level"),
    source: str | None = Query(None, description="Filter by source"),
    limit: int = Query(100, ge=1, le=1000, description="Max entries to return"),
):
    """Get diagnostic entries with optional filters."""
    return diagnostic.get_entries(
        category=category,
        level=level,
        source=source,
        limit=limit,
    )


@router.delete("/entries")
async def clear_diagnostic_entries():
    """Clear all diagnostic entries."""
    diagnostic.clear()
    return {"message": "Diagnostic entries cleared"}


@router.get("/errors")
async def get_diagnostic_errors(limit: int = Query(50, ge=1, le=200)):
    """Get recent error entries only."""
    return diagnostic.get_entries(level="error", limit=limit)


@router.get("/api-calls")
async def get_api_calls(limit: int = Query(100, ge=1, le=500)):
    """Get API call logs."""
    return diagnostic.get_entries(category="api", limit=limit)


@router.get("/adb-commands")
async def get_adb_commands(limit: int = Query(100, ge=1, le=500)):
    """Get ADB command logs."""
    return diagnostic.get_entries(category="adb", limit=limit)


@router.get("/actions")
async def get_action_logs(limit: int = Query(100, ge=1, le=500)):
    """Get phone agent action logs."""
    return diagnostic.get_entries(category="action", limit=limit)


@router.get("/errors/by-execution")
async def get_errors_by_execution():
    """Get errors grouped by execution context."""
    return diagnostic.get_errors_by_execution()


@router.get("/errors/execution/{execution_id}")
async def get_execution_errors(execution_id: str):
    """Get all errors for a specific execution."""
    return diagnostic.get_execution_errors(execution_id)


@router.get("/xpath-health")
async def get_xpath_health():
    """Check XPath recording pipeline health (parse, locate, u2/wda connectivity)."""
    result = check_xpath_pipeline()
    return {
        "status": result.status,
        "android_parse_ok": result.android_parse_ok,
        "android_locate_ok": result.android_locate_ok,
        "ios_parse_ok": result.ios_parse_ok,
        "ios_locate_ok": result.ios_locate_ok,
        "u2_connected": result.u2_connected,
        "wda_connected": result.wda_connected,
        "duration_ms": result.duration_ms,
        "errors": result.errors,
    }
