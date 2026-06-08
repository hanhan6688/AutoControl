from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


ALLOWED_TARGET_APPS = ("乐有家测试版", "乐办公测试版", "微信小程序")


class DeviceStatus(str, Enum):
    online = "online"
    offline = "offline"
    unauthorized = "unauthorized"
    unknown = "unknown"


class DeviceInfo(BaseModel):
    udid: str
    status: DeviceStatus
    platform: str = "android"
    model: str | None = None
    product: str | None = None
    transport_id: str | None = Field(default=None, alias="transport_id")
    os_version: str | None = None
    stream_provider: str | None = None
    stream_available: bool = False
    stream_note: str | None = None


class ScreenshotResponse(BaseModel):
    udid: str
    file_path: str
    url: str
    created_at: datetime


class ScrcpyStartResponse(BaseModel):
    udid: str
    pid: int
    command: list[str]


class ScrcpyStopResponse(BaseModel):
    udid: str
    stopped: bool


class DeviceControlRequest(BaseModel):
    command: str


class DeviceTapRequest(BaseModel):
    x: int
    y: int
    platform: str = "android"
    wda_url: str | None = None


class DeviceConnectRequest(BaseModel):
    address: str  # IP:port or emulator address


class DeviceConnectResponse(BaseModel):
    udid: str
    success: bool
    message: str = ""


class DeviceDisconnectResponse(BaseModel):
    address: str
    success: bool
    message: str = ""


class DeviceControlResponse(BaseModel):
    udid: str
    command: str
    stdout: str = ""
    stderr: str = ""
    success: bool


class VisualClickResponse(BaseModel):
    udid: str
    found: bool
    x: int | None = None
    y: int | None = None
    score: float = 0
    width: int | None = None
    height: int | None = None
    text: str | None = None
    template_path: str | None = None
    message: str = ""


class DeviceTextClickRequest(BaseModel):
    text: str
    contains: bool = True


class DeviceUiLocateRequest(BaseModel):
    x: int
    y: int
    platform: str = "android"
    package_name: str | None = None
    strict_xpath_only: bool = False
    cache_ttl_ms: int = 0
    wda_url: str | None = None


class DeviceUiBoundsResponse(BaseModel):
    left: int
    top: int
    right: int
    bottom: int
    width: int
    height: int
    center_x: int
    center_y: int


class DeviceUiElementResponse(BaseModel):
    platform: str
    package: str | None = None
    class_name: str
    text: str | None = None
    content_desc: str | None = None
    resource_id: str | None = None
    clickable: bool
    enabled: bool
    bounds: DeviceUiBoundsResponse
    xpath: str
    hierarchy_xpath: str | None = None
    selector: dict[str, str] = {}
    input_capable: bool = False
    depth: int
    index: int


class DeviceUiLocateResponse(BaseModel):
    udid: str
    found: bool
    element: DeviceUiElementResponse | None = None
    generated_code: str
    message: str


class HealthResponse(BaseModel):
    status: str
    app_name: str


class ImportedTestCaseResponse(BaseModel):
    id: int
    plan_id: int
    folder_id: int | None = None
    folder_name: str | None = None
    sequence: int
    system_name: str | None = None
    module: str | None = None
    case_name: str
    precondition: str | None = None
    steps: list[str] = []
    expected_result: str | None = None
    requirement_id: str | None = None
    case_type: str | None = None
    priority: str | None = None
    target_app: str | None = None
    test_module: str | None = None
    run_count: int = 0
    latest_result: str = "pending"
    latest_result_note: str = ""

    model_config = {"from_attributes": True}


class ImportedTestCaseCreateRequest(BaseModel):
    case_name: str = Field(..., min_length=1, max_length=500)
    steps: list[str] = Field(..., min_length=1)
    expected_result: str = Field(..., min_length=1)
    folder_id: int | None = None
    system_name: str | None = None
    module: str | None = None
    precondition: str = Field(..., min_length=1)
    requirement_id: str | None = None
    case_type: str | None = None
    priority: str | None = None
    target_app: str = Field(..., min_length=1)
    test_module: str | None = None

    @model_validator(mode="after")
    def validate_target_app(self) -> "ImportedTestCaseCreateRequest":
        if self.target_app not in ALLOWED_TARGET_APPS:
            raise ValueError(f"目标应用不支持：{self.target_app}，仅支持：{', '.join(ALLOWED_TARGET_APPS)}")
        return self

    @field_validator("case_name", "precondition", "expected_result")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("不能为空")
        return stripped

    @field_validator("steps")
    @classmethod
    def strip_steps(cls, value: list[str]) -> list[str]:
        steps = [step.strip() for step in value if step and step.strip()]
        if not steps:
            raise ValueError("至少填写一个用例步骤")
        return steps


class ImportedTestCaseBatchUpdateRequest(BaseModel):
    case_ids: list[int] = Field(..., min_length=1)
    system_name: str | None = None
    module: str | None = None
    target_app: str | None = None
    test_module: str | None = None

    @field_validator("case_ids")
    @classmethod
    def validate_case_ids(cls, value: list[int]) -> list[int]:
        case_ids = [int(item) for item in value if int(item) > 0]
        if not case_ids:
            raise ValueError("至少选择一条有效用例")
        return case_ids

    @field_validator("system_name", "module", "target_app", "test_module", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text

    @model_validator(mode="after")
    def validate_target_app(self) -> "ImportedTestCaseBatchUpdateRequest":
        if self.target_app and self.target_app not in ALLOWED_TARGET_APPS:
            raise ValueError(f"目标应用不支持：{self.target_app}，仅支持：{', '.join(ALLOWED_TARGET_APPS)}")
        return self


class TestPlanProjectResponse(BaseModel):
    id: int
    name: str
    source_filename: str | None = None
    total_cases: int = 0
    imported_at: datetime
    folders: list["TestCaseFolderResponse"] = []
    cases: list[ImportedTestCaseResponse] = []

    model_config = {"from_attributes": True}


class TestCaseFolderResponse(BaseModel):
    """测试用例文档响应"""
    id: int
    plan_id: int
    name: str
    requirement_summary: str | None = None
    source_type: str | None = None
    source_filename: str | None = None
    sequence: int
    total_cases: int
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class TestCaseFolderCreateRequest(BaseModel):
    """创建测试用例文档"""
    name: str = Field(..., min_length=1, max_length=255)
    requirement_summary: str | None = None
    source_type: str | None = "manual"
    source_filename: str | None = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("文档名称不能为空")
        return stripped


class TestCaseFolderUpdateRequest(BaseModel):
    """更新测试用例文档"""
    name: str | None = None
    requirement_summary: str | None = None


class SkippedRowResponse(BaseModel):
    """跳过行的响应模型"""

    row_number: int
    reason: str
    raw_data: dict[str, str] = {}


class ImportResultResponse(BaseModel):
    """导入结果响应模型"""

    id: int
    name: str
    source_filename: str | None = None
    total_cases: int = 0
    imported_at: datetime
    cases: list[ImportedTestCaseResponse] = []
    # 导入统计
    import_summary: dict[str, Any] = {}
    skipped_rows: list[SkippedRowResponse] = []

    model_config = {"from_attributes": True}


class TestPlanListItem(BaseModel):
    id: int
    name: str
    source_filename: str | None = None
    total_cases: int = 0
    imported_at: datetime

    model_config = {"from_attributes": True}


class TestCaseRunRequest(BaseModel):
    device_udid: str | None = None
    device_platform: str | None = None
    client_run_id: str | None = None


class TestCaseExecutionResponse(BaseModel):
    id: int
    plan_id: int
    case_id: int
    run_index: int
    device_udid: str | None = None
    run_result: str
    result_note: str = ""
    error_category: str | None = None
    action_trace: list[dict] = []
    started_at: datetime
    ended_at: datetime | None = None
    duration_ms: int | None = None

    model_config = {"from_attributes": True}


class BatchRunResponse(BaseModel):
    plan_id: int
    total_cases: int
    executions: list[TestCaseExecutionResponse]


class LoginAccountResponse(BaseModel):
    id: int
    platform: str
    label: str
    login_id: str
    password_masked: str
    note: str | None = None
    use_for_autoglm: bool = True
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class LoginAccountCreateRequest(BaseModel):
    platform: str = Field(..., min_length=1, max_length=64)
    label: str = Field(..., min_length=1, max_length=128)
    login_id: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1)
    note: str | None = None
    use_for_autoglm: bool = True

    @field_validator("platform", "label", "login_id", "password", "note")
    @classmethod
    def strip_account_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if "\n" in stripped or "\r" in stripped:
            raise ValueError("不能包含换行符")
        return stripped


class LoginAccountUpdateRequest(BaseModel):
    platform: str = Field(..., min_length=1, max_length=64)
    label: str = Field(..., min_length=1, max_length=128)
    login_id: str = Field(..., min_length=1, max_length=255)
    password: str | None = None
    note: str | None = None
    use_for_autoglm: bool = True

    @field_validator("platform", "label", "login_id", "password", "note")
    @classmethod
    def strip_account_update_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if "\n" in stripped or "\r" in stripped:
            raise ValueError("不能包含换行符")
        return stripped


# ── API Test Schemas ──────────────────────────────────────────────────────────


class ApiTestSuiteCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    base_url: str = Field(default="", max_length=1024)
    headers: dict[str, str] = {}
    auth_type: str | None = None
    auth_config: dict[str, Any] | None = None


class ApiTestSuiteUpdateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    base_url: str = Field(default="", max_length=1024)
    headers: dict[str, str] = {}
    auth_type: str | None = None
    auth_config: dict[str, Any] | None = None


class ApiTestSuiteResponse(BaseModel):
    id: int
    name: str
    base_url: str
    headers: dict[str, Any] = {}
    auth_type: str | None = None
    auth_config: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime | None = None
    cases: list["ApiTestCaseResponse"] = []

    model_config = {"from_attributes": True}


class ApiTestCaseCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=500)
    method: str = Field(default="GET", max_length=16)
    path: str = Field(default="", max_length=1024)
    headers: dict[str, str] = {}
    params: dict[str, Any] = {}
    body: dict[str, Any] | None = None
    expected_status: int = 200
    expected_body_contains: str | None = None
    expected_schema: dict[str, Any] | None = None
    extract_vars: dict[str, str] | None = None
    tags: str | None = None
    priority: str | None = None


class ApiTestCaseUpdateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=500)
    method: str = Field(default="GET", max_length=16)
    path: str = Field(default="", max_length=1024)
    headers: dict[str, str] = {}
    params: dict[str, Any] = {}
    body: dict[str, Any] | None = None
    expected_status: int = 200
    expected_body_contains: str | None = None
    expected_schema: dict[str, Any] | None = None
    extract_vars: dict[str, str] | None = None
    tags: str | None = None
    priority: str | None = None


class ApiTestCaseResponse(BaseModel):
    id: int
    suite_id: int
    sequence: int
    name: str
    method: str
    path: str
    headers: dict[str, Any] = {}
    params: dict[str, Any] = {}
    body: dict[str, Any] | None = None
    expected_status: int = 200
    expected_body_contains: str | None = None
    expected_schema: dict[str, Any] | None = None
    extract_vars: dict[str, Any] | None = None
    tags: str | None = None
    priority: str | None = None
    run_count: int = 0
    latest_result: str = "pending"
    latest_result_note: str = ""

    model_config = {"from_attributes": True}


class ApiTestExecutionResponse(BaseModel):
    id: int
    suite_id: int
    case_id: int
    run_index: int
    request_url: str
    request_method: str
    request_headers: dict[str, Any] = {}
    request_body: dict[str, Any] | None = None
    response_status: int | None = None
    response_headers: dict[str, Any] | None = None
    response_body: dict[str, Any] | None = None
    response_body_text: str | None = None
    response_time_ms: int | None = None
    run_result: str
    result_note: str = ""
    assertion_detail: dict[str, Any] | None = None
    started_at: datetime
    ended_at: datetime | None = None
    duration_ms: int | None = None

    model_config = {"from_attributes": True}


class ApiTestSuiteRunResponse(BaseModel):
    suite_id: int
    total_cases: int
    executions: list[ApiTestExecutionResponse]


# ── PC Agent Run Schemas ──────────────────────────────────────────────────────


class PCAgentRunResponse(BaseModel):
    id: int
    run_id: str
    session: str = "pc-autoexecute"
    task: str
    max_steps: int = 8
    run_result: str = "pending"
    result_note: str = ""
    action_trace: list[dict] = []
    steps_completed: int = 0
    duration_ms: int | None = None
    started_at: datetime
    ended_at: datetime | None = None
    log_url: str | None = None
    report_url: str | None = None

    model_config = {"from_attributes": True}


class PCAgentRunListResponse(BaseModel):
    items: list[PCAgentRunResponse]
    total: int


class MessageResponse(BaseModel):
    message: str


class RequirementAnalysisResponse(BaseModel):
    """AI 生成测试用例的结果响应"""

    id: int
    name: str
    source_filename: str | None = None
    total_cases: int = 0
    imported_at: datetime
    cases: list[ImportedTestCaseResponse] = []
    generation_summary: dict[str, Any] = {}

    model_config = {"from_attributes": True}
