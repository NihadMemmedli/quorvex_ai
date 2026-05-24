#!/usr/bin/env python3
"""Generate a subtle UI sound-design bed for the Quorvex demo video.

The output is intentionally synthetic and deterministic: soft clicks, keyboard
taps, light transitions, and a low ambience under the ElevenLabs narration.
"""

from __future__ import annotations

import argparse
import math
import random
import struct
import subprocess
import wave
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SCRIPT_DIR / "output"
SAMPLE_RATE = 44_100


def media_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        check=True,
        text=True,
        capture_output=True,
    )
    return float(result.stdout.strip())


def add_tone(samples: list[float], start: float, duration: float, frequency: float, volume: float) -> None:
    start_index = max(0, int(start * SAMPLE_RATE))
    length = max(1, int(duration * SAMPLE_RATE))
    end_index = min(len(samples), start_index + length)
    for index in range(start_index, end_index):
        progress = (index - start_index) / length
        envelope = math.sin(math.pi * progress)
        samples[index] += math.sin(2 * math.pi * frequency * index / SAMPLE_RATE) * volume * envelope


def add_click(samples: list[float], start: float, volume: float = 0.13) -> None:
    rng = random.Random(int(start * 1000))
    start_index = max(0, int(start * SAMPLE_RATE))
    length = int(0.055 * SAMPLE_RATE)
    for offset in range(length):
        index = start_index + offset
        if index >= len(samples):
            break
        progress = offset / length
        envelope = (1 - progress) ** 3
        transient = math.sin(2 * math.pi * 1850 * offset / SAMPLE_RATE)
        dust = rng.uniform(-0.35, 0.35)
        samples[index] += (transient + dust) * volume * envelope


def add_keytap(samples: list[float], start: float, volume: float = 0.075) -> None:
    rng = random.Random(int(start * 10_000))
    start_index = max(0, int(start * SAMPLE_RATE))
    length = int(rng.uniform(0.028, 0.045) * SAMPLE_RATE)
    frequency = rng.uniform(2100, 3100)
    for offset in range(length):
        index = start_index + offset
        if index >= len(samples):
            break
        progress = offset / length
        envelope = (1 - progress) ** 2.2
        tone = math.sin(2 * math.pi * frequency * offset / SAMPLE_RATE)
        samples[index] += tone * volume * envelope


def add_whoosh(samples: list[float], start: float, duration: float = 0.58, volume: float = 0.045) -> None:
    rng = random.Random(int(start * 1000) + 17)
    start_index = max(0, int(start * SAMPLE_RATE))
    length = max(1, int(duration * SAMPLE_RATE))
    for offset in range(length):
        index = start_index + offset
        if index >= len(samples):
            break
        progress = offset / length
        envelope = math.sin(math.pi * progress) ** 1.4
        sweep = math.sin(2 * math.pi * (180 + 480 * progress) * offset / SAMPLE_RATE)
        air = rng.uniform(-1.0, 1.0)
        samples[index] += (sweep * 0.3 + air * 0.7) * volume * envelope


def add_keyboard_run(samples: list[float], start: float, duration: float) -> None:
    rng = random.Random(42)
    current = start
    end = start + duration
    while current < end:
        add_keytap(samples, current)
        current += rng.uniform(0.055, 0.145)


def build_sound_design(duration: float) -> list[float]:
    rng = random.Random(7)
    sample_count = int(duration * SAMPLE_RATE)
    samples = [0.0] * sample_count

    for index in range(sample_count):
        seconds = index / SAMPLE_RATE
        low_motion = math.sin(2 * math.pi * 58 * seconds) * 0.009
        slow_motion = math.sin(2 * math.pi * 0.11 * seconds) * 0.006
        air = rng.uniform(-0.004, 0.004)
        samples[index] = low_motion + slow_motion + air

    for timestamp in (4.4, 11.8, 18.6, 27.2, 39.6, 49.4, 61.8, 73.8, 83.0):
        add_click(samples, timestamp)

    for timestamp in (8.3, 24.7, 37.9, 55.8, 70.8, 81.5):
        add_whoosh(samples, timestamp)

    for timestamp in (14.2, 31.3, 44.8, 66.5):
        add_tone(samples, timestamp, 0.18, 760, 0.025)

    add_keyboard_run(samples, 73.6, 4.8)
    return samples


def write_wav(samples: list[float], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        frames = bytearray()
        for sample in samples:
            clipped = max(-0.55, min(0.55, sample))
            value = int(clipped * 32767)
            frames.extend(struct.pack("<hh", value, value))
        wav.writeframes(frames)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate subtle demo-video UI sound design")
    parser.add_argument("--lang", choices=["en", "az"], default="en")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--voiceover", type=Path, help="Voiceover file used to infer duration")
    parser.add_argument("--duration", type=float, help="Explicit duration in seconds")
    args = parser.parse_args()

    output_dir = args.output_dir.resolve()
    voiceover = args.voiceover or output_dir / f"voiceover-{args.lang}.mp3"
    duration = args.duration if args.duration else media_duration(voiceover) + 2.0
    output_path = output_dir / f"sound-design-{args.lang}.wav"

    print(f"Generating sound design: {output_path}")
    print(f"Duration: {duration:.1f}s")
    samples = build_sound_design(duration)
    write_wav(samples, output_path)
    print(f"Saved {output_path} ({output_path.stat().st_size / 1024 / 1024:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
