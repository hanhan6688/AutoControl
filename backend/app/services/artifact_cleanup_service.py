from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.config import settings


@dataclass(frozen=True)
class CleanupCandidate:
    path: Path
    bytes: int
    mtime: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "bytes": self.bytes,
            "modified_at": datetime.fromtimestamp(self.mtime).isoformat(),
        }


class ArtifactCleanupService:
    """Cleanup generated reports and uploads with safe root checks."""

    def __init__(self, roots: list[Path] | None = None) -> None:
        self.roots = roots or [settings.static_dir / "reports", settings.uploads_dir]

    def cleanup(
        self,
        *,
        max_age_days: int | None = None,
        max_total_mb: int | None = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        candidates = self._select_candidates(max_age_days=max_age_days, max_total_mb=max_total_mb)
        removed_bytes = 0
        removed_paths: list[dict[str, Any]] = []

        for candidate in candidates:
            removed_bytes += candidate.bytes
            removed_paths.append(candidate.to_dict())
            if not dry_run:
                self._remove(candidate.path)

        return {
            "dry_run": dry_run,
            "candidate_count": len(candidates),
            "removed_count": 0 if dry_run else len(candidates),
            "candidate_bytes": removed_bytes,
            "candidate_mb": round(removed_bytes / 1024 / 1024, 2),
            "paths": removed_paths,
        }

    def _select_candidates(self, *, max_age_days: int | None, max_total_mb: int | None) -> list[CleanupCandidate]:
        all_candidates = self._collect_candidates()
        selected: dict[Path, CleanupCandidate] = {}

        if max_age_days is not None:
            cutoff = datetime.now() - timedelta(days=max_age_days)
            for candidate in all_candidates:
                if datetime.fromtimestamp(candidate.mtime) < cutoff:
                    selected[candidate.path] = candidate

        if max_total_mb is not None:
            max_total_bytes = max_total_mb * 1024 * 1024
            total_bytes = sum(candidate.bytes for candidate in all_candidates)
            for candidate in sorted(all_candidates, key=lambda item: item.mtime):
                if total_bytes <= max_total_bytes:
                    break
                selected[candidate.path] = candidate
                total_bytes -= candidate.bytes

        return sorted(selected.values(), key=lambda item: item.mtime)

    def _collect_candidates(self) -> list[CleanupCandidate]:
        candidates: list[CleanupCandidate] = []
        for root in self.roots:
            root = root.resolve()
            if not root.exists():
                continue
            for child in root.iterdir():
                if child.name == ".gitkeep":
                    continue
                if not self._is_inside(child, root):
                    continue
                candidates.append(
                    CleanupCandidate(
                        path=child,
                        bytes=self._path_size(child),
                        mtime=child.stat().st_mtime,
                    )
                )
        return candidates

    @staticmethod
    def _remove(path: Path) -> None:
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()

    @staticmethod
    def _path_size(path: Path) -> int:
        if path.is_file():
            return path.stat().st_size
        return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())

    @staticmethod
    def _is_inside(path: Path, root: Path) -> bool:
        resolved = path.resolve()
        return resolved == root or root in resolved.parents
