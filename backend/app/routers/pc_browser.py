"""PC端浏览器自动化 API 路由。"""

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from app.config import settings
from app.error_handler import handle_service_errors
from app.services.model_provider_service import ModelProviderService
from app.services.pc_agent_model_service import PCAgentModelService
from app.services.pc_browser_agent_service import PCBrowserAgentService, _agent_sessions
from app.services.pc_browser_service import PCBrowserService, BrowserError

router = APIRouter(prefix="/api/pc-browser", tags=["PC Browser Automation"])
LEYOUJIA_LOGIN_URL = "https://itest.leyoujia.com/jjslogin/index"
LEYOUJIA_PROD_LOGIN_URL = "https://i.leyoujia.com/jjslogin/index"
LEYOUJIA_AUTH_PROFILES = {
    "test": {
        "env": "test",
        "label": "测试环境",
        "login_url": LEYOUJIA_LOGIN_URL,
        "target_url": "https://zero-ai-test.leyoujia.com/",
        "state_file": "leyoujia-test.json",
    },
    "prod": {
        "env": "prod",
        "label": "生产环境",
        "login_url": LEYOUJIA_PROD_LOGIN_URL,
        "target_url": "https://zero-ai.leyoujia.com/",
        "state_file": "leyoujia-prod.json",
    },
}

# 全局服务实例
_browser_service = PCBrowserService()
handle_browser_errors = handle_service_errors({BrowserError: 500})


def _create_pc_browser_agent_service(provider: str = "default", model: str | None = None) -> PCBrowserAgentService:
    try:
        return PCBrowserAgentService(provider=provider, model=model)
    except TypeError as exc:
        if "unexpected keyword" not in str(exc):
            raise
        return PCBrowserAgentService()


def _create_pc_agent_model_service(config: Any) -> PCAgentModelService:
    try:
        return PCAgentModelService(config_provider=lambda: config)
    except TypeError as exc:
        if "unexpected keyword" not in str(exc):
            raise
        return PCAgentModelService()


class OpenBrowserRequest(BaseModel):
    url: str = Field(..., description="要打开的URL")
    session: str | None = Field(None, description="会话名称，用于多会话隔离")
    headed: bool = Field(False, description="是否显示浏览器窗口")


class OpenBrowserResponse(BaseModel):
    session_id: str
    url: str
    title: str


class SnapshotResponse(BaseModel):
    elements: list[dict[str, Any]]


class ClickRequest(BaseModel):
    element_ref: str = Field(..., description="元素引用，如 @e1")
    session: str | None = None
    new_tab: bool = False


class FillRequest(BaseModel):
    element_ref: str = Field(..., description="输入框元素引用")
    text: str = Field(..., description="要输入的文本")
    session: str | None = None


class TypeRequest(BaseModel):
    element_ref: str = Field(..., description="元素引用")
    text: str = Field(..., description="要输入的文本")
    session: str | None = None


class PressRequest(BaseModel):
    key: str = Field(..., description="按键名称，如 Enter, Tab, Escape")
    session: str | None = None


class ScrollRequest(BaseModel):
    direction: str = Field("down", description="滚动方向: up/down/left/right")
    amount: int = Field(300, description="滚动像素数")
    session: str | None = None


class ScreenshotRequest(BaseModel):
    path: str | None = Field(None, description="保存路径，不指定则使用临时路径")
    full_page: bool = Field(False, description="是否截取完整页面")
    session: str | None = None


class ScreenshotResponse(BaseModel):
    path: str
    url: str = ""


class WaitElementRequest(BaseModel):
    element_ref: str = Field(..., description="元素引用")
    timeout_ms: int = Field(25000, description="超时时间（毫秒）")
    session: str | None = None


class WaitTextRequest(BaseModel):
    text: str = Field(..., description="等待出现的文本")
    timeout_ms: int = Field(25000, description="超时时间（毫秒）")
    session: str | None = None


class WaitUrlRequest(BaseModel):
    pattern: str = Field(..., description="URL匹配模式，支持通配符 **")
    timeout_ms: int = Field(25000, description="超时时间（毫秒）")
    session: str | None = None


class WaitLoadRequest(BaseModel):
    load_type: str = Field("networkidle", description="加载类型: networkidle/domcontentloaded")
    session: str | None = None


class EvalJsRequest(BaseModel):
    script: str = Field(..., description="要执行的JavaScript代码")
    session: str | None = None


class SelectRequest(BaseModel):
    element_ref: str = Field(..., description="下拉框元素引用")
    value: str = Field(..., description="选项值")
    session: str | None = None


class UploadRequest(BaseModel):
    element_ref: str = Field(..., description="文件上传元素引用")
    file_path: str = Field(..., description="文件路径")
    session: str | None = None


class TabRequest(BaseModel):
    url: str | None = Field(None, description="新标签页URL")
    label: str | None = Field(None, description="标签页标签")
    session: str | None = None


class TabSwitchRequest(BaseModel):
    tab_id_or_label: str = Field(..., description="标签页ID或标签")
    session: str | None = None


class TabSwitchUrlRequest(BaseModel):
    pattern: str = Field(..., description="URL 匹配模式，例如 *example.com*")
    session: str | None = None


class TabCloseRequest(BaseModel):
    tab_id_or_label: str | None = Field(None, description="标签页ID或标签，不指定则关闭当前")
    session: str | None = None


class RecordRequest(BaseModel):
    output_path: str = Field(..., description="视频输出路径")
    session: str | None = None


class FindClickRequest(BaseModel):
    text: str = Field(..., description="要查找的文本")
    exact: bool = Field(False, description="是否精确匹配")
    session: str | None = None


class FindFillRequest(BaseModel):
    label: str = Field(..., description="标签文本")
    text: str = Field(..., description="要输入的文本")
    session: str | None = None


class StatePathRequest(BaseModel):
    path: str = Field(..., description="状态文件路径")
    session: str | None = None


class SessionRequest(BaseModel):
    session: str | None = None


class PCAgentRunRequest(BaseModel):
    task: str = Field(..., description="PC 端测试任务")
    session: str | None = Field("pc-autoexecute", description="agent-browser 会话名称")
    max_steps: int = Field(8, ge=1, le=30, description="最大执行步数")
    provider: str = Field("default", description="决策 provider: default/claude_code")
    model: str | None = Field(None, description="模型覆盖（如 sonnet, opus, haiku）")

    @field_validator("task")
    @classmethod
    def strip_task(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("任务不能为空")
        return stripped


class PCAgentModelConfigUpdateRequest(BaseModel):
    enabled: bool = True
    provider: str = Field("minimax_auto", min_length=1)
    base_url: str = ""
    model: str = ""
    api_key: str | None = None
    timeout_seconds: float = Field(30.0, ge=1, le=300)
    temperature: float = Field(0.1, ge=0, le=2)
    max_tokens: int = Field(300, ge=128, le=8192)


class PCAgentModelTestRequest(BaseModel):
    task: str = "测试 PC Agent 模型连接"
    config: PCAgentModelConfigUpdateRequest | None = None


class LeyoujiaAuthRequest(BaseModel):
    session: str | None = Field("pc-autoexecute", description="agent-browser 会话名称")
    env: str = Field("test", description="Leyoujia 环境：test/prod")


@router.post("/open", response_model=OpenBrowserResponse)
@handle_browser_errors
async def open_browser(request: OpenBrowserRequest) -> OpenBrowserResponse:
    """打开浏览器并导航到指定URL。"""
    result = _browser_service.open(
        url=request.url,
        session=request.session,
        headed=request.headed,
    )
    return OpenBrowserResponse(
        session_id=result.session_id,
        url=result.url,
        title=result.title,
    )


@router.get("/logs")
async def get_logs(session: str | None = None, limit: int = 100) -> dict[str, Any]:
    """获取 agent-browser 命令日志。"""
    entries = _browser_service.logs(session=session, limit=limit)
    return {
        "logs": [
            {
                "timestamp": entry.timestamp,
                "session": entry.session,
                "command": entry.command,
                "returncode": entry.returncode,
                "stdout": entry.stdout,
                "stderr": entry.stderr,
                "ok": entry.ok,
            }
            for entry in entries
        ]
    }


@router.post("/agent/run/stream")
async def run_pc_agent_stream(request: PCAgentRunRequest) -> StreamingResponse:
    """流式执行 PC Agent 单任务。"""

    async def iter_lines():
        try:
            async for event in _create_pc_browser_agent_service(
                provider=request.provider,
                model=request.model,
            ).iter_task_events(
                task=request.task,
                session=request.session,
                max_steps=request.max_steps,
            ):
                yield json.dumps(event, ensure_ascii=False) + "\n"
        except BrowserError as exc:
            yield json.dumps(
                {
                    "event": "error",
                    "type": "error",
                    "phase": "execution",
                    "message": str(exc),
                    "run_result": "failed",
                },
                ensure_ascii=False,
            ) + "\n"

    return StreamingResponse(iter_lines(), media_type="application/x-ndjson")


@router.post("/agent/run/{run_id}/resume")
async def resume_agent_run(run_id: str) -> dict[str, str]:
    """恢复暂停的 Agent 运行。"""
    session = _agent_sessions.get(run_id)
    if not session:
        raise HTTPException(status_code=404, detail="运行会话不存在或已结束")
    session.need_user_event.set()
    return {"status": "resumed"}


@router.post("/agent/run/{run_id}/cancel")
async def cancel_agent_run(run_id: str) -> dict[str, str]:
    """取消暂停的 Agent 运行。"""
    session = _agent_sessions.get(run_id)
    if not session:
        raise HTTPException(status_code=404, detail="运行会话不存在或已结束")
    session.cancelled = True
    session.need_user_event.set()
    return {"status": "cancelled"}


@router.get("/agent/runs")
def list_pc_agent_runs(page: int = 1, page_size: int = 20) -> dict[str, Any]:
    """获取 PC Agent 运行历史列表。"""
    from sqlalchemy import desc

    from app.database import SessionLocal
    from app.models import PCAgentRun

    db = SessionLocal()
    try:
        total = db.query(PCAgentRun).count()
        records = (
            db.query(PCAgentRun)
            .order_by(desc(PCAgentRun.started_at))
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        items = []
        for r in records:
            items.append({
                "id": r.id,
                "run_id": r.run_id,
                "session": r.session,
                "task": r.task,
                "max_steps": r.max_steps,
                "run_result": r.run_result,
                "result_note": r.result_note,
                "action_trace": r.action_trace or [],
                "steps_completed": r.steps_completed,
                "duration_ms": r.duration_ms,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "ended_at": r.ended_at.isoformat() if r.ended_at else None,
                "log_url": r.log_url,
                "report_url": r.report_url,
            })
        return {"items": items, "total": total}
    finally:
        db.close()


@router.delete("/agent/runs/{run_id}")
def delete_pc_agent_run(run_id: str) -> dict[str, str]:
    """删除 PC Agent 运行记录。"""
    from app.database import SessionLocal
    from app.models import PCAgentRun

    db = SessionLocal()
    try:
        record = db.query(PCAgentRun).filter(PCAgentRun.run_id == run_id).first()
        if not record:
            # 尝试按数据库 id 查找
            try:
                int_id = int(run_id)
                record = db.query(PCAgentRun).filter(PCAgentRun.id == int_id).first()
            except (ValueError, TypeError):
                pass
        if not record:
            raise HTTPException(status_code=404, detail="运行记录不存在")
        db.delete(record)
        db.commit()
        return {"status": "deleted"}
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="删除运行记录失败")
    finally:
        db.close()


@router.get("/auth/leyoujia/status")
def get_leyoujia_auth_status(env: str = "test") -> dict[str, Any]:
    profile = _leyoujia_profile(env)
    state_path = _leyoujia_state_path(env)
    return {
        "env": profile["env"],
        "label": profile["label"],
        "login_url": profile["login_url"],
        "target_url": profile["target_url"],
        "state_exists": state_path.exists(),
        "state_path": str(state_path),
    }


@router.post("/auth/leyoujia/open-login", response_model=OpenBrowserResponse)
@handle_browser_errors
def open_leyoujia_login(request: LeyoujiaAuthRequest) -> OpenBrowserResponse:
    profile = _leyoujia_profile(request.env)
    result = _browser_service.open(
        url=profile["login_url"],
        session=request.session,
        headed=True,
    )
    return OpenBrowserResponse(session_id=result.session_id, url=result.url, title=result.title)


@router.post("/auth/leyoujia/save")
@handle_browser_errors
def save_leyoujia_auth(request: LeyoujiaAuthRequest) -> dict[str, Any]:
    profile = _leyoujia_profile(request.env)
    state_path = _leyoujia_state_path(request.env)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    _browser_service.save_state(path=state_path, session=request.session)
    return {
        "status": "state_saved",
        "env": profile["env"],
        "label": profile["label"],
        "login_url": profile["login_url"],
        "target_url": profile["target_url"],
        "state_exists": state_path.exists(),
        "state_path": str(state_path),
    }


@router.post("/auth/leyoujia/load")
@handle_browser_errors
def load_leyoujia_auth(request: LeyoujiaAuthRequest) -> dict[str, Any]:
    profile = _leyoujia_profile(request.env)
    state_path = _leyoujia_state_path(request.env)
    if not state_path.exists():
        raise HTTPException(status_code=404, detail=f"Leyoujia {profile['label']}登录态不存在，请先登录并保存。")
    _browser_service.load_state(path=state_path, session=request.session)
    return {
        "status": "state_loaded",
        "env": profile["env"],
        "label": profile["label"],
        "login_url": profile["login_url"],
        "target_url": profile["target_url"],
        "state_exists": True,
        "state_path": str(state_path),
    }


@router.get("/agent/model/presets")
def get_pc_agent_model_presets() -> dict[str, Any]:
    presets = ModelProviderService().provider_presets()
    return {"presets": [preset.to_dict() for preset in presets]}


@router.get("/agent/model/config")
def get_pc_agent_model_config() -> dict[str, Any]:
    service = ModelProviderService()
    config = service.pc_agent_config().public_dict()
    config["presets"] = [preset.to_dict() for preset in service.provider_presets()]
    return config


@router.put("/agent/model/config")
def update_pc_agent_model_config(request: PCAgentModelConfigUpdateRequest) -> dict[str, Any]:
    service = ModelProviderService()
    config = service.apply_runtime_pc_agent_config(request.model_dump()).public_dict()
    config["presets"] = [preset.to_dict() for preset in service.provider_presets()]
    return config


@router.post("/agent/model/test")
def test_pc_agent_model(request: PCAgentModelTestRequest) -> dict[str, Any]:
    try:
        provider_service = ModelProviderService()
        config = provider_service.pc_agent_config()
        if request.config:
            config = provider_service.pc_agent_config_from_payload(request.config.model_dump())

        # 判断是否使用 Claude Code CLI
        if config.provider.strip().lower() == "claude_code":
            from app.services.claude_code_decision_provider import ClaudeCodeDecisionProvider
            decision_provider = ClaudeCodeDecisionProvider(
                model=config.model or "sonnet",
                api_key=config.api_key or None,
            )
        else:
            model_service = _create_pc_agent_model_service(config)
            decision_provider = model_service

        context = {
            "task": request.task,
            "step": 1,
            "url": "about:blank",
            "title": "PC Agent Model Test",
            "elements": [{"ref": "@e1", "tag": "button", "text": "测试按钮", "attrs": {}}],
            "history": [],
        }
        decision = decision_provider.decide(context)
        return {"ok": True, "decision": decision}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.post("/close")
@handle_browser_errors
async def close_browser(request: SessionRequest) -> dict[str, str]:
    """关闭浏览器会话。"""
    _browser_service.close(session=request.session)
    return {"status": "closed"}


@router.post("/close-all")
@handle_browser_errors
async def close_all_browsers() -> dict[str, str]:
    """关闭所有浏览器会话。"""
    _browser_service.close_all()
    return {"status": "all_closed"}


@router.get("/snapshot", response_model=SnapshotResponse)
@handle_browser_errors
async def get_snapshot(session: str | None = None, include_bounds: bool = False) -> SnapshotResponse:
    """获取页面快照，返回可交互元素列表。"""
    elements = _browser_service.snapshot(interactive_only=True, session=session, include_bounds=include_bounds)
    return SnapshotResponse(
        elements=[
            {
                "ref": e.ref,
                "tag": e.tag,
                "text": e.text,
                "attrs": e.attrs,
                "bounds": e.bounds,
            }
            for e in elements
        ]
    )


@router.post("/click")
@handle_browser_errors
async def click_element(request: ClickRequest) -> dict[str, str]:
    """点击元素。"""
    _browser_service.click(
        element_ref=request.element_ref,
        session=request.session,
        new_tab=request.new_tab,
    )
    return {"status": "clicked", "element": request.element_ref}


@router.post("/fill")
@handle_browser_errors
async def fill_input(request: FillRequest) -> dict[str, str]:
    """填充输入框（先清空再输入）。"""
    _browser_service.fill(
        element_ref=request.element_ref,
        text=request.text,
        session=request.session,
    )
    return {"status": "filled", "element": request.element_ref}


@router.post("/type")
@handle_browser_errors
async def type_text(request: TypeRequest) -> dict[str, str]:
    """在元素中输入文本（不清空）。"""
    _browser_service.type_text(
        element_ref=request.element_ref,
        text=request.text,
        session=request.session,
    )
    return {"status": "typed", "element": request.element_ref}


@router.post("/press")
@handle_browser_errors
async def press_key(request: PressRequest) -> dict[str, str]:
    """按键。"""
    _browser_service.press(key=request.key, session=request.session)
    return {"status": "pressed", "key": request.key}


@router.post("/hover")
@handle_browser_errors
async def hover_element(request: ClickRequest) -> dict[str, str]:
    """悬停在元素上。"""
    _browser_service.hover(element_ref=request.element_ref, session=request.session)
    return {"status": "hovered", "element": request.element_ref}


@router.post("/scroll")
@handle_browser_errors
async def scroll_page(request: ScrollRequest) -> dict[str, str]:
    """滚动页面。"""
    _browser_service.scroll(
        direction=request.direction,
        amount=request.amount,
        session=request.session,
    )
    return {"status": "scrolled", "direction": request.direction}


@router.post("/screenshot", response_model=ScreenshotResponse)
@handle_browser_errors
async def take_screenshot(request: ScreenshotRequest) -> ScreenshotResponse:
    """截取屏幕截图。"""
    if request.path:
        path = Path(request.path)
    else:
        import uuid
        target_dir = Path("pc-browser")
        path = target_dir / f"screenshot_{uuid.uuid4().hex[:8]}.png"
    if path.is_absolute():
        path = _safe_absolute_upload_path(path)
    else:
        path = Path("pc-browser") / path.name if path.parent == Path(".") else path
        path = _safe_upload_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    result = _browser_service.screenshot(
        path=path,
        full_page=request.full_page,
        session=request.session,
    )
    # Compute relative URL for frontend consumption
    uploads_root = (Path(__file__).resolve().parents[2] / "static" / "uploads").resolve()
    url = ""
    try:
        relative = result.resolve().relative_to(uploads_root)
        url = f"/static/uploads/{relative.as_posix()}"
    except (ValueError, OSError):
        pass
    return ScreenshotResponse(path=str(result), url=url)


def _safe_upload_path(path: Path) -> Path:
    root = (Path(__file__).resolve().parents[2] / "static" / "uploads").resolve()
    resolved = (root / path).resolve()
    if root != resolved and root not in resolved.parents:
        raise HTTPException(status_code=400, detail="Invalid screenshot path")
    return resolved


def _safe_absolute_upload_path(path: Path) -> Path:
    root = (Path(__file__).resolve().parents[2] / "static" / "uploads").resolve()
    resolved = path.resolve()
    if root != resolved and root not in resolved.parents:
        raise HTTPException(status_code=400, detail="Invalid screenshot path")
    return resolved


def _leyoujia_profile(env: str) -> dict[str, str]:
    key = (env or "test").strip().lower()
    profile = LEYOUJIA_AUTH_PROFILES.get(key)
    if not profile:
        raise HTTPException(status_code=400, detail="Leyoujia 环境只支持 test 或 prod。")
    return profile


def _leyoujia_state_path(env: str = "test") -> Path:
    profile = _leyoujia_profile(env)
    return (settings.backend_dir / ".pc_auth" / profile["state_file"]).resolve()


@router.get("/url")
@handle_browser_errors
async def get_current_url(session: str | None = None) -> dict[str, str]:
    """获取当前页面URL。"""
    url = _browser_service.get_url(session=session)
    return {"url": url}


@router.get("/title")
@handle_browser_errors
async def get_current_title(session: str | None = None) -> dict[str, str]:
    """获取当前页面标题。"""
    title = _browser_service.get_title(session=session)
    return {"title": title}


@router.get("/text/{element_ref}")
@handle_browser_errors
async def get_element_text(element_ref: str, session: str | None = None) -> dict[str, str]:
    """获取元素的文本内容。"""
    text = _browser_service.get_text(element_ref=element_ref, session=session)
    return {"element": element_ref, "text": text}


@router.post("/wait/element")
@handle_browser_errors
async def wait_for_element(request: WaitElementRequest) -> dict[str, str]:
    """等待元素出现。"""
    _browser_service.wait_for_element(
        element_ref=request.element_ref,
        timeout_ms=request.timeout_ms,
        session=request.session,
    )
    return {"status": "element_found", "element": request.element_ref}


@router.post("/wait/text")
@handle_browser_errors
async def wait_for_text(request: WaitTextRequest) -> dict[str, str]:
    """等待文本出现。"""
    _browser_service.wait_for_text(
        text=request.text,
        timeout_ms=request.timeout_ms,
        session=request.session,
    )
    return {"status": "text_found", "text": request.text}


@router.post("/wait/url")
@handle_browser_errors
async def wait_for_url(request: WaitUrlRequest) -> dict[str, str]:
    """等待URL匹配。"""
    _browser_service.wait_for_url(
        pattern=request.pattern,
        timeout_ms=request.timeout_ms,
        session=request.session,
    )
    return {"status": "url_matched", "pattern": request.pattern}


@router.post("/wait/load")
@handle_browser_errors
async def wait_for_load(request: WaitLoadRequest) -> dict[str, str]:
    """等待页面加载完成。"""
    _browser_service.wait_for_load(
        load_type=request.load_type,
        session=request.session,
    )
    return {"status": "loaded"}


@router.post("/eval")
@handle_browser_errors
async def evaluate_javascript(request: EvalJsRequest) -> dict[str, str]:
    """执行JavaScript代码。"""
    result = _browser_service.eval_js(script=request.script, session=request.session)
    return {"result": result}


@router.post("/select")
@handle_browser_errors
async def select_option(request: SelectRequest) -> dict[str, str]:
    """选择下拉框选项。"""
    _browser_service.select_option(
        element_ref=request.element_ref,
        value=request.value,
        session=request.session,
    )
    return {"status": "selected", "element": request.element_ref, "value": request.value}


@router.post("/check")
@handle_browser_errors
async def check_checkbox(request: ClickRequest) -> dict[str, str]:
    """勾选复选框。"""
    _browser_service.check(element_ref=request.element_ref, session=request.session)
    return {"status": "checked", "element": request.element_ref}


@router.post("/uncheck")
@handle_browser_errors
async def uncheck_checkbox(request: ClickRequest) -> dict[str, str]:
    """取消勾选复选框。"""
    _browser_service.uncheck(element_ref=request.element_ref, session=request.session)
    return {"status": "unchecked", "element": request.element_ref}


@router.post("/upload")
@handle_browser_errors
async def upload_file(request: UploadRequest) -> dict[str, str]:
    """上传文件。"""
    _browser_service.upload_file(
        element_ref=request.element_ref,
        file_path=request.file_path,
        session=request.session,
    )
    return {"status": "uploaded", "element": request.element_ref}


@router.get("/tabs")
@handle_browser_errors
async def list_tabs(session: str | None = None) -> dict[str, Any]:
    """列出所有标签页。"""
    tabs = _browser_service.tab_list(session=session)
    return {"tabs": tabs}


@router.post("/tabs/new")
@handle_browser_errors
async def new_tab(request: TabRequest) -> dict[str, str]:
    """打开新标签页。"""
    _browser_service.tab_new(url=request.url, label=request.label, session=request.session)
    return {"status": "tab_created"}


@router.post("/tabs/switch")
@handle_browser_errors
async def switch_tab(request: TabSwitchRequest) -> dict[str, str]:
    """切换标签页。"""
    _browser_service.tab_switch(
        tab_id_or_label=request.tab_id_or_label,
        session=request.session,
    )
    return {"status": "tab_switched", "tab": request.tab_id_or_label}


@router.post("/tabs/switch-url")
@handle_browser_errors
async def switch_tab_by_url(request: TabSwitchUrlRequest) -> dict[str, str]:
    """按 URL 模式切换标签页。"""
    _browser_service.tab_switch_url(pattern=request.pattern, session=request.session)
    return {"status": "tab_switched", "pattern": request.pattern}


@router.post("/tabs/close")
@handle_browser_errors
async def close_tab(request: TabCloseRequest) -> dict[str, str]:
    """关闭标签页。"""
    _browser_service.tab_close(
        tab_id_or_label=request.tab_id_or_label,
        session=request.session,
    )
    return {"status": "tab_closed"}


@router.post("/record/start")
@handle_browser_errors
async def start_recording(request: RecordRequest) -> dict[str, str]:
    """开始录制视频。"""
    _browser_service.record_start(output_path=request.output_path, session=request.session)
    return {"status": "recording_started", "output_path": request.output_path}


@router.post("/record/stop")
@handle_browser_errors
async def stop_recording(request: SessionRequest) -> dict[str, str]:
    """停止录制视频。"""
    _browser_service.record_stop(session=request.session)
    return {"status": "recording_stopped"}


@router.post("/find/click")
@handle_browser_errors
async def find_and_click(request: FindClickRequest) -> dict[str, str]:
    """通过文本查找并点击元素。"""
    _browser_service.find_and_click(
        text=request.text,
        exact=request.exact,
        session=request.session,
    )
    return {"status": "clicked", "text": request.text}


@router.post("/find/fill")
@handle_browser_errors
async def find_and_fill(request: FindFillRequest) -> dict[str, str]:
    """通过标签查找输入框并填充。"""
    _browser_service.find_and_fill(
        label=request.label,
        text=request.text,
        session=request.session,
    )
    return {"status": "filled", "label": request.label}


@router.post("/state/save")
@handle_browser_errors
async def save_state(request: StatePathRequest) -> dict[str, str]:
    """保存会话状态。"""
    _browser_service.save_state(path=request.path, session=request.session)
    return {"status": "state_saved", "path": request.path}


@router.post("/state/load")
@handle_browser_errors
async def load_state(request: StatePathRequest) -> dict[str, str]:
    """加载会话状态。"""
    _browser_service.load_state(path=request.path, session=request.session)
    return {"status": "state_loaded", "path": request.path}
