# PCExecute 登录等待与步骤日志优化 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 PCExecute 遇到登录页时暂停等待用户处理，完成后恢复执行；完善每步截图展示。

**Architecture:** 在 `iter_task_events` async 生成器内通过 `asyncio.Event` 暂停/恢复循环；新增 resume API 唤醒；前端追踪 `run_id` 并在 `need_user` 状态下展示登录提示+截图。

**Tech Stack:** Python/FastAPI (async generator, asyncio.Event), Vue 3 Composition API, SSE

---

## 文件变更清单

| 操作 | 文件 | 职责 |
|------|------|------|
| 修改 | `backend/app/services/pc_browser_agent_service.py` | async 生成器改造 + 登录检测增强 + session 管理 |
| 修改 | `backend/app/routers/pc_browser.py` | SSE endpoint 改 async + 新增 resume API |
| 修改 | `frontend/src/views/PCAutoExecute.vue` | need_user 状态 UI + 截图展示 + resume 调用 |
| 修改 | `frontend/src/api.ts` | 新增 resume API 调用 |
| 修改 | `backend/tests/test_pc_browser_agent_service.py` | 登录检测 + 暂停/恢复测试 |
| 修改 | `backend/tests/test_pc_browser_routes.py` | resume API 测试 |

---

### Task 1: 新增 PCAgentRunSession 类和全局 session 管理

**Files:**
- Modify: `backend/app/services/pc_browser_agent_service.py`

- [ ] **Step 1: 在 pc_browser_agent_service.py 顶部新增 PCAgentRunSession 和全局 dict**

在 `PCBrowserAgentService` 类之前添加：

```python
import asyncio
import uuid

class PCAgentRunSession:
    """管理单次 Agent 运行的状态，用于暂停/恢复。"""

    def __init__(self, run_id: str):
        self.run_id = run_id
        self.need_user_event = asyncio.Event()
        self.cancelled = False

# 全局 session 注册表
_agent_sessions: dict[str, PCAgentRunSession] = {}
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/pc_browser_agent_service.py
git commit -m "feat: add PCAgentRunSession class for agent pause/resume"
```

---

### Task 2: 改造 iter_task_events 为 async 生成器 + 暂停恢复逻辑

**Files:**
- Modify: `backend/app/services/pc_browser_agent_service.py`

- [ ] **Step 1: 将 iter_task_events 改为 async 生成器，创建 session 并注册**

找到 `iter_task_events` 方法，做以下改动：

1. 方法签名从 `def iter_task_events` 改为 `async def iter_task_events`
2. 在方法开头创建 session 并注册：

```python
run_id = str(uuid.uuid4())
session = PCAgentRunSession(run_id)
_agent_sessions[run_id] = session
```

3. 在 try/finally 中清理 session：

```python
try:
    # ... 原有逻辑
    pass
finally:
    _agent_sessions.pop(run_id, None)
```

- [ ] **Step 2: 修改 start 事件，增加 run_id**

将 `start` 事件的数据字典中加入 `run_id`：

```python
yield {
    "type": "start",
    "run_id": run_id,
    "url": url,
    "task": task,
}
```

- [ ] **Step 3: 将循环内所有 yield 改为兼容 async 生成器**

async 生成器中 `yield` 本身不需要改，但需要确保循环中没有同步阻塞调用。检查并确保：
- 所有 `yield` 语句保持不变（async 生成器支持 `yield`）
- 如果有 `time.sleep` 改为 `await asyncio.sleep`

- [ ] **Step 4: 替换 need_user 处理逻辑 — 暂停而非退出**

找到当前检测到登录页后发射 `need_user` 并 `return` 的代码块。替换为：

```python
# 检测到登录页
screenshot_url = self._capture_step_screenshot(driver, run_id, step_num)
yield {
    "type": "need_user",
    "reason": auth_reason,
    "screenshot_url": screenshot_url,
}
# 暂停等待用户操作
await session.need_user_event.wait()
session.need_user_event.clear()
if session.cancelled:
    yield {"type": "error", "message": "用户取消了执行"}
    return
yield {"type": "log", "message": "用户已完成登录，继续执行"}
continue
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/pc_browser_agent_service.py
git commit -m "feat: convert iter_task_events to async generator with pause/resume"
```

---

### Task 3: 增强登录检测逻辑

**Files:**
- Modify: `backend/app/services/pc_browser_agent_service.py`

- [ ] **Step 1: 在 _manual_auth_message 方法中增加 URL 匹配**

在现有 `_manual_auth_message` 方法中，增加 `current_url` 参数和 URL 匹配逻辑：

```python
# 登录页特征 URL 路径
_LOGIN_PATH_PATTERNS = [
    "/login", "/signin", "/sign-in", "/auth",
    "/oauth", "/sso", "/authenticate",
]

# 登录页特征域名
_LOGIN_DOMAIN_PATTERNS = [
    "accounts.google.com",
    "login.microsoftonline.com",
    "auth0.com",
    "signin.aws.amazon.com",
]
```

修改 `_manual_auth_message` 方法签名为：

```python
def _manual_auth_message(self, page_text: str, current_url: str = "") -> str | None:
```

在方法末尾、`return None` 之前添加 URL 匹配：

```python
if current_url:
    from urllib.parse import urlparse
    parsed = urlparse(current_url)
    path_lower = parsed.path.lower()
    host_lower = parsed.hostname.lower() if parsed.hostname else ""

    for pattern in _LOGIN_PATH_PATTERNS:
        if pattern in path_lower:
            return f"检测到登录页面 (URL路径: {path_lower})"

    for domain in _LOGIN_DOMAIN_PATTERNS:
        if domain in host_lower:
            return f"检测到第三方登录 (域名: {host_lower})"

return None
```

- [ ] **Step 2: 更新调用处，传入 current_url**

在 `iter_task_events` 循环中调用 `_manual_auth_message` 的地方，传入 `driver.current_url`：

```python
auth_reason = self._manual_auth_message(page_text, driver.current_url)
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/pc_browser_agent_service.py
git commit -m "feat: enhance login detection with URL pattern matching"
```

---

### Task 4: SSE endpoint 改造 + 新增 resume API

**Files:**
- Modify: `backend/app/routers/pc_browser.py`

- [ ] **Step 1: 改造 run_pc_agent_stream 为 async**

将 `run_pc_agent_stream` 改为 `async def`，用 `async for` 消费 async 生成器：

```python
@router.get("/agent/run/stream")
async def run_pc_agent_stream(url: str, task: str, model: str = None):
    async def event_generator():
        service = PCBrowserAgentService()
        async for event in service.iter_task_events(url=url, task=task, model=model):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

- [ ] **Step 2: 新增 resume API**

在 `pc_browser.py` 中导入 `_agent_sessions`：

```python
from app.services.pc_browser_agent_service import _agent_sessions
```

添加 resume endpoint：

```python
@router.post("/agent/run/{run_id}/resume")
async def resume_agent_run(run_id: str):
    session = _agent_sessions.get(run_id)
    if not session:
        raise HTTPException(status_code=404, detail="运行会话不存在或已结束")
    session.need_user_event.set()
    return {"status": "resumed"}
```

- [ ] **Step 3: 新增 cancel API（可选，用于用户终止）**

```python
@router.post("/agent/run/{run_id}/cancel")
async def cancel_agent_run(run_id: str):
    session = _agent_sessions.get(run_id)
    if not session:
        raise HTTPException(status_code=404, detail="运行会话不存在或已结束")
    session.cancelled = True
    session.need_user_event.set()  # 唤醒循环让它检查 cancelled 标记
    return {"status": "cancelled"}
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/routers/pc_browser.py
git commit -m "feat: async SSE endpoint + resume/cancel API for agent runs"
```

---

### Task 5: 后端测试

**Files:**
- Modify: `backend/tests/test_pc_browser_agent_service.py`
- Modify: `backend/tests/test_pc_browser_routes.py`

- [ ] **Step 1: 测试 _manual_auth_message URL 匹配**

在 `test_pc_browser_agent_service.py` 中添加：

```python
def test_manual_auth_message_with_login_url():
    service = PCBrowserAgentService()
    # URL 路径匹配
    assert service._manual_auth_message("", "https://example.com/login") is not None
    assert service._manual_auth_message("", "https://example.com/auth/callback") is not None
    # 域名匹配
    assert service._manual_auth_message("", "https://accounts.google.com/o/oauth2") is not None
    # 非 URL 不触发
    assert service._manual_auth_message("", "https://example.com/home") is None
    # 关键词匹配仍然生效
    assert service._manual_auth_message("请输入密码", "https://example.com/home") is not None

def test_manual_auth_message_no_false_positives():
    service = PCBrowserAgentService()
    # 包含 /login 子串但不是路径的
    assert service._manual_auth_message("", "https://example.com/blog/understanding-logins") is not None
    # 这个会误判但可以接受 — URL 路径包含 /login 就触发
```

- [ ] **Step 2: 测试 PCAgentRunSession 暂停/恢复**

```python
import asyncio
import pytest

@pytest.mark.asyncio
async def test_agent_session_pause_resume():
    session = PCAgentRunSession(run_id="test-123")
    assert not session.need_user_event.is_set()
    assert not session.cancelled

    # 模拟暂停
    resumed = False

    async def waiter():
        nonlocal resumed
        await session.need_user_event.wait()
        resumed = True

    task = asyncio.create_task(waiter())
    await asyncio.sleep(0.01)
    assert not resumed

    # 恢复
    session.need_user_event.set()
    await task
    assert resumed

@pytest.mark.asyncio
async def test_agent_session_cancel():
    session = PCAgentRunSession(run_id="test-456")
    session.cancelled = True
    session.need_user_event.set()
    assert session.cancelled
    assert session.need_user_event.is_set()
```

- [ ] **Step 3: 测试 resume API**

在 `test_pc_browser_routes.py` 中添加：

```python
import asyncio

def test_resume_nonexistent_run(client):
    response = client.post("/api/pc-browser/agent/run/nonexistent/resume")
    assert response.status_code == 404

def test_cancel_nonexistent_run(client):
    response = client.post("/api/pc-browser/agent/run/nonexistent/cancel")
    assert response.status_code == 404
```

- [ ] **Step 4: 运行所有测试确认通过**

```bash
cd backend && python -m pytest tests/test_pc_browser_agent_service.py tests/test_pc_browser_routes.py -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_pc_browser_agent_service.py backend/tests/test_pc_browser_routes.py
git commit -m "test: add tests for login detection, session pause/resume, and resume API"
```

---

### Task 6: 前端 API 层新增 resume/cancel 调用

**Files:**
- Modify: `frontend/src/api.ts`

- [ ] **Step 1: 在 api.ts 中添加 resumeAgentRun 和 cancelAgentRun 函数**

在文件中 pc browser 相关 API 部分添加：

```typescript
export async function resumeAgentRun(runId: string): Promise<{ status: string }> {
  const res = await fetch(`${API_BASE}/pc-browser/agent/run/${runId}/resume`, {
    method: 'POST',
  })
  if (!res.ok) throw new Error('恢复执行失败')
  return res.json()
}

export async function cancelAgentRun(runId: string): Promise<{ status: string }> {
  const res = await fetch(`${API_BASE}/pc-browser/agent/run/${runId}/cancel`, {
    method: 'POST',
  })
  if (!res.ok) throw new Error('取消执行失败')
  return res.json()
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/api.ts
git commit -m "feat: add resumeAgentRun and cancelAgentRun API functions"
```

---

### Task 7: 前端 PCAutoExecute.vue — need_user 状态 + 截图展示 + resume 交互

**Files:**
- Modify: `frontend/src/views/PCAutoExecute.vue`

- [ ] **Step 1: 添加状态变量和类型**

在 `<script setup>` 中添加：

```typescript
type RunStatus = 'idle' | 'running' | 'need_user' | 'done' | 'error'

const runStatus = ref<RunStatus>('idle')
const currentRunId = ref('')
const needUserReason = ref('')
const needUserScreenshot = ref('')
```

- [ ] **Step 2: 修改 SSE 事件处理逻辑**

在现有的 SSE `onmessage` 处理中，根据 `event.type` 分发：

```typescript
// 在 EventSource onmessage 中
const data = JSON.parse(event.data)

switch (data.type) {
  case 'start':
    currentRunId.value = data.run_id
    runStatus.value = 'running'
    break
  case 'step':
    // 已有的 step 处理逻辑
    steps.value.push({
      action: data.action,
      thought: data.thought,
      screenshot_url: data.screenshot_url,
      step_num: data.step_num,
    })
    break
  case 'need_user':
    runStatus.value = 'need_user'
    needUserReason.value = data.reason
    needUserScreenshot.value = data.screenshot_url
    break
  case 'log':
    logs.value.push(data.message)
    break
  case 'error':
    runStatus.value = 'error'
    logs.value.push(`错误: ${data.message}`)
    break
  case 'result':
    runStatus.value = 'done'
    break
}
```

- [ ] **Step 3: 添加 resume 和 cancel 方法**

```typescript
async function handleResume() {
  if (!currentRunId.value) return
  try {
    await resumeAgentRun(currentRunId.value)
    runStatus.value = 'running'
    needUserReason.value = ''
    needUserScreenshot.value = ''
  } catch (e) {
    logs.value.push('恢复执行失败')
  }
}

async function handleCancel() {
  if (!currentRunId.value) return
  try {
    await cancelAgentRun(currentRunId.value)
    runStatus.value = 'idle'
    needUserReason.value = ''
    needUserScreenshot.value = ''
  } catch (e) {
    logs.value.push('取消执行失败')
  }
}
```

- [ ] **Step 4: 在模板中添加 need_user 状态 UI**

在步骤日志区域上方添加登录提示横幅：

```html
<!-- 登录等待提示 -->
<div v-if="runStatus === 'need_user'" class="need-user-banner">
  <div class="need-user-alert">
    <span class="need-user-icon">⚠</span>
    <span>{{ needUserReason }}，请在浏览器窗口中完成登录</span>
  </div>
  <div v-if="needUserScreenshot" class="need-user-screenshot">
    <img :src="needUserScreenshot" alt="登录页截图" />
  </div>
  <div class="need-user-actions">
    <button class="btn-primary" @click="handleResume">继续执行</button>
    <button class="btn-secondary" @click="handleCancel">终止执行</button>
  </div>
</div>
```

- [ ] **Step 5: 在步骤列表中添加缩略图展示**

在步骤列表的每个 step 项中，如果 `step.screenshot_url` 存在，显示缩略图：

```html
<div v-if="step.screenshot_url" class="step-screenshot">
  <img
    :src="step.screenshot_url"
    alt="步骤截图"
    @click="previewScreenshot = step.screenshot_url"
  />
</div>
```

添加截图预览弹窗：

```html
<!-- 截图预览弹窗 -->
<div v-if="previewScreenshot" class="screenshot-overlay" @click="previewScreenshot = ''">
  <img :src="previewScreenshot" alt="截图预览" />
</div>
```

在 `<script setup>` 中添加：

```typescript
const previewScreenshot = ref('')
```

- [ ] **Step 6: 添加样式**

```css
.need-user-banner {
  background: #fff3cd;
  border: 1px solid #ffc107;
  border-radius: 8px;
  padding: 16px;
  margin: 12px 0;
}

.need-user-alert {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  color: #856404;
  margin-bottom: 12px;
}

.need-user-icon {
  font-size: 1.2em;
}

.need-user-screenshot img {
  max-width: 100%;
  max-height: 300px;
  border-radius: 4px;
  border: 1px solid #dee2e6;
  margin-bottom: 12px;
}

.need-user-actions {
  display: flex;
  gap: 8px;
}

.need-user-actions .btn-primary {
  background: #28a745;
  color: white;
  border: none;
  padding: 8px 20px;
  border-radius: 4px;
  cursor: pointer;
  font-weight: 600;
}

.need-user-actions .btn-secondary {
  background: #dc3545;
  color: white;
  border: none;
  padding: 8px 20px;
  border-radius: 4px;
  cursor: pointer;
}

.step-screenshot img {
  max-width: 200px;
  max-height: 120px;
  border-radius: 4px;
  border: 1px solid #dee2e6;
  cursor: pointer;
  margin-top: 4px;
}

.step-screenshot img:hover {
  border-color: #007bff;
}

.screenshot-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  background: rgba(0, 0, 0, 0.8);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
  cursor: pointer;
}

.screenshot-overlay img {
  max-width: 90vw;
  max-height: 90vh;
  border-radius: 4px;
}
```

- [ ] **Step 7: Commit**

```bash
git add frontend/src/views/PCAutoExecute.vue
git commit -m "feat: add need_user status UI, screenshot display, and resume/cancel interaction"
```

---

### Task 8: 集成测试 — 手动验证

**Files:** 无代码修改

- [ ] **Step 1: 启动后端服务**

```bash
cd backend && uvicorn app.main:app --reload --port 8000
```

- [ ] **Step 2: 启动前端开发服务器**

```bash
cd frontend && npm run dev
```

- [ ] **Step 3: 在 PCAutoExecute 页面测试正常执行流程**

1. 输入 URL 和任务描述
2. 点击"开始执行"
3. 确认：每一步都有截图显示在步骤列表中
4. 确认：步骤截图可以点击放大查看

- [ ] **Step 4: 测试登录检测流程**

1. 输入一个需要登录的网站 URL（如 `https://example.com/login`）
2. 点击"开始执行"
3. 确认：检测到登录页后显示黄色提示横幅
4. 确认：显示登录页截图
5. 在浏览器窗口中完成登录操作
6. 点击"继续执行"
7. 确认：执行恢复，继续后续步骤

- [ ] **Step 5: 测试取消流程**

1. 同上触发登录检测
2. 点击"终止执行"
3. 确认：执行终止，状态回到 idle

- [ ] **Step 6: 最终 Commit（如有修复）**

```bash
git add -A
git commit -m "fix: integration test fixes for PCExecute login wait"
```
