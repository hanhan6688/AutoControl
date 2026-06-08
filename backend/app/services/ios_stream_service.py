"""iOS screen stream using WebDriverAgent screenshot polling.

Unlike Android's scrcpy H.264 stream, iOS uses WDA's screenshot API
which returns PNG images. These are converted to JPEG for bandwidth
efficiency and sent directly to the frontend where they are rendered
to canvas via createImageBitmap.
"""

from __future__ import annotations

import asyncio
import io
import logging
from dataclasses import dataclass
from typing import AsyncIterator

from PIL import Image

from app.services import wda_service

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IosVideoMetadata:
    device_name: str
    width: int
    height: int
    codec: str = "mjpeg"


class IosStreamService:
    """Polls WDA for screenshots and yields JPEG frames at a target FPS.

    Usage::

        stream = IosStreamService(device_id="...", target_fps=10)
        await stream.start()
        async for jpeg_data in stream.iter_frames():
            # send jpeg_data to client
        stream.stop()
    """

    def __init__(
        self,
        device_id: str,
        target_fps: int = 10,
    ) -> None:
        self.device_id = device_id
        self.target_fps = target_fps
        self._running = False
        self._metadata: IosVideoMetadata | None = None

    async def start(self) -> None:
        """Initialize the stream by taking a test screenshot to get resolution."""
        self._running = True
        try:
            png_bytes = await asyncio.to_thread(wda_service.screenshot, self.device_id)
            if png_bytes:
                img = Image.open(io.BytesIO(png_bytes))
                self._metadata = IosVideoMetadata(
                    device_name=self.device_id,
                    width=img.width,
                    height=img.height,
                )
        except Exception as exc:
            logger.warning("iOS stream init screenshot failed: %s", exc)
            self._metadata = IosVideoMetadata(
                device_name=self.device_id,
                width=390,
                height=844,
            )

    def get_metadata(self) -> IosVideoMetadata | None:
        return self._metadata

    async def iter_frames(self) -> AsyncIterator[bytes]:
        """Yield JPEG frames from WDA screenshot polling."""
        interval = 1.0 / max(1, self.target_fps)
        while self._running:
            try:
                png_bytes = await asyncio.to_thread(wda_service.screenshot, self.device_id)
                if png_bytes:
                    # Convert PNG to JPEG for bandwidth efficiency
                    img = Image.open(io.BytesIO(png_bytes))
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=70)
                    yield buf.getvalue()
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.debug("iOS screenshot poll error: %s", exc)
                await asyncio.sleep(0.5)

    def stop(self) -> None:
        self._running = False
