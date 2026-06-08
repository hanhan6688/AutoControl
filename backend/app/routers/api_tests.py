from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from time import perf_counter

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import ApiTestCase, ApiTestExecution, ApiTestSuite
from app.schemas import (
    ApiTestCaseCreateRequest,
    ApiTestCaseResponse,
    ApiTestCaseUpdateRequest,
    ApiTestExecutionResponse,
    ApiTestSuiteCreateRequest,
    ApiTestSuiteResponse,
    ApiTestSuiteRunResponse,
    ApiTestSuiteUpdateRequest,
)
from app.services.api_test_service import ApiTestService
from app.utils import utc_iso

router = APIRouter(prefix="/api/api-tests", tags=["api-tests"])


@router.get("/suites", response_model=list[ApiTestSuiteResponse])
def list_api_test_suites(db: Session = Depends(get_db)) -> list[ApiTestSuite]:
    return db.query(ApiTestSuite).order_by(ApiTestSuite.created_at.desc()).all()


@router.post("/suites", response_model=ApiTestSuiteResponse)
def create_api_test_suite(
    payload: ApiTestSuiteCreateRequest,
    db: Session = Depends(get_db),
) -> ApiTestSuite:
    suite = ApiTestSuite(
        name=payload.name,
        base_url=payload.base_url,
        headers=payload.headers,
        auth_type=payload.auth_type,
        auth_config=payload.auth_config,
    )
    db.add(suite)
    db.commit()
    db.refresh(suite)
    return suite


@router.get("/suites/{suite_id}", response_model=ApiTestSuiteResponse)
def get_api_test_suite(suite_id: int, db: Session = Depends(get_db)) -> ApiTestSuite:
    suite = (
        db.query(ApiTestSuite)
        .options(selectinload(ApiTestSuite.cases))
        .filter(ApiTestSuite.id == suite_id)
        .first()
    )
    if not suite:
        raise HTTPException(status_code=404, detail="接口测试套件不存在")
    return suite


@router.put("/suites/{suite_id}", response_model=ApiTestSuiteResponse)
def update_api_test_suite(
    suite_id: int,
    payload: ApiTestSuiteUpdateRequest,
    db: Session = Depends(get_db),
) -> ApiTestSuite:
    suite = db.get(ApiTestSuite, suite_id)
    if not suite:
        raise HTTPException(status_code=404, detail="接口测试套件不存在")
    suite.name = payload.name
    suite.base_url = payload.base_url
    suite.headers = payload.headers
    suite.auth_type = payload.auth_type
    suite.auth_config = payload.auth_config
    db.commit()
    db.refresh(suite)
    return suite


@router.delete("/suites/{suite_id}")
def delete_api_test_suite(suite_id: int, db: Session = Depends(get_db)) -> dict[str, int]:
    suite = db.get(ApiTestSuite, suite_id)
    if not suite:
        raise HTTPException(status_code=404, detail="接口测试套件不存在")
    db.delete(suite)
    db.commit()
    return {"deleted": suite_id}


@router.post("/suites/{suite_id}/cases", response_model=ApiTestCaseResponse)
def create_api_test_case(
    suite_id: int,
    payload: ApiTestCaseCreateRequest,
    db: Session = Depends(get_db),
) -> ApiTestCase:
    suite = db.get(ApiTestSuite, suite_id)
    if not suite:
        raise HTTPException(status_code=404, detail="接口测试套件不存在")

    next_sequence = (
        db.query(func.max(ApiTestCase.sequence))
        .filter(ApiTestCase.suite_id == suite_id)
        .scalar()
        or 0
    ) + 1

    case = ApiTestCase(
        suite_id=suite_id,
        sequence=next_sequence,
        name=payload.name,
        method=payload.method,
        path=payload.path,
        headers=payload.headers,
        params=payload.params,
        body=payload.body,
        expected_status=payload.expected_status,
        expected_body_contains=payload.expected_body_contains,
        expected_schema=payload.expected_schema,
        extract_vars=payload.extract_vars,
        tags=payload.tags,
        priority=payload.priority,
        run_count=0,
        latest_result="pending",
        latest_result_note="",
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


@router.put("/cases/{case_id}", response_model=ApiTestCaseResponse)
def update_api_test_case(
    case_id: int,
    payload: ApiTestCaseUpdateRequest,
    db: Session = Depends(get_db),
) -> ApiTestCase:
    case = db.get(ApiTestCase, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="接口测试用例不存在")
    case.name = payload.name
    case.method = payload.method
    case.path = payload.path
    case.headers = payload.headers
    case.params = payload.params
    case.body = payload.body
    case.expected_status = payload.expected_status
    case.expected_body_contains = payload.expected_body_contains
    case.expected_schema = payload.expected_schema
    case.extract_vars = payload.extract_vars
    case.tags = payload.tags
    case.priority = payload.priority
    db.commit()
    db.refresh(case)
    return case


@router.delete("/cases/{case_id}")
def delete_api_test_case(case_id: int, db: Session = Depends(get_db)) -> dict[str, int]:
    case = db.get(ApiTestCase, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="接口测试用例不存在")
    db.delete(case)
    db.commit()
    return {"deleted": case_id}


@router.post("/cases/{case_id}/run", response_model=ApiTestExecutionResponse)
def run_api_test_case(case_id: int, db: Session = Depends(get_db)) -> ApiTestExecution:
    return ApiTestService(db).execute_case(case_id)


@router.post("/suites/{suite_id}/run", response_model=ApiTestSuiteRunResponse)
def run_api_test_suite(suite_id: int, db: Session = Depends(get_db)) -> ApiTestSuiteRunResponse:
    executions = ApiTestService(db).execute_suite(suite_id)
    return ApiTestSuiteRunResponse(
        suite_id=suite_id,
        total_cases=len(executions),
        executions=[ApiTestExecutionResponse.model_validate(execution) for execution in executions],
    )


@router.post("/suites/{suite_id}/run/stream")
def stream_api_test_suite_run(suite_id: int, db: Session = Depends(get_db)) -> StreamingResponse:
    stream = ApiTestService(db).iter_suite_event_lines(suite_id)
    return StreamingResponse(stream, media_type="application/x-ndjson")


@router.post("/cases/{case_id}/run/stream")
def stream_api_test_case_run(case_id: int, db: Session = Depends(get_db)) -> StreamingResponse:
    stream = ApiTestService(db).iter_case_event_lines(case_id)
    return StreamingResponse(stream, media_type="application/x-ndjson")
