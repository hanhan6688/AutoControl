from __future__ import annotations

import json
from unittest import mock

import httpx


# ---------------------------------------------------------------------------
# _substitute_vars
# ---------------------------------------------------------------------------

def test_substitute_vars_no_vars() -> None:
    from app.services.api_test_service import _substitute_vars

    assert _substitute_vars("hello world", {"name": "Alice"}) == "hello world"


def test_substitute_vars_single_var() -> None:
    from app.services.api_test_service import _substitute_vars

    assert _substitute_vars("Hello ${name}!", {"name": "Alice"}) == "Hello Alice!"


def test_substitute_vars_multiple_vars() -> None:
    from app.services.api_test_service import _substitute_vars

    result = _substitute_vars("${greeting} ${name}", {"greeting": "Hello", "name": "Bob"})
    assert result == "Hello Bob"


def test_substitute_vars_missing_var_kept_as_is() -> None:
    from app.services.api_test_service import _substitute_vars

    result = _substitute_vars("Hello ${missing}!", {"name": "Alice"})
    assert result == "Hello ${missing}!"


def test_substitute_vars_empty_context() -> None:
    from app.services.api_test_service import _substitute_vars

    assert _substitute_vars("Hello ${name}!", {}) == "Hello ${name}!"


# ---------------------------------------------------------------------------
# _substitute_vars_deep
# ---------------------------------------------------------------------------

def test_substitute_vars_deep_nested_dict() -> None:
    from app.services.api_test_service import _substitute_vars_deep

    obj = {"a": "${x}", "b": {"c": "${y}"}}
    ctx = {"x": "10", "y": "20"}
    result = _substitute_vars_deep(obj, ctx)
    assert result == {"a": "10", "b": {"c": "20"}}


def test_substitute_vars_deep_list() -> None:
    from app.services.api_test_service import _substitute_vars_deep

    obj = ["${x}", "${y}", "static"]
    ctx = {"x": "10", "y": "20"}
    result = _substitute_vars_deep(obj, ctx)
    assert result == ["10", "20", "static"]


def test_substitute_vars_deep_mixed() -> None:
    from app.services.api_test_service import _substitute_vars_deep

    obj = {"a": ["${x}", {"b": "${y}"}]}
    ctx = {"x": "10", "y": "20"}
    result = _substitute_vars_deep(obj, ctx)
    assert result == {"a": ["10", {"b": "20"}]}


def test_substitute_vars_deep_non_string_values_preserved() -> None:
    from app.services.api_test_service import _substitute_vars_deep

    obj = {"a": 42, "b": True, "c": None, "d": 3.14}
    result = _substitute_vars_deep(obj, {"x": "1"})
    assert result == {"a": 42, "b": True, "c": None, "d": 3.14}


# ---------------------------------------------------------------------------
# _extract_by_dot_path
# ---------------------------------------------------------------------------

def test_extract_by_dot_path_simple() -> None:
    from app.services.api_test_service import _extract_by_dot_path

    data = {"name": "Alice"}
    assert _extract_by_dot_path(data, "$.name") == "Alice"


def test_extract_by_dot_path_nested() -> None:
    from app.services.api_test_service import _extract_by_dot_path

    data = {"a": {"b": {"c": "deep"}}}
    assert _extract_by_dot_path(data, "$.a.b.c") == "deep"


def test_extract_by_dot_path_array_index() -> None:
    from app.services.api_test_service import _extract_by_dot_path

    data = {"items": ["first", "second", "third"]}
    assert _extract_by_dot_path(data, "$.items.1") == "second"


def test_extract_by_dot_path_missing_key_returns_none() -> None:
    from app.services.api_test_service import _extract_by_dot_path

    data = {"name": "Alice"}
    assert _extract_by_dot_path(data, "$.missing") is None


def test_extract_by_dot_path_no_dollar_prefix_returns_none() -> None:
    from app.services.api_test_service import _extract_by_dot_path

    data = {"name": "Alice"}
    assert _extract_by_dot_path(data, "name") is None


def test_extract_by_dot_path_array_out_of_bounds_returns_none() -> None:
    from app.services.api_test_service import _extract_by_dot_path

    data = {"items": ["a"]}
    assert _extract_by_dot_path(data, "$.items.5") is None


# ---------------------------------------------------------------------------
# _build_auth
# ---------------------------------------------------------------------------

def test_build_auth_bearer() -> None:
    from app.services import api_test_service as module
    from app.services.api_test_service import _build_auth

    suite = mock.MagicMock()
    suite.auth_type = "bearer"
    suite.auth_config = {"token": "my-token"}

    # httpx < 0.30 does not ship BearerAuth; the service references it at
    # runtime via httpx.BearerAuth, so we mock it on the module to test the
    # logic flow without depending on the installed httpx version.
    fake_bearer = mock.MagicMock(return_value=mock.MagicMock())
    with mock.patch.object(module.httpx, "BearerAuth", fake_bearer, create=True):
        result = _build_auth(suite)

    fake_bearer.assert_called_once_with("my-token")
    assert result is fake_bearer.return_value


def test_build_auth_basic() -> None:
    from app.services.api_test_service import _build_auth

    suite = mock.MagicMock()
    suite.auth_type = "basic"
    suite.auth_config = {"username": "user", "password": "pass"}

    result = _build_auth(suite)
    assert result == ("user", "pass")


def test_build_auth_no_auth() -> None:
    from app.services.api_test_service import _build_auth

    suite = mock.MagicMock()
    suite.auth_type = None
    suite.auth_config = None

    assert _build_auth(suite) is None


def test_build_auth_empty_auth_type() -> None:
    from app.services.api_test_service import _build_auth

    suite = mock.MagicMock()
    suite.auth_type = ""
    suite.auth_config = {"token": "abc"}

    assert _build_auth(suite) is None


def test_build_auth_unknown_type_returns_none() -> None:
    from app.services.api_test_service import _build_auth

    suite = mock.MagicMock()
    suite.auth_type = "digest"
    suite.auth_config = {"token": "abc"}

    assert _build_auth(suite) is None


# ---------------------------------------------------------------------------
# Helpers for iter_case_events / iter_suite_events
# ---------------------------------------------------------------------------

def _make_fake_suite(**overrides):
    """Build a mock ApiTestSuite with sensible defaults."""
    defaults = {
        "id": 1,
        "name": "Test Suite",
        "base_url": "https://api.example.com",
        "headers": {},
        "auth_type": None,
        "auth_config": None,
    }
    defaults.update(overrides)
    suite = mock.MagicMock()
    for k, v in defaults.items():
        setattr(suite, k, v)
    return suite


def _make_fake_case(suite=None, **overrides):
    """Build a mock ApiTestCase with sensible defaults."""
    if suite is None:
        suite = _make_fake_suite()
    defaults = {
        "id": 10,
        "suite_id": suite.id,
        "name": "Get Users",
        "method": "GET",
        "path": "/users",
        "headers": {},
        "params": {},
        "body": None,
        "expected_status": 200,
        "expected_body_contains": None,
        "expected_schema": None,
        "extract_vars": None,
        "run_count": 0,
        "latest_result": "pending",
        "latest_result_note": "",
        "suite": suite,
    }
    defaults.update(overrides)
    case = mock.MagicMock()
    for k, v in defaults.items():
        setattr(case, k, v)
    return case


def _make_fake_response(status_code=200, json_body=None, text_body=None):
    """Build a fake httpx Response."""
    if json_body is not None:
        text = text_body or json.dumps(json_body)
    else:
        text = text_body or ""
    resp = mock.MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text
    resp.headers = {"content-type": "application/json"}
    if json_body is not None:
        resp.json.return_value = json_body
    else:
        resp.json.side_effect = ValueError("no json")
    return resp


# ---------------------------------------------------------------------------
# iter_case_events
# ---------------------------------------------------------------------------

def test_iter_case_events_emits_expected_events() -> None:
    from app.services.api_test_service import ApiTestService

    db = mock.MagicMock()
    suite = _make_fake_suite()
    case = _make_fake_case(suite)
    execution = mock.MagicMock()
    execution.id = 42

    db.get.return_value = case
    db.add.return_value = None
    db.commit.return_value = None
    db.refresh.return_value = None

    fake_resp = _make_fake_response(200, {"status": "ok"})

    with mock.patch("app.services.api_test_service.httpx.Client") as MockClient:
        client_instance = mock.MagicMock()
        client_instance.request.return_value = fake_resp
        client_instance.__enter__ = mock.MagicMock(return_value=client_instance)
        client_instance.__exit__ = mock.MagicMock(return_value=False)
        MockClient.return_value = client_instance

        events = list(ApiTestService(db).iter_case_events(10))

    event_types = [e["event"] for e in events]
    assert "log" in event_types
    assert "request" in event_types
    assert "response" in event_types
    assert "result" in event_types


def test_iter_case_events_request_event_fields() -> None:
    from app.services.api_test_service import ApiTestService

    db = mock.MagicMock()
    suite = _make_fake_suite()
    case = _make_fake_case(suite, method="POST", path="/items", body={"name": "test"})
    execution = mock.MagicMock()
    execution.id = 42

    db.get.return_value = case
    db.add.return_value = None
    db.commit.return_value = None
    db.refresh.return_value = None

    fake_resp = _make_fake_response(201, {"id": 1})

    with mock.patch("app.services.api_test_service.httpx.Client") as MockClient:
        client_instance = mock.MagicMock()
        client_instance.request.return_value = fake_resp
        client_instance.__enter__ = mock.MagicMock(return_value=client_instance)
        client_instance.__exit__ = mock.MagicMock(return_value=False)
        MockClient.return_value = client_instance

        events = list(ApiTestService(db).iter_case_events(10))

    req_event = next(e for e in events if e["event"] == "request")
    assert req_event["method"] == "POST"
    assert req_event["url"] == "https://api.example.com/items"
    assert req_event["body"] == {"name": "test"}


def test_iter_case_events_status_match_passes() -> None:
    from app.services.api_test_service import ApiTestService

    db = mock.MagicMock()
    suite = _make_fake_suite()
    case = _make_fake_case(suite, expected_status=200)
    execution = mock.MagicMock()
    execution.id = 42

    db.get.return_value = case
    db.add.return_value = None
    db.commit.return_value = None
    db.refresh.return_value = None

    fake_resp = _make_fake_response(200, {"ok": True})

    with mock.patch("app.services.api_test_service.httpx.Client") as MockClient:
        client_instance = mock.MagicMock()
        client_instance.request.return_value = fake_resp
        client_instance.__enter__ = mock.MagicMock(return_value=client_instance)
        client_instance.__exit__ = mock.MagicMock(return_value=False)
        MockClient.return_value = client_instance

        events = list(ApiTestService(db).iter_case_events(10))

    result_event = next(e for e in events if e["event"] == "result")
    assert result_event["run_result"] == "passed"
    assert result_event["assertion_detail"]["status_ok"] is True


def test_iter_case_events_status_mismatch_fails() -> None:
    from app.services.api_test_service import ApiTestService

    db = mock.MagicMock()
    suite = _make_fake_suite()
    case = _make_fake_case(suite, expected_status=200)
    execution = mock.MagicMock()
    execution.id = 42

    db.get.return_value = case
    db.add.return_value = None
    db.commit.return_value = None
    db.refresh.return_value = None

    fake_resp = _make_fake_response(500, {"error": "fail"})

    with mock.patch("app.services.api_test_service.httpx.Client") as MockClient:
        client_instance = mock.MagicMock()
        client_instance.request.return_value = fake_resp
        client_instance.__enter__ = mock.MagicMock(return_value=client_instance)
        client_instance.__exit__ = mock.MagicMock(return_value=False)
        MockClient.return_value = client_instance

        events = list(ApiTestService(db).iter_case_events(10))

    result_event = next(e for e in events if e["event"] == "result")
    assert result_event["run_result"] == "failed"
    assert result_event["assertion_detail"]["status_ok"] is False


def test_iter_case_events_body_contains_passes() -> None:
    from app.services.api_test_service import ApiTestService

    db = mock.MagicMock()
    suite = _make_fake_suite()
    case = _make_fake_case(suite, expected_body_contains="success")
    execution = mock.MagicMock()
    execution.id = 42

    db.get.return_value = case
    db.add.return_value = None
    db.commit.return_value = None
    db.refresh.return_value = None

    fake_resp = _make_fake_response(200, {"message": "success"})

    with mock.patch("app.services.api_test_service.httpx.Client") as MockClient:
        client_instance = mock.MagicMock()
        client_instance.request.return_value = fake_resp
        client_instance.__enter__ = mock.MagicMock(return_value=client_instance)
        client_instance.__exit__ = mock.MagicMock(return_value=False)
        MockClient.return_value = client_instance

        events = list(ApiTestService(db).iter_case_events(10))

    result_event = next(e for e in events if e["event"] == "result")
    assert result_event["assertion_detail"]["body_contains_ok"] is True
    assert result_event["run_result"] == "passed"


def test_iter_case_events_body_contains_fails() -> None:
    from app.services.api_test_service import ApiTestService

    db = mock.MagicMock()
    suite = _make_fake_suite()
    case = _make_fake_case(suite, expected_body_contains="not_found_text")
    execution = mock.MagicMock()
    execution.id = 42

    db.get.return_value = case
    db.add.return_value = None
    db.commit.return_value = None
    db.refresh.return_value = None

    fake_resp = _make_fake_response(200, {"message": "something else"})

    with mock.patch("app.services.api_test_service.httpx.Client") as MockClient:
        client_instance = mock.MagicMock()
        client_instance.request.return_value = fake_resp
        client_instance.__enter__ = mock.MagicMock(return_value=client_instance)
        client_instance.__exit__ = mock.MagicMock(return_value=False)
        MockClient.return_value = client_instance

        events = list(ApiTestService(db).iter_case_events(10))

    result_event = next(e for e in events if e["event"] == "result")
    assert result_event["assertion_detail"]["body_contains_ok"] is False
    assert result_event["run_result"] == "failed"


def test_iter_case_events_schema_validation_passes() -> None:
    from app.services.api_test_service import ApiTestService

    db = mock.MagicMock()
    suite = _make_fake_suite()
    case = _make_fake_case(
        suite,
        expected_schema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    )
    execution = mock.MagicMock()
    execution.id = 42

    db.get.return_value = case
    db.add.return_value = None
    db.commit.return_value = None
    db.refresh.return_value = None

    fake_resp = _make_fake_response(200, {"name": "Alice"})

    with mock.patch("app.services.api_test_service.httpx.Client") as MockClient:
        client_instance = mock.MagicMock()
        client_instance.request.return_value = fake_resp
        client_instance.__enter__ = mock.MagicMock(return_value=client_instance)
        client_instance.__exit__ = mock.MagicMock(return_value=False)
        MockClient.return_value = client_instance

        events = list(ApiTestService(db).iter_case_events(10))

    result_event = next(e for e in events if e["event"] == "result")
    assert result_event["assertion_detail"]["schema_ok"] is True
    assert result_event["run_result"] == "passed"


def test_iter_case_events_schema_validation_fails() -> None:
    from app.services.api_test_service import ApiTestService

    db = mock.MagicMock()
    suite = _make_fake_suite()
    case = _make_fake_case(
        suite,
        expected_schema={
            "type": "object",
            "properties": {"age": {"type": "integer"}},
            "required": ["age"],
        },
    )
    execution = mock.MagicMock()
    execution.id = 42

    db.get.return_value = case
    db.add.return_value = None
    db.commit.return_value = None
    db.refresh.return_value = None

    # age is a string, not integer -- schema should fail
    fake_resp = _make_fake_response(200, {"age": "not_a_number"})

    with mock.patch("app.services.api_test_service.httpx.Client") as MockClient:
        client_instance = mock.MagicMock()
        client_instance.request.return_value = fake_resp
        client_instance.__enter__ = mock.MagicMock(return_value=client_instance)
        client_instance.__exit__ = mock.MagicMock(return_value=False)
        MockClient.return_value = client_instance

        events = list(ApiTestService(db).iter_case_events(10))

    result_event = next(e for e in events if e["event"] == "result")
    assert result_event["assertion_detail"]["schema_ok"] is False
    assert result_event["run_result"] == "failed"


def test_iter_case_events_schema_validation_non_json_body() -> None:
    from app.services.api_test_service import ApiTestService

    db = mock.MagicMock()
    suite = _make_fake_suite()
    case = _make_fake_case(
        suite,
        expected_schema={"type": "object"},
    )
    execution = mock.MagicMock()
    execution.id = 42

    db.get.return_value = case
    db.add.return_value = None
    db.commit.return_value = None
    db.refresh.return_value = None

    fake_resp = _make_fake_response(200, json_body=None, text_body="plain text")

    with mock.patch("app.services.api_test_service.httpx.Client") as MockClient:
        client_instance = mock.MagicMock()
        client_instance.request.return_value = fake_resp
        client_instance.__enter__ = mock.MagicMock(return_value=client_instance)
        client_instance.__exit__ = mock.MagicMock(return_value=False)
        MockClient.return_value = client_instance

        events = list(ApiTestService(db).iter_case_events(10))

    result_event = next(e for e in events if e["event"] == "result")
    assert result_event["assertion_detail"]["schema_ok"] is False


def test_iter_case_events_variable_extraction() -> None:
    from app.services.api_test_service import ApiTestService

    db = mock.MagicMock()
    suite = _make_fake_suite()
    case = _make_fake_case(
        suite,
        extract_vars={"token": "$.data.token", "user_id": "$.data.id"},
    )
    execution = mock.MagicMock()
    execution.id = 42

    db.get.return_value = case
    db.add.return_value = None
    db.commit.return_value = None
    db.refresh.return_value = None

    fake_resp = _make_fake_response(200, {"data": {"token": "abc123", "id": 7}})

    with mock.patch("app.services.api_test_service.httpx.Client") as MockClient:
        client_instance = mock.MagicMock()
        client_instance.request.return_value = fake_resp
        client_instance.__enter__ = mock.MagicMock(return_value=client_instance)
        client_instance.__exit__ = mock.MagicMock(return_value=False)
        MockClient.return_value = client_instance

        events = list(ApiTestService(db).iter_case_events(10))

    result_event = next(e for e in events if e["event"] == "result")
    assert result_event["extracted_vars"]["token"] == "abc123"
    assert result_event["extracted_vars"]["user_id"] == 7


def test_iter_case_events_variable_extraction_missing_path() -> None:
    from app.services.api_test_service import ApiTestService

    db = mock.MagicMock()
    suite = _make_fake_suite()
    case = _make_fake_case(
        suite,
        extract_vars={"missing_var": "$.nonexistent.path"},
    )
    execution = mock.MagicMock()
    execution.id = 42

    db.get.return_value = case
    db.add.return_value = None
    db.commit.return_value = None
    db.refresh.return_value = None

    fake_resp = _make_fake_response(200, {"data": "ok"})

    with mock.patch("app.services.api_test_service.httpx.Client") as MockClient:
        client_instance = mock.MagicMock()
        client_instance.request.return_value = fake_resp
        client_instance.__enter__ = mock.MagicMock(return_value=client_instance)
        client_instance.__exit__ = mock.MagicMock(return_value=False)
        MockClient.return_value = client_instance

        events = list(ApiTestService(db).iter_case_events(10))

    result_event = next(e for e in events if e["event"] == "result")
    # Missing path returns None, so it should not be added to extracted_vars
    assert "missing_var" not in result_event["extracted_vars"]


def test_iter_case_events_timeout_emits_error() -> None:
    from app.services.api_test_service import ApiTestService

    db = mock.MagicMock()
    suite = _make_fake_suite()
    case = _make_fake_case(suite)
    execution = mock.MagicMock()
    execution.id = 42

    db.get.return_value = case
    db.add.return_value = None
    db.commit.return_value = None
    db.refresh.return_value = None

    with mock.patch("app.services.api_test_service.httpx.Client") as MockClient:
        client_instance = mock.MagicMock()
        client_instance.request.side_effect = httpx.TimeoutException("timed out")
        client_instance.__enter__ = mock.MagicMock(return_value=client_instance)
        client_instance.__exit__ = mock.MagicMock(return_value=False)
        MockClient.return_value = client_instance

        events = list(ApiTestService(db).iter_case_events(10))

    event_types = [e["event"] for e in events]
    assert "error" in event_types
    assert "response" not in event_types

    error_event = next(e for e in events if e["event"] == "error")
    assert error_event["error_type"] == "timeout"

    result_event = next(e for e in events if e["event"] == "result")
    assert result_event["run_result"] == "failed"


def test_iter_case_events_request_error_emits_error() -> None:
    from app.services.api_test_service import ApiTestService

    db = mock.MagicMock()
    suite = _make_fake_suite()
    case = _make_fake_case(suite)
    execution = mock.MagicMock()
    execution.id = 42

    db.get.return_value = case
    db.add.return_value = None
    db.commit.return_value = None
    db.refresh.return_value = None

    with mock.patch("app.services.api_test_service.httpx.Client") as MockClient:
        client_instance = mock.MagicMock()
        client_instance.request.side_effect = httpx.RequestError("connection refused")
        client_instance.__enter__ = mock.MagicMock(return_value=client_instance)
        client_instance.__exit__ = mock.MagicMock(return_value=False)
        MockClient.return_value = client_instance

        events = list(ApiTestService(db).iter_case_events(10))

    error_event = next(e for e in events if e["event"] == "error")
    assert error_event["error_type"] == "request_error"

    result_event = next(e for e in events if e["event"] == "result")
    assert result_event["run_result"] == "failed"


def test_iter_case_events_case_not_found() -> None:
    from app.services.api_test_service import ApiTestService

    db = mock.MagicMock()
    db.get.return_value = None

    import pytest

    with pytest.raises(RuntimeError, match="not found"):
        list(ApiTestService(db).iter_case_events(999))


def test_iter_case_events_substitutes_context_vars() -> None:
    from app.services.api_test_service import ApiTestService

    db = mock.MagicMock()
    suite = _make_fake_suite()
    case = _make_fake_case(
        suite,
        path="/users/${user_id}/profile",
        headers={"X-Token": "${token}"},
        params={"page": "${page}"},
        body={"name": "${name}"},
    )
    execution = mock.MagicMock()
    execution.id = 42

    db.get.return_value = case
    db.add.return_value = None
    db.commit.return_value = None
    db.refresh.return_value = None

    fake_resp = _make_fake_response(200, {"ok": True})

    with mock.patch("app.services.api_test_service.httpx.Client") as MockClient:
        client_instance = mock.MagicMock()
        client_instance.request.return_value = fake_resp
        client_instance.__enter__ = mock.MagicMock(return_value=client_instance)
        client_instance.__exit__ = mock.MagicMock(return_value=False)
        MockClient.return_value = client_instance

        context = {"user_id": "42", "token": "secret", "page": "3", "name": "Alice"}
        events = list(ApiTestService(db).iter_case_events(10, context=context))

    req_event = next(e for e in events if e["event"] == "request")
    assert req_event["url"] == "https://api.example.com/users/42/profile"
    assert req_event["headers"]["X-Token"] == "secret"
    assert req_event["params"]["page"] == "3"
    assert req_event["body"]["name"] == "Alice"


# ---------------------------------------------------------------------------
# iter_suite_events
# ---------------------------------------------------------------------------

def test_iter_suite_events_emits_suite_start_and_result() -> None:
    from app.services.api_test_service import ApiTestService

    db = mock.MagicMock()
    suite = _make_fake_suite(id=1, name="My Suite")
    case1 = _make_fake_case(suite, id=10, name="Case 1", sequence=1)
    case2 = _make_fake_case(suite, id=11, name="Case 2", sequence=2)
    execution = mock.MagicMock()
    execution.id = 100

    db.get.side_effect = lambda model, pk: suite if model.__name__ == "ApiTestSuite" and pk == 1 else case1 if pk == 10 else case2
    # For iter_case_events, db.get is called with ApiTestCase
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [case1, case2]
    db.add.return_value = None
    db.commit.return_value = None
    db.refresh.return_value = None

    fake_resp = _make_fake_response(200, {"ok": True})

    with mock.patch("app.services.api_test_service.httpx.Client") as MockClient:
        client_instance = mock.MagicMock()
        client_instance.request.return_value = fake_resp
        client_instance.__enter__ = mock.MagicMock(return_value=client_instance)
        client_instance.__exit__ = mock.MagicMock(return_value=False)
        MockClient.return_value = client_instance

        events = list(ApiTestService(db).iter_suite_events(1))

    event_types = [e["event"] for e in events]
    assert "suite_start" in event_types
    assert "suite_result" in event_types

    suite_start = next(e for e in events if e["event"] == "suite_start")
    assert suite_start["suite_name"] == "My Suite"
    assert suite_start["total_cases"] == 2

    suite_result = next(e for e in events if e["event"] == "suite_result")
    assert suite_result["total_cases"] == 2


def test_iter_suite_events_emits_case_start_events() -> None:
    from app.services.api_test_service import ApiTestService

    db = mock.MagicMock()
    suite = _make_fake_suite(id=1)
    case1 = _make_fake_case(suite, id=10, name="First", sequence=1)
    case2 = _make_fake_case(suite, id=11, name="Second", sequence=2)
    execution = mock.MagicMock()
    execution.id = 100

    db.get.side_effect = lambda model, pk: {
        ("ApiTestSuite", 1): suite,
        ("ApiTestCase", 10): case1,
        ("ApiTestCase", 11): case2,
    }.get((model.__name__, pk))
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [case1, case2]
    db.add.return_value = None
    db.commit.return_value = None
    db.refresh.return_value = None

    fake_resp = _make_fake_response(200, {"ok": True})

    with mock.patch("app.services.api_test_service.httpx.Client") as MockClient:
        client_instance = mock.MagicMock()
        client_instance.request.return_value = fake_resp
        client_instance.__enter__ = mock.MagicMock(return_value=client_instance)
        client_instance.__exit__ = mock.MagicMock(return_value=False)
        MockClient.return_value = client_instance

        events = list(ApiTestService(db).iter_suite_events(1))

    case_starts = [e for e in events if e["event"] == "case_start"]
    assert len(case_starts) == 2
    assert case_starts[0]["case_name"] == "First"
    assert case_starts[0]["case_index"] == 1
    assert case_starts[1]["case_name"] == "Second"
    assert case_starts[1]["case_index"] == 2


def test_iter_suite_events_context_sharing() -> None:
    from app.services.api_test_service import ApiTestService

    db = mock.MagicMock()
    suite = _make_fake_suite(id=1)
    case1 = _make_fake_case(
        suite, id=10, name="Login", sequence=1,
        extract_vars={"auth_token": "$.token"},
    )
    case2 = _make_fake_case(
        suite, id=11, name="Get Profile", sequence=2,
        path="/profile",
        headers={"Authorization": "Bearer ${auth_token}"},
    )
    execution = mock.MagicMock()
    execution.id = 100

    call_count = 0

    def fake_db_get(model, pk):
        if model.__name__ == "ApiTestSuite" and pk == 1:
            return suite
        if pk == 10:
            return case1
        if pk == 11:
            return case2
        return None

    db.get.side_effect = fake_db_get
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [case1, case2]
    db.add.return_value = None
    db.commit.return_value = None
    db.refresh.return_value = None

    # First case returns a token, second case should receive it via context
    responses = [
        _make_fake_response(200, {"token": "secret123"}),
        _make_fake_response(200, {"profile": "data"}),
    ]

    with mock.patch("app.services.api_test_service.httpx.Client") as MockClient:
        client_instance = mock.MagicMock()
        client_instance.request.side_effect = responses
        client_instance.__enter__ = mock.MagicMock(return_value=client_instance)
        client_instance.__exit__ = mock.MagicMock(return_value=False)
        MockClient.return_value = client_instance

        events = list(ApiTestService(db).iter_suite_events(1))

    # The second case's request should have the token substituted in headers
    request_events = [e for e in events if e["event"] == "request"]
    assert len(request_events) == 2
    second_req = request_events[1]
    assert second_req["headers"]["Authorization"] == "Bearer secret123"

    # Suite result should include the extracted context
    suite_result = next(e for e in events if e["event"] == "suite_result")
    assert suite_result["context"].get("auth_token") == "secret123"


def test_iter_suite_events_suite_not_found() -> None:
    from app.services.api_test_service import ApiTestService

    db = mock.MagicMock()
    db.get.return_value = None

    import pytest

    with pytest.raises(RuntimeError, match="not found"):
        list(ApiTestService(db).iter_suite_events(999))


def test_iter_suite_events_no_cases_raises() -> None:
    from app.services.api_test_service import ApiTestService

    db = mock.MagicMock()
    suite = _make_fake_suite(id=1)

    def fake_get(model, pk):
        return suite

    db.get.side_effect = fake_get
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

    import pytest

    with pytest.raises(RuntimeError, match="no cases"):
        list(ApiTestService(db).iter_suite_events(1))


def test_iter_suite_events_case_result_events_include_suite_id() -> None:
    from app.services.api_test_service import ApiTestService

    db = mock.MagicMock()
    suite = _make_fake_suite(id=5)
    case1 = _make_fake_case(suite, id=10, name="Case", sequence=1)
    execution = mock.MagicMock()
    execution.id = 100

    def fake_get(model, pk):
        if model.__name__ == "ApiTestSuite" and pk == 5:
            return suite
        if pk == 10:
            return case1
        return None

    db.get.side_effect = fake_get
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [case1]
    db.add.return_value = None
    db.commit.return_value = None
    db.refresh.return_value = None

    fake_resp = _make_fake_response(200, {"ok": True})

    with mock.patch("app.services.api_test_service.httpx.Client") as MockClient:
        client_instance = mock.MagicMock()
        client_instance.request.return_value = fake_resp
        client_instance.__enter__ = mock.MagicMock(return_value=client_instance)
        client_instance.__exit__ = mock.MagicMock(return_value=False)
        MockClient.return_value = client_instance

        events = list(ApiTestService(db).iter_suite_events(5))

    result_events = [e for e in events if e["event"] == "result"]
    assert len(result_events) == 1
    assert result_events[0]["suite_id"] == 5
    assert result_events[0]["case_index"] == 1
