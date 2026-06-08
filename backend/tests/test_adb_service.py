import subprocess

from app.services.adb_service import ADBService


def test_dump_ui_hierarchy_uses_exec_out_and_strips_uiautomator_trailer(monkeypatch) -> None:
    service = ADBService(adb_path="adb")
    xml = "<?xml version='1.0' encoding='UTF-8'?><hierarchy><node /></hierarchy>"
    calls: list[list[str]] = []

    def fake_run_adb(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=f"{xml}\nUI hierchary dumped to: /dev/tty\n",
            stderr="",
        )

    monkeypatch.setattr(service, "_run_adb", fake_run_adb)

    assert service.dump_ui_hierarchy("device-1") == xml
    assert calls == [["-s", "device-1", "exec-out", "uiautomator", "dump", "--compressed", "/dev/tty"]]


def test_dump_ui_hierarchy_falls_back_to_remote_file_when_exec_out_has_no_xml(monkeypatch) -> None:
    service = ADBService(adb_path="adb")
    xml = "<?xml version='1.0' encoding='UTF-8'?><hierarchy><node /></hierarchy>"

    monkeypatch.setattr(
        service,
        "_run_adb",
        lambda args, timeout: subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="exec failed"),
    )
    monkeypatch.setattr(
        service,
        "shell_raw",
        lambda udid, command, timeout=10: subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=xml,
            stderr="",
        ),
    )

    assert service.dump_ui_hierarchy("device-1") == xml
