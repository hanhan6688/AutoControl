# Claude Code CLI 集成 PC Agent 设计

## Context

当前 PCExecute 的 Agent 使用自研 observe-decide-act 循环，每步调用 LLM（GPT-4o/DeepSeek 等）获取 JSON action 指令，后端通过 agent-browser 执行。用户希望将 AI 调用逻辑替换为 Claude Code CLI，利用 Claude 的强大推理能力提升测试执行质量，同时保留对其他模型的支持。

## 方案

**后端 CLI 调用（`claude -p`）**，作为新的 `decision_provider` 实现，与现有 LLM provider 并列可选。

### 核心原则

- **替换 decision_provider**：不改 `iter_task_events` 循环结构，只替换决策层
- **兼容多模型**：用户在 PcModelPanel 中选择 provider（claude_code / openai / deepseek 等）
- **Claude 决策 + agent-browser 执行**：Claude 只返回 JSON action，后端执行
- **保留 need_user**：Claude 返回 `need_user` action 时，后端照常暂停/恢复
- **纯文本 prompt**：先不传截图图片，用元素列表 + 任务描述

---

## 1. 后端：ClaudeCodeDecisionProvider

### 1.1 新文件 `backend/app/services/claude_code_decision_provider.py`

```python
class ClaudeCodeDecisionProvider:
    """通过 Claude Code CLI (claude -p) 提供 PC Agent 决策。"""

    def __init__(self, model: str = "sonnet", api_key: str | None = None):
        self.model = model
        self.api_key = api_key

    def decide(self, context: dict[str, Any]) -> dict[str, Any]:
        prompt = self._build_prompt(context)
        cmd = self._build_command(prompt)
        result = subprocess.run(cmd, capture_output=True, timeout=60, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Claude Code CLI 失败: {result.stderr}")
        return parse_decision_json(result.stdout)

    def _build_prompt(self, context: dict) -> str:
        """构建自然语言 prompt，包含任务、页面状态、历史步骤。"""
        # 见下方 prompt 模板

    def _build_command(self, prompt: str) -> list[str]:
        cmd = ["claude", "-p", prompt, "--model", self.model, "--output-format", "json"]
        # api_key 通过环境变量 ANTHROPIC_API_KEY 传递
        return cmd
```

### 1.2 Prompt 模板

```
你是 PC 端自动化测试 Agent。根据当前页面状态决定下一步操作。

## 任务
{task}

## 当前页面
- URL: {url}
- 标题: {title}
- 步骤: {step}/{max_steps}

## 页面可交互元素
{elements_formatted}

## 已执行步骤
{history_formatted}

## 可用操作
- click: 点击元素，需指定 target（如 @e3）
- fill: 填充输入框，需指定 target 和 text
- press: 按键，需指定 key（如 Enter, Tab, Escape）
- scroll: 滚动页面，需指定 direction（up/down）和 amount
- wait_text: 等待文本出现，需指定 text
- need_user: 需要用户手动处理（如登录），需指定 message
- finish: 任务完成，需指定 message

## 输出格式
返回 JSON 对象，包含 action、reason 字段和操作所需参数。

示例:
{"action": "click", "target": "@e3", "reason": "点击搜索按钮"}
{"action": "fill", "target": "@e5", "text": "测试内容", "reason": "在搜索框输入测试内容"}
{"action": "finish", "message": "页面显示搜索结果，任务完成", "reason": "验证通过"}
{"action": "need_user", "message": "检测到登录页面，请手动登录", "reason": "需要人工认证"}
```

### 1.3 API Key 管理

- Claude Code CLI 通过环境变量 `ANTHROPIC_API_KEY` 获取 API key
- 后端在调用 `subprocess.run` 时传入 `env={"ANTHROPIC_API_KEY": api_key}`
- API key 存储在 `ModelProviderService` 的配置中（和现有模型配置一致）

---

## 2. 后端：修改 PCBrowserAgentService

### 2.1 `iter_task_events` 增加 `provider` 参数

```python
async def iter_task_events(
    self,
    *,
    task: str,
    session: str | None = None,
    max_steps: int = 8,
    provider: str = "default",  # 新增：provider 选择
    model: str | None = None,   # 新增：模型覆盖
) -> AsyncIterator[dict[str, Any]]:
```

### 2.2 根据 provider 选择 decision_provider

```python
def _get_decision_provider(self, provider: str, model: str | None) -> DecisionProvider:
    if provider == "claude_code":
        from app.services.claude_code_decision_provider import ClaudeCodeDecisionProvider
        config = ModelProviderService().pc_agent_config()
        api_key = config.api_key  # 从配置获取
        return ClaudeCodeDecisionProvider(
            model=model or config.model or "sonnet",
            api_key=api_key,
        ).decide
    # 默认：现有 PCAgentModelService
    return PCAgentModelService().decide
```

---

## 3. 后端：修改路由层

### 3.1 `PCAgentRunRequest` 增加 `provider` 和 `model` 字段

```python
class PCAgentRunRequest(BaseModel):
    task: str = Field(..., description="PC 端测试任务")
    session: str | None = Field("pc-autoexecute")
    max_steps: int = Field(8, ge=1, le=30)
    provider: str = Field("default", description="决策 provider: default/claude_code")
    model: str | None = Field(None, description="模型覆盖（如 sonnet, opus, haiku）")
```

### 3.2 `run_pc_agent_stream` 传入 provider

```python
async for event in PCBrowserAgentService().iter_task_events(
    task=request.task,
    session=request.session,
    max_steps=request.max_steps,
    provider=request.provider,
    model=request.model,
):
```

---

## 4. 前端：PcModelPanel 增加 Claude Code 选项

### 4.1 Provider presets 增加 claude_code

```typescript
// 在 modelPresets 中增加:
{
  id: 'claude_code',
  name: 'Claude Code (CLI)',
  provider_type: 'claude_code',
  base_url: '',  // 不需要 base_url，走 CLI
  default_model: 'sonnet',
  api_key_label: 'Anthropic API Key',
  note: '通过 Claude Code CLI 调用，需要本地安装 claude 命令',
}
```

### 4.2 PcAgentPanel 传 provider 到 API

当用户选择了 `claude_code` provider 时，`runAgentTask` 需要把 `provider` 和 `model` 传给后端。

---

## 5. 前端：API 层更新

### 5.1 `PCAgentRunPayload` 增加 provider 和 model

```typescript
export interface PCAgentRunPayload {
  task: string
  session?: string | null
  max_steps?: number
  provider?: string      // 新增
  model?: string | null  // 新增
}
```

### 5.2 `usePcAgentRun` 传递 provider

```typescript
// 在 runAgentTask 中:
const finalEvent = await runPCAgentStream(
  {
    task,
    session: sessionName,
    max_steps: agentMaxSteps.value,
    provider: selectedProvider.value,  // 从 model composable 获取
    model: selectedModel.value,
  },
  appendAgentEvent,
  agentController.signal,
)
```

---

## 6. need_user 机制

不需要改动。Claude 返回 `{"action": "need_user", "message": "..."}` 时，后端 `iter_task_events` 中的现有逻辑已经处理：

```python
if action in {"need_user", "manual", "pause"}:
    # 现有的暂停/恢复逻辑
    yield self._event("need_user", ...)
    await agent_session.need_user_event.wait()
    ...
```

---

## 7. 错误处理

- **Claude Code CLI 未安装**：启动时检测 `claude` 命令是否可用，不可用时在 provider 列表中标记 `available: false`
- **CLI 调用超时**：`subprocess.run(timeout=60)` 超时后抛出 `RuntimeError`，被 `iter_task_events` 的 try/except 捕获，yield error 事件
- **API key 无效**：CLI 返回非零退出码和错误信息，解析后返回给前端
- **JSON 解析失败**：使用现有的 `parse_decision_json` 处理（支持 markdown code block 包裹的 JSON）

---

## 8. 文件变更清单

| 操作 | 文件 | 职责 |
|------|------|------|
| 新增 | `backend/app/services/claude_code_decision_provider.py` | Claude Code CLI 决策 provider |
| 修改 | `backend/app/services/pc_browser_agent_service.py` | 增加 provider/model 参数，选择 decision_provider |
| 修改 | `backend/app/routers/pc_browser.py` | PCAgentRunRequest 增加 provider/model，传入 service |
| 修改 | `backend/app/services/pc_agent_model_service.py` | provider presets 增加 claude_code |
| 修改 | `frontend/src/api.ts` | PCAgentRunPayload 增加 provider/model |
| 修改 | `frontend/src/composables/usePcAgentRun.ts` | 传递 provider/model 到 API |
| 修改 | `frontend/src/composables/usePcAgentModel.ts` | 支持 claude_code provider 类型 |

---

## 9. 不在范围内

- 截图图片传给 Claude（后续迭代）
- Claude Code 会话模式（`--resume`）
- Claude API + MCP 直接工具调用
- 替换现有的 agent-browser 执行层
- 前端 UI 大改（只在 PcModelPanel 增加选项）
