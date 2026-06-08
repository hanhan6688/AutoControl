from subprocess import CompletedProcess


def completed(command: str, returncode: int = 0, stdout: str = "", stderr: str = "") -> CompletedProcess[str]:
    return CompletedProcess(args=command, returncode=returncode, stdout=stdout, stderr=stderr)


class FakeADB:
    def __init__(self, responses: dict[str, CompletedProcess[str]] | None = None) -> None:
        self.responses = responses or {}
        self.commands: list[str] = []

    def shell_raw(self, udid: str, command: str, timeout: int = 10) -> CompletedProcess[str]:
        self.commands.append(command)
        return self.responses.get(command, completed(command))

    def capture_screen_png(self, udid: str, timeout: int = 8) -> bytes:
        return b"png"


def test_android_readiness_requires_adb_keyboard_package() -> None:
    from app.services.device_readiness_service import AndroidDeviceReadinessService

    adb = FakeADB(
        {
            "echo mobile_ai_testops_ready": completed("echo", stdout="mobile_ai_testops_ready\n"),
            "dumpsys window": completed("dumpsys", stdout="mCurrentFocus=Window{u0 com.example/.Main}\n"),
            "pm path com.android.adbkeyboard": completed("pm", returncode=1),
        }
    )

    result = AndroidDeviceReadinessService(adb).check("android-1")

    assert result.ready is False
    assert any(issue.code == "adb_keyboard_missing" for issue in result.issues)
    assert "ADB Keyboard" in result.summary


def test_android_readiness_fails_fast_when_device_shell_is_offline() -> None:
    from app.services.device_readiness_service import AndroidDeviceReadinessService

    adb = FakeADB(
        {
            "echo mobile_ai_testops_ready": completed(
                "echo",
                returncode=1,
                stderr="error: device offline",
            ),
        }
    )

    result = AndroidDeviceReadinessService(adb).check("android-1")

    assert result.ready is False
    assert [issue.code for issue in result.issues] == ["adb_shell_unavailable"]
    assert "offline" in result.summary
    assert "dumpsys window" not in adb.commands


def test_android_readiness_requires_adb_keyboard_ime_enabled() -> None:
    from app.services.device_readiness_service import AndroidDeviceReadinessService

    adb = FakeADB(
        {
            "echo mobile_ai_testops_ready": completed("echo", stdout="mobile_ai_testops_ready\n"),
            "dumpsys window": completed("dumpsys", stdout="mCurrentFocus=Window{u0 com.example/.Main}\n"),
            "pm path com.android.adbkeyboard": completed(
                "pm",
                stdout="package:/data/app/com.android.adbkeyboard/base.apk\n",
            ),
            "ime list -s": completed("ime", stdout="com.android.inputmethod.latin/.LatinIME\n"),
            "ime enable com.android.adbkeyboard/.AdbIME": completed("ime enable", returncode=1, stderr="Unknown id"),
        }
    )

    result = AndroidDeviceReadinessService(adb).check("android-1")

    assert result.ready is False
    assert any(issue.code == "adb_keyboard_ime_disabled" for issue in result.issues)
    assert "输入法" in result.summary
