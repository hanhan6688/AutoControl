"""Tests for ResultAssertionService with JudgeService integration."""
from unittest.mock import MagicMock, patch
from app.services.result_assertion_service import ResultAssertionService
from app.automation.autoglm.judge_service import JudgeService, JudgeResult


def _make_case(**overrides):
    case = MagicMock()
    case.case_name = overrides.get("case_name", "测试用例")
    case.precondition = overrides.get("precondition", "")
    case.steps = overrides.get("steps", [])
    case.expected_result = overrides.get("expected_result", "预期结果")
    case.target_app = overrides.get("target_app", "Demo")
    return case


class TestResultAssertionServiceWithJudgeService:
    def test_judge_verdict_added_when_checkpoints_provided(self):
        service = ResultAssertionService()
        case = _make_case()
        result = service.assert_result(
            case=case,
            action_trace=[],
            checkpoints_passed=2,
            total_checkpoints=2,
            final_app="com.demo.app",
            expected_app="com.demo.app",
        )
        assert "judge_verdict" in result
        assert result["judge_verdict"] == "passed"

    def test_judge_verdict_not_added_without_checkpoints(self):
        """Without checkpoint data, JudgeService is not invoked."""
        service = ResultAssertionService()
        case = _make_case()
        result = service.assert_result(
            case=case,
            action_trace=[],
        )
        assert "judge_verdict" not in result

    def test_judge_overrides_when_more_confident(self):
        """If JudgeService has higher confidence, its verdict takes precedence."""
        service = ResultAssertionService()
        case = _make_case()
        # Fallback would give "uncertain" with low confidence
        result = service.assert_result(
            case=case,
            action_trace=[],
            checkpoints_passed=0,
            total_checkpoints=2,
            final_app="com.demo.app",
            expected_app="com.demo.app",
        )
        # JudgeService should return "failed" with 0.8 confidence for 0 checkpoints
        assert result["judge_verdict"] == "failed"
        # JudgeService confidence > fallback confidence, so verdict is overridden
        assert result["verdict"] == "failed"

    def test_backward_compat_without_new_params(self):
        """Old callers without checkpoint params still work."""
        service = ResultAssertionService()
        case = _make_case()
        result = service.assert_result(
            case=case,
            action_trace=[],
        )
        assert "verdict" in result
        assert result["verdict"] in ("passed", "failed", "uncertain")


class TestJudgeServiceDeterministicLayer:
    def test_passed_when_all_checkpoints_match(self):
        judge = JudgeService()
        result = judge.determine(
            checkpoints_passed=3,
            total_checkpoints=3,
            final_app="com.app",
            expected_app="com.app",
        )
        assert result.verdict == "passed"

    def test_failed_when_app_wrong(self):
        judge = JudgeService()
        result = judge.determine(
            checkpoints_passed=3,
            total_checkpoints=3,
            final_app="com.other",
            expected_app="com.app",
        )
        assert result.verdict == "failed"

    def test_uncertain_when_partial(self):
        judge = JudgeService()
        result = judge.determine(
            checkpoints_passed=1,
            total_checkpoints=3,
            final_app="com.app",
            expected_app="com.app",
        )
        assert result.verdict == "uncertain"
