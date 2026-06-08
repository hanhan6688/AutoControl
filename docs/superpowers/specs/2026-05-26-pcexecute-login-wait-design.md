# PCExecute 登录等待与步骤日志优化设计

## 目标

优化 PCExecute（PCBrowserAgentService）的执行流程，实现：
1. 每一步的日志和截图完善展示
2. 遇到登录页面时暂停执行，弹窗提示用户处理
3. 用户完成登录后点击继续，恢复执行

## 范围

- **仅 PCAutoExecute.vue 独立页面**入口
- 用例执行部分（`_run_web_case_events`）保持现有 Leyoujia 登录态机制不变

## 方案：循环内暂停 + asyncio.Event 唤醒

在 `iter_task_events` 的 while 循环内检测登录页时不退出，改为 `await asyncio.Event.wait()` 暂停，用户点"继续"后通过 resume API set Event 唤醒循环。

选择此方案的原因：改动最小，保留完整 Agent 上下文，不需要序列化/恢复状态。

---

## 1. 后端：Agent 循环暂停/恢复机制

### 1.1 PCAgentRunSession 类

新增 `PCAgentRunSession` 管理单次运行的状态：

```python
class PCAgentRunSession:
    run_id: str
    need_user_event: asyncio.Event  # 暂停/恢复信号
    cancelled: bool = False
```

- 注册到全局 `_agent_sessions: dict[str, PCAgentRunSession]`，按 `run_id` 索引
- 运行结束后从 dict 中移除

### 1.2 iter_task_events 改造

- 从同步生成器改为 **async 生成器**（因为要 `await event.wait()`）
- 检测到登录页时：
  1. 发射 `need_user` 事件（含 `reason` 和 `screenshot_url`）
  2. `await session.need_user_event.wait()` 暂停
  3. 唤醒后 `session.need_user_event.clear()` 重置
  4. 发射 `log` 事件："用户已完成登录，继续执行"
  5. 继续循环

### 1.3 Resume API

`POST /api/pc-browser/agent/run/{run_id}/resume`

- 找到对应 `PCAgentRunSession`
- set `need_user_event`
- 返回 `{"status": "resumed"}`
- 找不到 session 时返回 404

### 1.4 SSE Endpoint 改造

- `run_pc_agent_stream` 改为 `async def`
- 用 `async for` 消费 async 生成器
- SSE 连接在 `need_user` 暂停期间保持（不推送新事件，但连接不断）

### 1.5 登录检测增强

在 `_manual_auth_message` 中增加 URL 匹配：

**关键词匹配**（现有）：
- password, captcha, 登录, verification, sign in, 登入

**URL 匹配**（新增）：
- 路径匹配：`/login`, `/signin`, `/auth`, `/oauth`, `/sso`
- 域名匹配：`accounts.google.com`, `login.microsoftonline.com`, `auth0.com`

URL 匹配和关键词匹配任一命中即触发 `need_user`。

---

## 2. 前端：交互与截图展示

### 2.1 运行状态机

```
idle → running → need_user → running → done/error
                  ↑              ↓
                  └──────────────┘  (可能多次触发)
```

新增 `need_user` 状态，区别于 `running` 和 `idle`。

### 2.2 need_user 状态 UI

- 顶部状态栏：显示 "⚠ 检测到登录页面，请在浏览器窗口中完成登录"
- 步骤日志区域：最后一条高亮显示登录检测信息
- 当前截图展示：在醒目位置显示登录页截图
- "继续执行"按钮：调用 `POST /api/pc-browser/agent/run/{run_id}/resume`
- "终止执行"按钮：终止当前任务

### 2.3 run_id 追踪

- SSE 流的 `start` 事件包含 `run_id`
- 前端保存 `currentRunId`，用于后续 resume 调用

### 2.4 截图展示增强

- 每个 `step` 事件携带 `screenshot_url`
- 步骤列表中每条 step 后面显示缩略图
- 点击缩略图可放大查看
- `need_user` 状态时在醒目位置展示当前截图

### 2.5 SSE 连接保持

- `need_user` 期间 SSE 连接保持，只是没有新事件
- resume 后 SSE 继续推送后续步骤事件
- SSE 超时断开时提示用户重新开始

---

## 3. 事件流结构

### 3.1 事件类型（保持现有，扩展字段）

| 事件 | 数据 | 说明 |
|------|------|------|
| `start` | `{run_id, url, task}` | 开始执行（新增 run_id） |
| `step` | `{action, thought, screenshot_url, step_num}` | 每一步（已有 screenshot_url） |
| `log` | `{message}` | 日志信息 |
| `error` | `{message}` | 错误 |
| `result` | `{success, message}` | 最终结果 |
| `need_user` | `{reason, screenshot_url}` | 需要用户干预（新增 screenshot_url） |

### 3.2 数据流时序

```
前端 -> POST /agent/run/stream (SSE)
后端 -> start {run_id, url, task}
后端 -> step {action, thought, screenshot_url, step_num}
后端 -> step ...
后端 -> need_user {reason: "检测到登录页面", screenshot_url}
  ↓ 前端展示登录提示 + 截图，用户在浏览器窗口操作登录
  ↓ 用户点击"继续执行"
前端 -> POST /agent/run/{run_id}/resume
后端 -> (唤醒 asyncio.Event)
后端 -> log {message: "用户已完成登录，继续执行"}
后端 -> step {action, thought, screenshot_url, step_num}
  ...
后端 -> result {success, message}
```

---

## 4. 错误处理

- **resume 时 session 不存在**：返回 404，前端提示"运行已结束或不存在"
- **SSE 连接断开**：前端检测 EventSource error，提示用户重新开始
- **用户长时间未操作**：后端不主动超时，SSE 连接由 uvicorn keep-alive 管理
- **重复 resume**：`need_user_event` 已 set 时幂等处理，不报错
- **运行被取消**：session.cancelled = True，循环检查后退出

---

## 5. 不在范围内

- 用例执行部分的登录处理（保持现有 Leyoujia 登录态机制）
- 自动检测登录完成（后续迭代考虑）
- WebSocket 替代 SSE
- AI 视觉模型判断登录页
