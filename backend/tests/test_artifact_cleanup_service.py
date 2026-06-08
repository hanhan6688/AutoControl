from __future__ import annotations

import os
import time
from pathlib import Path


def test_artifact_cleanup_dry_run_does_not_delete_files(tmp_path: Path) -> None:
    from app.services.artifact_cleanup_service import ArtifactCleanupService

    old_dir = tmp_path / "reports" / "old_run"
    old_dir.mkdir(parents=True)
    artifact = old_dir / "execution.json"
    artifact.write_text("{}", encoding="utf-8")
    old_time = time.time() - 40 * 24 * 60 * 60
    os.utime(old_dir, (old_time, old_time))
    os.utime(artifact, (old_time, old_time))

    result = ArtifactCleanupService(roots=[tmp_path / "reports"]).cleanup(max_age_days=30, dry_run=True)

    assert result["candidate_count"] == 1
    assert old_dir.exists()


def test_artifact_cleanup_removes_old_directories_when_not_dry_run(tmp_path: Path) -> None:
    from app.services.artifact_cleanup_service import ArtifactCleanupService

    old_dir = tmp_path / "uploads" / "old_upload"
    old_dir.mkdir(parents=True)
    artifact = old_dir / "screen.png"
    artifact.write_bytes(b"png")
    old_time = time.time() - 40 * 24 * 60 * 60
    os.utime(old_dir, (old_time, old_time))
    os.utime(artifact, (old_time, old_time))

    result = ArtifactCleanupService(roots=[tmp_path / "uploads"]).cleanup(max_age_days=30, dry_run=False)

    assert result["removed_count"] == 1
    assert not old_dir.exists()


def test_artifact_cleanup_protects_gitkeep(tmp_path: Path) -> None:
    from app.services.artifact_cleanup_service import ArtifactCleanupService

    root = tmp_path / "reports"
    root.mkdir()
    keep = root / ".gitkeep"
    keep.write_text("", encoding="utf-8")
    old_time = time.time() - 40 * 24 * 60 * 60
    os.utime(keep, (old_time, old_time))

    result = ArtifactCleanupService(roots=[root]).cleanup(max_age_days=30, dry_run=False)

    assert result["removed_count"] == 0
    assert keep.exists()
