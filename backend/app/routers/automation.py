"""Automation API — locator preview, assertion validation, image compare, and run management."""
from __future__ import annotations
import os
import uuid
from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel
from typing import List, Dict, Any

from app.automation.assertions.engine import AssertionEngine, AssertionResult, _find_template_in_screenshot
from app.automation.autoglm.case_planner import CasePlanner, CaseTaskPlan, Checkpoint
from app.automation.autoglm.checkpoint_validator import CheckpointValidator
from app.automation.core.models import AssertionSpec, LocatorChain
from app.automation.drivers.android_driver import AndroidDriver
from app.automation.drivers.ios_driver import IOSDriver
from app.automation.locators.resolver import LocatorResolver, ResolveResult
from app.automation.core.driver import DeviceDriver

router = APIRouter(prefix="/api/automation", tags=["automation"])

_run_store: dict[str, dict] = {}

# Template storage directory
_TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "static", "templates")


def _create_driver(udid: str, platform: str, wda_url: str | None = None) -> DeviceDriver:
    if platform == "ios":
        return IOSDriver(udid=udid, wda_url=wda_url or "http://localhost:8100")
    return AndroidDriver(udid=udid)


@router.get("/health")
def automation_health():
    return {"status": "ok"}


class CreateRunRequest(BaseModel):
    udid: str
    platform: str
    steps: List[Dict[str, Any]] = []


@router.post("/runs")
def create_run(request: CreateRunRequest = Body(...)):
    run_id = str(uuid.uuid4())
    _run_store[run_id] = {"udid": request.udid, "platform": request.platform, "steps": request.steps, "status": "created"}
    return {"run_id": run_id, "status": "created"}


@router.get("/runs/{run_id}")
def get_run(run_id: str):
    if run_id not in _run_store:
        raise HTTPException(status_code=404, detail="Run not found")
    return _run_store[run_id]


@router.post("/locators/preview")
def locator_preview(udid: str, platform: str, locator_chain: dict, wda_url: str | None = None):
    driver = _create_driver(udid, platform, wda_url)
    chain = LocatorChain.from_dict(locator_chain)
    resolver = LocatorResolver(driver)
    result = resolver.resolve(chain)
    d = {"found": result.found, "attempted_count": result.attempted_count}
    if result.resolved_locator is not None:
        d["resolved_locator"] = result.resolved_locator.to_dict()
    if result.coordinates is not None:
        d["coordinates"] = list(result.coordinates)
    return d


@router.post("/assertions/validate")
def assertion_validate(udid: str, platform: str, assertion: dict, wda_url: str | None = None):
    driver = _create_driver(udid, platform, wda_url)
    spec = AssertionSpec.from_dict(assertion)
    engine = AssertionEngine(driver)
    result = engine.evaluate(spec)
    return {"passed": result.passed, "assertion_type": result.assertion_type.value, "message": result.message}


class ImageCompareRequest(BaseModel):
    image_path: str
    threshold: float = 0.9


@router.post("/image/compare")
def image_compare(udid: str, platform: str, request: ImageCompareRequest, wda_url: str | None = None):
    driver = _create_driver(udid, platform, wda_url)
    match = _find_template_in_screenshot(driver, request.image_path)
    return {
        "matched": match.score >= request.threshold,
        "score": match.score,
        "location": list(match.location) if match.location else None,
        "threshold": request.threshold,
    }


@router.post("/image/capture-template")
def image_capture_template(udid: str, platform: str, name: str | None = None, wda_url: str | None = None):
    driver = _create_driver(udid, platform, wda_url)
    screenshot_bytes = driver.screenshot()
    template_name = name or f"template_{uuid.uuid4().hex[:8]}.png"
    template_dir = _TEMPLATE_DIR
    os.makedirs(template_dir, exist_ok=True)
    template_path = os.path.join(template_dir, template_name)
    with open(template_path, "wb") as f:
        f.write(screenshot_bytes)
    return {"template_path": template_path, "template_name": template_name}


class AutoGLMPlanRequest(BaseModel):
    case_id: int
    target_app: str
    platform: str
    launch_app_id: str = ""
    preconditions: list[str] = []
    steps: list[str] = []
    expected_result: str = ""


@router.post("/autoglm/plan")
def autoglm_plan(request: AutoGLMPlanRequest):
    planner = CasePlanner()
    plan = planner.build(
        case_id=request.case_id,
        target_app=request.target_app,
        platform=request.platform,
        launch_app_id=request.launch_app_id,
        preconditions=request.preconditions,
        steps=request.steps,
        expected_result=request.expected_result,
    )
    return plan.to_dict()


@router.post("/autoglm/validate-checkpoint")
def autoglm_validate_checkpoint(udid: str, platform: str, checkpoint: dict, wda_url: str | None = None):
    driver = _create_driver(udid, platform, wda_url)
    cp = Checkpoint(
        id=checkpoint.get("id", "cp_1"),
        goal=checkpoint.get("goal", ""),
        instructions=checkpoint.get("instructions", []),
        success_signals=checkpoint.get("success_signals", []),
        failure_signals=checkpoint.get("failure_signals", []),
        takeover_signals=checkpoint.get("takeover_signals", []),
        allowed_actions=checkpoint.get("allowed_actions", ["tap", "swipe", "input", "back", "home", "wait"]),
        max_steps=checkpoint.get("max_steps", 12),
    )
    source_xml = driver.dump_source()
    app_info = driver.current_app()
    foreground_app = app_info.get("package", "") or app_info.get("bundle_id", "")
    validator = CheckpointValidator()
    result = validator.validate(cp, source_xml=source_xml, foreground_app=foreground_app)
    return {"passed": result.passed, "failed": result.failed, "message": result.message}
