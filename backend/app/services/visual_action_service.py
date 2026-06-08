from __future__ import annotations

import base64
from dataclasses import dataclass
from io import BytesIO
from typing import Any

import httpx
import numpy as np
from PIL import Image
from PIL import UnidentifiedImageError

try:
    import cv2
except ImportError:  # pragma: no cover - exercised only when optional dependency is absent
    cv2 = None

from app.services.adb_service import ADBService
from app.services import u2_service
from app.config import settings


class VisualActionError(RuntimeError):
    pass


@dataclass(frozen=True)
class VisualMatch:
    found: bool
    x: int | None = None
    y: int | None = None
    score: float = 0.0
    width: int | None = None
    height: int | None = None
    text: str | None = None


class VisualActionService:
    def __init__(self, adb: ADBService | None = None) -> None:
        self.adb = adb or ADBService()

    def find_template(self, screen_png: bytes, template_png: bytes, threshold: float = 0.92) -> VisualMatch:
        try:
            screen = Image.open(BytesIO(screen_png)).convert("RGB")
            template = Image.open(BytesIO(template_png)).convert("RGB")
        except UnidentifiedImageError as exc:
            raise VisualActionError("screen or template is not a valid image") from exc
        if template.width > screen.width or template.height > screen.height:
            return VisualMatch(found=False)
        if threshold < 0 or threshold > 1:
            raise VisualActionError("threshold must be between 0 and 1")

        if cv2 is not None and np is not None:
            return self._find_template_with_opencv(screen, template, threshold)

        return self._find_template_bruteforce(screen, template, threshold)

    def _find_template_with_opencv(self, screen: Image.Image, template: Image.Image, threshold: float) -> VisualMatch:
        screen_array = cv2.cvtColor(np.array(screen), cv2.COLOR_RGB2BGR)
        template_array = cv2.cvtColor(np.array(template), cv2.COLOR_RGB2BGR)
        result = cv2.matchTemplate(screen_array, template_array, cv2.TM_SQDIFF_NORMED)
        min_value, _max_value, min_location, _max_location = cv2.minMaxLoc(result)
        score = round(max(0.0, min(1.0, 1.0 - float(min_value))), 4)
        found = score >= threshold
        return VisualMatch(
            found=found,
            x=min_location[0] + template.width // 2 if found else None,
            y=min_location[1] + template.height // 2 if found else None,
            score=score,
            width=template.width if found else None,
            height=template.height if found else None,
        )

    def _find_template_bruteforce(self, screen: Image.Image, template: Image.Image, threshold: float) -> VisualMatch:
        best_score = -1.0
        best_x = 0
        best_y = 0
        screen_pixels = screen.load()
        template_pixels = template.load()
        max_delta = template.width * template.height * 3 * 255

        for y in range(screen.height - template.height + 1):
            for x in range(screen.width - template.width + 1):
                delta = 0
                for ty in range(template.height):
                    for tx in range(template.width):
                        sr, sg, sb = screen_pixels[x + tx, y + ty]
                        tr, tg, tb = template_pixels[tx, ty]
                        delta += abs(sr - tr) + abs(sg - tg) + abs(sb - tb)
                score = 1 - (delta / max_delta)
                if score > best_score:
                    best_score = score
                    best_x = x
                    best_y = y
                    if score == 1.0:
                        break
            if best_score == 1.0:
                break

        found = best_score >= threshold
        return VisualMatch(
            found=found,
            x=best_x + template.width // 2 if found else None,
            y=best_y + template.height // 2 if found else None,
            score=round(max(best_score, 0), 4),
            width=template.width if found else None,
            height=template.height if found else None,
        )

    def click_template(self, udid: str, template_png: bytes, threshold: float = 0.92) -> VisualMatch:
        match = self.find_template(self.adb.capture_screen_png(udid), template_png, threshold=threshold)
        if match.found and match.x is not None and match.y is not None:
            self._tap_device(udid, match.x, match.y)
        return match

    def click_text(self, udid: str, text: str, contains: bool = True) -> VisualMatch:
        screen_png = self.adb.capture_screen_png(udid)
        blocks = self._recognize_text_blocks(screen_png)
        target = text.strip()
        for block in blocks:
            block_text = str(block.get("text", ""))
            matched = target in block_text if contains else target == block_text
            if not matched:
                continue
            x, y = self._box_center(block.get("box"))
            self._tap_device(udid, x, y)
            return VisualMatch(found=True, x=x, y=y, score=float(block.get("score", 0)), text=block_text)

        return VisualMatch(found=False)

    def _tap_device(self, udid: str, x: int, y: int) -> None:
        if settings.u2_enabled:
            try:
                u2_service.click(udid, x, y)
                return
            except Exception:
                pass
        self.adb.shell(udid, f"input tap {x} {y}", timeout=10)

    def _recognize_text_blocks(self, image_png: bytes) -> list[dict[str, Any]]:
        if settings.ocr_base_url:
            return self._recognize_text_blocks_with_umi_ocr(image_png)

        return self._recognize_text_blocks_with_rapidocr(image_png)

    def _recognize_text_blocks_with_umi_ocr(self, image_png: bytes) -> list[dict[str, Any]]:
        payload = {
            "base64": base64.b64encode(image_png).decode("ascii"),
            "options": {
                "data.format": "dict",
                "tbpu.parser": "multi_none",
            },
        }
        try:
            response = httpx.post(f"{settings.ocr_base_url.rstrip('/')}/api/ocr", json=payload, timeout=20)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise VisualActionError(f"OCR request failed: {exc}") from exc

        data = response.json()
        if data.get("code") == 101:
            return []
        if data.get("code") != 100:
            raise VisualActionError(str(data.get("data") or "OCR failed"))
        blocks = data.get("data")
        return blocks if isinstance(blocks, list) else []

    def _recognize_text_blocks_with_rapidocr(self, image_png: bytes) -> list[dict[str, Any]]:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:
            raise VisualActionError(
                "OCR_BASE_URL is not configured and rapidocr-onnxruntime is not installed. "
                "Start Umi-OCR HTTP service or install rapidocr-onnxruntime."
            ) from exc

        try:
            img = Image.open(BytesIO(image_png)).convert("RGB")
        except UnidentifiedImageError as exc:
            raise VisualActionError("screen is not a valid image") from exc

        img_array = np.array(img)
        ocr = RapidOCR()
        result, elapse = ocr(img_array)
        if result is None:
            return []

        blocks = []
        for item in result:
            box, text, score = item
            blocks.append({
                "text": text,
                "box": [[int(p[0]), int(p[1])] for p in box],
                "score": float(score),
            })
        return blocks

    @staticmethod
    def _box_center(box: Any) -> tuple[int, int]:
        if not isinstance(box, list) or len(box) < 4:
            raise VisualActionError("OCR result does not contain a valid box")
        xs = [int(point[0]) for point in box if isinstance(point, (list, tuple)) and len(point) >= 2]
        ys = [int(point[1]) for point in box if isinstance(point, (list, tuple)) and len(point) >= 2]
        if not xs or not ys:
            raise VisualActionError("OCR result does not contain a valid box")
        return round(sum(xs) / len(xs)), round(sum(ys) / len(ys))
