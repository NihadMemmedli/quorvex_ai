#!/usr/bin/env python3
"""
ElevenLabs Voice Generation Script
Generates AI voiceover audio for the demo video in English and Azerbaijani.

Usage:
    python scripts/demo-video/generate-voice.py
    python scripts/demo-video/generate-voice.py --lang en   # English only
    python scripts/demo-video/generate-voice.py --lang az   # Azeri only
    python scripts/demo-video/generate-voice.py --lang en --input scripts/demo-video/output/narration-en.md
    python scripts/demo-video/generate-voice.py --voice "George"  # Specific voice

Prerequisites:
    pip install elevenlabs
    ELEVENLABS_API_KEY in .env, .env.prod, or environment
"""

import os
import sys
import argparse
import re
from pathlib import Path

# Load environment files from project root. .env.prod is supported because the
# production OpenAI key is commonly kept there for release/demo workflows.
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
for ENV_FILE in (PROJECT_ROOT / ".env", PROJECT_ROOT / ".env.local", PROJECT_ROOT / ".env.prod"):
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and not os.environ.get(key):
                    os.environ[key] = value

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PREFERRED_WARM_VOICES = (
    "Eldrin - Crisp British Baritone",
    "George - Warm, Captivating Storyteller",
    "George",
    "Adam",
)


def get_api_key() -> str:
    key = os.environ.get("ELEVENLABS_API_KEY", "")
    return key


def narration_path_for(language: str) -> Path:
    generated = OUTPUT_DIR / f"narration-{language}.md"
    if generated.exists():
        return generated
    return Path(__file__).resolve().parent / f"narration-{language}.md"


def narration_text_from_markdown(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Narration file not found: {path}")

    lines: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("**") or line == "---":
            continue
        if line.startswith(">"):
            line = line.lstrip("> ").strip()
        lines.append(line)

    text = re.sub(r"\s+", " ", " ".join(lines)).strip()
    if not text:
        raise ValueError(f"Narration file has no speakable text: {path}")
    return text


def list_voices(client):
    """List available voices for selection."""
    response = client.voices.get_all()
    print("\n📢 Available voices:")
    for voice in response.voices:
        labels = voice.labels or {}
        accent = labels.get("accent", "")
        gender = labels.get("gender", "")
        desc = labels.get("description", "")
        print(f"  • {voice.name} ({gender}, {accent}) — {desc}")
    print()


def voice_display_name(voice) -> str:
    labels = voice.labels or {}
    accent = labels.get("accent", "")
    description = labels.get("description", "")
    details = ", ".join(part for part in (accent, description) if part)
    return f"{voice.name} ({details})" if details else voice.name


def generate_voiceover(
    client,
    text: str,
    output_path: Path,
    voice_name: str = "Adam",
    model_id: str = "eleven_multilingual_v2",
    stability: float = 0.38,
    similarity_boost: float = 0.76,
    style: float = 0.58,
):
    """Generate voiceover audio using ElevenLabs API."""
    from elevenlabs import VoiceSettings

    print(f"🎙️  Generating voiceover: {output_path.name}")
    print(f"   Voice ID: {voice_name} | Model: {model_id}")
    print(f"   Text length: {len(text)} chars")

    audio = client.text_to_speech.convert(
        text=text,
        voice_id=voice_name,
        model_id=model_id,
        voice_settings=VoiceSettings(
            stability=stability,
            similarity_boost=similarity_boost,
            style=style,
            use_speaker_boost=True,
        ),
        output_format="mp3_44100_128",
    )

    # Write audio bytes
    with open(output_path, "wb") as f:
        for chunk in audio:
            f.write(chunk)

    size_kb = output_path.stat().st_size / 1024
    print(f"   ✅ Saved: {output_path} ({size_kb:.0f} KB)")


def looks_like_voice_id(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{16,}", value))


def resolve_voice_id(client, voice_name: str) -> tuple[str, str]:
    """Resolve a voice name or ID to an ElevenLabs voice ID and display name."""
    configured_id = os.environ.get("ELEVENLABS_DEMO_VOICE_ID", "").strip()
    if configured_id:
        return configured_id, "ELEVENLABS_DEMO_VOICE_ID"

    response = client.voices.get_all()
    voices = response.voices

    configured_voice = os.environ.get("ELEVENLABS_DEMO_VOICE", "").strip()
    if configured_voice:
        voice_name = configured_voice

    if voice_name.lower() in {"auto", "warm-founder", "warm_founder"}:
        for preferred in PREFERRED_WARM_VOICES:
            for voice in voices:
                if voice.name.lower() == preferred.lower():
                    return voice.voice_id, voice.name

        available = ", ".join(voice_display_name(voice) for voice in voices[:12])
        raise RuntimeError(
            "None of the preferred warm demo voices were available. "
            f"Tried: {', '.join(PREFERRED_WARM_VOICES)}. "
            "Set ELEVENLABS_DEMO_VOICE_ID or pass --voice with one of these available voices: "
            f"{available}"
        )

    for voice in response.voices:
        if voice.name.lower() == voice_name.lower():
            return voice.voice_id, voice.name

    if looks_like_voice_id(voice_name):
        return voice_name, "custom voice ID"

    available = ", ".join(voice.name for voice in voices[:20])
    raise RuntimeError(
        f"Voice '{voice_name}' was not found. Pass --voice with an exact name or set "
        f"ELEVENLABS_DEMO_VOICE_ID. Available examples: {available}"
    )


def main():
    global OUTPUT_DIR

    parser = argparse.ArgumentParser(description="Generate AI voiceover for demo video")
    parser.add_argument("--lang", choices=["en", "az", "both"], default="both",
                        help="Language to generate (default: both)")
    parser.add_argument("--input", type=Path,
                        help="Narration markdown file to read. Use only with --lang en or --lang az.")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR,
                        help="Directory for generated voiceover files")
    parser.add_argument("--voice", default="auto",
                        help="ElevenLabs voice name, ID, or 'auto' for a warm founder voice (default: auto)")
    parser.add_argument("--model", default="eleven_multilingual_v2",
                        help="ElevenLabs model ID (default: eleven_multilingual_v2)")
    parser.add_argument("--stability", type=float, default=0.38,
                        help="Voice stability (0-1, default: 0.38)")
    parser.add_argument("--similarity", type=float, default=0.76,
                        help="Similarity boost (0-1, default: 0.76)")
    parser.add_argument("--style", type=float, default=0.58,
                        help="Style expressiveness (0-1, default: 0.58)")
    parser.add_argument("--list-voices", action="store_true",
                        help="List available voices and exit")
    args = parser.parse_args()

    if args.input and args.lang == "both":
        parser.error("--input can only be used when --lang is en or az")

    OUTPUT_DIR = args.output_dir.resolve()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    api_key = get_api_key()
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY not found in environment, .env, or .env.prod")

    from elevenlabs import ElevenLabs

    client = ElevenLabs(api_key=api_key)

    if args.list_voices:
        list_voices(client)
        return

    voice_id, voice_label = resolve_voice_id(client, args.voice)
    print(f"Using ElevenLabs voice: {voice_label}")

    total_chars = 0

    if args.lang in ("en", "both"):
        input_path = args.input if args.input else narration_path_for("en")
        text = narration_text_from_markdown(input_path)
        print(f"📝 English narration: {input_path}")
        total_chars += len(text)
        generate_voiceover(
            client=client,
            text=text,
            output_path=OUTPUT_DIR / "voiceover-en.mp3",
            voice_name=voice_id,
            model_id=args.model,
            stability=args.stability,
            similarity_boost=args.similarity,
            style=args.style,
        )

    if args.lang in ("az", "both"):
        input_path = args.input if args.input else narration_path_for("az")
        text = narration_text_from_markdown(input_path)
        print(f"📝 Azeri narration: {input_path}")
        total_chars += len(text)
        generate_voiceover(
            client=client,
            text=text,
            output_path=OUTPUT_DIR / "voiceover-az.mp3",
            voice_name=voice_id,
            model_id=args.model,
            stability=args.stability,
            similarity_boost=args.similarity,
            style=args.style,
        )

    print(f"\n📊 Character usage: {total_chars} / 10,000 (free tier monthly limit)")
    print("✅ Voice generation complete!")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
