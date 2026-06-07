#!/usr/bin/env python3
"""FastMCP server for guarded Quorvex OBS recording workflows."""

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
PLAN_NAME = "obs-recording-plan.json"

mcp = FastMCP(
    "quorvex-obs-recorder",
    instructions=(
        "Prepare and execute OBS recording workflows for Quorvex episodes. "
        "Recording, scene switching, and stop actions default to dry-run and require confirm=true plus OBS_DRY_RUN=0."
    ),
)


class ObsSceneStep(BaseModel):
    """One planned OBS scene step."""

    order: int
    scene_name: str
    note: str | None = None


class ObsRecordingPlan(BaseModel):
    """Dry-run recording plan persisted for review before OBS control."""

    episode_id: str
    output_hint: str
    scene_sequence: list[ObsSceneStep] = Field(default_factory=list)
    checklist: list[str] = Field(default_factory=list)


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


def _dry_run_enabled() -> bool:
    return os.environ.get("OBS_DRY_RUN", "1").lower() not in {"0", "false", "no", "off"}


def _obs_config() -> dict[str, Any]:
    return {
        "host": os.environ.get("OBS_WEBSOCKET_HOST", "127.0.0.1"),
        "port": int(os.environ.get("OBS_WEBSOCKET_PORT", "4455")),
        "password_configured": bool(os.environ.get("OBS_WEBSOCKET_PASSWORD")),
        "dry_run": _dry_run_enabled(),
    }


def _required_confirmation(action: str, episode_id: str | None = None, extra: str = "") -> str:
    base = f"OBS_DRY_RUN=0 python tools/obs_mcp/server.py {action}"
    if episode_id:
        base += f" --episode {episode_id}"
    if extra:
        base += f" {extra}"
    return f"{base} --confirm"


def _object_to_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    data = getattr(value, "attrs", None)
    if isinstance(data, dict):
        return data
    data = getattr(value, "__dict__", None)
    if isinstance(data, dict):
        return {key: val for key, val in data.items() if not key.startswith("_")}
    return {"value": str(value)}


def _require_obs_client() -> Any:
    try:
        import obsws_python as obs
    except ImportError as exc:
        raise RuntimeError(
            "Missing OBS dependency. Install obsws-python in the active Python environment before confirmed OBS control."
        ) from exc
    password = os.environ.get("OBS_WEBSOCKET_PASSWORD")
    if not password:
        raise RuntimeError("OBS_WEBSOCKET_PASSWORD is required for confirmed OBS WebSocket control.")
    return obs.ReqClient(
        host=os.environ.get("OBS_WEBSOCKET_HOST", "127.0.0.1"),
        port=int(os.environ.get("OBS_WEBSOCKET_PORT", "4455")),
        password=password,
        timeout=float(os.environ.get("OBS_WEBSOCKET_TIMEOUT", "5")),
    )


def _parse_scene_sequence(scene_sequence: list[str] | str | None) -> list[ObsSceneStep]:
    if scene_sequence is None:
        values = [
            "Quorvex Dashboard - Failed Run",
            "Quorvex Dashboard - Runs",
            "Quorvex Dashboard - Agent Findings",
            "Quorvex Dashboard - Specs",
            "Quorvex Dashboard - Database Testing",
            "Quorvex Dashboard - Final",
        ]
    elif isinstance(scene_sequence, str):
        values = [part.strip() for part in scene_sequence.split(",") if part.strip()]
    else:
        values = [part.strip() for part in scene_sequence if part.strip()]
    return [ObsSceneStep(order=index + 1, scene_name=value) for index, value in enumerate(values)]


def _prepare_recording_plan(episode_id: str, scene_sequence: list[str] | str | None = None) -> dict[str, Any]:
    episode_dir = _episode_dir(episode_id)
    if not episode_dir.exists():
        raise FileNotFoundError(f"Episode folder not found: {_relative(episode_dir)}")
    plan = ObsRecordingPlan(
        episode_id=episode_id,
        output_hint=str(_relative(episode_dir / "build" / f"recording-demo-{episode_id}.mov")),
        scene_sequence=_parse_scene_sequence(scene_sequence),
        checklist=[
            "Seed deterministic data with make youtube-demo-seed.",
            "Open the dashboard at the Quorvex Demo Shop failed checkout run.",
            "Prefer dashboard footage over avatar footage.",
            "Verify audio input levels and 1080p canvas before recording.",
            "After recording, assemble with make youtube-final EP=<id> RECORDING=<path>.",
        ],
    )
    payload = {
        "generated_at": _utc_now(),
        "dry_run": True,
        "action": "prepare_recording",
        "obs": _obs_config(),
        "plan": plan.model_dump(),
        "required_confirmation_command": _required_confirmation("start-recording", episode_id),
    }
    path = _build_dir(episode_id) / PLAN_NAME
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"status": "dry_run_ready", "plan_path": _relative(path), **payload}


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)
)
def obs_get_status() -> dict[str, Any]:
    """Read OBS recording status when available, or return dry-run configuration."""
    if _dry_run_enabled():
        return {
            "status": "dry_run",
            "obs": _obs_config(),
            "message": "OBS was not contacted. Set OBS_DRY_RUN=0 for a read-only WebSocket status check.",
        }
    client = _require_obs_client()
    return {"status": "ok", "record_status": _object_to_dict(client.get_record_status())}


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)
)
def obs_list_scenes() -> dict[str, Any]:
    """List OBS scenes when available, or return dry-run configuration."""
    if _dry_run_enabled():
        return {
            "status": "dry_run",
            "obs": _obs_config(),
            "message": "OBS was not contacted. Set OBS_DRY_RUN=0 for a read-only scene list.",
        }
    client = _require_obs_client()
    response = _object_to_dict(client.get_scene_list())
    scenes = response.get("scenes", [])
    return {"status": "ok", "current_program_scene_name": response.get("current_program_scene_name"), "scenes": scenes}


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
)
def obs_prepare_recording(episode_id: str, scene_sequence: list[str] | None = None) -> dict[str, Any]:
    """Create a dry-run OBS recording plan for an episode."""
    return _prepare_recording_plan(episode_id, scene_sequence)


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)
)
def obs_start_recording(episode_id: str, confirm: bool = False) -> dict[str, Any]:
    """Start OBS recording only when confirm=true and OBS_DRY_RUN=0."""
    if not confirm or _dry_run_enabled():
        result = _prepare_recording_plan(episode_id)
        result["status"] = "dry_run_blocked"
        result["message"] = "OBS recording was not started. Set confirm=true and OBS_DRY_RUN=0 to start recording."
        return result
    client = _require_obs_client()
    response = client.start_record()
    return {"status": "recording_started", "response": _object_to_dict(response)}


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)
)
def obs_switch_scene(scene_name: str, confirm: bool = False) -> dict[str, Any]:
    """Switch the OBS program scene only when confirm=true and OBS_DRY_RUN=0."""
    if not confirm or _dry_run_enabled():
        return {
            "status": "dry_run_blocked",
            "action": "switch_scene",
            "scene_name": scene_name,
            "message": "OBS scene was not switched. Set confirm=true and OBS_DRY_RUN=0 to switch scenes.",
            "required_confirmation_command": _required_confirmation(
                "switch-scene",
                extra=f"--scene-name '{scene_name}'",
            ),
        }
    client = _require_obs_client()
    response = client.set_current_program_scene(scene_name)
    return {"status": "scene_switched", "scene_name": scene_name, "response": _object_to_dict(response)}


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)
)
def obs_stop_recording(confirm: bool = False) -> dict[str, Any]:
    """Stop OBS recording only when confirm=true and OBS_DRY_RUN=0."""
    if not confirm or _dry_run_enabled():
        return {
            "status": "dry_run_blocked",
            "action": "stop_recording",
            "message": "OBS recording was not stopped. Set confirm=true and OBS_DRY_RUN=0 to stop recording.",
            "required_confirmation_command": _required_confirmation("stop-recording"),
        }
    client = _require_obs_client()
    response = client.stop_record()
    return {"status": "recording_stopped", "response": _object_to_dict(response)}


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _missing_optional_dependencies() -> list[str]:
    try:
        import obsws_python  # noqa: F401
    except ImportError:
        return ["obsws-python"]
    return []


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Quorvex OBS MCP server and dry-run CLI.")
    subparsers = parser.add_subparsers(dest="command")

    check = subparsers.add_parser("check", help="Check local OBS MCP configuration.")
    check.add_argument("--episode", default="001")

    prepare = subparsers.add_parser("prepare-recording", help="Write a dry-run OBS recording plan.")
    prepare.add_argument("--episode", default="001")
    prepare.add_argument("--scene-sequence")

    start = subparsers.add_parser("start-recording", help="Start recording, or dry-run without --confirm.")
    start.add_argument("--episode", default="001")
    start.add_argument("--confirm", action="store_true")

    switch = subparsers.add_parser("switch-scene", help="Switch OBS scene, or dry-run without --confirm.")
    switch.add_argument("--scene-name", required=True)
    switch.add_argument("--confirm", action="store_true")

    subparsers.add_parser("stop-recording", help="Stop recording, or dry-run without --confirm.").add_argument(
        "--confirm", action="store_true"
    )
    subparsers.add_parser("status", help="Read OBS status.")
    subparsers.add_parser("list-scenes", help="List OBS scenes.")
    return parser


def _run_cli(argv: list[str]) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            _print_json(
                {
                    "ok": True,
                    "obs": _obs_config(),
                    "episode_dir": _relative(_episode_dir(args.episode)),
                    "missing_optional_dependencies": _missing_optional_dependencies(),
                }
            )
        elif args.command == "prepare-recording":
            _print_json(obs_prepare_recording(args.episode, args.scene_sequence))
        elif args.command == "start-recording":
            _print_json(obs_start_recording(args.episode, args.confirm))
        elif args.command == "switch-scene":
            _print_json(obs_switch_scene(args.scene_name, args.confirm))
        elif args.command == "stop-recording":
            _print_json(obs_stop_recording(args.confirm))
        elif args.command == "status":
            _print_json(obs_get_status())
        elif args.command == "list-scenes":
            _print_json(obs_list_scenes())
        else:
            parser.print_help()
            return 2
    except Exception as exc:
        _print_json({"ok": False, "error": str(exc), "error_type": type(exc).__name__})
        return 1
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1:
        raise SystemExit(_run_cli(sys.argv[1:]))
    mcp.run(transport="stdio")
