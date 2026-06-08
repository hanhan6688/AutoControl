from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

from app.config import settings


class HarmonyError(RuntimeError):
    pass


@dataclass(frozen=True)
class HarmonyDevice:
    udid: str
    status: str
    platform: str = "harmony"
    model: str | None = None
    product: str | None = None
    os_version: str | None = None
    stream_provider: str | None = None
    stream_available: bool = False
    stream_note: str | None = "HarmonyOS support reserved for future"


class HarmonyService:
    """HarmonyOS device discovery using HDC."""

    def __init__(self, hdc_path: str | None = None) -> None:
        self.hdc_path = hdc_path or settings.resolved_hdc_path

    def list_devices(self) -> list[HarmonyDevice]:
        if shutil.which(self.hdc_path) is None:
            return []

        result = subprocess.run(
            [self.hdc_path, "list", "targets"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            raise HarmonyError(result.stderr.strip() or "hdc list targets failed")

        devices: list[HarmonyDevice] = []
        for line in result.stdout.splitlines():
            value = line.strip()
            if not value or value.lower().startswith(("empty", "list of")):
                continue
            udid = value.split()[0]
            devices.append(
                HarmonyDevice(
                    udid=udid,
                    status="online",
                    stream_provider="hdc",
                    stream_available=False,
                    stream_note="HarmonyOS device discovered; AutoGLM execution uses HDC",
                )
            )
        return devices
