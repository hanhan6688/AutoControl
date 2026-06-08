from __future__ import annotations

import json
import re
from collections.abc import Iterator
from datetime import datetime
from time import perf_counter

import httpx
import jsonschema
from sqlalchemy.orm import Session

from app.config import settings
from app.models import ApiTestSuite, ApiTestCase, ApiTestExecution
from app.utils import utc_iso

_VAR_PATTERN = re.compile(r"\$\{(\w+)\}")


def _substitute_vars(value: str, context: dict) -> str:
    if not context:
        return value

    def _replace(match: re.Match) -> str:
        var_name = match.group(1)
        replacement = context.get(var_name)
        if replacement is None:
            return match.group(0)
        return str(replacement)

    return _VAR_PATTERN.sub(_replace, value)


def _substitute_vars_deep(obj: object, context: dict) -> object:
    if isinstance(obj, str):
        return _substitute_vars(obj, context)
    if isinstance(obj, dict):
        return {k: _substitute_vars_deep(v, context) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_substitute_vars_deep(item, context) for item in obj]
    return obj


def _extract_by_dot_path(data: dict, path: str) -> object:
    if not path.startswith("$."):
        return None
    parts = path[2:].split(".")
    current: object = data
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
        if current is None:
            return None
    return current


def _build_auth(suite: ApiTestSuite) -> httpx.Auth | tuple[str, str] | None:
    if not suite.auth_type or not suite.auth_config:
        return None
    config = suite.auth_config or {}
    if suite.auth_type == "bearer":
        token = config.get("token", "")
        return httpx.BearerAuth(token)
    if suite.auth_type == "basic":
        username = config.get("username", "")
        password = config.get("password", "")
        return (username, password)
    return None


class ApiTestService:
    def __init__(self, db: Session):
        self.db = db

    def _make_client(self) -> httpx.Client:
        return httpx.Client(timeout=settings.api_test_default_timeout)

    def execute_case(self, case_id: int, context: dict | None = None) -> ApiTestExecution:
        execution_id: int | None = None
        for event in self.iter_case_events(case_id, context=context):
            if event.get("event") == "result":
                execution_id = event.get("execution_id")

        if execution_id is None:
            raise RuntimeError("API test case execution did not produce a result")
        execution = self.db.get(ApiTestExecution, execution_id)
        if execution is None:
            raise RuntimeError("API test execution record not found")
        return execution

    def execute_suite(self, suite_id: int) -> list[ApiTestExecution]:
        executions: list[ApiTestExecution] = []
        for event in self.iter_suite_events(suite_id):
            if event.get("event") == "result":
                execution_id = event.get("execution_id")
                if execution_id:
                    execution = self.db.get(ApiTestExecution, execution_id)
                    if execution:
                        executions.append(execution)
        return executions

    def iter_suite_events(self, suite_id: int) -> Iterator[dict]:
        suite = self.db.get(ApiTestSuite, suite_id)
        if not suite:
            raise RuntimeError("API test suite not found")

        cases = (
            self.db.query(ApiTestCase)
            .filter(ApiTestCase.suite_id == suite_id)
            .order_by(ApiTestCase.sequence)
            .all()
        )
        if not cases:
            raise RuntimeError("API test suite has no cases")

        context: dict = {}

        yield {
            "event": "suite_start",
            "timestamp": utc_iso(),
            "suite_id": suite_id,
            "suite_name": suite.name,
            "total_cases": len(cases),
        }

        for index, case in enumerate(cases, start=1):
            yield {
                "event": "case_start",
                "timestamp": utc_iso(),
                "suite_id": suite_id,
                "case_id": case.id,
                "case_index": index,
                "case_name": case.name,
                "total_cases": len(cases),
            }
            for event in self.iter_case_events(case.id, context=context):
                event.setdefault("suite_id", suite_id)
                event.setdefault("case_index", index)
                event.setdefault("total_cases", len(cases))
                if event.get("event") == "result":
                    extracted = event.get("extracted_vars", {})
                    context.update(extracted)
                yield event

        yield {
            "event": "suite_result",
            "timestamp": utc_iso(),
            "suite_id": suite_id,
            "total_cases": len(cases),
            "context": context,
        }

    def iter_case_events(self, case_id: int, context: dict | None = None) -> Iterator[dict]:
        case = self.db.get(ApiTestCase, case_id)
        if not case:
            raise RuntimeError("API test case not found")

        suite = case.suite
        ctx = dict(context or {})
        started = datetime.utcnow()
        timer = perf_counter()
        run_index = case.run_count + 1

        yield {
            "event": "log",
            "timestamp": utc_iso(),
            "case_id": case.id,
            "message": f"Starting API test case: {case.name}",
        }

        merged_headers: dict = dict(suite.headers or {})
        merged_headers.update(case.headers or {})

        auth = _build_auth(suite)

        substituted_path = _substitute_vars(case.path, ctx)
        base_url = (suite.base_url or "").rstrip("/")
        path = substituted_path.lstrip("/")
        full_url = f"{base_url}/{path}" if base_url else substituted_path

        substituted_params = _substitute_vars_deep(case.params or {}, ctx)
        substituted_headers = _substitute_vars_deep(merged_headers, ctx)
        substituted_body = _substitute_vars_deep(case.body, ctx) if case.body is not None else None

        yield {
            "event": "request",
            "timestamp": utc_iso(),
            "case_id": case.id,
            "method": case.method,
            "url": full_url,
            "headers": substituted_headers,
            "params": substituted_params,
            "body": substituted_body,
        }

        response_status: int | None = None
        response_headers: dict | None = None
        response_body: dict | None = None
        response_body_text: str | None = None
        response_time_ms: int | None = None
        run_result = "failed"
        result_note = ""
        assertion_detail: dict = {"status_ok": False, "body_contains_ok": None, "schema_ok": None, "errors": []}
        extracted_vars: dict = {}

        try:
            with self._make_client() as client:
                request_kwargs: dict = {
                    "method": case.method,
                    "url": full_url,
                    "params": substituted_params,
                }
                request_kwargs["headers"] = substituted_headers
                if auth is not None:
                    request_kwargs["auth"] = auth
                if substituted_body is not None:
                    request_kwargs["json"] = substituted_body

                req_timer = perf_counter()
                response = client.request(**request_kwargs)
                response_time_ms = max(1, int((perf_counter() - req_timer) * 1000))

                response_status = response.status_code
                response_headers = dict(response.headers)
                response_body_text = response.text
                try:
                    response_body = response.json()
                except Exception:
                    response_body = None

        except httpx.TimeoutException as exc:
            result_note = f"Request timed out: {exc}"
            assertion_detail["errors"].append(result_note)
            yield {
                "event": "error",
                "timestamp": utc_iso(),
                "case_id": case.id,
                "message": result_note,
                "error_type": "timeout",
            }
        except httpx.RequestError as exc:
            result_note = f"Request failed: {exc}"
            assertion_detail["errors"].append(result_note)
            yield {
                "event": "error",
                "timestamp": utc_iso(),
                "case_id": case.id,
                "message": result_note,
                "error_type": "request_error",
            }
        else:
            yield {
                "event": "response",
                "timestamp": utc_iso(),
                "case_id": case.id,
                "status": response_status,
                "headers": response_headers,
                "body": response_body,
                "body_text": response_body_text,
                "response_time_ms": response_time_ms,
            }

            if response_status == case.expected_status:
                assertion_detail["status_ok"] = True
            else:
                assertion_detail["status_ok"] = False
                msg = f"Expected status {case.expected_status}, got {response_status}"
                assertion_detail["errors"].append(msg)

            if case.expected_body_contains:
                body_str = response_body_text or ""
                if case.expected_body_contains in body_str:
                    assertion_detail["body_contains_ok"] = True
                else:
                    assertion_detail["body_contains_ok"] = False
                    msg = f"Body does not contain expected text: {case.expected_body_contains!r}"
                    assertion_detail["errors"].append(msg)

            if case.expected_schema:
                if response_body is None:
                    assertion_detail["schema_ok"] = False
                    msg = "Cannot validate schema: response body is not valid JSON"
                    assertion_detail["errors"].append(msg)
                else:
                    try:
                        jsonschema.validate(instance=response_body, schema=case.expected_schema)
                        assertion_detail["schema_ok"] = True
                    except jsonschema.ValidationError as exc:
                        assertion_detail["schema_ok"] = False
                        msg = f"Schema validation failed: {exc.message}"
                        assertion_detail["errors"].append(msg)

            if case.extract_vars and response_body is not None:
                for var_name, dot_path in case.extract_vars.items():
                    if isinstance(dot_path, str):
                        value = _extract_by_dot_path(response_body, dot_path)
                        if value is not None:
                            extracted_vars[var_name] = value

            all_ok = assertion_detail["status_ok"]
            if assertion_detail["body_contains_ok"] is False:
                all_ok = False
            if assertion_detail["schema_ok"] is False:
                all_ok = False

            if all_ok:
                run_result = "passed"
                result_note = "All assertions passed"
            else:
                run_result = "failed"
                result_note = "; ".join(assertion_detail["errors"]) or "Assertion failed"

        duration_ms = max(1, int((perf_counter() - timer) * 1000))

        execution = ApiTestExecution(
            suite_id=case.suite_id,
            case_id=case.id,
            run_index=run_index,
            request_url=full_url,
            request_method=case.method,
            request_headers=substituted_headers,
            request_body=substituted_body,
            response_status=response_status,
            response_headers=response_headers,
            response_body=response_body,
            response_body_text=response_body_text,
            response_time_ms=response_time_ms,
            run_result=run_result,
            result_note=result_note,
            assertion_detail=assertion_detail,
            started_at=started,
            ended_at=datetime.utcnow(),
            duration_ms=duration_ms,
        )
        self.db.add(execution)

        case.run_count = run_index
        case.latest_result = run_result
        case.latest_result_note = result_note
        self.db.commit()
        self.db.refresh(execution)

        yield {
            "event": "result",
            "timestamp": utc_iso(),
            "execution_id": execution.id,
            "case_id": case.id,
            "run_result": run_result,
            "result_note": result_note,
            "assertion_detail": assertion_detail,
            "extracted_vars": extracted_vars,
            "response_status": response_status,
            "response_time_ms": response_time_ms,
            "duration_ms": duration_ms,
        }

    def iter_suite_event_lines(self, suite_id: int) -> Iterator[str]:
        for event in self.iter_suite_events(suite_id):
            yield json.dumps(event, ensure_ascii=False, default=str) + "\n"

    def iter_case_event_lines(self, case_id: int, context: dict | None = None) -> Iterator[str]:
        for event in self.iter_case_events(case_id, context=context):
            yield json.dumps(event, ensure_ascii=False, default=str) + "\n"
