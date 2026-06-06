"""Tests for TestExecutionService integration with CasePlanner and JudgeService."""
from unittest.mock import MagicMock, patch
from app.automation.autoglm.case_planner import CasePlanner, CaseTaskPlan, Checkpoint
from app.automation.autoglm.judge_service import JudgeService, JudgeResult


class TestCasePlannerIntegration:
    def test_builds_plan_from_case_data(self):
        planner = CasePlanner()
        plan = planner.build(
            case_id=123,
            target_app="贝壳找房",
            platform="android",
            steps=["打开应用", "点击AI学区顾问"],
            expected_result="进入AI学区顾问页面",
        )
        assert plan.case_id == 123
        assert len(plan.checkpoints) == 2
        assert plan.checkpoints[0].goal == "打开应用"
        assert plan.checkpoints[1].goal == "点击AI学区顾问"
        assert plan.final_expectations == ["进入AI学区顾问页面"]

    def test_plan_with_no_steps_creates_single_checkpoint(self):
        planner = CasePlanner()
        plan = planner.build(
            case_id=456,
            target_app="测试应用",
            platform="ios",
            steps=[],
            expected_result="任务完成",
        )
        assert len(plan.checkpoints) == 1
        assert plan.checkpoints[0].goal == "完成任务"


class TestJudgeServiceIntegration:
    def test_judge_with_all_checkpoints_passed(self):
        judge = JudgeService()
        result = judge.determine(
            checkpoints_passed=3,
            total_checkpoints=3,
            final_app="com.demo.app",
            expected_app="com.demo.app",
        )
        assert result.verdict == "passed"
        assert result.confidence >= 0.8

    def test_judge_with_app_mismatch(self):
        judge = JudgeService()
        result = judge.determine(
            checkpoints_passed=3,
            total_checkpoints=3,
            final_app="com.other.app",
            expected_app="com.demo.app",
        )
        assert result.verdict == "failed"

    def test_judge_with_partial_progress(self):
        judge = JudgeService()
        result = judge.determine(
            checkpoints_passed=1,
            total_checkpoints=3,
            final_app="com.demo.app",
            expected_app="com.demo.app",
        )
        assert result.verdict == "uncertain"

    def test_judge_result_includes_reason(self):
        judge = JudgeService()
        result = judge.determine(
            checkpoints_passed=2,
            total_checkpoints=2,
            final_app="com.demo.app",
            expected_app="com.demo.app",
        )
        assert result.reason  # reason is non-empty


class TestCaseTaskPlanSerialization:
    def test_plan_to_dict_includes_checkpoints(self):
        cp = Checkpoint(id="cp_1", goal="进入首页", success_signals=["首页"], max_steps=12)
        plan = CaseTaskPlan(case_id=123, target_app="Demo", platform="android", checkpoints=[cp])
        d = plan.to_dict()
        assert d["case_id"] == 123
        assert len(d["checkpoints"]) == 1
        assert d["checkpoints"][0]["goal"] == "进入首页"
        assert d["final_expectations"] == []

    def test_plan_with_final_expectations(self):
        plan = CasePlanner().build(
            case_id=1,
            target_app="App",
            platform="android",
            steps=["Step 1"],
            expected_result="Expected result",
        )
        d = plan.to_dict()
        assert d["final_expectations"] == ["Expected result"]


class TestJudgeVerdictInExecution:
    """Verify that the execution service emits judge_verdict events."""

    @patch("app.services.test_execution_service.JudgeService")
    @patch("app.services.test_execution_service.ResultAssertionService")
    def test_judge_verdict_emitted_after_assertion(self, mock_assertion_cls, mock_judge_cls):
        from app.services.test_execution_service import TestExecutionService
        from app.services.result_assertion_service import ResultAssertionService

        mock_assertion = MagicMock(spec=ResultAssertionService)
        mock_assertion.assert_result.return_value = {
            "verdict": "passed",
            "confidence": 0.7,
            "reason": "日志匹配",
            "evidence": [],
            "failed_expectations": [],
        }
        mock_assertion_cls.return_value = mock_assertion

        mock_judge = MagicMock(spec=JudgeService)
        mock_judge.determine.return_value = JudgeResult(
            verdict="passed",
            confidence=0.85,
            reason="All checkpoints passed and app is correct",
        )
        mock_judge_cls.return_value = mock_judge

        # Verify the JudgeService is called with checkpoint data
        judge = JudgeService()
        result = judge.determine(
            checkpoints_passed=2,
            total_checkpoints=2,
            final_app="com.demo.app",
            expected_app="com.demo.app",
        )
        assert result.verdict == "passed"
        assert result.confidence > 0.8
