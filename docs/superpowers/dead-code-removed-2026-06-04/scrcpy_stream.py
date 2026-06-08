"""Scrcpy H.264 stream manager — captures video via scrcpy CLI and emits NAL units.

Strategy: Run ``scrcpy --no-window --record=<fifo>`` to produce an mkv file,
then read it in real-time with ffmpeg to extract raw H.264.  This is the most
reliable cross-platform approach because the scrcpy CLI handles all ADB setup,
version negotiation, and socket management automatically.

Alternative: If scrcpy --record-format=rawvideo works (scrcpy v2+), we can
read H.264 NAL units directly from stdout.
"""

from __future__ import annotations

import asyncio
import logging
import os
import struct
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator

from app.config import settings
from app.services.adb_service import ADBError, ADBService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScrcpyVideoMetadata:
    device_name: str
    width: int
    height: int
    codec: int


@dataclass(frozen=True)
class ScrcpyVideoPacket:
    type: str  # "configuration" or "data"
    data: bytes
    keyframe: bool = False
    pts: int = 0


class ScrcpyStreamError(RuntimeError):
    pass


class ScrcpyStream:
    """Manages a scrcpy instance and provides an async iterator of H.264 packets.

    Uses the scrcpy CLI command. Two capture strategies are tried:

    1. ``scrcpy --record=- --record-format=h264`` — direct raw H.264 on stdout
    2. Fallback: ``scrcpy --record=<temp>`` + ``ffmpeg -i <temp> -c:v copy -f h264 -``
       — mkv → h264 extraction via ffmpeg pipe
    """

    def __init__(
        self,
        device_id: str,
        max_size: int = 800,
        bit_rate: int = 2_000_000,
        max_fps: int = 30,
        adb: ADBService | None = None,
    ) -> None:
        self.device_id = device_id
        self.max_size = max_size
        self.bit_rate = bit_rate
        self.max_fps = max_fps
        self.adb = adb or ADBService()
        self._process: subprocess.Popen[bytes] | None = None
        self._ffmpeg_process: subprocess.Popen[bytes] | None = None
        self._metadata: ScrcpyVideoMetadata | None = None
        self._running = False
        self._temp_file: str | None = None

    async def start(self) -> None:
        """Start scrcpy and read initial metadata from device."""
        self._running = True

        # Get device screen resolution for metadata
        width, height = 1080, 2400  # defaults
        try:
            size_output = await asyncio.to_thread(
                self.adb.shell, self.device_id, "wm size", timeout=5,
            )
            for line in size_output.splitlines():
                if "Physical size" in line:
                    parts = line.split(":")[-1].strip()
                    w, h = parts.split("x")
                    width, height = int(w), int(h)
                    break
        except Exception as exc:
            logger.debug("Failed to get screen size: %s", exc)

        # Get device model name
        model = self.device_id
        try:
            model = await asyncio.to_thread(
                self.adb.shell, self.device_id, "getprop ro.product.model", timeout=5,
            )
            model = model.strip() or self.device_id
        except Exception:
            pass

        self._metadata = ScrcpyVideoMetadata(
            device_name=model,
            width=width,
            height=height,
            codec=0x68323634,  # "h264"
        )

        scrcpy_path = settings.resolved_scrcpy_path

        # ── Strategy 1: scrcpy --record=- --record-format=h264 ────────
        # This writes raw H.264 to stdout (scrcpy v2.0+).
        command = [
            scrcpy_path,
            "--serial", self.device_id,
            "--no-window",
            "--no-audio",
            "--no-control",
            "--video-codec=h264",
            f"--max-size={self.max_size}",
            f"--video-bit-rate={self.bit_rate}",
            f"--max-fps={self.max_fps}",
            "--record=-",
            "--record-format=h264",
        ]

        try:
            logger.info("scrcpy start: %s", " ".join(command))
            self._process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
            )
            await asyncio.sleep(0.8)
            if self._process.poll() is not None:
                stderr = self._process.stderr.read().decode("utf-8", errors="replace")
                logger.warning("scrcpy exited early (strategy 1): %s", stderr[:500])
                self._process = None
                # Fall through to strategy 2
            else:
                logger.info("scrcpy process started (pid %d) — strategy 1: raw H.264 stdout", self._process.pid)
                return
        except FileNotFoundError:
            logger.warning("scrcpy binary not found at %s", scrcpy_path)
            self._process = None
        except Exception as exc:
            logger.warning("scrcpy strategy 1 failed: %s", exc)
            self._process = None

        # ── Strategy 2: scrcpy --record=<file> + ffmpeg pipe ──────────
        ffmpeg_path = settings.resolved_ffmpeg_path
        if not ffmpeg_path or not Path(ffmpeg_path).exists():
            raise ScrcpyStreamError(f"Neither scrcpy raw output nor ffmpeg available. scrcpy={scrcpy_path}, ffmpeg={ffmpeg_path}")

        # Create temp file for scrcpy recording
        tmp_dir = tempfile.gettempdir()
        self._temp_file = os.path.join(tmp_dir, f"scrcpy_{self.device_id}_{int(time.time())}.mkv")

        scrcpy_cmd = [
            scrcpy_path,
            "--serial", self.device_id,
            "--no-window",
            "--no-audio",
            "--no-control",
            "--video-codec=h264",
            f"--max-size={self.max_size}",
            f"--video-bit-rate={self.bit_rate}",
            f"--max-fps={self.max_fps}",
            f"--record={self._temp_file}",
        ]

        ffmpeg_cmd = [
            ffmpeg_path,
            "-y",
            "-i", self._temp_file,
            "-c:v", "copy",
            "-f", "h264",
            "-",
        ]

        try:
            logger.info("scrcpy start (strategy 2): record=%s", self._temp_file)
            self._process = subprocess.Popen(
                scrcpy_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
            )
            await asyncio.sleep(1.0)  # Wait for scrcpy to start writing

            # Start ffmpeg to extract raw H.264 from the mkv
            self._ffmpeg_process = subprocess.Popen(
                ffmpeg_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
            logger.info("scrcpy + ffmpeg pipeline started — strategy 2")
        except Exception as exc:
            self.stop()
            raise ScrcpyStreamError(f"Failed to start scrcpy+ffmpeg pipeline: {exc}") from exc

    def get_metadata(self) -> ScrcpyVideoMetadata | None:
        return self._metadata

    def _get_stdout(self):
        """Get the stdout pipe to read H.264 data from."""
        if self._ffmpeg_process and self._ffmpeg_process.stdout:
            return self._ffmpeg_process.stdout
        if self._process and self._process.stdout:
            return self._process.stdout
        return None

    async def iter_packets(self) -> AsyncIterator[ScrcpyVideoPacket]:
        """Read raw H.264 stream and yield NAL units."""
        stdout = self._get_stdout()
        if stdout is None:
            logger.error("No stdout pipe available for H.264 reading")
            return

        buffer = b""

        try:
            while self._running:
                chunk = await asyncio.to_thread(stdout.read, 65536)
                if not chunk:
                    logger.info("H.264 stream EOF")
                    break

                buffer += chunk

                # Split on NAL start codes — yield complete NAL units
                while len(buffer) > 4:
                    # Find next start code after the first one
                    next_idx = -1
                    search_start = 1
                    while search_start < len(buffer) - 3:
                        if buffer[search_start:search_start+3] == b"\x00\x00\x01":
                            # Check if it's a 4-byte start code
                            if search_start > 0 and buffer[search_start-1] == 0:
                                next_idx = search_start - 1
                            else:
                                next_idx = search_start
                            break
                        search_start += 1

                    if next_idx == -1:
                        # Keep some buffer for start code detection
                        if len(buffer) > 500_000:
                            # Prevent unbounded growth — yield what we have
                            # as a single packet (likely a large IDR frame)
                            nal_data = buffer
                            buffer = b""
                        else:
                            break

                        nal_type = _get_nal_type(nal_data)
                        yield ScrcpyVideoPacket(
                            type="configuration" if nal_type in (7, 8) else "data",
                            data=nal_data,
                            keyframe=nal_type == 5,
                            pts=int(time.time() * 1_000_000),
                        )
                    else:
                        nal_data = buffer[:next_idx]
                        buffer = buffer[next_idx:]

                        if len(nal_data) < 4:
                            continue

                        nal_type = _get_nal_type(nal_data)

                        yield ScrcpyVideoPacket(
                            type="configuration" if nal_type in (7, 8) else "data",
                            data=nal_data,
                            keyframe=nal_type == 5,
                            pts=int(time.time() * 1_000_000),
                        )

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("H.264 stream read error: %s", exc)
        finally:
            self._running = False

    def stop(self) -> None:
        """Stop all processes and clean up."""
        self._running = False
        for proc in (self._ffmpeg_process, self._process):
            if proc is not None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                except Exception:
                    pass
        self._ffmpeg_process = None
        self._process = None

        # Clean up temp file
        if self._temp_file and os.path.exists(self._temp_file):
            try:
                os.unlink(self._temp_file)
            except Exception:
                pass
            self._temp_file = None


def _get_nal_type(data: bytes) -> int:
    """Extract the NAL unit type from raw H.264 data with start code."""
    if len(data) < 4:
        return 0
    # 4-byte start code: 00 00 00 01
    if data[2] == 0 and data[3] == 1:
        if len(data) > 4:
            return data[4] & 0x1F
    # 3-byte start code: 00 00 01
    elif data[2] == 1:
        if len(data) > 3:
            return data[3] & 0x1F
    return 0
