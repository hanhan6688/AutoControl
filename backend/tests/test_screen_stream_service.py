from app.config import settings
import socket
from queue import Empty

from app.services.screen_stream_service import (
    ADBPngStreamSession,
    ScrcpyFfmpegMjpegStreamSession,
    ScrcpyH264StreamSession,
    ScreenStreamIdle,
    ScreenStreamService,
)
from app.routers.devices import _is_recoverable_stream_error, _is_stream_idle_error


def test_auto_stream_ignores_legacy_adb_default(monkeypatch) -> None:
    monkeypatch.setattr(settings, "android_stream_provider", "adb")

    session = ScreenStreamService(adb=object()).create_android_session(
        udid="android-1",
        provider="auto",
    )

    assert isinstance(session, ScrcpyFfmpegMjpegStreamSession)


def test_auto_stream_uses_ffmpeg_mjpeg_default(monkeypatch) -> None:
    monkeypatch.setattr(settings, "android_stream_provider", "scrcpy-ffmpeg-mjpeg")

    session = ScreenStreamService(adb=object()).create_android_session(
        udid="android-1",
        provider="auto",
    )

    assert isinstance(session, ScrcpyFfmpegMjpegStreamSession)


def test_explicit_raw_h264_provider_still_supported() -> None:
    session = ScreenStreamService(adb=object()).create_android_session(
        udid="android-1",
        provider="scrcpy-h264",
    )

    assert isinstance(session, ScrcpyH264StreamSession)


def test_scrcpy_webcodecs_alias_uses_raw_h264_provider() -> None:
    session = ScreenStreamService(adb=object()).create_android_session(
        udid="android-1",
        provider="scrcpy-webcodecs",
    )

    assert isinstance(session, ScrcpyH264StreamSession)


def test_auto_stream_does_not_fallback_to_minicap() -> None:
    providers = ScreenStreamService.fallback_providers_after_failure(
        requested_provider="auto",
        failed_provider="scrcpy-h264",
    )

    assert providers == ["scrcpy-ffmpeg-mjpeg", "adb"]


def test_auto_stream_stops_after_minicap_failure() -> None:
    providers = ScreenStreamService.fallback_providers_after_failure(
        requested_provider="auto",
        failed_provider="minicap",
    )

    assert providers == []


def test_explicit_scrcpy_provider_falls_back_without_minicap() -> None:
    providers = ScreenStreamService.fallback_providers_after_failure(
        requested_provider="scrcpy-h264",
        failed_provider="scrcpy-h264",
    )

    assert providers == ["scrcpy-ffmpeg-mjpeg", "adb"]


def test_explicit_adb_provider_is_supported_as_last_resort() -> None:
    session = ScreenStreamService(adb=object()).create_android_session(
        udid="android-1",
        provider="adb",
    )

    assert isinstance(session, ADBPngStreamSession)


def test_socket_timeout_is_recoverable_stream_error() -> None:
    assert _is_recoverable_stream_error(TimeoutError("timed out")) is True


def test_scrcpy_h264_socket_timeout_is_idle_not_disconnect() -> None:
    class IdleSocket:
        def recv(self, size: int) -> bytes:
            raise socket.timeout("timed out")

    session = ScrcpyH264StreamSession(
        udid="android-1",
        local_port=28183,
        adb=object(),
    )
    session.sock = IdleSocket()

    try:
        session.read_frame()
    except ScreenStreamIdle as exc:
        assert "timed out" in str(exc)
    else:
        raise AssertionError("socket timeout should be reported as stream idle")


def test_stream_idle_is_not_recoverable_disconnect() -> None:
    idle = ScreenStreamIdle("no new frame")

    assert _is_stream_idle_error(idle) is True
    assert _is_recoverable_stream_error(idle) is False


def test_scrcpy_ffmpeg_empty_frame_queue_is_idle_not_disconnect() -> None:
    class EmptyQueue:
        def get(self, timeout: int) -> bytes:
            raise Empty()

    session = ScrcpyFfmpegMjpegStreamSession(
        udid="android-1",
        local_port=28183,
        adb=object(),
    )
    session._frame_queue = EmptyQueue()

    try:
        session.read_frame()
    except ScreenStreamIdle as exc:
        assert "idle timeout" in str(exc)
    else:
        raise AssertionError("ffmpeg frame queue timeout should be reported as stream idle")


def test_scrcpy_raw_stream_keeps_dummy_byte_for_forward_tunnel() -> None:
    session = ScrcpyH264StreamSession(
        udid="android-1",
        local_port=28183,
        max_size=960,
        max_fps=15,
        adb=object(),
    )

    options = session._server_options()

    assert "raw_stream=true" not in options
    assert "control=true" in options
    assert "control=false" not in options
    assert "send_device_meta=false" in options
    assert "send_frame_meta=false" in options
    assert "send_dummy_byte=true" in options


def test_scrcpy_strips_initial_codec_stream_metadata() -> None:
    session = ScrcpyH264StreamSession(
        udid="android-1",
        local_port=28183,
        adb=object(),
    )
    payload = b"h264" + (432).to_bytes(4, "big") + (960).to_bytes(4, "big") + b"\x00\x00\x00\x01"

    assert session._strip_initial_stream_meta(payload) == b"\x00\x00\x00\x01"
    assert session._strip_initial_stream_meta(payload) == payload


def test_scrcpy_video_dummy_byte_is_discarded() -> None:
    class DummySocket:
        def __init__(self) -> None:
            self.timeout = None

        def gettimeout(self):
            return self.timeout

        def settimeout(self, value):
            self.timeout = value

        def recv(self, size: int) -> bytes:
            return b"\x00"

    session = ScrcpyH264StreamSession(udid="android-1", local_port=28183, adb=object())
    session.sock = DummySocket()

    session._read_video_dummy_byte()

    assert session._pending_payload == b""


def test_scrcpy_first_video_byte_is_preserved_when_dummy_is_missing() -> None:
    class FirstFrameSocket:
        def __init__(self) -> None:
            self.timeout = None

        def gettimeout(self):
            return self.timeout

        def settimeout(self, value):
            self.timeout = value

        def recv(self, size: int) -> bytes:
            return b"\x01"

    session = ScrcpyH264StreamSession(udid="android-1", local_port=28183, adb=object())
    session.sock = FirstFrameSocket()

    session._read_video_dummy_byte()

    assert session._pending_payload == b"\x01"
