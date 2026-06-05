"""Tests for CaseTaskPlan builder."""

from app.automation.autoglm.case_planner import CaseTaskPlan, Checkpoint, CasePlanner


class TestCaseTaskPlan:
    def test_plan_has_case_id(self):
        plan = CaseTaskPlan(case_id=123, target_app="贝壳找房", platform="android")
        assert plan.case_id == 123
        assert plan.platform == "android"

    def test_plan_has_checkpoints(self):
        cp = Checkpoint(id="cp_1", goal="进入首页", instructions=["打开应用"], success_signals=["看到首页"], max_steps=12)
        plan = CaseTaskPlan(case_id=123, target_app="贝壳找房", platform="android", checkpoints=[cp])
        assert len(plan.checkpoints) == 1
        assert plan.checkpoints[0].id == "cp_1"

    def test_plan_to_dict(self):
        cp = Checkpoint(id="cp_1", goal="进入首页", instructions=["打开应用"], success_signals=["看到首页"], max_steps=12)
        plan = CaseTaskPlan(case_id=123, target_app="贝壳找房", platform="android", checkpoints=[cp])
        d = plan.to_dict()
        assert d["case_id"] == 123
        assert d["checkpoints"][0]["id"] == "cp_1"


class TestCasePlanner:
    def test_build_from_case(self):
        planner = CasePlanner()
        plan = planner.build(
            case_id=123,
            target_app="贝壳找房",
            platform="android",
            launch_app_id="com.ke.app",
            preconditions=["应用已安装"],
            steps=["打开应用", "点击AI学区顾问"],
            expected_result="进入AI学区顾问页面",
        )
        assert plan.case_id == 123
        assert plan.launch_app_id == "com.ke.app"
        assert len(plan.checkpoints) >= 1
        assert plan.checkpoints[0].goal == "打开应用"
