#!/usr/bin/env python3
"""Assemble a captioned MP4 when FFmpeg lacks the subtitles/drawtext filters."""

from __future__ import annotations

import argparse
import re
import subprocess
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def srt_time_to_seconds(value: str) -> float:
    hours, minutes, rest = value.split(":")
    seconds, millis = rest.split(",")
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000


def parse_srt(path: Path) -> list[tuple[float, float, str]]:
    blocks = [block.strip() for block in path.read_text(encoding="utf-8").strip().split("\n\n") if block.strip()]
    captions: list[tuple[float, float, str]] = []
    for block in blocks:
        lines = block.splitlines()
        if len(lines) < 3:
            continue
        start_raw, end_raw = [part.strip() for part in lines[1].split("-->")]
        captions.append((srt_time_to_seconds(start_raw), srt_time_to_seconds(end_raw), "\n".join(lines[2:])))
    return captions


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/SFNS.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def render_caption_images(captions: list[tuple[float, float, str]], output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    font = load_font(34)
    paths: list[Path] = []

    for index, (_, _, text) in enumerate(captions, start=1):
        image = Image.new("RGBA", (1920, 1080), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        text_lines: list[str] = []
        for line in text.splitlines():
            text_lines.extend(textwrap.wrap(line, width=58) or [""])
        caption_text = "\n".join(text_lines)
        bbox = draw.multiline_textbbox((0, 0), caption_text, font=font, spacing=10, align="center")
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        padding_x, padding_y = 32, 20
        box_width = text_width + padding_x * 2
        box_height = text_height + padding_y * 2
        x = (1920 - box_width) // 2
        y = 1080 - box_height - 34
        draw.rounded_rectangle((x, y, x + box_width, y + box_height), radius=12, fill=(0, 0, 0, 175))
        draw.multiline_text(
            (960, y + padding_y),
            caption_text,
            font=font,
            fill=(255, 255, 255, 255),
            anchor="ma",
            spacing=10,
            align="center",
        )
        path = output_dir / f"caption-{index:02d}.png"
        image.save(path)
        paths.append(path)

    return paths


def media_duration(path: Path) -> int:
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        check=True,
        text=True,
        capture_output=True,
    )
    duration = float(result.stdout.strip())
    return int(duration) + 2


def assemble(
    recording: Path,
    voiceover: Path,
    captions: Path,
    output: Path,
    overlay_dir: Path,
    sound_design: Path | None = None,
) -> None:
    parsed_captions = parse_srt(captions)
    overlay_paths = render_caption_images(parsed_captions, overlay_dir)
    target_duration = media_duration(voiceover)
    has_sound_design = sound_design is not None and sound_design.exists()

    command = [
        "ffmpeg",
        "-y",
        "-stream_loop",
        "-1",
        "-i",
        str(recording),
        "-i",
        str(voiceover),
    ]
    if has_sound_design:
        command.extend(["-i", str(sound_design)])
    for overlay_path in overlay_paths:
        command.extend(["-loop", "1", "-i", str(overlay_path)])

    filters = [
        "[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,"
        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black[base]"
    ]
    last_label = "base"
    overlay_input_offset = 3 if has_sound_design else 2
    for index, (start, end, _) in enumerate(parsed_captions, start=1):
        next_label = f"v{index}"
        filters.append(
            f"[{last_label}][{index + overlay_input_offset - 1}:v]"
            f"overlay=0:0:enable=between(t\\,{start:.3f}\\,{end:.3f})[{next_label}]"
        )
        last_label = next_label

    if has_sound_design:
        filters.extend(
            [
                "[1:a]volume=1.0[a0]",
                "[2:a]volume=0.32[a1]",
                "[a0][a1]amix=inputs=2:duration=first:dropout_transition=0[a]",
            ]
        )

    command.extend(
        [
            "-t",
            str(target_duration),
            "-filter_complex",
            ";".join(filters),
            "-map",
            f"[{last_label}]",
            "-map",
            "[a]" if has_sound_design else "1:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-profile:v",
            "high",
            "-level",
            "4.0",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-ar",
            "44100",
            "-r",
            "30",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )
    subprocess.run(command, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Assemble an MP4 with PNG-rendered caption overlays")
    parser.add_argument("--recording", type=Path, required=True)
    parser.add_argument("--voiceover", type=Path, required=True)
    parser.add_argument("--captions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overlay-dir", type=Path, required=True)
    parser.add_argument("--sound-design", type=Path)
    args = parser.parse_args()

    assemble(args.recording, args.voiceover, args.captions, args.output, args.overlay_dir, args.sound_design)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
