from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass

from app.config import settings


class IOSError(RuntimeError):
    pass


@dataclass(frozen=True)
class IOSDevice:
    udid: str
    status: str
    platform: str = "ios"
    model: str | None = None
    product: str | None = None
    transport_id: str | None = None
    os_version: str | None = None
    stream_provider: str | None = "go-ios"
    stream_available: bool = False
    stream_note: str | None = "go-ios command is not available"


class IOSService:
    def __init__(self, ios_path: str | None = None) -> None:
        self.ios_path = ios_path or settings.resolved_ios_path

    def list_devices(self) -> list[IOSDevice]:
        if shutil.which(self.ios_path) is None:
            return []

        result = subprocess.run(
            [self.ios_path, "list", "--details"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            fallback = subprocess.run(
                [self.ios_path, "list"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if fallback.returncode != 0:
                raise IOSError(fallback.stderr.strip() or result.stderr.strip() or "go-ios list failed")
            return self._parse_plain_list(fallback.stdout)

        return self._parse_details(result.stdout)

    @staticmethod
    def _parse_details(output: str) -> list[IOSDevice]:
        try:
            payload = json.loads(output)
        except json.JSONDecodeError:
            return IOSService._parse_plain_list(output)

        if isinstance(payload, dict):
            raw_devices = payload.get("deviceList") or payload.get("devices") or []
        elif isinstance(payload, list):
            raw_devices = payload
        else:
            raw_devices = []

        devices: list[IOSDevice] = []
        for item in raw_devices:
            if not isinstance(item, dict):
                continue
            udid = item.get("udid") or item.get("UDID") or item.get("identifier")
            if not udid:
                continue
            devices.append(
                IOSDevice(
                    udid=udid,
                    status="online",
                    model=item.get("deviceName") or item.get("name") or item.get("model"),
                    product=item.get("productType") or item.get("ProductType"),
                    os_version=item.get("productVersion") or item.get("ProductVersion"),
                    stream_note="go-ios device discovered; screen stream adapter reserved",
                )
            )
        return devices

    @staticmethod
    def _parse_plain_list(output: str) -> list[IOSDevice]:
        devices: list[IOSDevice] = []
        for line in output.splitlines():
            value = line.strip()
            if not value or value.lower().startswith(("udid", "no device")):
                continue
            udid = value.split()[0]
            devices.append(
                IOSDevice(
                    udid=udid,
                    status="online",
                    stream_note="go-ios device discovered; screen stream adapter reserved",
                )
            )
        return devices
