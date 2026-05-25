#!/usr/bin/env python3
"""Generate a YouTube tutorial production pack from the Quorvex episode catalog."""

from __future__ import annotations

import argparse
import json
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = PROJECT_ROOT / "content" / "youtube" / "episode-catalog.json"
EPISODES_DIR = PROJECT_ROOT / "content" / "youtube" / "episodes"


@dataclass(frozen=True)
class CaptionBlock:
    start: str
    end: str
    text: str


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return slug or "episode"


def load_catalog(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def find_episode(catalog: dict[str, Any], episode_id: str) -> dict[str, Any]:
    for episode in catalog["episodes"]:
        if episode["id"] == episode_id:
            return episode
    raise SystemExit(f"Unknown episode id: {episode_id}")


def read_doc_excerpt(relative_path: str, max_chars: int = 2600) -> str:
    path = PROJECT_ROOT / relative_path
    if not path.exists() or path.is_dir():
        return f"[Missing or non-text source: {relative_path}]"
    if path.suffix.lower() in {".png", ".gif", ".webm", ".mp4"}:
        return f"[Visual source: {relative_path}]"
    text = path.read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:max_chars]


def clean_speakable_text(markdown: str) -> str:
    lines: list[str] = []
    for raw in markdown.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("- ") or line.startswith("|"):
            continue
        if line.startswith(">"):
            line = line.lstrip("> ").strip()
        if line.startswith("Avatar:"):
            continue
        lines.append(line)
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def split_caption_text(text: str, max_chars: int = 64) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    captions: list[str] = []
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
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
    usable_duration = max(duration_seconds - 1.0, len(chunks) * 1.8)
    step = usable_duration / len(chunks)
    captions: list[CaptionBlock] = []
    for index, chunk in enumerate(chunks):
        start = 0.5 + index * step
        end = min(0.5 + (index + 1) * step, duration_seconds)
        captions.append(
            CaptionBlock(
                start=seconds_to_srt_time(start),
                end=seconds_to_srt_time(end),
                text=chunk,
            )
        )
    return captions


def render_srt(captions: list[CaptionBlock]) -> str:
    blocks = [
        f"{index}\n{caption.start} --> {caption.end}\n{caption.text}"
        for index, caption in enumerate(captions, start=1)
    ]
    return "\n\n".join(blocks) + "\n"


def estimate_duration_seconds(markdown: str) -> int:
    text = clean_speakable_text(markdown)
    words = re.findall(r"\b[\w'-]+\b", text)
    return max(60, round(len(words) / 140 * 60))


def render_script(catalog: dict[str, Any], episode: dict[str, Any]) -> str:
    channel = catalog["channel"]
    title = episode["title"]
    repo = channel["repo_url"]
    docs = channel["docs_url"]

    if episode["id"] == "001":
        body = f"""
# {title}

> If your team already uses Playwright, the hard part is not believing that automated tests matter. The hard part is writing enough useful coverage without spending every sprint inside selectors, waits, setup code, and flaky failures.

> Quorvex AI is built around one practical idea: let agents help create and validate tests, but keep the final output as normal Playwright code your team can inspect, commit, and run in CI.

> In this tutorial, I will show the first workflow end to end. We will start from the repo, open the dashboard, describe a small test in plain English, run it through the pipeline, and inspect the generated Playwright file.

> The point is not to watch a polished demo and assume everything is automatic. The point is to understand the loop: write a clear spec, let Quorvex plan against the target, generate a test, validate it in a browser, and then review the output like engineering work.

> Start on the GitHub repo. The README gives the product shape: Quorvex is self-hosted, AI-assisted, and code-first. It can work with specs, PRDs, exploration, API checks, load tests, security checks, database checks, CI gates, and autonomous coverage discovery, but the first video should stay narrow.

> The fastest path is the minimal setup. For a local evaluation, it keeps the number of services low while still showing the real dashboard and generation flow. For production or team usage, Quorvex also supports the full stack with queues, storage, browser viewing, credentials, schedules, and integrations.

> If you want the quickest trial, use the minimal README. If you want to evaluate the full platform shape, use the main getting-started tutorial. Either way, the first target is simple: get the backend and dashboard running, then generate one test.

> Before adding credentials, pause on the model configuration. Quorvex uses an Anthropic-compatible setup. That can point to Anthropic, OpenRouter, Z.ai, or another compatible endpoint, depending on how you run it. The exact provider matters less than having a working token and a model that can follow the generation workflow.

> Once the app is running, open the dashboard. The dashboard is not just decoration around a CLI. It is where a team can create specs, inspect runs, review artifacts, track requirements, see regression history, and understand what the agents did.

> For the first video, keep the dashboard tour brief. We only need enough context to create or run a spec. Later videos can go deeper into requirements, API testing, PRDs, autonomous missions, and CI quality gates.

> Now move to the most important object in the first workflow: the spec. A Quorvex spec is just markdown. It names the test, describes the steps, and states the expected outcome. That makes the request reviewable before any code is generated.

> This is an important design choice. If the input is vague, the generated code will probably be vague too. A good spec gives the agent a clear target URL, a small user flow, and an observable outcome.

> For the first run, use a simple public page or one workflow in your own application. Keep it small. A good first test proves the pipeline and gives you generated code that is easy to inspect.

> In the getting-started tutorial, the example checks a dynamic loading page and verifies that the Hello World message appears after the loading step completes. That is not a business-critical workflow, but it is a good first proof because the expected result is easy to see.

> After the spec is ready, run the pipeline. Under the hood, Quorvex is not trying to give you a cute code snippet. The workflow is planning, generation, validation, and repair attempts when failures are concrete enough to address.

> Planning matters because web tests need sequencing. The agent has to understand where to navigate, what to click, what to wait for, and what assertion proves the flow worked.

> Browser context matters because selectors are not reliable when they are guessed from a prompt alone. A real browser gives the system evidence about what is actually on the page.

> Generation matters because the output should be standard Playwright TypeScript. This is the key ownership point. You should be able to open the file, read it, edit it, commit it, and run it without Quorvex sitting in the middle of every future CI job.

> Validation matters because generated code is only useful after it runs. A failing generated test is not worthless, but it is not done. The run artifacts tell you whether the failure is in the target app, the spec, timing, selectors, authentication, or the generated code itself.

> When the run completes, do not just look for a green status. Open the generated file. Check the locators. Check the assertions. Check whether the code reads like something you would accept in a pull request.

> This review habit is what separates useful AI automation from throwaway demos. If the test is readable and the assertion is meaningful, the generated file can become part of the suite. If it is too broad, too brittle, or too clever, edit it or improve the spec and run again.

> If validation fails, the run artifacts still matter. Screenshots, logs, browser evidence, and failure details make the problem concrete. The goal is not magic. The goal is a faster loop with evidence.

> In a real team, this also changes the review conversation. Instead of asking whether AI wrote a perfect test, the better question is whether the system produced a useful candidate with enough evidence for an engineer or QA automation owner to make a decision.

> This workflow is why Quorvex is self-hosted and code-first. AI helps with planning, generation, validation, exploration, and repair, but your team keeps normal tests that can run without an AI dependency during every CI job.

> That also means you can start small. You do not need to migrate a whole test suite. Pick one flow with clear value. Generate one test. Review the output. Run it locally. Then decide whether the next workflow should be another UI test, an API check, a PRD-to-tests flow, or a CI gate.

> If you are evaluating Quorvex for a team, I would measure three things after this first run. First, did it save time compared with writing the same Playwright test by hand? Second, is the generated code readable enough to maintain? Third, did the artifacts explain what happened when the run passed or failed?

> If the answer is no, the feedback is still useful. It tells us whether the spec format needs better guidance, whether the dashboard needs clearer evidence, or whether the generation pipeline needs a stronger constraint.

> To try this yourself, open the repo, follow the minimal setup, and create one spec from a real workflow your team cares about. If that first generated test is useful, the next step is to add PRD coverage, API checks, regression batches, and CI quality gates.

> The repo is {repo}, and the docs are at {docs}. Star Quorvex AI if you want to follow the project, and send feedback from real Playwright workflows. That feedback is the most useful signal for what to improve next.
"""
    else:
        flow_lines = " ".join(episode.get("screen_flow", []))
        body = f"""
# {title}

> This tutorial is about a practical testing problem: {episode["audience_problem"]}

> The promise for this video is simple: {episode["promise"]}

> Quorvex AI is a self-hosted AI testing workspace for teams that want agents to help with coverage while still keeping normal Playwright code.

> The walkthrough will follow the actual product, not a slide deck. We will use the dashboard, terminal commands, generated artifacts, and the source docs that explain the workflow.

> The screen flow for this episode is: {flow_lines}

> The key thing to watch is ownership. Quorvex can help plan, generate, validate, and repair, but the final test output should still be reviewable by engineers.

> When you apply this to your own app, start with one workflow that is annoying to maintain by hand. Use the generated output as a pull request candidate, not as something to trust blindly.

> If this workflow fits your team, try the docs at {docs}, star the repo at {repo}, and share where the current flow needs to be more reliable.
"""

    return body.strip()


def render_avatar_segments(episode: dict[str, Any]) -> str:
    return f"""# Avatar Segments: {episode["title"]}

Use these as short AI-avatar clips. Keep each clip under 20 seconds when possible.

## Hook

Today we are going from a plain-English testing idea to generated Playwright code with Quorvex AI.

## Transition 1

Now that the setup is running, the important part is the spec. It is readable before any code is generated.

## Transition 2

The generated file is the proof point. We are not stopping at a summary. We are checking the actual Playwright output.

## Outro

Try this with one real workflow from your app, then inspect the generated code like you would inspect any pull request.

## Upload Disclosure Note

If the avatar looks or sounds like a realistic person, disclose AI-avatar usage in YouTube Studio when prompted for altered or synthetic content.
"""


def render_metadata(catalog: dict[str, Any], episode: dict[str, Any], duration_seconds: int) -> str:
    channel = catalog["channel"]
    title = episode["title"]
    tags = ", ".join(episode["keywords"])
    minutes = max(1, duration_seconds // 60)
    chapters = [
        ("00:00", "Why this workflow matters"),
        ("00:45", "Setup and dashboard"),
        ("02:00", "Write the spec"),
        ("03:30", "Run the pipeline"),
        ("05:30", "Inspect generated Playwright"),
        (f"{max(6, minutes - 1):02}:00", "Next steps"),
    ]
    chapter_text = "\n".join(f"{time} {label}" for time, label in chapters)
    return f"""# Metadata: {title}

## Title

{title}

## Description

{episode["promise"]}

Quorvex AI is a self-hosted AI testing platform that turns specs, PRDs, and app exploration into validated Playwright tests your team can inspect, commit, and run in CI.

GitHub: {channel["repo_url"]}
Docs: {channel["docs_url"]}

## Chapters

{chapter_text}

## Tags

{tags}

## Thumbnail Text

{episode["thumbnail"]}

## Pinned Comment

Try the workflow from the video and share where it breaks down in your real Playwright setup. Repo: {channel["repo_url"]}

## Disclosure

This video may use an AI avatar for presenter segments and ElevenLabs-generated narration. The product walkthrough, code, and dashboard footage should be captured from the real Quorvex project.
"""


def render_shot_list(episode: dict[str, Any]) -> str:
    lines = "\n".join(f"- {item}" for item in episode.get("screen_flow", []))
    return f"""# Shot List: {episode["title"]}

## Required Product Footage

{lines}

## Capture Notes

- Record at 1920x1080.
- Keep browser zoom between 90% and 110%.
- Use slow cursor movement and pause briefly before clicks.
- Show generated code and run artifacts long enough to read.
- Hide or replace real API keys, credentials, emails, and private project names.

## Suggested Assets

- `docs/assets/ui/product-flow.gif`
- `docs/assets/ui/dashboard-overview.png`
- `docs/assets/ui/runs.png`
- `docs/assets/ui/spec-editor.png`
- `docs/assets/ui/analytics.png`
"""


def render_checklist(episode: dict[str, Any]) -> str:
    return f"""# Production Checklist: {episode["title"]}

## Pre-Production

- [ ] Confirm the episode promise is still accurate.
- [ ] Run the relevant setup path locally.
- [ ] Prepare a clean demo project or seeded demo data.
- [ ] Confirm no secrets appear in the browser, terminal, or generated files.

## Production

- [ ] Generate or revise `script.md`.
- [ ] Generate ElevenLabs narration into `build/voiceover-en.mp3`.
- [ ] Render avatar clips from `avatar-segments.md`.
- [ ] Capture product screen recording.
- [ ] Add captions from `captions.srt`.
- [ ] Add simple callouts for commands, generated files, and run status.

## Review

- [ ] Audio is clear and evenly mixed.
- [ ] Screen text is readable on mobile.
- [ ] Avatar clips do not dominate the tutorial.
- [ ] Claims match the repo and docs.
- [ ] YouTube disclosure is set if realistic AI avatar clips are used.

## Publish

- [ ] Upload full 16:9 tutorial.
- [ ] Add `metadata.md` title, description, tags, chapters, and pinned comment.
- [ ] Publish one short teaser for LinkedIn/X/YouTube Shorts.
- [ ] Track comments, retention drop-offs, subscribers, GitHub stars, and docs traffic.
"""


def render_brief(catalog: dict[str, Any], episode: dict[str, Any]) -> str:
    defaults = catalog["defaults"]
    sources = "\n".join(
        f"- `{path}`" for path in [episode["primary_doc"], *episode.get("supporting_docs", [])]
    )
    excerpts = "\n\n".join(
        f"## {path}\n\n{textwrap.indent(read_doc_excerpt(path, 1600), '> ')}"
        for path in [episode["primary_doc"], *episode.get("supporting_docs", [])[:2]]
    )
    return f"""# Brief: {episode["title"]}

## Audience

{defaults["audience"]}

## Problem

{episode["audience_problem"]}

## Promise

{episode["promise"]}

## Call to Action

{episode["cta"]}

## Sources

{sources}

## Source Excerpts

{excerpts}
"""


def write_episode_pack(catalog: dict[str, Any], episode: dict[str, Any], force: bool) -> None:
    episode_dir = EPISODES_DIR / episode["id"]
    episode_dir.mkdir(parents=True, exist_ok=True)
    script = render_script(catalog, episode)
    duration = estimate_duration_seconds(script)
    files = {
        "brief.md": render_brief(catalog, episode),
        "script.md": script,
        "avatar-segments.md": render_avatar_segments(episode),
        "captions.srt": render_srt(create_even_captions(clean_speakable_text(script), duration)),
        "metadata.md": render_metadata(catalog, episode, duration),
        "shot-list.md": render_shot_list(episode),
        "production-checklist.md": render_checklist(episode),
    }
    for filename, content in files.items():
        path = episode_dir / filename
        if path.exists() and not force:
            print(f"Skipped existing {path.relative_to(PROJECT_ROOT)}")
            continue
        path.write_text(content.strip() + "\n", encoding="utf-8")
        print(f"Saved {path.relative_to(PROJECT_ROOT)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Quorvex YouTube episode production assets")
    parser.add_argument("--episode", "-e", default="001", help="Episode id, or 'all'")
    parser.add_argument("--catalog", type=Path, default=CATALOG_PATH)
    parser.add_argument("--force", action="store_true", help="Overwrite existing episode files")
    args = parser.parse_args()

    catalog = load_catalog(args.catalog)
    if args.episode == "all":
        episodes = catalog["episodes"]
    else:
        episodes = [find_episode(catalog, args.episode)]

    for episode in episodes:
        write_episode_pack(catalog, episode, args.force)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
