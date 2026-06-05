"""Tests for PromptBuilder — scoped prompt per checkpoint."""

from app.automation.autoglm.case_planner import Checkpoint
from app.automation.autoglm.prompt_builder import PromptBuilder


class TestPromptBuilder:
    def test_builds_prompt_with_checkpoint_goal(self):
        builder = PromptBuilder()
        cp = Checkpoint(id="cp_1", goal="进入首页", instructions=["打开应用"], success_signals=["看到首页"], max_steps=12)
        prompt = builder.build(checkpoint=cp, platform="android", target_app="贝壳找房")
        assert "进入首页" in prompt
        assert "android" in prompt.lower()

    def test_includes_success_signals(self):
        builder = PromptBuilder()
        cp = Checkpoint(id="cp_1", goal="进入首页", success_signals=["看到首页", "底部导航出现首页标签"], max_steps=12)
        prompt = builder.build(checkpoint=cp, platform="android", target_app="贝壳找房")
        assert "看到首页" in prompt
        assert "底部导航出现首页标签" in prompt

    def test_includes_forbidden_actions(self):
        builder = PromptBuilder()
        cp = Checkpoint(id="cp_1", goal="进入首页", allowed_actions=["tap", "swipe"], max_steps=12)
        prompt = builder.build(checkpoint=cp, platform="android", target_app="贝壳找房")
        assert "tap" in prompt or "swipe" in prompt
