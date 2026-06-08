# Mobile-AI-TestOps AI 自动化测试方案

## 1. 总目标

把项目做成一个统一的 AI 自动化测试平台：

- 移动端AutoGLM由 Open-AutoGLM 执行。
- PC/Web AutoGLM由 agent-browser 执行。
- Excel/CSV 中的每条AutoGLM都生成独立执行记录、步骤日志、截图和单用例报告。
- 一份 Excel/CSV 测试计划生成一个总报告，汇总所有用例的执行结果。
- 遇到登录、验证码、扫码、权限确认等敏感步骤时，平台暂停执行，允许用户手动接管，然后继续执行。

核心原则：

```text
移动端 = AutoGLM 负责动手机
PC/Web = agent-browser 负责动浏览器
AI 编排层 = 把AutoGLM改写成更稳定的任务书
判断 Agent = 根据日志、截图、页面结果和预期结果判断是否通过
报告层 = 保存每一步证据，形成可复盘测试报告
```

## 2. 总体架构

| 层级 | 移动端 | PC/Web 端 | 作用 |
|---|---|---|---|
| 用例入口 | Excel / CSV / 单条手工用例 | Excel / CSV / 单条手工用例 | 统一管理AutoGLM |
| 平台识别 | app / wechat_mini / android_app / ios_app / harmony_app | web | 判断使用哪个执行器 |
| 编排 AI | Case Planner | Case Planner | 把人话用例改写成执行任务书 |
| 执行器 | Open-AutoGLM | agent-browser CLI | 真正操作手机或浏览器 |
| 连接层 | ADB / WDA / HDC | Chrome / Chromium / CDP | 连接真实执行环境 |
| 人工接管 | 手机手动登录、授权 | Electron 可见浏览器手动登录、验证码 | 敏感步骤暂停处理 |
| 证据采集 | AutoGLM 日志、截图、终态截图 | 每步截图、DOM snapshot、命令日志 | 形成报告证据 |
| 判断 Agent | 结合截图、日志、预期结果判断 | 结合截图、DOM 文本、预期结果判断 | 生成 pass / fail / uncertain |
| 报告层 | 单用例报告 + 批量报告 | 单用例报告 + 批量报告 | 类似 MobAI 的报告体验 |

## 3. 移动端执行方案

移动端继续以 Open-AutoGLM 作为主执行器。

执行流程：

1. 用户选择在线设备。
2. 平台识别设备类型：Android / iOS / HarmonyOS。
3. 根据平台生成不同执行命令：
   - Android: ADB
   - iOS: WDA
   - HarmonyOS: HDC
4. Case Planner 分析AutoGLM，生成任务书。
5. 执行分两段：
   - 前置条件：把手机带到测试起点。
   - 正式步骤：执行AutoGLM动作。
6. AutoGLM 日志流式输出到当前AutoGLM展开区域。
7. 执行结束保存终态截图。
8. 判断 Agent 根据预期结果、日志和截图判断结果。
9. 保存单用例报告。

移动端附加能力：

- AutoExecute 控件录制与回放。
- OCR 点击。
- 图片模板匹配。
- 坐标点击兜底。
- ADB Keyboard 检测。
- 软件安装/依赖检查。

## 4. PC/Web 执行方案

PC/Web 端使用 agent-browser 作为执行器。

重要判断：

agent-browser 本质是 CLI 工具，不应该把它当成实时浏览器 UI 框架。最终稳定方案应该以“每步截图 + 日志 + DOM snapshot”为核心证据，而不是强依赖实时渲染。

Electron 内嵌浏览器保留为辅助能力：

- 用户需要手动登录、验证码、扫码时可见接管。
- 用户调试时可以观察当前页面。
- 不是核心执行依据。

PC/Web 执行流程：

1. 打开目标 URL。
2. agent-browser 获取当前页面：
   - URL
   - title
   - interactive snapshot
   - 页面文本
3. PC Agent 读取任务书和当前页面状态。
4. AI 输出结构化动作：

```json
{
  "action": "click",
  "target": "@e12",
  "reason": "点击登录按钮"
}
```

支持动作：

- click
- fill
- press
- scroll
- wait_text
- finish
- need_user

5. agent-browser 执行动作。
6. 每一步保存截图。
7. 前端在当前AutoGLM下流式显示：
   - AI 决策
   - 执行动作
   - 命令日志
   - 步骤截图
8. 遇到登录、验证码、扫码、二次验证时返回 `need_user`。
9. 用户在 Electron 可见浏览器中手动完成。
10. 用户点击继续，PC Agent 从当前页面继续执行。
11. 执行完成后保存报告。

## 5. 统一AutoGLM执行流程

```text
导入 Excel / CSV
  -> 解析每一条AutoGLM
  -> 判断 platform_type
  -> 生成任务书
  -> 分发执行器
     -> 移动端：Open-AutoGLM
     -> PC/Web：agent-browser
  -> 流式输出日志
  -> 保存步骤证据
  -> 判断 Agent 断言结果
  -> 生成单用例报告
  -> 汇总测试计划总报告
```

## 6. 报告目录结构

建议报告目录如下：

```text
backend/app/static/reports/runs/
  plan_20260520_001/
    summary.json
    summary.html
    case_001/
      execution.json
      report.html
      trace.json
      screenshots/
        step_001.png
        step_002.png
        final.png
    case_002/
      execution.json
      report.html
      trace.json
      screenshots/
        step_001.png
        step_002.png
        final.png
```

单用例报告包含：

- 用例基本信息。
- 平台类型。
- 执行器类型。
- 任务书。
- 每步日志。
- 每步截图。
- 最终截图。
- AI 判断结果。
- 失败原因分类。
- 原始 trace 文件链接。

总报告包含：

- 总用例数。
- 通过数。
- 失败数。
- 不确定数。
- 通过率。
- 每条用例结果。
- 每条用例报告链接。
- 错误分类统计。

## 7. 阶段计划

| 阶段 | 目标 | 主要任务 | 输出 |
|---|---|---|---|
| P0 | 稳定基础链路 | 清理路径、统一配置、稳定前后端端口发现 | 项目可稳定启动 |
| P1 | 移动端执行稳定 | AutoGLM 两阶段执行、三端设备切换、日志流式输出 | 手机用例可执行 |
| P2 | 移动端证据增强 | 终态截图、外置日志、报告索引瘦身 | 单用例报告稳定 |
| P3 | PC/Web 执行 MVP | agent-browser 单任务执行、每步截图、日志流式输出 | PC AutoExecute 可用 |
| P4 | 人工接管 | 移动端/PC 端遇登录、验证码、权限时暂停继续 | 可处理真实业务登录 |
| P5 | 统一用例分发 | 根据 platform_type 自动选择 AutoGLM 或 agent-browser | 一套 Excel 跑多平台 |
| P6 | 判断 Agent | 根据预期结果、日志、截图判断 pass/fail/uncertain | 不再只看执行完成 |
| P7 | 报告体系 | 每条用例一个报告目录，总计划一个汇总报告 | 类 MobAI 报告体验 |
| P8 | 回归能力 | 移动端 AutoExecute 录制回放、PC 端 snapshot/ref 脚本沉淀 | 可重复执行回归脚本 |

## 8. 最终方案

最终项目形态：

```text
Mobile-AI-TestOps
  ├─ 测试计划管理
  ├─ AutoGLM导入
  ├─ 移动端执行中心
  │   ├─ Android
  │   ├─ iOS
  │   ├─ HarmonyOS
  │   └─ Open-AutoGLM
  ├─ PC/Web 执行中心
  │   ├─ agent-browser
  │   ├─ 每步截图
  │   ├─ DOM snapshot
  │   └─ 人工接管浏览器
  ├─ AI 编排层
  ├─ 判断 Agent
  ├─ AutoExecute 回归录制
  └─ 报告中心
```

最终用户体验：

1. 用户导入一份 Excel/CSV。
2. 平台识别每条用例是移动端还是 PC/Web。
3. 用户选择移动设备或 PC 执行环境。
4. 点击执行。
5. 每条用例展开区实时显示执行日志。
6. 每一步保存截图。
7. 遇到登录/验证码时平台暂停并提示用户处理。
8. 用户处理后继续执行。
9. 执行完成后生成单用例报告。
10. 整份测试计划生成总报告。

## 9. 当前建议

短期建议先做：

1. 把 PC AutoExecute 从“实时浏览器画面”调整为“步骤截图 + 日志 + snapshot”模式。
2. 把 PC Agent 接入AutoGLM执行入口。
3. `platform_type = web` 时走 agent-browser。
4. `platform_type = app / wechat_mini / android_app / ios_app / harmony_app` 时走 Open-AutoGLM。
5. 报告目录统一，移动端和 PC 端都使用同一套 ReportWriter。

这样项目会更稳，也更容易打包成 exe。
