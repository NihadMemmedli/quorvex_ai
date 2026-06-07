#!/usr/bin/env python3
"""FastMCP server for guarded Quorvex YouTube publishing workflows."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EPISODES_DIR = PROJECT_ROOT / "content" / "youtube" / "episodes"
MANIFEST_NAME = "youtube-upload-manifest.json"
YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.upload",
]

mcp = FastMCP(
    "quorvex-youtube-upload",
    instructions=(
        "Prepare and execute YouTube upload workflows for Quorvex episodes. "
        "All account-mutating tools default to dry-run manifests and require confirm=true plus YOUTUBE_DRY_RUN=0."
    ),
)


class EpisodeAssets(BaseModel):
    """Resolved local files for a YouTube episode."""

    episode_id: str
    episode_dir: str
    metadata_path: str | None = None
    script_path: str | None = None
    captions_path: str | None = None
    shot_list_path: str | None = None
    video_path: str | None = None
    thumbnail_path: str | None = None
    missing: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _relative(path: Path | str | None) -> str | None:
    if path is None:
        return None
    resolved = Path(path)
    try:
        return str(resolved.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(resolved)


def _episode_dir(episode_id: str) -> Path:
    clean_id = episode_id.strip()
    if not clean_id:
        raise ValueError("episode_id is required, for example '001'.")
    if "/" in clean_id or "\\" in clean_id or clean_id.startswith("."):
        raise ValueError("episode_id must be a simple folder name such as '001'.")
    return EPISODES_DIR / clean_id


def _build_dir(episode_id: str) -> Path:
    path = _episode_dir(episode_id) / "build"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _resolve_path(value: str | None, *, base: Path = PROJECT_ROOT) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    return path


def _find_first(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists() and path.is_file():
            return path
    return None


def _default_video_path(episode_id: str) -> Path | None:
    episode_dir = _episode_dir(episode_id)
    return _find_first(
        [
            episode_dir / "build" / f"youtube-{episode_id}.mp4",
            episode_dir / "build" / f"{episode_id}.mp4",
            episode_dir / f"youtube-{episode_id}.mp4",
        ]
    )


def _default_thumbnail_path(episode_id: str) -> Path | None:
    episode_dir = _episode_dir(episode_id)
    candidates: list[Path] = []
    for directory in (episode_dir, episode_dir / "build", episode_dir / "renders"):
        for stem in ("thumbnail", f"thumbnail-{episode_id}", f"youtube-{episode_id}-thumbnail"):
            for ext in (".png", ".jpg", ".jpeg", ".webp"):
                candidates.append(directory / f"{stem}{ext}")
    return _find_first(candidates)


def _read_section(markdown: str, heading: str) -> str:
    lines = markdown.splitlines()
    capture = False
    captured: list[str] = []
    target = f"## {heading}".lower()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            if capture:
                break
            capture = stripped.lower() == target
            continue
        if capture:
            captured.append(line)
    return "\n".join(captured).strip()


def _strip_code_fences(text: str) -> str:
    lines = text.splitlines()
    if len(lines) >= 2 and lines[0].strip().startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return text.strip()


def _parse_tags(text: str) -> list[str]:
    return [part.strip() for part in text.replace("\n", ",").split(",") if part.strip()]


def _load_episode_metadata(episode_id: str) -> dict[str, Any]:
    path = _episode_dir(episode_id) / "metadata.md"
    if not path.exists():
        raise FileNotFoundError(f"Missing YouTube metadata file: {_relative(path)}")
    markdown = path.read_text(encoding="utf-8")
    title = _read_section(markdown, "Recommended Title").splitlines()
    description = _strip_code_fences(_read_section(markdown, "Description"))
    tags = _parse_tags(_read_section(markdown, "Tags"))
    if not title or not title[0].strip():
        raise ValueError(f"Missing 'Recommended Title' section in {_relative(path)}.")
    if not description:
        raise ValueError(f"Missing 'Description' section in {_relative(path)}.")
    return {
        "title": title[0].strip(),
        "description": description,
        "tags": tags,
        "categoryId": os.environ.get("YOUTUBE_CATEGORY_ID", "28"),
        "privacyStatus": os.environ.get("YOUTUBE_PRIVACY_STATUS", "private"),
        "selfDeclaredMadeForKids": os.environ.get("YOUTUBE_MADE_FOR_KIDS", "0").lower() in {"1", "true", "yes"},
    }


def _dry_run_enabled(env_name: str = "YOUTUBE_DRY_RUN") -> bool:
    return os.environ.get(env_name, "1").lower() not in {"0", "false", "no", "off"}


def _required_confirmation(action: str, episode_id: str | None = None, extra: str = "") -> str:
    base = f"YOUTUBE_DRY_RUN=0 python tools/youtube_mcp/server.py {action}"
    if episode_id:
        base += f" --episode {episode_id}"
    if extra:
        base += f" {extra}"
    return f"{base} --confirm"


def _write_manifest(episode_id: str, manifest: dict[str, Any]) -> Path:
    path = _build_dir(episode_id) / MANIFEST_NAME
    payload = {
        "generated_at": _utc_now(),
        "dry_run": True,
        **manifest,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _validate_episode_assets(
    episode_id: str,
    video_path: str | None = None,
    thumbnail_path: str | None = None,
) -> EpisodeAssets:
    episode_dir = _episode_dir(episode_id)
    missing: list[str] = []
    warnings: list[str] = []

    if not episode_dir.exists():
        raise FileNotFoundError(f"Episode folder not found: {_relative(episode_dir)}")

    required = {
        "metadata.md": episode_dir / "metadata.md",
        "script.md": episode_dir / "script.md",
        "captions.srt": episode_dir / "captions.srt",
        "shot-list.md": episode_dir / "shot-list.md",
    }
    for label, path in required.items():
        if not path.exists():
            missing.append(label)

    resolved_video = _resolve_path(video_path) or _default_video_path(episode_id)
    resolved_thumbnail = _resolve_path(thumbnail_path) or _default_thumbnail_path(episode_id)

    if resolved_video is None or not resolved_video.exists():
        missing.append(video_path or f"build/youtube-{episode_id}.mp4")
    if resolved_thumbnail is None or not resolved_thumbnail.exists():
        missing.append(thumbnail_path or "thumbnail image under episode root, build/, or renders/")

    try:
        _load_episode_metadata(episode_id)
    except (FileNotFoundError, ValueError) as exc:
        missing.append(str(exc))

    return EpisodeAssets(
        episode_id=episode_id,
        episode_dir=_relative(episode_dir) or str(episode_dir),
        metadata_path=_relative(required["metadata.md"]) if required["metadata.md"].exists() else None,
        script_path=_relative(required["script.md"]) if required["script.md"].exists() else None,
        captions_path=_relative(required["captions.srt"]) if required["captions.srt"].exists() else None,
        shot_list_path=_relative(required["shot-list.md"]) if required["shot-list.md"].exists() else None,
        video_path=_relative(resolved_video) if resolved_video and resolved_video.exists() else None,
        thumbnail_path=_relative(resolved_thumbnail) if resolved_thumbnail and resolved_thumbnail.exists() else None,
        missing=missing,
        warnings=warnings,
    )


def _prepare_upload_manifest(
    episode_id: str,
    video_path: str | None = None,
    thumbnail_path: str | None = None,
    action: str = "prepare_upload",
) -> dict[str, Any]:
    assets = _validate_episode_assets(episode_id, video_path, thumbnail_path)
    metadata = _load_episode_metadata(episode_id)
    manifest = {
        "action": action,
        "episode_id": episode_id,
        "channel_id": os.environ.get("YOUTUBE_CHANNEL_ID"),
        "assets": assets.model_dump(),
        "metadata": metadata,
        "required_confirmation_command": _required_confirmation(
            "upload-video",
            episode_id,
            f"--video-path {assets.video_path or (video_path or f'content/youtube/episodes/{episode_id}/build/youtube-{episode_id}.mp4')}",
        ),
    }
    path = _write_manifest(episode_id, manifest)
    return {
        "status": "dry_run_ready",
        "manifest_path": _relative(path),
        **manifest,
    }


def _credentials_config() -> dict[str, str | None]:
    return {
        "client_secrets_file": os.environ.get("YOUTUBE_CLIENT_SECRETS_FILE"),
        "token_file": os.environ.get("YOUTUBE_TOKEN_FILE"),
        "channel_id": os.environ.get("YOUTUBE_CHANNEL_ID"),
    }


def _require_youtube_service() -> Any:
    config = _credentials_config()
    token_file = config["token_file"]
    if not token_file:
        raise RuntimeError("YOUTUBE_TOKEN_FILE is required for confirmed YouTube API calls.")
    token_path = _resolve_path(token_file)
    if token_path is None or not token_path.exists():
        raise RuntimeError(
            "YouTube token file was not found. Run OAuth setup first and set YOUTUBE_TOKEN_FILE to the token JSON path."
        )
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError(
            "Missing YouTube API dependencies. Install google-api-python-client, google-auth-oauthlib, "
            "and google-auth-httplib2 in the active Python environment."
        ) from exc

    credentials = Credentials.from_authorized_user_file(str(token_path), YOUTUBE_SCOPES)
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        token_path.write_text(credentials.to_json(), encoding="utf-8")
    if not credentials.valid:
        raise RuntimeError(
            "YouTube credentials are invalid or expired. Refresh the OAuth token and retry the confirmed action."
        )
    return build("youtube", "v3", credentials=credentials)


def _upload_video_confirmed(episode_id: str, video_path: str) -> dict[str, Any]:
    service = _require_youtube_service()
    try:
        from googleapiclient.http import MediaFileUpload
    except ImportError as exc:
        raise RuntimeError("Missing google-api-python-client dependency for MediaFileUpload.") from exc

    assets = _validate_episode_assets(episode_id, video_path, None)
    if assets.missing:
        raise FileNotFoundError(f"Cannot upload until missing assets are fixed: {assets.missing}")
    metadata = _load_episode_metadata(episode_id)
    body = {
        "snippet": {
            "title": metadata["title"],
            "description": metadata["description"],
            "tags": metadata["tags"],
            "categoryId": metadata["categoryId"],
        },
        "status": {
            "privacyStatus": metadata["privacyStatus"],
            "selfDeclaredMadeForKids": metadata["selfDeclaredMadeForKids"],
        },
    }
    request = service.videos().insert(
        part="snippet,status",
        body=body,
        media_body=MediaFileUpload(str(_resolve_path(video_path)), chunksize=-1, resumable=True),
    )
    response = request.execute()
    return {
        "status": "uploaded",
        "video_id": response.get("id"),
        "response": response,
    }


def _get_video(service: Any, video_id: str, part: str = "snippet,status") -> dict[str, Any]:
    response = service.videos().list(part=part, id=video_id).execute()
    items = response.get("items", [])
    if not items:
        raise RuntimeError(f"YouTube video not found or inaccessible: {video_id}")
    return items[0]


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def youtube_validate_episode_assets(episode_id: str) -> dict[str, Any]:
    """Validate local episode files before upload preparation."""
    assets = _validate_episode_assets(episode_id)
    return {
        "ok": not assets.missing,
        "assets": assets.model_dump(),
        "next_step": "Run make youtube-final EP=<id> RECORDING=<path> if the final MP4 is missing.",
    }


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def youtube_prepare_upload(
    episode_id: str,
    video_path: str | None = None,
    thumbnail_path: str | None = None,
) -> dict[str, Any]:
    """Create a dry-run upload manifest for an episode without calling YouTube."""
    return _prepare_upload_manifest(episode_id, video_path, thumbnail_path)


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)
)
def youtube_upload_video(episode_id: str, video_path: str, confirm: bool = False) -> dict[str, Any]:
    """Upload an episode MP4 to YouTube only when confirm=true and YOUTUBE_DRY_RUN=0."""
    if not confirm or _dry_run_enabled():
        result = _prepare_upload_manifest(episode_id, video_path, None, action="upload_video")
        result["status"] = "dry_run_blocked"
        result["message"] = "No YouTube API mutation was made. Set confirm=true and YOUTUBE_DRY_RUN=0 to upload."
        return result
    return _upload_video_confirmed(episode_id, video_path)


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)
)
def youtube_update_metadata(video_id: str, metadata: dict[str, Any], confirm: bool = False) -> dict[str, Any]:
    """Update title, description, tags, category, or privacy for a YouTube video with confirmation."""
    if not confirm or _dry_run_enabled():
        return {
            "status": "dry_run_blocked",
            "action": "update_metadata",
            "video_id": video_id,
            "metadata": metadata,
            "message": "No YouTube metadata was changed. Set confirm=true and YOUTUBE_DRY_RUN=0 to update.",
            "required_confirmation_command": _required_confirmation(
                "update-metadata",
                extra=f"--video-id {video_id} --metadata-json '<json>'",
            ),
        }
    service = _require_youtube_service()
    existing = _get_video(service, video_id)
    snippet = existing.get("snippet", {})
    snippet.update({key: value for key, value in metadata.items() if key in {"title", "description", "tags", "categoryId"}})
    response = service.videos().update(part="snippet", body={"id": video_id, "snippet": snippet}).execute()
    return {"status": "metadata_updated", "video_id": video_id, "response": response}


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)
)
def youtube_set_thumbnail(video_id: str, thumbnail_path: str, confirm: bool = False) -> dict[str, Any]:
    """Set a custom YouTube thumbnail with confirmation."""
    resolved = _resolve_path(thumbnail_path)
    if resolved is None or not resolved.exists():
        raise FileNotFoundError(f"Thumbnail not found: {thumbnail_path}")
    if not confirm or _dry_run_enabled():
        return {
            "status": "dry_run_blocked",
            "action": "set_thumbnail",
            "video_id": video_id,
            "thumbnail_path": _relative(resolved),
            "message": "No YouTube thumbnail was changed. Set confirm=true and YOUTUBE_DRY_RUN=0 to update.",
            "required_confirmation_command": _required_confirmation(
                "set-thumbnail",
                extra=f"--video-id {video_id} --thumbnail-path {_relative(resolved)}",
            ),
        }
    service = _require_youtube_service()
    try:
        from googleapiclient.http import MediaFileUpload
    except ImportError as exc:
        raise RuntimeError("Missing google-api-python-client dependency for MediaFileUpload.") from exc
    response = service.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(resolved))).execute()
    return {"status": "thumbnail_updated", "video_id": video_id, "response": response}


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)
)
def youtube_schedule_publish(video_id: str, publish_at: str, confirm: bool = False) -> dict[str, Any]:
    """Schedule a private YouTube video for publication at an ISO 8601 timestamp."""
    if not confirm or _dry_run_enabled():
        return {
            "status": "dry_run_blocked",
            "action": "schedule_publish",
            "video_id": video_id,
            "publish_at": publish_at,
            "message": "No YouTube schedule was changed. Set confirm=true and YOUTUBE_DRY_RUN=0 to schedule.",
            "required_confirmation_command": _required_confirmation(
                "schedule-publish",
                extra=f"--video-id {video_id} --publish-at {publish_at}",
            ),
        }
    service = _require_youtube_service()
    existing = _get_video(service, video_id)
    status = existing.get("status", {})
    status.update({"privacyStatus": "private", "publishAt": publish_at})
    response = service.videos().update(part="status", body={"id": video_id, "status": status}).execute()
    return {"status": "publish_scheduled", "video_id": video_id, "publish_at": publish_at, "response": response}


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)
)
def youtube_get_video_status(video_id: str) -> dict[str, Any]:
    """Read YouTube status and snippet information for one video."""
    service = _require_youtube_service()
    item = _get_video(service, video_id)
    snippet = item.get("snippet", {})
    status = item.get("status", {})
    return {
        "video_id": video_id,
        "title": snippet.get("title"),
        "privacy_status": status.get("privacyStatus"),
        "upload_status": status.get("uploadStatus"),
        "publish_at": status.get("publishAt"),
        "raw": item,
    }


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)
)
def youtube_list_channel_videos(limit: int = 20, page_token: str | None = None) -> dict[str, Any]:
    """List recent videos for the configured channel."""
    channel_id = os.environ.get("YOUTUBE_CHANNEL_ID")
    if not channel_id:
        raise RuntimeError("YOUTUBE_CHANNEL_ID is required to list channel videos.")
    service = _require_youtube_service()
    response = (
        service.search()
        .list(
            part="snippet",
            channelId=channel_id,
            maxResults=max(1, min(limit, 50)),
            order="date",
            pageToken=page_token,
            type="video",
        )
        .execute()
    )
    return {
        "channel_id": channel_id,
        "next_page_token": response.get("nextPageToken"),
        "videos": [
            {
                "video_id": item.get("id", {}).get("videoId"),
                "title": item.get("snippet", {}).get("title"),
                "published_at": item.get("snippet", {}).get("publishedAt"),
            }
            for item in response.get("items", [])
        ],
    }


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Quorvex YouTube MCP server and dry-run CLI.")
    subparsers = parser.add_subparsers(dest="command")

    check = subparsers.add_parser("check", help="Check local configuration and episode readiness.")
    check.add_argument("--episode", default="001")

    validate = subparsers.add_parser("validate", help="Validate episode assets.")
    validate.add_argument("--episode", default="001")

    prepare = subparsers.add_parser("prepare-upload", help="Write a dry-run upload manifest.")
    prepare.add_argument("--episode", default="001")
    prepare.add_argument("--video-path")
    prepare.add_argument("--thumbnail-path")

    upload = subparsers.add_parser("upload-video", help="Upload video, or dry-run without --confirm.")
    upload.add_argument("--episode", default="001")
    upload.add_argument("--video-path", required=True)
    upload.add_argument("--confirm", action="store_true")

    update = subparsers.add_parser("update-metadata", help="Update YouTube metadata.")
    update.add_argument("--video-id", required=True)
    update.add_argument("--metadata-json", required=True)
    update.add_argument("--confirm", action="store_true")

    thumb = subparsers.add_parser("set-thumbnail", help="Set YouTube thumbnail.")
    thumb.add_argument("--video-id", required=True)
    thumb.add_argument("--thumbnail-path", required=True)
    thumb.add_argument("--confirm", action="store_true")

    schedule = subparsers.add_parser("schedule-publish", help="Schedule publication.")
    schedule.add_argument("--video-id", required=True)
    schedule.add_argument("--publish-at", required=True)
    schedule.add_argument("--confirm", action="store_true")

    status = subparsers.add_parser("get-video-status", help="Read video status.")
    status.add_argument("--video-id", required=True)

    list_videos = subparsers.add_parser("list-channel-videos", help="List channel videos.")
    list_videos.add_argument("--limit", type=int, default=20)
    list_videos.add_argument("--page-token")

    return parser


def _run_cli(argv: list[str]) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            assets = _validate_episode_assets(args.episode)
            _print_json(
                {
                    "ok": True,
                    "dry_run": _dry_run_enabled(),
                    "credentials": _credentials_config(),
                    "episode_assets": assets.model_dump(),
                    "missing_optional_dependencies": _missing_optional_dependencies(),
                }
            )
        elif args.command == "validate":
            _print_json(youtube_validate_episode_assets(args.episode))
        elif args.command == "prepare-upload":
            _print_json(youtube_prepare_upload(args.episode, args.video_path, args.thumbnail_path))
        elif args.command == "upload-video":
            _print_json(youtube_upload_video(args.episode, args.video_path, args.confirm))
        elif args.command == "update-metadata":
            _print_json(youtube_update_metadata(args.video_id, json.loads(args.metadata_json), args.confirm))
        elif args.command == "set-thumbnail":
            _print_json(youtube_set_thumbnail(args.video_id, args.thumbnail_path, args.confirm))
        elif args.command == "schedule-publish":
            _print_json(youtube_schedule_publish(args.video_id, args.publish_at, args.confirm))
        elif args.command == "get-video-status":
            _print_json(youtube_get_video_status(args.video_id))
        elif args.command == "list-channel-videos":
            _print_json(youtube_list_channel_videos(args.limit, args.page_token))
        else:
            parser.print_help()
            return 2
    except Exception as exc:
        _print_json({"ok": False, "error": str(exc), "error_type": type(exc).__name__})
        return 1
    return 0


def _missing_optional_dependencies() -> list[str]:
    missing: list[str] = []
    for module, package in (
        ("googleapiclient.discovery", "google-api-python-client"),
        ("google_auth_oauthlib.flow", "google-auth-oauthlib"),
        ("google_auth_httplib2", "google-auth-httplib2"),
    ):
        try:
            __import__(module)
        except ImportError:
            missing.append(package)
    return missing


if __name__ == "__main__":
    if len(sys.argv) > 1:
        raise SystemExit(_run_cli(sys.argv[1:]))
    mcp.run(transport="stdio")
