from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.database import Base


class User(Base):
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Device(Base):
    __tablename__ = "device"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    udid: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    platform: Mapped[str] = mapped_column(String(32), default="android")
    model: Mapped[str | None] = mapped_column(String(128))
    os_version: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="offline")
    current_task_id: Mapped[int | None] = mapped_column(Integer)
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class TestCase(Base):
    __tablename__ = "test_case"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    case_name: Mapped[str] = mapped_column(String(255), nullable=False)
    module: Mapped[str | None] = mapped_column(String(128))
    raw_text: Mapped[str | None] = mapped_column(Text)
    structured_json: Mapped[dict | None] = mapped_column(JSON)
    expected_result: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class TestScript(Base):
    __tablename__ = "test_script"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("test_case.id"))
    script_type: Mapped[str] = mapped_column(String(64), default="maestro")
    script_content: Mapped[str | None] = mapped_column(Text)
    generated_by_ai: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class TestTask(Base):
    __tablename__ = "test_task"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    task_name: Mapped[str] = mapped_column(String(255), nullable=False)
    script_id: Mapped[int | None] = mapped_column(ForeignKey("test_script.id"))
    device_id: Mapped[int | None] = mapped_column(ForeignKey("device.id"))
    app_version: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    result_summary: Mapped[dict | None] = mapped_column(JSON)
    teardown_done: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class TestResult(Base):
    __tablename__ = "test_result"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("test_task.id"))
    status: Mapped[str | None] = mapped_column(String(32))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    failed_step: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    ai_analysis: Mapped[dict | None] = mapped_column(JSON)
    ai_analysis_status: Mapped[str] = mapped_column(String(32), default="pending")
    report_path: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class TestArtifact(Base):
    __tablename__ = "test_artifact"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    result_id: Mapped[int | None] = mapped_column(ForeignKey("test_result.id"))
    artifact_type: Mapped[str | None] = mapped_column(String(64))
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class TestPlanProject(Base):
    __tablename__ = "test_plan_project"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source_filename: Mapped[str | None] = mapped_column(String(255))
    total_cases: Mapped[int] = mapped_column(Integer, default=0)
    imported_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    folders: Mapped[list["TestCaseFolder"]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="TestCaseFolder.sequence",
    )

    cases: Mapped[list["ImportedTestCase"]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="ImportedTestCase.sequence",
    )


class TestCaseFolder(Base):
    """测试用例文档 - 测试计划与用例之间的中间层级

    一个测试计划包含多个文档，每个文档对应一个功能/需求。
    """

    __tablename__ = "test_case_folder"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    plan_id: Mapped[int] = mapped_column(Integer, ForeignKey("test_plan_project.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    requirement_summary: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[str | None] = mapped_column(String(64))
    source_filename: Mapped[str | None] = mapped_column(String(255))
    sequence: Mapped[int] = mapped_column(Integer, default=0)
    total_cases: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    plan: Mapped[TestPlanProject] = relationship(back_populates="folders")
    cases: Mapped[list["ImportedTestCase"]] = relationship(
        back_populates="folder",
        cascade="all, delete-orphan",
        order_by="ImportedTestCase.sequence",
    )


class ImportedTestCase(Base):
    __tablename__ = "imported_test_case"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("test_plan_project.id"), nullable=False, index=True)
    folder_id: Mapped[int | None] = mapped_column(ForeignKey("test_case_folder.id", ondelete="SET NULL"), nullable=True, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    system_name: Mapped[str | None] = mapped_column(String(128))
    module: Mapped[str | None] = mapped_column(String(128))
    case_name: Mapped[str] = mapped_column(String(500), nullable=False)
    precondition: Mapped[str | None] = mapped_column(Text)
    steps: Mapped[list[str]] = mapped_column(JSON, default=list)
    expected_result: Mapped[str | None] = mapped_column(Text)
    requirement_id: Mapped[str | None] = mapped_column(String(255))
    case_type: Mapped[str | None] = mapped_column(String(64))
    priority: Mapped[str | None] = mapped_column(String(32))
    test_module: Mapped[str | None] = mapped_column(String(128))
    target_app: Mapped[str | None] = mapped_column(String(128))
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    latest_result: Mapped[str] = mapped_column(String(32), default="pending")
    latest_result_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    plan: Mapped[TestPlanProject] = relationship(back_populates="cases")
    folder: Mapped[TestCaseFolder | None] = relationship(back_populates="cases")
    executions: Mapped[list["TestCaseExecution"]] = relationship(
        back_populates="case",
        cascade="all, delete-orphan",
        order_by="TestCaseExecution.run_index",
    )


class TestCaseExecution(Base):
    __tablename__ = "test_case_execution"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("test_plan_project.id"), nullable=False, index=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("imported_test_case.id"), nullable=False, index=True)
    run_index: Mapped[int] = mapped_column(Integer, nullable=False)
    device_udid: Mapped[str | None] = mapped_column(String(128))
    run_result: Mapped[str] = mapped_column(String(32), default="pending")
    result_note: Mapped[str] = mapped_column(Text, default="")
    autoglm_configured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_category: Mapped[str | None] = mapped_column(String(64))
    trace_id: Mapped[str | None] = mapped_column(String(64))
    action_trace: Mapped[list[dict]] = mapped_column(JSON, default=list)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)
    duration_ms: Mapped[int | None] = mapped_column(Integer)

    case: Mapped[ImportedTestCase] = relationship(back_populates="executions")


class LoginAccount(Base):
    __tablename__ = "login_account"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    platform: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    login_id: Mapped[str] = mapped_column(String(255), nullable=False)
    password: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    use_for_autoglm: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class ApiTestSuite(Base):
    __tablename__ = "api_test_suite"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    base_url: Mapped[str] = mapped_column(String(1024), default="", server_default="")
    headers: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    auth_type: Mapped[str | None] = mapped_column(String(32))
    auth_config: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    cases: Mapped[list["ApiTestCase"]] = relationship(
        back_populates="suite",
        cascade="all, delete-orphan",
        order_by="ApiTestCase.sequence",
    )


class ApiTestCase(Base):
    __tablename__ = "api_test_case"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    suite_id: Mapped[int] = mapped_column(ForeignKey("api_test_suite.id"), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    method: Mapped[str] = mapped_column(String(16), default="GET", server_default="GET")
    path: Mapped[str] = mapped_column(String(1024), default="", server_default="")
    headers: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    params: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    body: Mapped[dict | None] = mapped_column(JSON)
    expected_status: Mapped[int] = mapped_column(Integer, default=200, server_default="200")
    expected_body_contains: Mapped[str | None] = mapped_column(Text)
    expected_schema: Mapped[dict | None] = mapped_column(JSON)
    extract_vars: Mapped[dict | None] = mapped_column(JSON)
    tags: Mapped[str | None] = mapped_column(String(255))
    priority: Mapped[str | None] = mapped_column(String(16))
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    latest_result: Mapped[str] = mapped_column(String(32), default="pending", server_default="pending")
    latest_result_note: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    suite: Mapped[ApiTestSuite] = relationship(back_populates="cases")
    executions: Mapped[list["ApiTestExecution"]] = relationship(
        back_populates="case",
        cascade="all, delete-orphan",
        order_by="ApiTestExecution.run_index",
    )


class ApiTestExecution(Base):
    __tablename__ = "api_test_execution"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    suite_id: Mapped[int] = mapped_column(ForeignKey("api_test_suite.id"), nullable=False, index=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("api_test_case.id"), nullable=False, index=True)
    run_index: Mapped[int] = mapped_column(Integer, nullable=False)
    request_url: Mapped[str] = mapped_column(Text, default="", server_default="")
    request_method: Mapped[str] = mapped_column(String(16), default="GET", server_default="GET")
    request_headers: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    request_body: Mapped[dict | None] = mapped_column(JSON)
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_headers: Mapped[dict | None] = mapped_column(JSON)
    response_body: Mapped[dict | None] = mapped_column(JSON)
    response_body_text: Mapped[str | None] = mapped_column(Text)
    response_time_ms: Mapped[int | None] = mapped_column(Integer)
    run_result: Mapped[str] = mapped_column(String(32), default="pending", server_default="pending")
    result_note: Mapped[str] = mapped_column(Text, default="", server_default="")
    assertion_detail: Mapped[dict | None] = mapped_column(JSON)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)
    duration_ms: Mapped[int | None] = mapped_column(Integer)

    case: Mapped[ApiTestCase] = relationship(back_populates="executions")


class PCAgentRun(Base):
    """PC Agent 运行记录。"""

    __tablename__ = "pc_agent_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    run_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    session: Mapped[str] = mapped_column(String(64), default="pc-autoexecute", server_default="pc-autoexecute")
    task: Mapped[str] = mapped_column(Text, nullable=False)
    max_steps: Mapped[int] = mapped_column(Integer, default=8, server_default="8")
    run_result: Mapped[str] = mapped_column(String(32), default="pending", server_default="pending")
    result_note: Mapped[str] = mapped_column(Text, default="", server_default="")
    action_trace: Mapped[list[dict]] = mapped_column(JSON, default=list, server_default="[]")
    steps_completed: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)
    log_url: Mapped[str | None] = mapped_column(Text)
    report_url: Mapped[str | None] = mapped_column(Text)
