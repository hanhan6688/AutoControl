from __future__ import annotations

import base64
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.config import settings


class ADBError(RuntimeError):
    pass


@dataclass(frozen=True)
class ADBDevice:
    udid: str
    status: str
    platform: str = "android"
    model: str | None = None
    product: str | None = None
    transport_id: str | None = None
    os_version: str | None = None
    stream_provider: str | None = None
    stream_available: bool = False
    stream_note: str | None = None


class ADBService:
    def __init__(self, adb_path: str | None = None) -> None:
        self.adb_path = adb_path or settings.resolved_adb_path

    def list_devices(self) -> list[ADBDevice]:
        result = self._run(["devices", "-l"], timeout=10)
        devices: list[ADBDevice] = []

        for line in result.stdout.splitlines()[1:]:
            line = line.strip()
            if not line:
                continue

            parts = line.split()
            udid = parts[0]
            status = self._normalize_status(parts[1] if len(parts) > 1 else "unknown")
            details = self._parse_details(parts[2:])
            os_version = self.get_os_version(udid) if status == "online" else None
            devices.append(
                ADBDevice(
                    udid=udid,
                    status=status,
                    platform="android",
                    model=details.get("model"),
                    product=details.get("product"),
                    transport_id=details.get("transport_id"),
                    os_version=os_version,
                    stream_provider=settings.android_stream_provider,
                    stream_available=status == "online",
                    stream_note="online" if status == "online" else "device is not online",
                )
            )

        return devices

    def get_prop(self, udid: str, prop: str) -> str | None:
        result = self._run(["-s", udid, "shell", "getprop", prop], timeout=8)
        value = result.stdout.strip()
        return value or None

    def get_os_version(self, udid: str) -> str | None:
        return self.get_prop(udid, "ro.build.version.release")

    def get_sdk_version(self, udid: str) -> str | None:
        return self.get_prop(udid, "ro.build.version.sdk")

    def get_cpu_abi(self, udid: str) -> str | None:
        return self.get_prop(udid, "ro.product.cpu.abi")

    def get_screen_size(self, udid: str) -> tuple[int, int]:
        result = self._run(["-s", udid, "shell", "wm", "size"], timeout=8)
        match = re.search(r"(\d+)x(\d+)", result.stdout)
        if not match:
            raise ADBError(f"cannot parse screen size: {result.stdout.strip()}")
        return int(match.group(1)), int(match.group(2))

    def push(self, udid: str, local_path: Path, remote_path: str) -> None:
        self._run(["-s", udid, "push", str(local_path), remote_path], timeout=30)

    def shell(self, udid: str, command: str, timeout: int = 10) -> subprocess.CompletedProcess[str]:
        return self._run(["-s", udid, "shell", command], timeout=timeout)

    @staticmethod
    def _decode_result(result: subprocess.CompletedProcess[bytes]) -> subprocess.CompletedProcess[str]:
        """Decode subprocess bytes output to UTF-8 strings."""
        stdout = result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
        stderr = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""
        return subprocess.CompletedProcess(
            args=result.args,
            returncode=result.returncode,
            stdout=stdout,
            stderr=stderr,
        )

    def _run_adb(self, args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        """Run an adb subprocess with binary output and UTF-8 decoding."""
        result = subprocess.run(
            [self.adb_path, *args],
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        return self._decode_result(result)

    def shell_raw(self, udid: str, command: str, timeout: int = 10) -> subprocess.CompletedProcess[str]:
        # shell_raw uses errors="ignore" for stdout to handle mixed encodings
        raw = subprocess.run(
            [self.adb_path, "-s", udid, "shell", command],
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        stdout = raw.stdout.decode("utf-8", errors="ignore") if raw.stdout else ""
        stderr = raw.stderr.decode("utf-8", errors="ignore") if raw.stderr else ""
        return subprocess.CompletedProcess(
            args=raw.args, returncode=raw.returncode, stdout=stdout, stderr=stderr,
        )

    def install_apk(self, udid: str, apk_path: Path, timeout: int = 60) -> subprocess.CompletedProcess[str]:
        result = self._run_adb(["-s", udid, "install", "-r", str(apk_path)], timeout)
        if result.returncode != 0:
            raise ADBError(result.stderr.strip() or result.stdout.strip() or "adb install failed")
        return result

    def forward(self, udid: str, local_port: int, remote: str) -> None:
        self._run(["-s", udid, "forward", f"tcp:{local_port}", remote], timeout=10)

    def remove_forward(self, udid: str, local_port: int) -> None:
        self._run(["-s", udid, "forward", "--remove", f"tcp:{local_port}"], timeout=10)

    def take_screenshot(self, udid: str) -> tuple[Path, str, datetime]:
        created_at = datetime.utcnow()
        safe_udid = re.sub(r"[^A-Za-z0-9_.-]", "_", udid)
        target_dir = settings.uploads_dir / "devices" / safe_udid
        target_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{created_at.strftime('%Y%m%d%H%M%S')}_screenshot.png"
        target_path = target_dir / filename

        result = subprocess.run(
            [self.adb_path, "-s", udid, "exec-out", "screencap", "-p"],
            capture_output=True,
            timeout=20,
            check=False,
        )
        if result.returncode != 0:
            error = (result.stderr.decode("utf-8", errors="ignore") if result.stderr else "").strip()
            raise ADBError(error or "adb screencap failed")
        if not result.stdout:
            raise ADBError("adb screencap returned empty content")

        target_path.write_bytes(result.stdout)
        relative_path = target_path.relative_to(settings.static_dir).as_posix()
        return target_path, f"/static/{relative_path}", created_at

    def capture_screen_png(self, udid: str, timeout: int = 8) -> bytes:
        result = subprocess.run(
            [self.adb_path, "-s", udid, "exec-out", "screencap", "-p"],
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        if result.returncode != 0:
            error = (result.stderr.decode("utf-8", errors="ignore") if result.stderr else "").strip()
            raise ADBError(error or "adb screencap failed")
        if not result.stdout:
            raise ADBError("adb screencap returned empty content")
        return result.stdout

    def dump_ui_hierarchy(self, udid: str, timeout: int = 30) -> str:
        direct_commands = [
            ["-s", udid, "exec-out", "uiautomator", "dump", "--compressed", "/dev/tty"],
            ["-s", udid, "exec-out", "uiautomator", "dump", "/dev/tty"],
        ]
        errors: list[str] = []
        for command in direct_commands:
            result = self._run_adb(command, timeout)
            xml = self._extract_ui_xml(result.stdout)
            if result.returncode == 0 and xml:
                return xml
            errors.append(result.stderr.strip() or result.stdout.strip())

        for remote_path in ("/sdcard/window_dump.xml", "/data/local/tmp/window_dump.xml"):
            result = self.shell_raw(
                udid,
                f"rm -f {remote_path}; "
                f"(uiautomator dump --compressed {remote_path} >/dev/null 2>&1 "
                f"|| uiautomator dump {remote_path} >/dev/null 2>&1); "
                f"cat {remote_path}; rm -f {remote_path}",
                timeout=timeout,
            )
            xml = self._extract_ui_xml(result.stdout)
            if result.returncode == 0 and xml:
                return xml
            errors.append(result.stderr.strip() or result.stdout.strip())

        detail = next((item for item in reversed(errors) if item), "")
        raise ADBError(detail or "uiautomator dump returned empty content")

    @staticmethod
    def _extract_ui_xml(output: str) -> str:
        start = output.find("<?xml")
        if start < 0:
            start = output.find("<hierarchy")
        end = output.rfind("</hierarchy>")
        if start < 0 or end < 0:
            return ""
        return output[start : end + len("</hierarchy>")].strip()

    def ensure_adb_keyboard(self, udid: str) -> str | None:
        """Switch to ADBKeyboard IME for text input. Returns the original IME id."""
        result = self.shell_raw(udid, "settings get secure default_input_method", timeout=5)
        original_ime = result.stdout.strip() or None
        self.shell_raw(
            udid,
            "ime enable com.android.adbkeyboard/.AdbIME && "
            "ime set com.android.adbkeyboard/.AdbIME",
            timeout=5,
        )
        return original_ime

    def restore_keyboard(self, udid: str, original_ime: str) -> None:
        """Restore the original IME after ADBKeyboard use."""
        if not original_ime:
            return
        self.shell_raw(udid, f"ime set {original_ime}", timeout=5)

    def clear_text(self, udid: str) -> None:
        """Clear text in the currently focused input field via ADBKeyboard broadcast."""
        self.shell_raw(udid, "am broadcast -a ADB_CLEAR_TEXT", timeout=5)

    def input_text(self, udid: str, value: str) -> None:
        # Try ADBKeyboard broadcast first (supports Chinese + special chars).
        # The caller (_input_with_keyboard) is responsible for ensuring
        # ADBKeyboard IME is active before calling this method.
        encoded_text = base64.b64encode(value.encode("utf-8")).decode("ascii")
        result = self.shell_raw(
            udid,
            f"am broadcast -a ADB_INPUT_B64 --es msg {encoded_text}",
            timeout=8,
        )
        if result.returncode == 0:
            return
        # Fallback: adb `input text` only supports ASCII
        if not value.isascii():
            raise ADBError(result.stderr.strip() or "ADB Keyboard input failed")
        self.shell(udid, f"input text {self._escape_input_text(value)}", timeout=8)

    def connect(self, address: str, timeout: int = 10) -> tuple[str, bool]:
        """Connect to a remote ADB device (emulator or network device).

        Args:
            address: IP:port or emulator address (e.g., "192.168.1.100:5555", "emulator-5554")
            timeout: Connection timeout in seconds

        Returns:
            tuple of (udid, success)
        """
        result = self._run_adb(["connect", address], timeout)
        output = result.stdout.strip()
        success = "connected" in output.lower() or result.returncode == 0
        udid = address
        return udid, success

    def disconnect(self, address: str, timeout: int = 10) -> bool:
        """Disconnect from a remote ADB device."""
        result = self._run_adb(["disconnect", address], timeout)
        return result.returncode == 0 or "disconnected" in result.stdout.lower()

    def _run(self, args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        result = self._run_adb(args, timeout)
        if result.returncode != 0:
            raise ADBError(result.stderr.strip() or result.stdout.strip() or "adb command failed")
        return result

    @staticmethod
    def _normalize_status(status: str) -> str:
        if status == "device":
            return "online"
        if status in {"offline", "unauthorized"}:
            return status
        return "unknown"

    @staticmethod
    def _parse_details(parts: list[str]) -> dict[str, str]:
        details: dict[str, str] = {}
        for part in parts:
            if ":" not in part:
                continue
            key, value = part.split(":", 1)
            details[key] = value
        return details

    @staticmethod
    def _escape_input_text(value: str) -> str:
        return value.replace("\\", "\\\\").replace(" ", "%s").replace("'", "\\'")
