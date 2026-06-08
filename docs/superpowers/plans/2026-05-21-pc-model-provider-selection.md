# PC Model Provider Selection Implementation Plan
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a PC/Web-only model selection layer for AI computer/browser operation, while leaving mobile Open-AutoGLM execution unchanged.

**Architecture:** Keep mobile using `AUTOGLM_*` and the existing mobile execution path. Split PC Agent decisions out of `CASE_PLANNER_*` into a dedicated `PC_AGENT_*` configuration and provider adapter layer. The PC Agent remains screenshot/log/report-first: agent-browser executes browser actions, the model only decides structured actions.

**Tech Stack:** FastAPI, Pydantic settings, OpenAI SDK, optional Anthropic-compatible HTTP adapter, agent-browser CLI, Vue 3 Composition API, Element Plus, pytest, Vite.

---

## Current State

### What PC Execution Uses Now

Current PC/Web execution already exists in two places:

- `frontend/src/views/PCAutoExecute.vue`
  - Uses screenshot-first UI.
  - Calls `openPCBrowser(... headed:false)`.
  - Shows step screenshot, AI log, command log, and page snapshot elements.
  - Does not rely on real-time Electron browser rendering as the core UI.

- `backend/app/services/test_execution_service.py`
  - Detects Web cases through `platform_type`.
  - Uses `PCBrowserService` and `PCBrowserAgentService`.
  - Runs `agent-browser` for PC/Web test cases.
  - Saves step screenshots under the report folder.

- `backend/app/services/pc_browser_agent_service.py`
  - Reads current URL/title/snapshot.
  - Asks the model for the next action.
  - Executes actions through `agent-browser`.
  - Captures screenshots after every step.
  - Pauses with `need_user` for login/password/captcha/QR/2FA.

### Current Weak Point

PC Agent currently reuses:

```text
CASE_PLANNER_BASE_URL
CASE_PLANNER_MODEL
CASE_PLANNER_API_KEY
CASE_PLANNER_TIMEOUT_SECONDS
```

That is convenient but semantically wrong:

- Case Planner should rewrite test cases.
- PC Agent should operate the browser/computer.
- Result Assertion should judge the result.
- Mobile AutoGLM should operate the phone.

These are four different roles and should have separate model configs.

---

## Target Design

### Model Roles

| Role | Environment Variables | Purpose | Mobile Impact |
|---|---|---|---|
| Mobile executor | `AUTOGLM_*` | Open-AutoGLM phone execution | Keep unchanged |
| Case planner | `CASE_PLANNER_*` | Rewrite human cases into task plans | Keep existing behavior |
| PC agent | `PC_AGENT_*` | Decide next browser action for agent-browser | New only for PC/Web |
| Result assertion | `RESULT_ASSERTION_*` | Judge pass/fail/uncertain | Keep existing behavior |

### PC Agent Config

Add these settings:

```env
PC_AGENT_ENABLED=true
PC_AGENT_PROVIDER=openai_compatible
PC_AGENT_BASE_URL=https://open.bigmodel.cn/api/paas/v4
PC_AGENT_MODEL=GLM-4.7-Flash
PC_AGENT_API_KEY=EMPTY
PC_AGENT_TIMEOUT_SECONDS=30
PC_AGENT_TEMPERATURE=0.1
PC_AGENT_MAX_TOKENS=700
```

Fallback rule:

```text
PC_AGENT_API_KEY if configured
  -> CASE_PLANNER_API_KEY if configured
  -> disabled with clear frontend/backend message
```

### Provider Types

Support provider adapters, not scattered conditionals:

| Provider Type | Protocol | Examples | Implementation |
|---|---|---|---|
| `openai_compatible` | OpenAI Chat Completions | Zhipu, DeepSeek, Qwen, Moonshot, MiniMax `/v1`, OpenAI-compatible vLLM | Use OpenAI SDK |
| `anthropic_compatible` | Anthropic Messages | Claude, MiniMax Anthropic endpoint if used | Use lightweight HTTP adapter |
| `custom_openai` | User-defined OpenAI-compatible base URL | local vLLM, LiteLLM, OneAPI | Use OpenAI SDK |

Do not hardcode only one vendor. Presets should fill forms; the runtime should use the selected provider config.

### Initial Presets

The UI should provide presets but still allow custom values:

| Preset | Provider Type | Base URL | Model Example |
|---|---|---|---|
| Zhipu GLM | `openai_compatible` | `https://open.bigmodel.cn/api/paas/v4` | `GLM-4.7-Flash` |
| DeepSeek | `openai_compatible` | `https://api.deepseek.com` | configurable |
| Qwen / DashScope compatible | `openai_compatible` | configurable | configurable |
| Moonshot / Kimi | `openai_compatible` | configurable | configurable |
| MiniMax OpenAI Compatible | `openai_compatible` | `https://api.minimaxi.com/v1` | configurable |
| MiniMax Anthropic Compatible | `anthropic_compatible` | `https://api.minimaxi.com/anthropic` | configurable |
| Local vLLM / OneAPI / LiteLLM | `custom_openai` | user input | user input |

Model names are deliberately configurable because model catalog names change.

---

## Component Map

### Backend

- `backend/app/services/model_provider_service.py`
  - Owns provider presets.
  - Builds request clients.
  - Normalizes responses to `{ content: string }`.
  - Masks API keys in status responses.

- `backend/app/services/pc_agent_model_service.py`
  - Uses `model_provider_service`.
  - Sends PC Agent prompt.
  - Parses structured JSON action.

- `backend/app/services/pc_browser_agent_service.py`
  - Stops calling OpenAI directly.
  - Accepts a `decision_provider`.
  - Defaults to `PCAgentModelService.decide`.
  - Continues to own observe/act/screenshot event loop.

- `backend/app/routers/pc_browser.py`
  - Adds config/status endpoints:
    - `GET /api/pc-browser/agent/model/config`
    - `PUT /api/pc-browser/agent/model/config`
    - `GET /api/pc-browser/agent/model/presets`
    - `POST /api/pc-browser/agent/model/test`

- `backend/app/config.py`
  - Adds `PC_AGENT_*` settings.

- `backend/.env.example`
  - Documents PC Agent model config separately from mobile AutoGLM.

### Frontend

- `frontend/src/api.ts`
  - Add `PCAgentModelConfig`, `PCAgentProviderPreset`, API functions.
  - Extend `PCAgentRunPayload` with optional `model_config_id` only if later persistence is added.

- `frontend/src/views/PCAutoExecute.vue`
  - Add compact model selector panel.
  - Show current provider/model.
  - Allow choosing preset, custom base URL/model/API key.
  - Add “测试连接” button.
  - Keep screenshot-first execution UI.

Future split if the file grows:

- `frontend/src/components/pc/PCAgentModelConfigPanel.vue`
- `frontend/src/composables/usePCAgentModelConfig.ts`

---

## Implementation Tasks

### Task 1: Backend Settings And Presets

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/.env.example`
- Create: `backend/app/services/model_provider_service.py`
- Test: `backend/tests/test_model_provider_service.py`

- [ ] Add `PC_AGENT_*` settings to `Settings`.

Expected fields:

```python
pc_agent_enabled: bool = True
pc_agent_provider: str = "openai_compatible"
pc_agent_base_url: str = ""
pc_agent_model: str = ""
pc_agent_api_key: str = ""
pc_agent_timeout_seconds: float = 30.0
pc_agent_temperature: float = 0.1
pc_agent_max_tokens: int = 700
```

- [ ] Add provider preset dataclass.

```python
@dataclass(frozen=True)
class ModelProviderPreset:
    id: str
    name: str
    provider_type: str
    base_url: str
    default_model: str
    api_key_label: str
    note: str
```

- [ ] Add tests:

```python
def test_pc_agent_config_falls_back_to_case_planner_api_key(monkeypatch):
    from app.config import settings
    from app.services.model_provider_service import ModelProviderService

    monkeypatch.setattr(settings, "pc_agent_api_key", "")
    monkeypatch.setattr(settings, "case_planner_api_key", "planner-key")

    config = ModelProviderService().pc_agent_config()

    assert config.api_key == "planner-key"
```

```python
def test_provider_presets_include_openai_and_anthropic_compatible():
    from app.services.model_provider_service import ModelProviderService

    presets = ModelProviderService().provider_presets()
    types = {preset.provider_type for preset in presets}

    assert "openai_compatible" in types
    assert "anthropic_compatible" in types
```

### Task 2: PC Agent Model Service

**Files:**
- Create: `backend/app/services/pc_agent_model_service.py`
- Modify: `backend/app/services/pc_browser_agent_service.py`
- Test: `backend/tests/test_pc_agent_model_service.py`
- Test: `backend/tests/test_pc_browser_agent_service.py`

- [ ] Move model-calling logic out of `PCBrowserAgentService`.
- [ ] Add `PCAgentModelService.decide(context)`.
- [ ] Keep `PCBrowserAgentService` focused on:
  - observe
  - manual-auth detection
  - execute action
  - screenshot evidence
  - stream events

Desired constructor:

```python
class PCBrowserAgentService:
    def __init__(
        self,
        browser: PCBrowserService | None = None,
        decision_provider: DecisionProvider | None = None,
        artifact_root: Path | None = None,
    ) -> None:
        self.decision_provider = decision_provider or PCAgentModelService().decide
```

- [ ] Add tests:

```python
def test_pc_browser_agent_uses_injected_decision_provider(tmp_path):
    # existing behavior stays passing
```

```python
def test_pc_agent_model_service_uses_pc_agent_config(monkeypatch):
    # fake OpenAI client; assert base_url/model/api_key come from PC_AGENT_*
```

### Task 3: Provider Client Adapters

**Files:**
- Modify: `backend/app/services/model_provider_service.py`
- Test: `backend/tests/test_model_provider_service.py`

- [ ] Implement `OpenAICompatibleClient`.
- [ ] Implement `AnthropicCompatibleClient`.
- [ ] Normalize all provider responses to plain text content.

Adapter interface:

```python
class ChatClient(Protocol):
    def complete_json_action(self, *, messages: list[dict[str, str]], model: str, timeout: float) -> str:
        ...
```

OpenAI-compatible:

```python
OpenAI(base_url=config.base_url, api_key=config.api_key, timeout=config.timeout_seconds)
```

Anthropic-compatible:

```http
POST {base_url}/v1/messages or provider-specific resolved endpoint
headers:
  x-api-key: ...
  anthropic-version: 2023-06-01
body:
  model
  max_tokens
  temperature
  messages
```

Important:

- Do not send API keys to frontend except masked.
- Do not store API keys in reports.
- Log provider/model but mask keys.

### Task 4: PC Browser Model Config API

**Files:**
- Modify: `backend/app/routers/pc_browser.py`
- Test: `backend/tests/test_pc_browser_routes.py`

- [ ] Add response/request models:

```python
class PCAgentModelConfigResponse(BaseModel):
    enabled: bool
    provider: str
    base_url: str
    model: str
    api_key_masked: str
    timeout_seconds: float
    temperature: float
    max_tokens: int
    presets: list[dict[str, str]]
```

```python
class PCAgentModelConfigUpdateRequest(BaseModel):
    enabled: bool
    provider: str
    base_url: str
    model: str
    api_key: str | None = None
    timeout_seconds: float = 30
    temperature: float = 0.1
    max_tokens: int = 700
```

- [ ] Add endpoints:

```text
GET /api/pc-browser/agent/model/config
PUT /api/pc-browser/agent/model/config
GET /api/pc-browser/agent/model/presets
POST /api/pc-browser/agent/model/test
```

- [ ] For the first version, update `.env` through existing settings file helper only if available. If no helper exists, keep runtime-only update and document restart persistence as a follow-up.

### Task 5: Frontend Model Selector

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/views/PCAutoExecute.vue`
- Optional Create: `frontend/src/components/pc/PCAgentModelConfigPanel.vue`

- [ ] Add API types/functions.
- [ ] Add model selector to PC AutoExecute right panel.
- [ ] Keep source state minimal:
  - `pcAgentConfig`
  - `pcAgentPresets`
  - `configBusy`
  - `configTesting`
- [ ] Derived labels via `computed`.
- [ ] Add “测试连接” button.
- [ ] Add save button.

UI fields:

```text
Provider preset
Provider type
Base URL
Model
API key
Timeout
Temperature
Max tokens
```

Do not add this to mobile execution pages.

### Task 6: Test Case Execution Uses PC Agent Config

**Files:**
- Modify: `backend/app/services/test_execution_service.py`
- Test: `backend/tests/test_test_plans.py`

- [ ] Ensure `_run_web_case_events()` uses `PCBrowserAgentService` with the new `PCAgentModelService`.
- [ ] Emit selected provider/model in logs:

```json
{
  "event": "log",
  "phase": "agent",
  "type": "pc_agent_model",
  "provider": "openai_compatible",
  "model": "GLM-4.7-Flash"
}
```

- [ ] Keep mobile paths untouched:
  - `_build_autoglm_command`
  - `_autoglm_env`
  - `_run_autoglm_phase`

### Task 7: Verification

**Commands:**

```powershell
python -m pytest backend\tests -q
npm run build
```

Expected:

```text
backend tests pass
frontend build passes
existing Element Plus chunk warning may remain
```

---

## Acceptance Criteria

- PC/Web execution can choose a model provider independently from mobile AutoGLM.
- Mobile AutoGLM config and execution behavior are unchanged.
- PC Agent logs include selected provider and model.
- PC AutoExecute UI shows current model config.
- API keys are masked in responses and not written to reports.
- OpenAI-compatible providers work through a unified adapter.
- Anthropic-compatible providers have a separate adapter boundary.
- Existing PC screenshot-first behavior remains.
- Existing backend tests continue passing.

---

## Recommended First Implementation Order

1. Backend settings and provider presets.
2. `PCAgentModelService`.
3. Replace direct OpenAI call inside `PCBrowserAgentService`.
4. Add config/status/test endpoints.
5. Add frontend model selector.
6. Add selected provider/model logs to PC execution.
7. Run full verification.
