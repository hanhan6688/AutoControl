"""Tests for CheckpointValidator — validates success/failure signals."""

from app.automation.autoglm.case_planner import Checkpoint
from app.automation.autoglm.checkpoint_validator import CheckpointValidator


class TestCheckpointValidator:
    def test_success_signal_found(self):
        validator = CheckpointValidator()
        cp = Checkpoint(id="cp_1", goal="进入首页", success_signals=["首页"], max_steps=12)
        result = validator.validate(cp, source_xml="<node text='首页'/>")
        assert result.passed is True

    def test_success_signal_not_found(self):
        validator = CheckpointValidator()
        cp = Checkpoint(id="cp_1", goal="进入首页", success_signals=["首页"], max_steps=12)
        result = validator.validate(cp, source_xml="<node text='设置'/>")
        assert result.passed is False

    def test_failure_signal_detected(self):
        validator = CheckpointValidator()
        cp = Checkpoint(id="cp_1", goal="进入首页", failure_signals=["崩溃"], max_steps=12)
        result = validator.validate(cp, source_xml="<node text='应用崩溃'/>")
        assert result.failed is True
