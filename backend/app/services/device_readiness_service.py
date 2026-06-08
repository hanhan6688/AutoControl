from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.config import settings
from app.services.adb_service import ADBError, ADBService


ADB_KEYBOARD_PACKAGE = "com.android.adbkeyboard"
ADB_KEYBOARD_IME = "com.android.adbkeyboard/.AdbIME"


@dataclass(frozen=True)
class DeviceReadinessIssue:
    code: str
    message: str
    action: str


@dataclass(frozen=True)
class DeviceReadinessResult:
    platform: str
    udid: str
    ready: bool
    summary: str
    issues: list[DeviceReadinessIssue] = field(default_factory=list)
    checks: dict[str, object] = field(default_factory=dict)


class AndroidDeviceReadinessService:
    def __init__(self, adb: ADBService | None = None) -> None:
        self.adb = adb or ADBService()

    def check(self, udid: str, *, auto_prepare: bool = True) -> DeviceReadinessResult:
        issues: list[DeviceReadinessIssue] = []
        checks: dict[str, object] = {}

        shell_probe = self.adb.shell_raw(udid, "echo mobile_ai_testops_ready", timeout=5)
        if shell_probe.returncode != 0 or "mobile_ai_testops_ready" not in shell_probe.stdout:
            message = (shell_probe.stderr or shell_probe.stdout or "adb shell 无响应").strip()
            issues.append(
                DeviceReadinessIssue(
                    code="adb_shell_unavailable",
                    message=f"ADB shell 不可用：{message}",
                    action="请在手机上允许 USB 调试授权；如果显示 offline，请重新插拔数据线、解锁手机后执行 adb kill-server && adb start-server。",
                )
            )
            return self._result(udid, issues, checks)
        checks["adb_shell"] = "ok"

        window_probe = self._probe_window(udid, auto_prepare=auto_prepare)
        checks["dumpsys_window"] = "ok" if window_probe else "empty"
        if not window_probe:
            issues.append(
                DeviceReadinessIssue(
                    code="window_unavailable",
                    message="手机窗口信息不可用：dumpsys window 没有输出。",
                    action="请保持手机解锁、亮屏，并确认 USB 调试仍为在线状态；隐私空间、应用锁或安全黑屏页面可能会阻止自动化读取窗口。",
                )
            )

        try:
            screenshot = self.adb.capture_screen_png(udid, timeout=8)
            checks["screenshot_bytes"] = len(screenshot)
            if not screenshot:
                issues.append(
                    DeviceReadinessIssue(
                        code="screenshot_empty",
                        message="手机截图为空，AutoGLM 无法观察当前屏幕。",
                        action="请解锁手机、关闭安全黑屏/隐私保护页面后重试。",
                    )
                )
        except Exception as exc:
            checks["screenshot_error"] = str(exc)
            issues.append(
                DeviceReadinessIssue(
                    code="screenshot_failed",
                    message=f"手机截图失败：{exc}",
                    action="请确认设备在线、屏幕亮起，并允许 USB 调试。",
                )
            )

        if not self._is_adb_keyboard_installed(udid):
            apk_path = settings.resolved_adb_keyboard_apk_path
            if auto_prepare and apk_path:
                install_error = self._install_adb_keyboard(udid, apk_path)
                if install_error:
                    issues.append(
                        DeviceReadinessIssue(
                            code="adb_keyboard_install_failed",
                            message=f"ADB Keyboard 自动安装失败：{install_error}",
                            action="请手动安装 ADBKeyboard.apk，或检查 ADB_KEYBOARD_APK_PATH 指向的 APK 是否可安装。",
                        )
                    )
                elif not self._is_adb_keyboard_installed(udid):
                    issues.append(
                        DeviceReadinessIssue(
                            code="adb_keyboard_missing",
                            message="已尝试安装 ADB Keyboard，但手机上仍检测不到该应用。",
                            action="请手动安装 ADBKeyboard.apk 后重试。",
                        )
                    )
            else:
                issues.append(
                    DeviceReadinessIssue(
                        code="adb_keyboard_missing",
                        message="手机未安装 ADB Keyboard，AutoGLM 输入中文/复杂文本会失败。",
                        action="请安装 ADBKeyboard.apk，或把 APK 放到项目工具目录并在 backend/.env 配置 ADB_KEYBOARD_APK_PATH。",
                    )
                )

        if self._is_adb_keyboard_installed(udid):
            ime_ready = self._ensure_adb_keyboard_ime(udid, auto_prepare=auto_prepare)
            checks["adb_keyboard_ime"] = "ok" if ime_ready else "disabled"
            if not ime_ready:
                issues.append(
                    DeviceReadinessIssue(
                        code="adb_keyboard_ime_disabled",
                        message="ADB Keyboard 已安装，但没有启用为可用输入法。",
                        action="请在手机 设置 > 输入法/键盘 中启用 ADB Keyboard，或允许系统通过 ADB 执行 ime enable。",
                    )
                )
        else:
            checks["adb_keyboard_ime"] = "missing_package"

        return self._result(udid, issues, checks)

    def _probe_window(self, udid: str, *, auto_prepare: bool) -> bool:
        window_probe = self.adb.shell_raw(udid, "dumpsys window", timeout=10)
        if window_probe.returncode == 0 and window_probe.stdout.strip():
            return True
        if not auto_prepare:
            return False

        self.adb.shell_raw(udid, "input keyevent KEYCODE_WAKEUP", timeout=5)
        self.adb.shell_raw(udid, "wm dismiss-keyguard", timeout=5)
        retry = self.adb.shell_raw(udid, "dumpsys window", timeout=10)
        return retry.returncode == 0 and bool(retry.stdout.strip())

    def _is_adb_keyboard_installed(self, udid: str) -> bool:
        result = self.adb.shell_raw(udid, f"pm path {ADB_KEYBOARD_PACKAGE}", timeout=8)
        return result.returncode == 0 and "package:" in result.stdout

    def _install_adb_keyboard(self, udid: str, apk_path: Path) -> str | None:
        try:
            self.adb.install_apk(udid, apk_path)
            return None
        except (ADBError, OSError, TimeoutError) as exc:
            return str(exc)

    def _ensure_adb_keyboard_ime(self, udid: str, *, auto_prepare: bool) -> bool:
        enabled = self.adb.shell_raw(udid, "ime list -s", timeout=8)
        if ADB_KEYBOARD_IME in enabled.stdout:
            return True
        if not auto_prepare:
            return False

        self.adb.shell_raw(udid, f"ime enable {ADB_KEYBOARD_IME}", timeout=8)
        enabled_after = self.adb.shell_raw(udid, "ime list -s", timeout=8)
        return ADB_KEYBOARD_IME in enabled_after.stdout

    @staticmethod
    def _result(
        udid: str,
        issues: list[DeviceReadinessIssue],
        checks: dict[str, object],
    ) -> DeviceReadinessResult:
        if issues:
            summary = "；".join(f"{issue.message} 处理方式：{issue.action}" for issue in issues)
        else:
            summary = "Android 设备自动化依赖检查通过。"
        return DeviceReadinessResult(
            platform="android",
            udid=udid,
            ready=not issues,
            summary=summary,
            issues=issues,
            checks=checks,
        )
