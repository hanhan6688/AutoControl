# 统一自动化引擎 V2 设计

**Date:** 2026-06-05
**Status:** Draft
**Scope:** Android / iOS 自动化录制、回放、等待、断言、报告、Electron 内嵌投屏联动

---

## 1. 背景

当前项目的自动化能力已经具备可用雏形，但入口和能力分散在三条链路里：

- `backend/app/routers/scripts.py`
  负责 `auto_execute`、`ocr`、`image`、`input` 等脚本运行时对象
- `backend/app/services/script_run_service.py`
  负责脚本子进程执行、流式输出、取消执行
- `backend/app/services/test_execution_service.py`
  负责 AutoGLM 用例执行、日志归档、终态截图、结果断言

前端也存在两类使用方式：

- `frontend/src/views/DeviceManager.vue`
  面向设备投屏、手工操作、录制脚本
- `frontend/src/views/TestCaseManager.vue`
  面向 AutoGLM 用例管理、执行和报告

这套结构能工作，但已经暴露出四个实际问题：

1. 录制、回放、AI 执行使用的是三套相邻但不统一的能力模型。
2. Android 与 iOS 虽然都能接入，但上层接口并未完全统一，导致录制和断言逻辑很难共享。
3. 等待、断言、证据采集已经有部分实现，但没有成为强制的一等能力，脚本和 AI 路径都容易退化为“点一下、等一会儿、看日志”。
4. Electron 下内嵌投屏已经是主交互面，但自动化模块还没有围绕“内嵌投屏即录制工作台”重构。

本设计的目标不是推翻现有实现，而是把现有能力收敛成一个统一的 Automation Engine。

---

## 2. 目标

### 2.1 目标内

- 抽象一套跨 Android / iOS 的自动化执行模型
- 统一录制、脚本回放、AI 执行的底层设备能力
- 把等待、断言、失败留证据做成默认能力，而不是可选工具函数
- 让 Electron 内嵌投屏成为 Android 主录制入口
- 让 iOS 基于 WDA screenshot + source 进入同一套录制与回放框架
- 保留现有 `auto_execute` Python 脚本兼容层，避免一次性推倒重写

### 2.2 非目标

- 不在本阶段替换 Open-AutoGLM 为新的手机 Agent
- 不在本阶段重做前端整体信息架构
- 不在本阶段引入 Appium 作为主执行器
- 不在本阶段把所有旧脚本自动迁移为新 DSL

---

## 3. 当前代码映射

| 现有文件 | 当前职责 | V2 中的定位 |
|---|---|---|
| `backend/app/routers/scripts.py` | 提供 `ScriptUI`、`ScriptOCR`、`ScriptInput` 等脚本运行时 | 变为 Automation SDK 兼容层 |
| `backend/app/services/script_run_service.py` | 脚本运行与流式日志 | 保留，作为 Python Runner 外壳 |
| `backend/app/services/test_execution_service.py` | AutoGLM 执行、报告、断言 | 拆分为 AI Supervisor + Run Orchestrator |
| `backend/app/services/result_assertion_service.py` | 执行后结果判断 | 变为 Assertion/Judge 子系统一部分 |
| `backend/app/services/ui_element_service.py` | UI 树解析、元素定位 | 成为 Locator/Hierarchy 核心 |
| `backend/app/services/wda_service.py` | iOS WDA 交互 | 成为 iOS Driver 底层实现 |
| `backend/app/services/ios_service.py` | iOS 设备发现 | 继续负责设备发现与能力标记 |
| `frontend/src/views/DeviceManager.vue` | 投屏、录制、控件点击 | 变为 Automation Workbench |
| `frontend/src/views/TestCaseManager.vue` | 用例执行、报告查看 | 变为 Run Center + Report Center |

---

## 4. 总体架构

```text
Frontend (Electron + Vue)
  -> Automation Workbench
  -> Test Run Center
  -> Report Viewer

Automation API
  -> Recording Session API
  -> Run API
  -> Locator Preview API
  -> Assertion API

Automation Engine
  -> Runner
  -> Driver Layer
  -> Locator Resolver
  -> Wait Engine
  -> Assertion Engine
  -> Evidence Collector

Platform Drivers
  -> AndroidDriver (ADB + UIAutomator + scrcpy control)
  -> IOSDriver (WDA + go-ios discovery)
```

核心原则：

- 录制、脚本回放、AI 执行都走同一套 Driver 抽象
- 每一步操作前后都能采集状态和证据
- 每一条录制出来的步骤都优先生成“定位器 + 等待 + 动作”，而不是裸坐标
- 坐标、OCR、图像识别只作为降级链路

---

## 5. 核心对象模型

建议新增目录：

```text
backend/app/automation/
  core/
  drivers/
  locators/
  waits/
  assertions/
  recording/
  reports/
```

### 5.1 Step

每个自动化步骤都统一为结构化对象：

```json
{
  "id": "step_12",
  "title": "点击登录按钮",
  "action": { "type": "tap", "locator": { "type": "resource_id", "value": "com.demo:id/login" } },
  "before_wait": { "type": "visible", "locator": { "type": "text", "value": "登录" }, "timeout": 10 },
  "after_wait": { "type": "screen_changed", "timeout": 3 },
  "assertions": [
    { "type": "exists", "locator": { "type": "resource_id", "value": "com.demo:id/home_title" } }
  ]
}
```

### 5.2 Locator

定位器必须支持链式降级：

```json
{
  "primary": { "type": "resource_id", "value": "com.demo:id/login" },
  "fallbacks": [
    { "type": "text", "value": "登录" },
    { "type": "xpath", "value": "//*[@text='登录']" },
    { "type": "ocr_text", "value": "登录" },
    { "type": "coordinate_ratio", "x": 0.52, "y": 0.82 }
  ]
}
```

### 5.3 WaitSpec

等待条件不是简单 `sleep`，而是显式状态：

- `visible`
- `gone`
- `exists`
- `text_equals`
- `text_contains`
- `enabled`
- `screen_changed`
- `app_foreground`
- `source_stable`
- `ocr_contains`

### 5.4 AssertionSpec

断言对象统一由 Assertion Engine 执行：

- `exists`
- `not_exists`
- `text_equals`
- `text_contains`
- `ocr_contains`
- `image_exists`
- `app_foreground`
- `ai_result`

### 5.5 Evidence

每一步证据结构固定：

```json
{
  "screenshot_path": ".../step_12.png",
  "source_dump_path": ".../step_12.xml",
  "ocr_summary": ["登录", "首页"],
  "current_app": "com.demo.app",
  "duration_ms": 421
}
```

---

## 6. Driver 设计

### 6.1 统一接口

```python
class DeviceDriver:
    platform: str

    async def launch(self, app_id: str) -> None: ...
    async def stop_app(self, app_id: str) -> None: ...
    async def tap(self, x: int, y: int) -> None: ...
    async def swipe(self, sx: int, sy: int, ex: int, ey: int, duration_ms: int) -> None: ...
    async def input_text(self, text: str) -> None: ...
    async def press_key(self, key: str) -> None: ...
    async def screenshot(self) -> bytes: ...
    async def dump_source(self) -> str: ...
    async def current_app(self) -> dict: ...
    async def screen_size(self) -> tuple[int, int]: ...
```

### 6.2 AndroidDriver

实现来源：

- 输入控制：ADB / scrcpy control / `u2_service`
- UI source：UIAutomator XML
- screenshot：`u2_service.screenshot()` 或 `adb exec-out screencap -p`
- launch/current_app：ADB shell 能力

原则：

- 录制场景优先走当前内嵌 scrcpy 对应的控制链路
- 回放场景优先走稳定 selector，其次坐标

### 6.3 IOSDriver

实现来源：

- 设备发现：`IOSService`
- 交互：`wda_service.click/swipe/launch_app`
- source：`wda_service.dump_source`
- screenshot：`wda_service.screenshot`

原则：

- iOS 初期不依赖实时视频流，也能先完成录制、回放、断言闭环
- Bundle ID 启动、WDA source、截图证据必须统一进入同一套 Runner

---

## 7. 录制设计

### 7.1 Android

Electron 下 Android 全部默认内嵌 scrcpy 后，录制流程统一为：

1. 用户在内嵌投屏上点击或拖拽
2. 前端得到宿主区域坐标
3. 后端换算到设备像素坐标
4. `UIElementService` 基于当前 hierarchy 反查最优元素
5. 生成 `LocatorChain`
6. 生成结构化 Step
7. 同时渲染成兼容 Python 代码写回编辑器

生成代码示例：

```python
auto_execute.wait_for_element(resource_id="com.demo:id/login", timeout=10)
auto_execute.click(resource_id="com.demo:id/login", fallback=(541, 1768))
```

### 7.2 iOS

录制流程类似，但视图来自 WDA screenshot：

1. 前端显示当前截图
2. 用户点击截图区域
3. 后端基于 WDA source 反查元素
4. 生成 iOS LocatorChain
5. 输出兼容 Python 脚本与结构化 Step

### 7.3 录制动作范围

必须支持：

- 点击
- 长按
- 滑动
- 文本输入
- 返回 / Home
- 启动 App
- 显式等待
- 插入断言
- 插入截图检查点

---

## 8. 等待与断言

### 8.1 等待策略

当前 `ScriptUI` 已有 `wait_for_element()` 和 `assert_text_visible()`，但还不够统一。V2 要求：

- 每个 `tap/input/long_press` 都允许声明前置等待
- 录制生成脚本默认补等待，不直接输出裸动作
- 运行器支持统一超时、轮询间隔和自动截图

### 8.2 断言策略

断言不再只是最终结果判断，也支持步骤级断言：

- 步骤后断言：页面标题出现、按钮消失、提示文案出现
- 用例末尾断言：目标页面、目标文本、目标状态成立
- 多证据断言：UI hierarchy + OCR + screenshot + AI judge

### 8.3 失败留证据

任一步失败，都必须保存：

- 当前截图
- 当前 source dump
- 当前 locator 解析链
- 当前设备与 App 状态
- 上一步成功步骤 ID

---

## 9. Runner 与报告

Runner 应统一脚本回放和未来结构化用例执行：

```text
create run
  -> init driver
  -> setup device/app
  -> execute step
     -> before wait
     -> action
     -> after wait
     -> step assertions
     -> evidence collection
     -> stream event
  -> finalize report
```

事件流建议统一为：

- `run_started`
- `step_started`
- `wait_started`
- `action_executed`
- `assertion_passed`
- `assertion_failed`
- `evidence_saved`
- `run_finished`

报告目录沿用现有 `ReportWriter` 风格，但补充每步证据索引。

---

## 10. API 与前端改造

### 10.1 后端 API

建议新增：

- `POST /api/automation/runs`
- `GET /api/automation/runs/{run_id}`
- `GET /api/automation/runs/{run_id}/events`
- `POST /api/automation/recordings`
- `POST /api/automation/locators/preview`
- `POST /api/automation/assertions/validate`

### 10.2 DeviceManager

重心从“投屏页面”升级为“自动化工作台”：

- Android 内嵌 scrcpy 画面作为默认录制面板
- iOS 截图画面作为录制面板
- 增加定位器预览、等待条件、断言插入
- 录制输出既写 Python，也写结构化 Step

### 10.3 TestCaseManager

从“只看 AutoGLM 日志”升级为“统一 Run Center”：

- 展示结构化步骤
- 展示每步等待、动作、断言和证据
- 展示失败定位器与截图
- 为 AutoGLM 和脚本回放共用同一套报告视图

---

## 11. 兼容策略

旧能力不能立刻删除，兼容方案如下：

1. `ScriptUI` 保留，但内部逐步改为调用新的 Driver / Locator / Wait / Assertion 层
2. 旧脚本继续支持 `auto_execute.click()`、`auto_execute.input()`、`auto_execute.wait()`
3. 新录制优先生成新风格语句，但保持旧运行时可执行
4. `test_execution_service.py` 后续可以逐步迁移到新 Runner，而不是一次性重写

---

## 12. 分期落地

### Phase 1

- 建立 `DeviceDriver` 抽象
- 把 Android / iOS 底层设备能力统一封装

### Phase 2

- 建立 `LocatorChain`、`WaitSpec`、`AssertionSpec`
- 让 `ScriptUI` 改走统一执行层

### Phase 3

- 改造 `DeviceManager.vue` 录制输出
- Android / iOS 都生成结构化 Step + Python 脚本

### Phase 4

- 引入统一 Runner 和事件流
- 报告按步骤保存证据

### Phase 5

- 让 AutoGLM 执行也接入同一套 Evidence、Assertion 和 Report 模型

---

## 13. 测试策略

后端：

- Locator 解析单测
- Android/iOS Driver 契约测试
- Wait / Assertion 规则单测
- Runner 事件流测试

前端：

- DeviceManager 录制流程测试
- TestCaseManager 报告展示测试
- Electron 内嵌 scrcpy 交互验证

回归重点：

- Android 内嵌录制可用
- iOS WDA 录制可用
- 录制脚本可以直接回放
- 失败时一定产出截图和 source dump

---

## 14. 关键结论

这次重构不应该从“再加几个工具函数”入手，而应该从“统一执行模型”入手。现有代码里已经有不少可复用资产：

- `ScriptUI` 已有等待、断言、iOS 基础支持
- `UIElementService` 已经能做 UI 树定位
- `wda_service.py` 已经足够支撑 iOS Driver MVP
- Electron 内嵌 scrcpy 已经具备成为 Android 录制主入口的条件

V2 的重点不是推翻，而是把这些能力收束到同一套 Driver、Locator、Wait、Assertion、Runner 体系里，让普通实时投屏、控件录制、脚本回放、AI 执行最终使用同一条技术主干。
