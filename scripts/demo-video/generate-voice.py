#!/usr/bin/env python3
"""
ElevenLabs Voice Generation Script
Generates AI voiceover audio for the demo video in English and Azerbaijani.

Usage:
    python scripts/demo-video/generate-voice.py
    python scripts/demo-video/generate-voice.py --lang en   # English only
    python scripts/demo-video/generate-voice.py --lang az   # Azeri only
    python scripts/demo-video/generate-voice.py --voice "Rachel"  # Specific voice

Prerequisites:
    pip install elevenlabs
    ELEVENLABS_API_KEY in .env or environment
"""

import os
import sys
import argparse
from pathlib import Path

# Load .env from project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ENV_FILE = PROJECT_ROOT / ".env"
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Narration texts — must match the .md scripts exactly
NARRATION_EN = (
    "Writing a hundred test cases by hand takes weeks. "
    "Watch this AI do it in thirty seconds. "
    "Manual test writing is slow, error-prone, and doesn't scale. "
    "This dashboard changes everything. "
    "Point this AI at any web app. "
    "It explores every page, discovers user flows, and maps API endpoints — "
    "completely on its own. No scripts, no setup — just a URL. "
    "From exploration to production-ready Playwright tests — fully automated. "
    "Requirements extraction, test generation, and self-healing validation — "
    "all in one pipeline. When a test breaks, the AI fixes it automatically. "
    "Not just UI tests. API testing from OpenAPI specs. "
    "Load testing with real-time metrics. Multi-tier security scanning. "
    "Database quality checks. Even LLM evaluation for your AI models. "
    "CI/CD integration with GitHub and GitLab. "
    "Full requirements traceability. Regression reports. "
    "Cron scheduling. Multi-project isolation. "
    "AI-powered test automation. From zero to full coverage. Try it today."
)

NARRATION_AZ = (
    "Yüz test yazısını əllə yazmaq həftələr çəkir. "
    "Bu süni intellektin bunu otuz saniyəyə necə etdiyinə baxın. "
    "Əl ilə test yazmaq yavaş, səhvlərə meyilli və miqyaslanmır. "
    "Bu panel hər şeyi dəyişir. "
    "Bu süni intellekti istənilən veb tətbiqə yönəldin. "
    "O, hər səhifəni araşdırır, istifadəçi axınlarını kəşf edir və "
    "API nöqtələrini xəritələyir — tamamilə müstəqil şəkildə. "
    "Skript yoxdur, quraşdırma yoxdur — sadəcə bir URL. "
    "Kəşfiyyatdan istehsala hazır Playwright testlərinə — tam avtomatik. "
    "Tələblərin çıxarılması, test generasiyası və özünü bərpa edən validasiya — "
    "hamısı bir boru kəmərində. Test sınanda süni intellekt onu avtomatik düzəldir. "
    "Yalnız UI testləri deyil. OpenAPI spesifikasiyalarından API testləri. "
    "Real vaxt metrikalı yük testləri. Çoxsəviyyəli təhlükəsizlik skanı. "
    "Verilənlər bazası keyfiyyət yoxlamaları. "
    "Hətta süni intellekt modelləri üçün LLM qiymətləndirməsi. "
    "GitHub və GitLab ilə CI/CD inteqrasiyası. "
    "Tam tələb izlənməsi. Reqressiya hesabatları. "
    "Cron planlaşdırma. Çoxlayihəli izolyasiya. "
    "Süni intellektlə test avtomatlaşdırması. Sıfırdan tam əhatəyə. Bu gün sınayın."
)


def get_api_key() -> str:
    key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not key:
        print("❌ ELEVENLABS_API_KEY not found in environment or .env file")
        print("   Get a free key at: https://elevenlabs.io")
        sys.exit(1)
    return key


def list_voices(client):
    """List available voices for selection."""
    from elevenlabs import VoiceSettings
    response = client.voices.get_all()
    print("\n📢 Available voices:")
    for voice in response.voices:
        labels = voice.labels or {}
        accent = labels.get("accent", "")
        gender = labels.get("gender", "")
        desc = labels.get("description", "")
        print(f"  • {voice.name} ({gender}, {accent}) — {desc}")
    print()


def generate_voiceover(
    client,
    text: str,
    output_path: Path,
    voice_name: str = "Adam",
    model_id: str = "eleven_multilingual_v2",
    stability: float = 0.5,
    similarity_boost: float = 0.75,
    style: float = 0.3,
):
    """Generate voiceover audio using ElevenLabs API."""
    from elevenlabs import VoiceSettings

    print(f"🎙️  Generating voiceover: {output_path.name}")
    print(f"   Voice: {voice_name} | Model: {model_id}")
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


def resolve_voice_id(client, voice_name: str) -> str:
    """Resolve a voice name to its ID. Returns the name if it looks like an ID already."""
    response = client.voices.get_all()
    for voice in response.voices:
        if voice.name.lower() == voice_name.lower():
            return voice.voice_id
    # If no match, assume it's already a voice ID
    return voice_name


def main():
    parser = argparse.ArgumentParser(description="Generate AI voiceover for demo video")
    parser.add_argument("--lang", choices=["en", "az", "both"], default="both",
                        help="Language to generate (default: both)")
    parser.add_argument("--voice", default="Adam",
                        help="ElevenLabs voice name (default: Adam)")
    parser.add_argument("--model", default="eleven_multilingual_v2",
                        help="ElevenLabs model ID (default: eleven_multilingual_v2)")
    parser.add_argument("--stability", type=float, default=0.5,
                        help="Voice stability (0-1, default: 0.5)")
    parser.add_argument("--similarity", type=float, default=0.75,
                        help="Similarity boost (0-1, default: 0.75)")
    parser.add_argument("--style", type=float, default=0.3,
                        help="Style expressiveness (0-1, default: 0.3)")
    parser.add_argument("--list-voices", action="store_true",
                        help="List available voices and exit")
    args = parser.parse_args()

    api_key = get_api_key()

    from elevenlabs import ElevenLabs
    client = ElevenLabs(api_key=api_key)

    if args.list_voices:
        list_voices(client)
        return

    voice_id = resolve_voice_id(client, args.voice)
    print(f"🔑 Using voice ID: {voice_id}")

    if args.lang in ("en", "both"):
        generate_voiceover(
            client=client,
            text=NARRATION_EN,
            output_path=OUTPUT_DIR / "voiceover-en.mp3",
            voice_name=voice_id,
            model_id=args.model,
            stability=args.stability,
            similarity_boost=args.similarity,
            style=args.style,
        )

    if args.lang in ("az", "both"):
        generate_voiceover(
            client=client,
            text=NARRATION_AZ,
            output_path=OUTPUT_DIR / "voiceover-az.mp3",
            voice_name=voice_id,
            model_id=args.model,
            stability=args.stability,
            similarity_boost=args.similarity,
            style=args.style,
        )

    total_chars = 0
    if args.lang in ("en", "both"):
        total_chars += len(NARRATION_EN)
    if args.lang in ("az", "both"):
        total_chars += len(NARRATION_AZ)

    print(f"\n📊 Character usage: {total_chars} / 10,000 (free tier monthly limit)")
    print("✅ Voice generation complete!")


if __name__ == "__main__":
    main()
