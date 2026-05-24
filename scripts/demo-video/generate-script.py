#!/usr/bin/env python3
"""
Generate narration, captions, and social copy for Quorvex demo videos.

The default path uses OpenAI's Responses API with structured JSON output.
Use --dry-run to create deterministic local assets without an API key.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
OUTPUT_DIR = SCRIPT_DIR / "output"
DEFAULT_CONFIG = SCRIPT_DIR / "campaign-config.json"

LANGUAGE_NAMES = {
    "en": "English",
    "az": "Azerbaijani",
}


@dataclass(frozen=True)
class CaptionBlock:
    start: str
    end: str
    text: str


def load_dotenv() -> None:
    for env_file in (PROJECT_ROOT / ".env", PROJECT_ROOT / ".env.local", PROJECT_ROOT / ".env.prod"):
        if not env_file.exists():
            continue
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and not os.environ.get(key):
                os.environ[key] = value


def load_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_context() -> str:
    parts: list[str] = []
    for relative in ("README.md", "docs/community/launch-kit.md"):
        path = PROJECT_ROOT / relative
        if path.exists():
            text = path.read_text(encoding="utf-8", errors="replace")
            parts.append(f"# {relative}\n{text[:9000]}")
    return "\n\n".join(parts)


def clean_narration_text(markdown: str) -> str:
    lines: list[str] = []
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("**") or line == "---":
            continue
        if line.startswith(">"):
            line = line.lstrip("> ").strip()
        lines.append(line)
    text = " ".join(lines)
    return re.sub(r"\s+", " ", text).strip()


def split_caption_text(text: str, max_chars: int = 62) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    captions: list[str] = []
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) <= max_chars:
            captions.append(sentence)
            continue
        words = sentence.split()
        current: list[str] = []
        for word in words:
            candidate = " ".join([*current, word])
            if len(candidate) > max_chars and current:
                captions.append(" ".join(current))
                current = [word]
            else:
                current.append(word)
        if current:
            captions.append(" ".join(current))
    return captions


def seconds_to_srt_time(seconds: float) -> str:
    milliseconds = int(round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def create_even_captions(text: str, duration_seconds: int) -> list[CaptionBlock]:
    chunks = split_caption_text(text)
    if not chunks:
        return []
    start_offset = 0.5
    usable_duration = max(duration_seconds - 1.5, len(chunks) * 2.0)
    step = usable_duration / len(chunks)
    captions: list[CaptionBlock] = []
    for index, chunk in enumerate(chunks):
        start = start_offset + index * step
        end = min(start_offset + (index + 1) * step, duration_seconds)
        captions.append(
            CaptionBlock(
                start=seconds_to_srt_time(start),
                end=seconds_to_srt_time(end),
                text=chunk,
            )
        )
    return captions


def render_srt(captions: list[CaptionBlock]) -> str:
    blocks: list[str] = []
    for index, caption in enumerate(captions, start=1):
        text = caption.text.replace("\\n", "\n")
        blocks.append(f"{index}\n{caption.start} --> {caption.end}\n{text}")
    return "\n\n".join(blocks) + "\n"


def parse_caption_blocks(raw_blocks: list[dict[str, str]]) -> list[CaptionBlock]:
    captions: list[CaptionBlock] = []
    for raw in raw_blocks:
        start = raw.get("start", "").strip()
        end = raw.get("end", "").strip()
        text = raw.get("text", "").strip()
        if not start or not end or not text:
            continue
        captions.append(CaptionBlock(start=start, end=end, text=text))
    return captions


def response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "narration_markdown": {"type": "string"},
            "caption_blocks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "start": {"type": "string"},
                        "end": {"type": "string"},
                        "text": {"type": "string"},
                    },
                    "required": ["start", "end", "text"],
                },
            },
            "linkedin_post": {"type": "string"},
            "github_caption": {"type": "string"},
        },
        "required": [
            "narration_markdown",
            "caption_blocks",
            "linkedin_post",
            "github_caption",
        ],
    }


def build_prompt(config: dict[str, Any], language: str, duration_seconds: int, context: str) -> list[dict[str, str]]:
    language_name = LANGUAGE_NAMES[language]
    system = (
        "You are a founder writing a natural product-demo voiceover for an open-source developer tool. "
        "Write like a senior engineer speaking to another engineer: direct, human, specific, and low-hype. "
        "Return only JSON that matches the requested schema. Keep claims grounded in the source context."
    )
    user = f"""
Create a {duration_seconds}-second demo-video content pack for Quorvex AI.

Language: {language_name}
Channel: {config["target_channel"]}
Format: {config["format"]}
Audience: {", ".join(config["audience"])}
Positioning: {config["positioning"]}
Calls to action: {", ".join(config["calls_to_action"])}
Hashtags: {" ".join(config["hashtags"])}

Requirements:
- Narration must sound conversational and human, not like a feature matrix.
- Narration markdown must use section headings and blockquotes; every speakable narration line must start with ">".
- Captions must cover the narration in order using SRT timestamps from 00:00:00,500 through about {duration_seconds} seconds.
- Caption text should be readable in 1 short line when possible.
- Align the story to this screen sequence: healthy Command Center, Autonomous Missions, Discovery with browser evidence, Live Browser View, custom agents, RTM, Assistant chat, Reporting.
- Mention that the assistant can create custom agents and launch follow-up QA work from chat.
- Avoid claiming "zero setup", "full coverage", or guaranteed automatic fixes.
- Avoid corporate phrases like "quality data", "surfaces", "leverage", "unlock", "seamless", "robust", and "game changer".
- Use contractions where they sound natural.
- Prefer short sentences. Vary sentence length so the read feels human.
- LinkedIn post must point people to the GitHub repo and ask for practical feedback.
- GitHub caption must be one short sentence for README or launch materials.
- Do not invent customer numbers, benchmarks, integrations, or guarantees.

Source context:
{context}
""".strip()
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def generate_with_openai(
    config: dict[str, Any],
    language: str,
    duration_seconds: int,
    model: str,
) -> dict[str, Any]:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not found in environment or .env file")

    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    response = client.responses.create(
        model=model,
        input=build_prompt(config, language, duration_seconds, read_context()),
        text={
            "format": {
                "type": "json_schema",
                "name": "demo_video_content_pack",
                "strict": True,
                "schema": response_schema(),
            }
        },
    )
    raw_text = response.output_text
    return json.loads(raw_text)


def dry_run_pack(config: dict[str, Any], language: str, duration_seconds: int) -> dict[str, Any]:
    source = SCRIPT_DIR / f"narration-{language}.md"
    if source.exists():
        narration_markdown = source.read_text(encoding="utf-8")
    else:
        narration_markdown = (
            "# English Narration Script\n\n"
            "> This is Quorvex AI, a self-hosted QA workspace for teams that want agents to do real testing work, while people still make the calls. "
            "Here, the dashboard is clean on purpose. You can see what passed, what is covered, what agents are doing now, and what needs a review next. "
            "Autonomous missions can explore the product, inspect browser evidence, look for risk, and propose tests without quietly changing your code. "
            "The live browser view matters because you can see what the agent actually looked at, instead of trusting a vague summary. "
            "You can also create custom agents for a release gate, a risky checkout flow, or any area your team cares about. "
            "RTM keeps the requirements honest. It shows covered, partial, and missing areas, so the next testing gap is obvious. "
            "And the assistant ties the workflow together. From chat, it can create a custom agent, start a follow-up run, inspect RTM, summarize evidence, and prepare test proposals for review. "
            "If you build with Playwright and want AI testing you can inspect, star Quorvex AI on GitHub and try it on a real workflow.\n"
        )
    narration_text = clean_narration_text(narration_markdown)
    captions = create_even_captions(narration_text, duration_seconds)
    hashtags = " ".join(config["hashtags"])
    return {
        "narration_markdown": narration_markdown,
        "caption_blocks": [
            {"start": caption.start, "end": caption.end, "text": caption.text}
            for caption in captions
        ],
        "linkedin_post": (
            "I am building Quorvex AI: a self-hosted QA workspace where agents can explore, "
            "collect browser evidence, map RTM coverage, and prepare Playwright test proposals "
            "that engineers can review before anything lands.\n\n"
            "The new demo focuses on the actual workflow: autonomous missions, live browser view, "
            "custom agents, RTM, and an assistant that can create agents or launch follow-up QA work from chat.\n\n"
            "GitHub: https://github.com/NihadMemmedli/quorvex_ai\n\n"
            "I would especially value feedback from teams already using Playwright in real release workflows.\n\n"
            f"{hashtags}"
        ),
        "github_caption": "Self-hosted AI QA agents with browser evidence, RTM, and reviewable Playwright proposals.",
    }


def write_pack(pack: dict[str, Any], language: str, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    captions = parse_caption_blocks(pack["caption_blocks"])
    files = {
        output_dir / f"narration-{language}.md": pack["narration_markdown"].strip() + "\n",
        output_dir / f"captions-{language}.srt": render_srt(captions),
        output_dir / f"linkedin-post-{language}.md": pack["linkedin_post"].strip() + "\n",
        output_dir / f"github-caption-{language}.txt": pack["github_caption"].strip() + "\n",
    }
    for path, content in files.items():
        path.write_text(content, encoding="utf-8")
        try:
            display_path = path.relative_to(PROJECT_ROOT)
        except ValueError:
            display_path = path
        print(f"Saved {display_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate demo-video script, captions, and social copy")
    parser.add_argument("--lang", choices=["en", "az", "both"], default="en")
    parser.add_argument("--variant", default="github-linkedin")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--duration", type=int, default=None, help="Target duration in seconds")
    parser.add_argument("--model", default=os.environ.get("OPENAI_MODEL", "gpt-5.4-mini"))
    parser.add_argument("--dry-run", action="store_true", help="Generate local template output without OpenAI")
    args = parser.parse_args()

    load_dotenv()
    config = load_config(args.config)
    if args.variant != config["variant"]:
        raise SystemExit(f"Unknown variant '{args.variant}'. Expected '{config['variant']}'.")

    duration = args.duration or int(config["duration_seconds"]["default"])
    output_dir = args.output_dir.resolve()
    languages = ["en", "az"] if args.lang == "both" else [args.lang]

    for language in languages:
        print(f"Generating {LANGUAGE_NAMES[language]} content pack...")
        if args.dry_run:
            pack = dry_run_pack(config, language, duration)
        else:
            pack = generate_with_openai(config, language, duration, args.model)
        write_pack(pack, language, output_dir)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
