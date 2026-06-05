"""Tests for JudgeService — deterministic + AI verdict."""

from app.automation.autoglm.judge_service import JudgeService, JudgeResult


class TestJudgeService:
    def test_deterministic_pass_when_checkpoints_pass(self):
        judge = JudgeService()
        result = judge.determine(checkpoints_passed=3, total_checkpoints=3, final_app="com.demo.app", expected_app="com.demo.app")
        assert result.verdict == "passed"

    def test_deterministic_fail_when_app_mismatch(self):
        judge = JudgeService()
        result = judge.determine(checkpoints_passed=3, total_checkpoints=3, final_app="com.other.app", expected_app="com.demo.app")
        assert result.verdict == "failed"

    def test_deterministic_uncertain_when_partial(self):
        judge = JudgeService()
        result = judge.determine(checkpoints_passed=1, total_checkpoints=3, final_app="com.demo.app", expected_app="com.demo.app")
        assert result.verdict == "uncertain"
