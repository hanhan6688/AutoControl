"""PromptBuilder — generates scoped prompts for each checkpoint."""

from __future__ import annotations

from app.automation.autoglm.case_planner import Checkpoint


class PromptBuilder:
    """Builds a constrained prompt for a single checkpoint."""

    def build(self, checkpoint: Checkpoint, platform: str, target_app: str, state_summary: str = "") -> str:
        lines: list[str] = [
            "你正在执行移动端测试的一个阶段任务。",
            "",
            f"平台：{platform}",
            f"目标应用：{target_app}",
            f"当前阶段目标：{checkpoint.goal}",
        ]

        if state_summary:
            lines.extend(["", "当前页面状态摘要：", state_summary])

        if checkpoint.success_signals:
            lines.extend(["", "成功信号："])
            for idx, signal in enumerate(checkpoint.success_signals, start=1):
                lines.append(f"{idx}. {signal}")

        if checkpoint.failure_signals:
            lines.extend(["", "失败信号："])
            for idx, signal in enumerate(checkpoint.failure_signals, start=1):
                lines.append(f"{idx}. {signal}")

        if checkpoint.allowed_actions:
            lines.extend(["", f"允许动作：{', '.join(checkpoint.allowed_actions)}"])

        lines.extend(["", f"最大步数：{checkpoint.max_steps}", "", "如果你认为任务完成，必须让最终界面满足成功信号。"])

        return "\n".join(lines)
