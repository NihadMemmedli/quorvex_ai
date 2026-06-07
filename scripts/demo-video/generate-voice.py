#!/usr/bin/env python3
"""Generate ElevenLabs narration for demo and YouTube episode scripts."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "output"
ENV_FILES = (PROJECT_ROOT / ".env", PROJECT_ROOT / ".env.local", PROJECT_ROOT / ".env.prod")
DEFAULT_DEMO_VOICE_ID = "DODLEQrClDo8wCz460ld"


def load_dotenv() -> None:
    if os.environ.get("QUORVEX_SKIP_DOTENV") == "1":
        return
    for env_file in ENV_FILES:
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


def narration_path_for(language: str) -> Path:
    generated = DEFAULT_OUTPUT_DIR / f"narration-{language}.md"
    if generated.exists():
        return generated
    return Path(__file__).resolve().parent / f"narration-{language}.md"


def narration_text_from_markdown(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Narration file not found: {path}")

    lines: list[str] = []
    in_fence = False
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not line:
            continue
        if line.startswith("#") or line.startswith("|") or line == "---":
            continue
        if line.startswith("- ") or re.match(r"^\d+\.\s+", line):
            continue
        if line.startswith(">"):
            line = line.lstrip("> ").strip()
        lines.append(line)

    text = re.sub(r"\s+", " ", " ".join(lines)).strip()
    if not text:
        raise ValueError(f"Narration file has no speakable text: {path}")
    return text


def voice_display_name(voice: Any) -> str:
    labels = voice.labels or {}
    details = ", ".join(part for part in (labels.get("accent", ""), labels.get("description", "")) if part)
    return f"{voice.name} ({details})" if details else voice.name


def list_voices(client: Any) -> None:
    response = client.voices.get_all()
    print("\nAvailable ElevenLabs voices:")
    for voice in response.voices:
        print(f"  - {voice.name} [{voice.voice_id}]")
    print()


def looks_like_voice_id(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{16,}", value))


def selected_voice_hint(requested_voice: str) -> str:
    configured_id = os.environ.get("ELEVENLABS_DEMO_VOICE_ID", "").strip()
    if configured_id:
        return configured_id
    return requested_voice.strip() or os.environ.get("ELEVENLABS_DEMO_VOICE", "").strip() or DEFAULT_DEMO_VOICE_ID


def resolve_voice_id(client: Any, requested_voice: str) -> tuple[str, str]:
    configured_id = os.environ.get("ELEVENLABS_DEMO_VOICE_ID", "").strip()
    if configured_id:
        return configured_id, f"ELEVENLABS_DEMO_VOICE_ID ({configured_id})"

    voice_name = selected_voice_hint(requested_voice)
    if looks_like_voice_id(voice_name):
        return voice_name, f"voice ID {voice_name}"

    response = client.voices.get_all()
    voices = list(response.voices)

    for voice in voices:
        if voice.name.lower() == voice_name.lower():
            return voice.voice_id, voice.name

    available = ", ".join(voice_display_name(voice) for voice in voices[:20])
    raise RuntimeError(
        f"ElevenLabs voice '{voice_name}' was not found. Run "
        "`python scripts/demo-video/generate-voice.py --list-voices`, pass `VOICE=\"Exact Voice Name\"`, "
        "or set ELEVENLABS_DEMO_VOICE_ID to a voice ID. "
        f"Available examples: {available}"
    )


def generate_voiceover(
    *,
    client: Any,
    text: str,
    output_path: Path,
    voice_id: str,
    model_id: str,
    stability: float,
    similarity_boost: float,
    style: float,
) -> None:
    from elevenlabs import VoiceSettings

    output_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Generating voiceover: {output_path}")
    print(f"  Voice ID: {voice_id}")
    print(f"  Model: {model_id}")
    print(f"  Text length: {len(text)} characters")

    audio = client.text_to_speech.convert(
        text=text,
        voice_id=voice_id,
        model_id=model_id,
        voice_settings=VoiceSettings(
            stability=stability,
            similarity_boost=similarity_boost,
            style=style,
            use_speaker_boost=True,
        ),
        output_format="mp3_44100_128",
    )
    with output_path.open("wb") as file:
        for chunk in audio:
            file.write(chunk)

    size_kb = output_path.stat().st_size / 1024
    print(f"Saved {output_path} ({size_kb:.0f} KB)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate ElevenLabs voiceover for demo video assets")
    parser.add_argument("--lang", choices=["en", "az", "both"], default="both")
    parser.add_argument("--input", type=Path, help="Narration markdown file. Use only with --lang en or --lang az.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--voice",
        default=os.environ.get("ELEVENLABS_DEMO_VOICE", DEFAULT_DEMO_VOICE_ID),
        help=(
            f"ElevenLabs voice name or ID (default: {DEFAULT_DEMO_VOICE_ID}). "
            "ELEVENLABS_DEMO_VOICE_ID wins when set."
        ),
    )
    parser.add_argument("--model", default=os.environ.get("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2"))
    parser.add_argument("--stability", type=float, default=0.38)
    parser.add_argument("--similarity", type=float, default=0.76)
    parser.add_argument("--style", type=float, default=0.58)
    parser.add_argument("--list-voices", action="store_true", help="List available ElevenLabs voices and exit")
    return parser


def main() -> int:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args()

    if args.input and args.lang == "both":
        parser.error("--input can only be used when --lang is en or az")

    api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        voice_hint = selected_voice_hint(args.voice)
        raise RuntimeError(
            "ELEVENLABS_API_KEY is required for voice generation. "
            "Set it in the environment, .env, .env.local, or .env.prod. "
            f"Selected voice: {voice_hint}. "
            "After setting it, run `python scripts/demo-video/generate-voice.py --list-voices` "
            "to confirm available account voices, pass `VOICE=\"Exact Voice Name\"`, "
            "or set ELEVENLABS_DEMO_VOICE_ID to a voice ID."
        )

    try:
        from elevenlabs import ElevenLabs
    except ImportError as exc:
        raise RuntimeError("Python package `elevenlabs` is required. Install it with `pip install elevenlabs`.") from exc

    client = ElevenLabs(api_key=api_key)
    if args.list_voices:
        list_voices(client)
        return 0

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    voice_id, voice_label = resolve_voice_id(client, args.voice)
    print(f"Using ElevenLabs voice: {voice_label}")

    total_chars = 0
    languages = ["en", "az"] if args.lang == "both" else [args.lang]
    for language in languages:
        input_path = args.input if args.input else narration_path_for(language)
        text = narration_text_from_markdown(input_path)
        total_chars += len(text)
        print(f"Narration source ({language}): {input_path}")
        generate_voiceover(
            client=client,
            text=text,
            output_path=output_dir / f"voiceover-{language}.mp3",
            voice_id=voice_id,
            model_id=args.model,
            stability=args.stability,
            similarity_boost=args.similarity,
            style=args.style,
        )

    print(f"Character usage for this run: {total_chars}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
