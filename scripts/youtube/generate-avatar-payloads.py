#!/usr/bin/env python3
"""Create HeyGen-ready avatar payloads from an episode's avatar segments.

By default this writes JSON payloads only. Passing --submit will call HeyGen's
v3 video API and may spend API balance.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EPISODES_DIR = PROJECT_ROOT / "content" / "youtube" / "episodes"
HEYGEN_VIDEOS_URL = "https://api.heygen.com/v3/videos"


def load_dotenv() -> None:
    for env_file in (PROJECT_ROOT / ".env", PROJECT_ROOT / ".env.local", PROJECT_ROOT / ".env.prod"):
        if not env_file.exists():
            continue
        for raw in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and not os.environ.get(key):
                os.environ[key] = value


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "segment"


def parse_segments(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Avatar segments file not found: {path}")

    segments: list[dict[str, str]] = []
    current_title = ""
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_title, current_lines
        text = " ".join(line.strip() for line in current_lines if line.strip()).strip()
        if current_title and text and "disclosure" not in current_title.lower():
            segments.append({"title": current_title, "text": text})
        current_title = ""
        current_lines = []

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if line.startswith("## "):
            flush()
            current_title = line.removeprefix("## ").strip()
            continue
        if current_title and line.strip() and not line.startswith("#"):
            current_lines.append(line)

    flush()
    return segments


def build_payload(
    *,
    avatar_id: str,
    voice_id: str,
    script: str,
    resolution: str,
    engine: str,
    background: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": "avatar",
        "avatar_id": avatar_id,
        "voice_id": voice_id,
        "script": script,
        "resolution": resolution,
        "background": background,
    }
    if engine == "avatar_v":
        payload["engine"] = {"type": "avatar_v"}
    return payload


def submit_payload(api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        HEYGEN_VIDEOS_URL,
        data=body,
        method="POST",
        headers={
            "X-Api-Key": api_key,
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate or submit HeyGen avatar payloads for a YouTube episode")
    parser.add_argument("--episode", "-e", default="001")
    parser.add_argument("--avatar-id", default=os.environ.get("HEYGEN_AVATAR_ID", ""))
    parser.add_argument("--voice-id", default=os.environ.get("HEYGEN_VOICE_ID", ""))
    parser.add_argument("--resolution", default=os.environ.get("HEYGEN_AVATAR_RESOLUTION", "1080p"))
    parser.add_argument("--engine", choices=["avatar_iv", "avatar_v"], default=os.environ.get("HEYGEN_AVATAR_ENGINE", "avatar_iv"))
    parser.add_argument("--background", default=os.environ.get("HEYGEN_AVATAR_BACKGROUND", "#0B0F19"))
    parser.add_argument("--submit", action="store_true", help="Submit payloads to HeyGen. This may spend API balance.")
    args = parser.parse_args()

    load_dotenv()
    episode_dir = EPISODES_DIR / args.episode
    build_dir = episode_dir / "build" / "avatar"
    build_dir.mkdir(parents=True, exist_ok=True)

    if not args.avatar_id:
        raise SystemExit("HEYGEN_AVATAR_ID or --avatar-id is required")
    if not args.voice_id:
        raise SystemExit("HEYGEN_VOICE_ID or --voice-id is required")

    api_key = os.environ.get("HEYGEN_API_KEY", "")
    if args.submit and not api_key:
        raise SystemExit("HEYGEN_API_KEY is required when using --submit")

    segments = parse_segments(episode_dir / "avatar-segments.md")
    if not segments:
        raise SystemExit(f"No avatar segments found for episode {args.episode}")

    manifest: list[dict[str, Any]] = []
    for index, segment in enumerate(segments, start=1):
        slug = slugify(segment["title"])
        payload = build_payload(
            avatar_id=args.avatar_id,
            voice_id=args.voice_id,
            script=segment["text"],
            resolution=args.resolution,
            engine=args.engine,
            background=args.background,
        )
        payload_path = build_dir / f"{index:02d}-{slug}.json"
        payload_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

        record: dict[str, Any] = {
            "title": segment["title"],
            "payload": str(payload_path.relative_to(PROJECT_ROOT)),
            "expected_output": str((build_dir / f"{index:02d}-{slug}.mp4").relative_to(PROJECT_ROOT)),
        }
        if args.submit:
            response = submit_payload(api_key, payload)
            response_path = build_dir / f"{index:02d}-{slug}.response.json"
            response_path.write_text(json.dumps(response, indent=2) + "\n", encoding="utf-8")
            record["response"] = str(response_path.relative_to(PROJECT_ROOT))
            record["heygen_response"] = response
        manifest.append(record)
        print(f"Saved {payload_path.relative_to(PROJECT_ROOT)}")

    manifest_path = build_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {manifest_path.relative_to(PROJECT_ROOT)}")
    if not args.submit:
        print("Payloads were not submitted. Pass --submit to call HeyGen and spend API balance.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
