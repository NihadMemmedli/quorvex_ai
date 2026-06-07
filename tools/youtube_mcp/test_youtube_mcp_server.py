from __future__ import annotations

import importlib.util
from pathlib import Path


SERVER_PATH = Path(__file__).with_name("server.py")
spec = importlib.util.spec_from_file_location("youtube_mcp_server", SERVER_PATH)
server = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(server)


def test_prepare_upload_writes_dry_run_manifest(tmp_path: Path, monkeypatch) -> None:
    video = tmp_path / "youtube-001.mp4"
    video.write_bytes(b"dry-run-video")
    monkeypatch.setenv("YOUTUBE_DRY_RUN", "1")

    result = server.youtube_prepare_upload("001", video_path=str(video))

    assert result["status"] == "dry_run_ready"
    manifest_path = server.PROJECT_ROOT / result["manifest_path"]
    assert manifest_path.exists()
    assert str(video) not in result["assets"]["missing"]
    assert result["metadata"]["title"]


def test_upload_video_without_confirm_is_blocked_and_dry_run(tmp_path: Path, monkeypatch) -> None:
    video = tmp_path / "youtube-001.mp4"
    video.write_bytes(b"dry-run-video")
    monkeypatch.setenv("YOUTUBE_DRY_RUN", "1")

    result = server.youtube_upload_video("001", str(video), confirm=False)

    assert result["status"] == "dry_run_blocked"
    assert "No YouTube API mutation" in result["message"]
