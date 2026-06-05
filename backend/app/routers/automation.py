"""Automation API — locator preview, assertion validation, and run management."""
from __future__ import annotations
from fastapi import APIRouter, HTTPException
from app.automation.assertions.engine import AssertionEngine, AssertionResult
from app.automation.core.models import AssertionSpec, LocatorChain
from app.automation.drivers.android_driver import AndroidDriver
from app.automation.drivers.ios_driver import IOSDriver
from app.automation.locators.resolver import LocatorResolver, ResolveResult
from app.automation.core.driver import DeviceDriver
import uuid

router = APIRouter(prefix="/api/automation", tags=["automation"])

_run_store: dict[str, dict] = {}

def _create_driver(udid: str, platform: str, wda_url: str | None = None) -> DeviceDriver:
    if platform == "ios":
        return IOSDriver(udid=udid, wda_url=wda_url or "http://localhost:8100")
    return AndroidDriver(udid=udid)

@router.get("/health")
def automation_health():
    return {"status": "ok"}

from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel
from typing import List, Dict, Any

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
