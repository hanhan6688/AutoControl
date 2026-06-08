# AutoGLM 执行准确度提升设计

**Date:** 2026-06-05
**Status:** Draft
**Scope:** Mobile AutoGLM 执行规划、分阶段监督、状态校验、结果判断、iOS 支持

---

## 1. 问题定义

当前移动端 AutoGLM 执行链路的核心文件是 `backend/app/services/test_execution_service.py`，现状可以概括为：

1. 把整条用例压成一段统一 prompt，通过 `_build_unified_prompt()` 一次性交给 Open-AutoGLM。
2. 通过 `_run_autoglm_phase()` 启动 `main.py`，解析 stdout 里的行动块和截图事件。
3. 执行结束后再调用 `ResultAssertionService.assert_result()` 做最终判断。

这条链路能跑通，但准确度上限很低，原因不是模型单点问题，而是执行框架本身缺少监督和结构化上下文。

---

## 2. 当前准确度问题

### 2.1 任务书过粗

`_build_unified_prompt()` 当前只拼接：

- 目标应用
- 前置条件
- 用例步骤
- 预期结果
- 可用登录账号

问题在于：

- 没有把一条长用例拆成可验证的小目标
- 没有把“成功信号”“失败信号”“禁止动作”显式告诉模型
- 没有为 Android / iOS 提供平台差异化提示

### 2.2 执行过程缺少中间校验

`_run_autoglm_phase()` 能读到：

- Action JSON
- 步骤截图
- 手工接管提示

但它不会在每一步之后验证：

- 当前页面是否真的发生了预期变化
- 是否已经离开目标 App
- 是否误入登录、广告、权限、升级页面
- 是否已经卡住

模型一旦在中途走偏，只会继续偏下去，直到最后失败。

### 2.3 结果断言偏后置、偏脆弱

`ResultAssertionService` 当前的 fallback 主要依赖日志关键词匹配：

- 日志包含预期关键词就可能判 `passed`
- 有终态截图但证据不足就判 `uncertain`

这意味着：

- “执行完成”可能被过度接近“测试通过”
- 终态截图没有和结构化 checkpoint 绑定
- 断言主要发生在最后，而不是沿途逐步收敛不确定性

### 2.4 录制与 AutoGLM 没有共用状态能力

当前 `ScriptUI` 已经具备：

- `wait_for_element`
- `assert_element`
- `assert_text_visible`
- iOS WDA selector / screenshot 能力

但 AutoGLM 执行链路没有复用这些能力，因此录制回放和 AI 执行之间没有共享“页面状态判断”的基础设施。

---

## 3. 设计目标

### 3.1 目标内

- 提升 AutoGLM 真正完成业务目标的命中率
- 降低“执行完成但结果不对”的假阳性
- 降低“本可自动修复却直接失败”的假失败
- 支持 Android / iOS 共用同一套编排与监督框架
- 把每一次 AutoGLM 执行沉淀成可复盘的结构化数据

### 3.2 非目标

- 不在本阶段替换 Open-AutoGLM 核心模型
- 不依赖模型内部暴露更多私有推理接口
- 不要求一次性做到全页面确定性自动化

---

## 4. 方案对比

### 方案 A：保持黑盒，只优化 prompt

做法：

- 继续一次性执行整条用例
- 只改 prompt 模板和登录提示

优点：

- 改动最小

缺点：

- 中间状态仍不可控
- 误操作无法及时拉回
- 准确度提升有限

### 方案 B：半监督执行器

做法：

- 把一条用例拆成多个 checkpoint
- AutoGLM 分段执行
- 每段执行后由平台侧做状态校验和必要修复

优点：

- 能明显提升准确度
- 不要求改 Open-AutoGLM 内核
- 能和现有 `ScriptUI` / `ResultAssertionService` / WDA 能力结合

缺点：

- 执行框架更复杂

### 方案 C：尽量改成确定性脚本执行

做法：

- 把大部分 AutoGLM 用例先转为结构化脚本或录制脚本

优点：

- 回归稳定性最高

缺点：

- 失去 AutoGLM 对开放任务的优势
- 不适合你当前“AI 执行 + 录制共存”的产品定位

**结论：推荐方案 B。**

---

## 5. 推荐架构

建议新增：

```text
backend/app/services/autoglm/
  case_planner.py
  prompt_builder.py
  execution_supervisor.py
  state_probe.py
  checkpoint_validator.py
  repair_service.py
  judge_service.py
```

职责拆分：

- `CasePlanner`
  把原始用例转成结构化 `CaseTaskPlan`
- `PromptBuilder`
  针对当前 checkpoint 生成更短、更约束的 prompt
- `ExecutionSupervisor`
  分段调用 Open-AutoGLM，驱动整体状态机
- `StateProbe`
  采集 screenshot、source、current app、OCR 摘要
- `CheckpointValidator`
  判断当前是否达到某一步的成功信号
- `RepairService`
  在偏航时尝试回退、返回、重试、重启 App
- `JudgeService`
  结合全程证据给出最终 verdict

---

## 6. CaseTaskPlan 设计

当前 `_build_unified_prompt()` 需要升级为结构化计划对象，而不是纯文本。

```json
{
  "case_id": 123,
  "target_kind": "app",
  "platform": "android",
  "target_app": "贝壳找房",
  "launch_app_id": "com.ke.app",
  "preconditions": [
    "应用已安装",
    "如未登录可使用指定账号登录"
  ],
  "checkpoints": [
    {
      "id": "cp_1",
      "goal": "进入首页",
      "instructions": ["打开应用", "如果出现升级弹窗先关闭"],
      "success_signals": ["看到首页", "底部导航出现首页标签"],
      "failure_signals": ["崩溃", "卡在系统权限页超过10秒"],
      "takeover_signals": ["短信验证码", "扫码登录"],
      "allowed_actions": ["tap", "swipe", "input", "back", "home", "wait"],
      "max_steps": 12
    }
  ],
  "final_expectations": [
    "进入 AI 学区顾问页面",
    "页面出现 AI 学区顾问 文案"
  ]
}
```

关键变化：

- 一条长用例拆成多个 checkpoint
- 每个 checkpoint 都有可验证的成功信号
- 明确 takeover 信号，避免模型硬闯验证码

---

## 7. 执行状态机

推荐执行流程：

```text
load case
  -> build CaseTaskPlan
  -> preflight
  -> for checkpoint in checkpoints
       -> build scoped prompt
       -> run Open-AutoGLM
       -> collect state
       -> validate checkpoint
       -> repair or takeover if needed
  -> final judge
  -> write report
```

### 7.1 Preflight

在正式调用模型前先做平台侧检查：

- 设备在线
- App 可启动
- 截图能力可用
- source 能力可用
- 当前前台应用可读取
- iOS WDA 会话正常

如果这些前置能力不健康，不要把失败甩给模型。

### 7.2 Scoped Prompt

每次只给 AutoGLM 当前 checkpoint 的目标，而不是整条用例全文。

prompt 必须包含：

- 当前 checkpoint 目标
- 当前已知页面状态摘要
- 成功信号
- 禁止动作
- takeover 条件
- 剩余动作预算

### 7.3 Checkpoint Validation

每段执行后平台主动验证：

- 是否进入了目标页面
- 是否看到了目标文本
- 是否仍在目标 App
- 是否进入已知错误态

验证失败时不要立刻结束，应先进入修复流程。

### 7.4 Repair

平台级修复策略：

- 再等一次
- 返回一次
- 关闭弹窗
- 重新启动 App
- 重新执行当前 checkpoint 一次

同一 checkpoint 默认最多修复 1 到 2 次，避免无限循环。

### 7.5 Final Judge

只有当最终 checkpoint 成功，并且终态证据满足 `final_expectations`，才允许判 `passed`。

---

## 8. 状态采集设计

`StateProbe` 负责统一采集多源状态，不再只依赖 AutoGLM stdout。

### 8.1 Android

- screenshot
- 当前前台 package / activity
- UIAutomator XML
- OCR 文本摘要

### 8.2 iOS

- screenshot
- 当前 bundle id
- WDA source
- OCR 文本摘要

### 8.3 输出结构

```json
{
  "timestamp": "2026-06-05T10:00:00Z",
  "platform": "ios",
  "foreground_app": "com.demo.ios",
  "visible_texts": ["登录", "首页"],
  "source_summary": {
    "buttons": ["登录", "取消"],
    "inputs": ["手机号输入框"]
  },
  "artifacts": {
    "screenshot_path": "...png",
    "source_path": "...xml"
  }
}
```

---

## 9. 提升准确度的关键机制

### 9.1 缩短模型任务跨度

一次只做一个 checkpoint，而不是整条用例。

### 9.2 显式成功信号

例如：

- “看到首页”
- “出现提交成功提示”
- “顶部标题为 AI 学区顾问”

没有成功信号，模型只能凭感觉结束。

### 9.3 显式失败信号

例如：

- 停留在登录页
- 当前 App 被切到浏览器
- 出现系统权限弹窗

### 9.4 结构化动作预算

每段允许的动作数有限，超出预算就进入人工或修复，而不是无限乱点。

### 9.5 平台侧验证先于最终 AI 断言

平台可确定的事情不要交给大模型：

- 当前 App 是否正确
- 文案是否出现
- 页面元素是否存在

AI Judge 只处理平台难以确定的语义结果。

---

## 10. PromptBuilder 设计

prompt 不再是简单拼接，而是模板化生成：

```text
你正在执行移动端测试的一个阶段任务。

平台：Android
目标应用：贝壳找房
当前阶段目标：进入 AI 学区顾问页面
当前页面状态摘要：
- 前台应用：com.ke.app
- 可见文本：首页, 推荐, AI学区

成功信号：
1. 顶部标题出现“AI学区顾问”
2. 页面主体出现“AI学区顾问”相关文案

禁止动作：
1. 不要退出目标应用
2. 不要在无法确认页面时连续随机点击

接管条件：
1. 短信验证码
2. 扫码登录

如果你认为任务完成，必须让最终界面满足成功信号。
```

这比当前 `_build_unified_prompt()` 更短、更约束，也更适合多次分段调用。

---

## 11. Judge 设计

`ResultAssertionService` 应升级为 `JudgeService`，分两层：

### 11.1 Deterministic Judge

优先使用平台可证实的规则：

- checkpoint 全通过
- 终态文本命中
- 终态页面元素命中
- 当前 App 正确

满足这些规则时可以直接 `passed`。

### 11.2 AI Judge

只有在以下场景才调用模型：

- 页面是语义型结果，单靠元素命中不够
- OCR / source 证据互相冲突
- 截图需要视觉理解

AI Judge 的输入必须包含：

- 结构化 checkpoint 结果
- 终态截图
- 关键日志
- source 摘要

而不是只喂原始日志。

---

## 12. 登录与人工接管

当前链路已能识别 `MANUAL_TAKEOVER_REQUIRED:`，但策略还偏粗。

新设计要求：

- 登录账号以结构化上下文传入 `CaseTaskPlan`
- 平台侧区分“可自动登录”和“必须人工接管”
- 接管恢复后从当前 checkpoint 继续，而不是整条用例重来
- 报告必须标记哪一步发生了人工接管

iOS 也必须共享同一套 takeover 协议。

---

## 13. 报告与指标

新的 AutoGLM 报告必须能回答四个问题：

1. 模型当时要完成什么 checkpoint
2. 它做了哪些动作
3. 平台为什么认为这一步成功、失败或需要接管
4. 最终结论基于哪些证据

建议新增指标：

- `checkpoint_pass_rate`
- `repair_rate`
- `manual_takeover_rate`
- `final_uncertain_rate`
- `false_positive_review_rate`
- `ios_case_pass_rate`
- `android_case_pass_rate`

这些指标比“进程返回码”更能反映真实准确度。

---

## 14. iOS 支持要求

AutoGLM 准确度设计必须从一开始兼容 iOS，而不是 Android 做完再补。

iOS 最低要求：

- 用例计划可带 `bundle_id`
- 支持 WDA launch / source / screenshot
- checkpoint 校验支持 iOS locator
- 接管恢复可继续当前 checkpoint
- 终态 Judge 支持基于 WDA source 和截图判断

这和统一自动化引擎 V2 的 Driver 设计是一致的。

---

## 15. 分期落地

### Phase 1

- 新增 `CaseTaskPlan`
- 用结构化计划替换纯拼接 prompt

### Phase 2

- 引入 `ExecutionSupervisor`
- 把一条用例拆为多个 checkpoint 执行

### Phase 3

- 引入 `StateProbe` 与 `CheckpointValidator`
- 每段执行后做平台侧校验

### Phase 4

- 引入 `RepairService`
- 支持有限重试、返回、重启 App

### Phase 5

- 重构 `ResultAssertionService` 为 `JudgeService`
- 报告改为 checkpoint 级证据

---

## 16. 关键结论

当前 AutoGLM 准确度不够，根因不只是模型，而是执行框架把“任务拆解、过程监督、状态校验、结果判断”都压得太薄。

最值得做的不是继续堆 prompt，而是建立一套半监督执行框架：

- 结构化计划
- 分 checkpoint 执行
- 平台侧状态探测
- 平台侧成功/失败校验
- 有限自动修复
- 证据驱动的最终 Judge

这样做既能明显提升 Android 准确度，也能自然扩展到 iOS，并且能和现有录制、等待、断言体系接上同一条主干。
