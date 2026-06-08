from __future__ import annotations

import subprocess


def completed(stdout: str = "", stderr: str = "", returncode: int = 0) -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess(
        args=["agent-browser"],
        returncode=returncode,
        stdout=stdout.encode("utf-8"),
        stderr=stderr.encode("utf-8"),
    )


def test_pc_browser_service_opens_url_and_records_logs(monkeypatch) -> None:
    from app.services.pc_browser_service import PCBrowserService

    commands: list[list[str]] = []

    def fake_run(cmd, capture_output, timeout, check):
        commands.append(cmd)
        if "open" in cmd and "https://example.com" in cmd:
            return completed(stdout="✓ PC AutoExecute\nhttps://example.com\n")
        if cmd[-2:] == ["get", "title"]:
            return completed(stdout="PC AutoExecute\n")
        if cmd[-2:] == ["get", "url"]:
            return completed(stdout="https://example.com\n")
        return completed()

    monkeypatch.setattr(subprocess, "run", fake_run)

    service = PCBrowserService(agent_browser_path="agent-browser")
    result = service.open("https://example.com", session="pc")

    assert result.session_id == "pc"
    assert result.title == "PC AutoExecute"
    assert result.url == "https://example.com"
    assert commands[0] == ["agent-browser", "--session", "pc", "open", "https://example.com"]
    assert service.logs(session="pc")[0].command == commands[0]


def test_pc_browser_service_raises_on_nonzero_exit(monkeypatch) -> None:
    from app.services.pc_browser_service import BrowserError, PCBrowserService

    def fake_run(cmd, capture_output, timeout, check):
        return completed(stderr="cannot open url", returncode=1)

    monkeypatch.setattr(subprocess, "run", fake_run)

    service = PCBrowserService(agent_browser_path="agent-browser")

    try:
        service.open("https://invalid.test")
    except BrowserError as exc:
        assert "cannot open url" in str(exc)
    else:
        raise AssertionError("expected BrowserError")


def test_pc_browser_service_records_timeout_as_browser_error(monkeypatch) -> None:
    from app.services.pc_browser_service import BrowserError, PCBrowserService

    def fake_run(cmd, capture_output, timeout, check):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout)

    monkeypatch.setattr(subprocess, "run", fake_run)

    service = PCBrowserService(agent_browser_path="agent-browser")

    try:
        service.snapshot(session="pc")
    except BrowserError as exc:
        assert "timed out after 60s" in str(exc)
    else:
        raise AssertionError("expected BrowserError")

    assert service.logs(session="pc")[0].returncode == 124
