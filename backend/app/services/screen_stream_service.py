from __future__ import annotations

import socket
import struct
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Full, Queue
from typing import Protocol

from app.config import settings
from app.services.adb_service import ADBError, ADBService
from app.services.scrcpy_control_service import ScrcpyControlClient, scrcpy_control_service


class ScreenStreamError(RuntimeError):
    pass


class ScreenStreamIdle(ScreenStreamError):
    pass


SCRCPY_CONNECT_ATTEMPTS = 12
SCRCPY_CONNECT_TIMEOUT_SECONDS = 0.35
SCRCPY_DUMMY_BYTE_TIMEOUT_SECONDS = 1.0
SCRCPY_READ_TIMEOUT_SECONDS = 6.0


@dataclass(frozen=True)
class StreamFrame:
    payload: bytes
    mime_type: str
    provider: str

class ScreenStreamSession(Protocol):
    provider: str
    mime_type: str

    def start(self) -> None:
        ...

    def read_frame(self) -> StreamFrame:
        ...

    def stop(self) -> None:
        ...


class ADBPngStreamSession:
    provider = "adb"
    mime_type = "image/png"

    def __init__(self, udid: str, adb: ADBService | None = None) -> None:
        self.udid = udid
        self.adb = adb or ADBService()

    def start(self) -> None:
        return None

    def read_frame(self) -> StreamFrame:
        return StreamFrame(
            payload=self.adb.capture_screen_png(self.udid, timeout=8),
            mime_type=self.mime_type,
            provider=self.provider,
        )

    def stop(self) -> None:
        return None


class MinicapStreamSession:
    provider = "minicap"
    mime_type = "image/jpeg"

    def __init__(self, udid: str, local_port: int, adb: ADBService | None = None) -> None:
        self.udid = udid
        self.local_port = local_port
        self.adb = adb or ADBService()
        self.process: subprocess.Popen[bytes] | None = None
        self.sock: socket.socket | None = None

    def start(self) -> None:
        binary_path, so_path = self._resolve_minicap_files()
        width, height = self.adb.get_screen_size(self.udid)

        self.adb.push(self.udid, binary_path, "/data/local/tmp/minicap")
        self.adb.push(self.udid, so_path, "/data/local/tmp/minicap.so")
        self.adb.shell(self.udid, "chmod 755 /data/local/tmp/minicap")
        self.adb.forward(self.udid, self.local_port, "localabstract:minicap")

        projection = f"{width}x{height}@{width}x{height}/0"
        command = f"LD_LIBRARY_PATH=/data/local/tmp /data/local/tmp/minicap -P {projection}"
        self.process = subprocess.Popen(
            [self.adb.adb_path, "-s", self.udid, "shell", command],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        self.sock = self._connect_socket()
        self._read_banner()

    def read_frame(self) -> StreamFrame:
        if self.sock is None:
            raise ScreenStreamError("minicap socket is not connected")

        length_bytes = self._recv_exact(4)
        frame_length = struct.unpack("<I", length_bytes)[0]
        if frame_length <= 0:
            raise ScreenStreamError("minicap returned an empty frame")

        payload = self._recv_exact(frame_length)
        return StreamFrame(payload=payload, mime_type=self.mime_type, provider=self.provider)

    def stop(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            finally:
                self.sock = None

        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
            finally:
                self.process = None

        try:
            self.adb.remove_forward(self.udid, self.local_port)
        except ADBError:
            pass

    def _connect_socket(self) -> socket.socket:
        last_error: OSError | None = None
        for _ in range(30):
            try:
                sock = socket.create_connection(("127.0.0.1", self.local_port), timeout=1)
                sock.settimeout(5)
                return sock
            except OSError as exc:
                last_error = exc
                time.sleep(0.1)
        raise ScreenStreamError(f"minicap socket connect failed: {last_error}")

    def _read_banner(self) -> None:
        banner = self._recv_exact(24)
        version = banner[0]
        banner_length = banner[1]
        if version == 0 or banner_length < 24:
            raise ScreenStreamError("invalid minicap banner")

    def _recv_exact(self, size: int) -> bytes:
        if self.sock is None:
            raise ScreenStreamError("minicap socket is not connected")

        chunks: list[bytes] = []
        remaining = size
        while remaining > 0:
            chunk = self.sock.recv(remaining)
            if not chunk:
                raise ScreenStreamError("minicap socket closed")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _resolve_minicap_files(self) -> tuple[Path, Path]:
        abi = self.adb.get_cpu_abi(self.udid)
        sdk = self.adb.get_sdk_version(self.udid)
        if not abi or not sdk:
            raise ScreenStreamError("cannot resolve device ABI or SDK for minicap")

        binary_candidates = [
            settings.minicap_dir / "bin" / abi / "minicap",
            settings.minicap_dir / abi / "minicap",
            settings.minicap_dir / "minicap",
        ]
        so_candidates = [
            settings.minicap_dir / "libs" / f"android-{sdk}" / abi / "minicap.so",
            settings.minicap_dir / f"android-{sdk}" / abi / "minicap.so",
            settings.minicap_dir / abi / "minicap.so",
            settings.minicap_dir / "minicap.so",
        ]

        binary_path = next((path for path in binary_candidates if path.exists()), None)
        so_path = next((path for path in so_candidates if path.exists()), None)
        if binary_path is None or so_path is None:
            raise ScreenStreamError(
                "minicap files not found. Expected backend/tools/minicap/bin/{abi}/minicap "
                "and backend/tools/minicap/libs/android-{sdk}/{abi}/minicap.so"
            )
        return binary_path, so_path


class ScrcpyH264StreamSession:
    provider = "scrcpy-h264"
    mime_type = "video/h264"

    def __init__(
        self,
        udid: str,
        local_port: int,
        max_size: int = 720,
        max_fps: int = 30,
        control: bool = True,
        adb: ADBService | None = None,
    ) -> None:
        self.udid = udid
        self.local_port = local_port
        self.max_size = max_size
        self.max_fps = max_fps
        self.control = control
        self.adb = adb or ADBService()
        self.process: subprocess.Popen[bytes] | None = None
        self.sock: socket.socket | None = None
        self.control_sock: socket.socket | None = None
        self.control_client: ScrcpyControlClient | None = None
        self._pending_payload = b""
        self._codec_width = 0
        self._codec_height = 0
        self._initial_stream_meta_stripped = False

    def start(self) -> None:
        if not settings.scrcpy_server_path.exists():
            raise ScreenStreamError(f"scrcpy-server not found: {settings.scrcpy_server_path}")

        self._kill_stale_server()
        self.adb.push(self.udid, settings.scrcpy_server_path, "/data/local/tmp/scrcpy-server.jar")
        version = self._scrcpy_version()
        last_error: Exception | None = None

        for _ in range(3):
            self._pending_payload = b""
            self._initial_stream_meta_stripped = False
            try:
                self.adb.remove_forward(self.udid, self.local_port)
            except ADBError:
                pass
            self.adb.forward(self.udid, self.local_port, "localabstract:scrcpy")

            command = [
                self.adb.adb_path,
                "-s",
                self.udid,
                "shell",
                "CLASSPATH=/data/local/tmp/scrcpy-server.jar",
                "app_process",
                "/",
                "com.genymobile.scrcpy.Server",
                version,
                *self._server_options(),
            ]
            self.process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            try:
                self.sock = self._connect_socket(expect_dummy_byte=True)
                if self.control:
                    self.control_sock = self._connect_socket(expect_dummy_byte=False)
                else:
                    self.control_sock = None

                if self.control:
                    try:
                        width, height = self.adb.get_screen_size(self.udid)
                    except ADBError:
                        width, height = 1080, 1920
                    self.control_client = ScrcpyControlClient(self.control_sock, width, height)
                    scrcpy_control_service.register(self.udid, self.control_client)
                return
            except ScreenStreamError as exc:
                last_error = exc
                self.stop()
                time.sleep(0.2)

        raise ScreenStreamError(str(last_error) if last_error else "scrcpy h264 socket connect failed")

    def _server_options(self) -> list[str]:
        return [
            "tunnel_forward=true",
            "audio=false",
            f"control={'true' if self.control else 'false'}",
            "cleanup=false",
            "send_device_meta=false",
            "send_codec_meta=true",
            "send_frame_meta=false",
            "send_dummy_byte=true",
            f"max_size={self.max_size}",
            f"max_fps={self.max_fps}",
            "video_bit_rate=8000000",
            "video_codec=h264",
            "log_level=warn",
        ]

    def read_frame(self) -> StreamFrame:
        """Read a raw H.264 chunk and strip the codec metadata prefix once."""
        if self.sock is None:
            raise ScreenStreamError("scrcpy h264 socket is not connected")

        try:
            payload = self.sock.recv(65536)
        except (ConnectionError, OSError, socket.timeout) as exc:
            if isinstance(exc, socket.timeout):
                raise ScreenStreamIdle(
                    f"scrcpy h264 frame timed out after {SCRCPY_READ_TIMEOUT_SECONDS:g}s"
                ) from exc
            detail = self._server_error_tail()
            message = "scrcpy h264 socket closed"
            if detail:
                message = f"{message}: {detail}"
            raise ScreenStreamError(message) from exc
        if not payload:
            raise ScreenStreamError("scrcpy h264 socket closed")
        payload = self._strip_initial_stream_meta(payload)
        if not payload:
            return self.read_frame()

        return StreamFrame(payload=payload, mime_type=self.mime_type, provider=self.provider)

    # ------------------------------------------------------------------
    # Low-level socket helpers
    # ------------------------------------------------------------------

    def _strip_initial_stream_meta(self, payload: bytes) -> bytes:
        if self._initial_stream_meta_stripped:
            return payload
        self._initial_stream_meta_stripped = True
        if len(payload) < 12:
            return payload
        codec = payload[:4]
        if codec not in {b"h264", b"h265", b"av01"}:
            return payload
        self._codec_width = int.from_bytes(payload[4:8], "big")
        self._codec_height = int.from_bytes(payload[8:12], "big")
        return payload[12:]

    def _kill_stale_server(self) -> None:
        """Kill any leftover scrcpy server on the device and clean stale forwards."""
        try:
            self.adb.shell(self.udid, "pkill -f app_process.*scrcpy-server")
        except Exception:
            pass
        try:
            self.adb.remove_forward(self.udid, self.local_port)
        except ADBError:
            pass
        try:
            self.adb.shell(self.udid, "forward --remove localabstract:scrcpy")
        except Exception:
            pass

    def stop(self) -> None:
        if self.control_client is not None:
            scrcpy_control_service.unregister(self.udid, self.control_client)
            self.control_client = None

        if self.control_sock is not None:
            try:
                self.control_sock.close()
            finally:
                self.control_sock = None

        if self.sock is not None:
            try:
                self.sock.close()
            finally:
                self.sock = None

        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
            finally:
                self.process = None

        try:
            self.adb.remove_forward(self.udid, self.local_port)
        except ADBError:
            pass

        self._initial_stream_meta_stripped = False

    def _connect_socket(self, expect_dummy_byte: bool = True) -> socket.socket:
        last_error: OSError | None = None
        for _ in range(SCRCPY_CONNECT_ATTEMPTS):
            if self.process is not None and self.process.poll() is not None:
                detail = self._server_error_tail()
                message = "scrcpy h264 server exited before socket connected"
                if detail:
                    message = f"{message}: {detail}"
                raise ScreenStreamError(message)
            try:
                sock = socket.create_connection(
                    ("127.0.0.1", self.local_port),
                    timeout=SCRCPY_CONNECT_TIMEOUT_SECONDS,
                )
                if expect_dummy_byte:
                    sock.settimeout(SCRCPY_DUMMY_BYTE_TIMEOUT_SECONDS)
                    dummy = sock.recv(1)
                    if dummy != b"\x00":
                        sock.close()
                        last_error = OSError("scrcpy dummy byte was not received")
                        time.sleep(0.1)
                        continue
                sock.settimeout(SCRCPY_READ_TIMEOUT_SECONDS)
                return sock
            except OSError as exc:
                last_error = exc
                time.sleep(0.1)
        raise ScreenStreamError(f"scrcpy h264 socket connect failed: {last_error}")

    def _read_video_dummy_byte(self) -> None:
        if self.sock is None:
            raise ScreenStreamError("scrcpy h264 socket is not connected")
        previous_timeout = self.sock.gettimeout()
        try:
            self.sock.settimeout(SCRCPY_DUMMY_BYTE_TIMEOUT_SECONDS)
            first = self.sock.recv(1)
        except socket.timeout:
            return
        finally:
            self.sock.settimeout(previous_timeout)

        if first == b"\x00":
            return
        if first:
            self._pending_payload = first

    @staticmethod
    def _scrcpy_version() -> str:
        result = subprocess.run(
            [settings.resolved_scrcpy_path, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode != 0:
            raise ScreenStreamError(result.stderr.strip() or "cannot read scrcpy version")

        first_line = result.stdout.splitlines()[0].strip()
        parts = first_line.split()
        if len(parts) < 2:
            raise ScreenStreamError(f"cannot parse scrcpy version: {first_line}")
        return parts[1]

    def _server_error_tail(self) -> str:
        if self.process is None or self.process.poll() is None or self.process.stderr is None:
            return ""

        try:
            stderr = self.process.stderr.read().decode("utf-8", errors="ignore")
        except OSError:
            return ""
        lines = [line.strip() for line in stderr.splitlines() if line.strip()]
        return " | ".join(lines[-3:])


class ScrcpyFfmpegMjpegStreamSession:
    provider = "scrcpy-ffmpeg-mjpeg"
    mime_type = "image/jpeg"

    def __init__(
        self,
        udid: str,
        local_port: int,
        max_size: int = 720,
        max_fps: int = 30,
        adb: ADBService | None = None,
    ) -> None:
        self.udid = udid
        self.local_port = local_port
        self.max_size = max_size
        self.max_fps = max(1, min(max_fps, 30))
        self.adb = adb or ADBService()
        self.h264_session = ScrcpyH264StreamSession(
            udid=udid,
            local_port=local_port,
            max_size=max_size,
            max_fps=self.max_fps,
            adb=self.adb,
        )
        self.process: subprocess.Popen[bytes] | None = None
        self._stop_event = threading.Event()
        self._frame_queue: Queue[bytes] = Queue(maxsize=3)
        self._feed_thread: threading.Thread | None = None
        self._read_thread: threading.Thread | None = None
        self._worker_error: Exception | None = None

    def start(self) -> None:
        self.h264_session.start()
        command = [
            settings.resolved_ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-fflags",
            "nobuffer",
            "-flags",
            "low_delay",
            "-probesize",
            "32",
            "-analyzeduration",
            "0",
            "-f",
            "h264",
            "-i",
            "pipe:0",
            "-an",
            "-vf",
            f"fps={self.max_fps}",
            "-q:v",
            "5",
            "-f",
            "mjpeg",
            "pipe:1",
        ]

        try:
            self.process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as exc:
            self.h264_session.stop()
            raise ScreenStreamError(f"ffmpeg start failed: {exc}") from exc

        self._feed_thread = threading.Thread(target=self._feed_ffmpeg, name=f"screen-h264-feed-{self.udid}", daemon=True)
        self._read_thread = threading.Thread(target=self._read_mjpeg, name=f"screen-mjpeg-read-{self.udid}", daemon=True)
        self._feed_thread.start()
        self._read_thread.start()

    def read_frame(self) -> StreamFrame:
        try:
            payload = self._frame_queue.get(timeout=5)
            return StreamFrame(payload=payload, mime_type=self.mime_type, provider=self.provider)
        except Empty as exc:
            if self._worker_error is not None:
                raise ScreenStreamError(f"ffmpeg stream worker failed: {self._worker_error}") from self._worker_error
            if self.process is not None and self.process.poll() is not None:
                detail = self._ffmpeg_error_tail()
                message = f"ffmpeg stream exited with code {self.process.returncode}"
                if detail:
                    message = f"{message}: {detail}"
                raise ScreenStreamError(message) from exc
            raise ScreenStreamIdle("ffmpeg decoded frame idle timeout") from exc

    def stop(self) -> None:
        self._stop_event.set()
        self.h264_session.stop()

        if self.process is not None:
            if self.process.stdin is not None:
                try:
                    self.process.stdin.close()
                except OSError:
                    pass
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
            self.process = None

        for thread in (self._feed_thread, self._read_thread):
            if thread is not None and thread.is_alive():
                thread.join(timeout=0.5)
        self._feed_thread = None
        self._read_thread = None

    def _feed_ffmpeg(self) -> None:
        try:
            while not self._stop_event.is_set():
                if self.process is None or self.process.stdin is None or self.process.poll() is not None:
                    return
                try:
                    frame = self.h264_session.read_frame()
                except ScreenStreamIdle:
                    time.sleep(0.01)
                    continue
                self.process.stdin.write(frame.payload)
                self.process.stdin.flush()
        except Exception as exc:
            if not self._stop_event.is_set():
                self._worker_error = exc
            if self.process is not None and self.process.stdin is not None:
                try:
                    self.process.stdin.close()
                except OSError:
                    pass

    def _read_mjpeg(self) -> None:
        if self.process is None or self.process.stdout is None:
            return

        buffer = bytearray()
        try:
            while not self._stop_event.is_set():
                chunk = self.process.stdout.read(4096)
                if not chunk:
                    if self.process.poll() is not None:
                        return
                    time.sleep(0.01)
                    continue
                buffer.extend(chunk)
                self._emit_complete_jpegs(buffer)
        except Exception as exc:
            if not self._stop_event.is_set():
                self._worker_error = exc

    def _emit_complete_jpegs(self, buffer: bytearray) -> None:
        while True:
            start = buffer.find(b"\xff\xd8")
            if start < 0:
                if len(buffer) > 1024 * 1024:
                    del buffer[:-2]
                return
            if start > 0:
                del buffer[:start]

            end = buffer.find(b"\xff\xd9", 2)
            if end < 0:
                return

            payload = bytes(buffer[: end + 2])
            del buffer[: end + 2]
            try:
                self._frame_queue.put_nowait(payload)
            except Full:
                try:
                    self._frame_queue.get_nowait()
                except Empty:
                    pass
                self._frame_queue.put_nowait(payload)

    def _ffmpeg_error_tail(self) -> str:
        if self.process is None or self.process.stderr is None:
            return ""
        try:
            stderr = self.process.stderr.read().decode("utf-8", errors="ignore")
        except OSError:
            return ""
        lines = [line.strip() for line in stderr.splitlines() if line.strip()]
        return " | ".join(lines[-3:])


class ScreenStreamService:
    def __init__(self, adb: ADBService | None = None) -> None:
        self.adb = adb or ADBService()

    def create_android_session(
        self,
        udid: str,
        provider: str = "auto",
        max_size: int = 720,
        max_fps: int = 30,
        control: bool = True,
    ) -> ScreenStreamSession:
        selected_provider = provider if provider != "auto" else settings.android_stream_provider
        if provider == "auto" and selected_provider in {"", "auto", "adb"}:
            selected_provider = "scrcpy-ffmpeg-mjpeg"
        if selected_provider == "scrcpy-webcodecs":
            selected_provider = "scrcpy-h264"

        if selected_provider == "scrcpy-ffmpeg-mjpeg":
            return ScrcpyFfmpegMjpegStreamSession(
                udid=udid,
                local_port=self._scrcpy_port_for_udid(udid),
                max_size=max_size,
                max_fps=max_fps,
                adb=self.adb,
            )
        if selected_provider == "scrcpy-h264":
            return ScrcpyH264StreamSession(
                udid=udid,
                local_port=self._scrcpy_port_for_udid(udid),
                max_size=max_size,
                max_fps=max_fps,
                control=control,
                adb=self.adb,
            )
        if selected_provider == "minicap":
            return MinicapStreamSession(
                udid=udid,
                local_port=self._port_for_udid(udid),
                adb=self.adb,
            )
        if selected_provider == "adb":
            return ADBPngStreamSession(udid=udid, adb=self.adb)

        raise ScreenStreamError(f"unsupported android stream provider: {provider}")

    @staticmethod
    def fallback_providers_after_failure(requested_provider: str, failed_provider: str) -> list[str]:
        requested = ScreenStreamService._normalize_provider(requested_provider)
        failed = ScreenStreamService._normalize_provider(failed_provider)
        if requested == "minicap" or failed == "minicap":
            return []

        chain = ["scrcpy-h264", "scrcpy-ffmpeg-mjpeg", "adb"]
        if failed not in chain:
            return []
        return chain[chain.index(failed) + 1 :]

    @staticmethod
    def _normalize_provider(provider: str) -> str:
        value = (provider or "auto").strip().lower()
        if value == "scrcpy-webcodecs":
            return "scrcpy-h264"
        if value == "auto":
            selected = (settings.android_stream_provider or "scrcpy-h264").strip().lower()
            if selected in {"", "auto"}:
                return "scrcpy-h264"
            if selected == "adb":
                return "scrcpy-ffmpeg-mjpeg"
            if selected == "scrcpy-webcodecs":
                return "scrcpy-h264"
            return selected
        return value

    @staticmethod
    def _port_for_udid(udid: str) -> int:
        return settings.minicap_port_start + (sum(ord(char) for char in udid) % 1000)

    @staticmethod
    def _scrcpy_port_for_udid(udid: str) -> int:
        return settings.scrcpy_web_port_start + (sum(ord(char) for char in udid) % 1000)
