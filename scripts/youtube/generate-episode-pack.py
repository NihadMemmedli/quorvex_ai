#!/usr/bin/env python3
"""Generate deterministic YouTube episode production assets."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = PROJECT_ROOT / "content" / "youtube" / "episode-catalog.json"
EPISODES_DIR = PROJECT_ROOT / "content" / "youtube" / "episodes"
TIMED_HEADING_RE = re.compile(r"^###\s+(\d+):(\d{2})-(\d+):(\d{2})\s+(.+)$")


EPISODE_001_FILES = {
    "brief.md": """# Episode Brief: AI-Generated Playwright Tests Failed — Now What?

## Goal

Record the first Quorvex AI YouTube demo as a practical QA triage workflow that starts on a red checkout failure, not a perfect green-path product tour.

## Audience

QA engineers and QA automation leads who use Playwright, review generated Playwright work, and need failures to become organized evidence.

## Promise

Show how Quorvex AI turns failed AI-generated checkout tests into organized QA work: specs, run history, agent findings, evidence, test ideas, database checks, and dashboard quality signals.

## Seeded Demo

Use:

```bash
make youtube-demo-seed
```

Then select `Quorvex Demo Shop`.

## Main Story

AI-generated tests and agents can fail. Useful QA systems make those failures explainable, reviewable, and ready for triage.

## Required Screens

- Failed checkout run detail with red status visible in the first 5 seconds.
- Runs page with failed checkout runs.
- Run detail with selector drift and payment validation evidence.
- Project selector with `Quorvex Demo Shop`.
- Dashboard with pass/fail trend, failure categories, flaky tests, and slowest tests.
- Agents page with `Checkout Failure Triage`.
- Specs page with checkout, cart, login, discount, and order confirmation specs.
- Database Testing page with customer/order/payment quality checks.

## CTA

Star the repo, run the seeded demo, and comment with the next QA workflow to cover.
""",
    "avatar-segments.md": """# Avatar Segments

Use avatar footage only for short bookends and section transitions. Keep the main video screen-first.

## Hook

Most AI testing demos show a perfect green run. This one starts on the red checkout failure, where real QA work starts.

## Transition To Agent Findings

Now that the runs tell us what failed, the useful question is what a QA engineer should do next.

## Transition To Specs

The generated Playwright code is not the source of truth. The spec is the source of intent.

## Outro

Seed the demo, inspect the AI-generated Playwright failures, and tell me which QA workflow you want to see next.
""",
    "metadata.md": """# Metadata

## Recommended Title

AI-Generated Playwright Tests Failed — Now What?

## Title Options

1. AI-Generated Playwright Tests Failed — Now What?
2. Your AI Playwright Tests Failed. Here Is the QA Triage Workflow.
3. Failed Checkout Tests to Agent Findings and QA Evidence
4. Stop Losing Failed Tests: Organize Playwright QA with Quorvex AI
5. AI Agents for QA Engineers: Playwright Failures, Specs, and Evidence

## Description

In this first Quorvex AI demo, we start with a red checkout run and show what happens after AI-generated Playwright tests fail.

The walkthrough covers failed checkout runs, selector drift, payment validation regression, cart total mismatch, flaky checkout state, agent findings, evidence, generated test ideas, markdown specs, dashboard quality signals, and database-testing checks. The goal is not a perfect green-path demo. The goal is a practical QA triage workflow.

Try the deterministic demo:

```bash
make youtube-demo-seed
```

Chapters:

```text
0:00 Failed checkout tests are the point
0:30 Why useful QA systems make failure actionable
1:15 Quorvex Demo Shop setup
2:30 Walk through a failed checkout run
4:00 Agent findings, evidence, and test ideas
5:45 Specs connected to generated Playwright work
7:00 Database and dashboard quality signals
8:15 Recap: organize Playwright QA work
9:30 Try the seeded demo
```

## Pinned Comment

The demo is deterministic and starts from a failed checkout run. Seed the same project with:

```bash
make youtube-demo-seed
```

Then select `Quorvex Demo Shop`. What should the next workflow cover: API contract testing, PR test selection, database checks, or Playwright maintenance?

## Thumbnail Prompt

Create a clean, professional YouTube thumbnail for a QA automation product demo. Show a modern software dashboard on a laptop screen with a red failed checkout test in the first visual focus and organized QA cards on the right labeled Findings, Evidence, Specs, and DB Checks. Add a subtle commerce checkout context using small cart and payment icons. Use high contrast, crisp UI detail, and a serious engineering tone. Avoid cartoon mascots, busy backgrounds, fake code rain, and exaggerated facial expressions. Leave open space for the text "NOW WHAT?".

## Thumbnail Text Options

1. NOW WHAT?
2. RED RUN TO QA PLAN
3. PLAYWRIGHT FAILURES, ORGANIZED
4. AI QA TRIAGE

## Tags

Playwright, QA automation, AI testing, software testing, test automation, flaky tests, checkout testing, database testing, QA engineering, AI agents
""",
    "shot-list.md": """# Shot List

1. Failed checkout run first frame: open `quorvex-demo-shop-checkout-selector-drift` with a red failed status visible before narration begins.
2. Run logs: show lifecycle, execution log, selector drift message, and validation evidence in the first 5 seconds.
3. Runs page: briefly show payment validation regression, cart total mismatch, flaky checkout state, and slow checkout rows.
4. Project selector: choose Quorvex Demo Shop if the recording needs the setup context.
5. Dashboard trend: highlight pass/fail trend, failure categories, flaky tests, and slowest tests.
6. Runs page: filter or scan for checkout failures.
7. Run detail: return to `quorvex-demo-shop-checkout-selector-drift` and explain selector drift versus product defects.
8. Run details: show payment validation regression evidence and cart total mismatch evidence.
9. Agents page: open `Checkout Failure Triage`.
10. Agent overview: show summary, pages checked, finding count, test idea count.
11. Agent findings tab: show selector drift, payment validation, and cart total findings.
12. Agent test ideas tab: show API-backed cart total contract and session retry idea.
13. Specs page: open checkout payment validation markdown spec.
14. Generated test view or run detail code area: show Playwright test derived from the spec.
15. Specs page: briefly show cart, login, discount, and order confirmation specs.
16. Database Testing page: show Quorvex Demo Shop connection, latest run, failed checks.
17. Database check details: show duplicate email or payments/order total mismatch sample data.
18. Dashboard final frame: return to quality signals and summarize the workflow.
""",
    "production-checklist.md": """# Production Checklist

## Before Recording

- Run `make youtube-demo-seed`.
- If Postgres is not running, use `make youtube-demo-seed SKIP_DATABASE=1` and skip the database-testing shot.
- Start the app and open the dashboard.
- Select `Quorvex Demo Shop` in the project selector.
- Open the failed checkout run before recording starts so the first frame is a red run, not the dashboard overview.
- Confirm the first 5 seconds can show the red failed checkout status and the selector drift log evidence.
- Confirm dashboard shows failed runs, flaky tests, slowest tests, and failure categories.
- Confirm `/runs` lists seeded checkout runs.
- Confirm the selector drift run detail opens and shows logs.
- Confirm `/agents` lists `Checkout Failure Triage`.
- Confirm agent findings, test ideas, and evidence tabs have content.
- Confirm `/specs` shows the `quorvex-demo-shop` specs.
- Confirm `/database-testing` shows `Quorvex Demo Shop` data if database seed was enabled.

## Browser Setup

- Use a clean browser profile.
- Set zoom to 100 percent.
- Use a 1440x900 or 1920x1080 capture area.
- Hide bookmarks and unrelated extensions.
- Keep the terminal out of frame unless showing the seed command.

## Delivery Notes

- Keep the tone practical and QA-focused.
- Avoid implying the agent fixes code automatically.
- Distinguish product defects from automation maintenance.
- Keep the platform tour narrow: dashboard, runs, agents, specs, database testing.
- Strongest on-screen moments: red checkout failure, hidden Pay now locator drift, Payment authorized after expired card, cart total mismatch, flaky refresh timeout, agent findings, API-backed cart total test idea, database payment/order mismatch.

## Final Commands

- `make youtube-demo-seed`
- `make youtube-voice EP=001 VOICE=DODLEQrClDo8wCz460ld`
- `make youtube-final EP=001 RECORDING=path/to/recording.mp4`

## Final QA

- Rewatch the first 5 seconds and confirm the hook shows a red checkout failure immediately.
- Confirm the first 30 seconds does not feel like a dashboard overview.
- Confirm no private environment variables, tokens, or local customer data are visible.
- Confirm the pinned comment includes the seed command.
""",
}


def timestamp_to_seconds(minutes: str, seconds: str) -> float:
    return int(minutes) * 60 + int(seconds)


def format_srt_timestamp(total_seconds: float) -> str:
    milliseconds = int(round(total_seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def strip_inline_markdown(text: str) -> str:
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    return text.strip()


def chunk_caption_text(text: str, max_length: int = 84) -> list[str]:
    sentences = [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", text) if sentence.strip()]
    chunks: list[str] = []
    for sentence in sentences:
        sentence = strip_inline_markdown(sentence)
        if not sentence:
            continue
        if len(sentence) <= max_length:
            chunks.append(sentence)
            continue

        current: list[str] = []
        current_length = 0
        for word in sentence.split():
            proposed_length = current_length + len(word) + (1 if current else 0)
            if current and proposed_length > max_length:
                chunks.append(" ".join(current))
                current = [word]
                current_length = len(word)
            else:
                current.append(word)
                current_length = proposed_length
        if current:
            chunks.append(" ".join(current))
    return chunks


def parse_script_sections(script_path: Path) -> list[tuple[float, float, list[str]]]:
    sections: list[tuple[float, float, list[str]]] = []
    current_index: int | None = None
    in_fence = False

    for raw_line in script_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not line:
            continue

        match = TIMED_HEADING_RE.match(line)
        if match:
            start = timestamp_to_seconds(match.group(1), match.group(2))
            end = timestamp_to_seconds(match.group(3), match.group(4))
            sections.append((start, end, []))
            current_index = len(sections) - 1
            continue

        if line.startswith("#") or line.startswith("|") or line == "---":
            continue
        if line.startswith("- ") or re.match(r"^\d+\.\s+", line):
            continue
        if current_index is None:
            continue

        start, end, lines = sections[current_index]
        lines.append(strip_inline_markdown(line.lstrip("> ").strip()))
        sections[current_index] = (start, end, lines)

    return sections


def generate_srt_from_script(script_path: Path) -> str:
    entries: list[str] = []
    counter = 1

    for start, end, lines in parse_script_sections(script_path):
        chunks = chunk_caption_text(" ".join(lines))
        if not chunks:
            continue
        total_weight = sum(max(1, len(chunk)) for chunk in chunks)
        cursor = start
        duration = max(0.1, end - start)

        for index, chunk in enumerate(chunks):
            if index == len(chunks) - 1:
                next_cursor = end
            else:
                next_cursor = cursor + duration * (max(1, len(chunk)) / total_weight)
            entries.append(
                f"{counter}\n"
                f"{format_srt_timestamp(cursor)} --> {format_srt_timestamp(next_cursor)}\n"
                f"{chunk}\n"
            )
            counter += 1
            cursor = next_cursor

    if not entries:
        raise ValueError(f"No caption entries could be generated from {script_path}")
    return "\n".join(entries).strip() + "\n"


def load_catalog(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def find_episode(catalog: dict[str, Any], episode_id: str) -> dict[str, Any]:
    for episode in catalog.get("episodes", []):
        if episode.get("id") == episode_id:
            return episode
    raise SystemExit(f"Unknown episode id: {episode_id}")


def write_episode_001(force: bool) -> None:
    episode_dir = EPISODES_DIR / "001"
    episode_dir.mkdir(parents=True, exist_ok=True)
    script_path = episode_dir / "script.md"
    if not script_path.exists():
        raise SystemExit(f"Missing script source: {script_path.relative_to(PROJECT_ROOT)}")

    for filename, content in EPISODE_001_FILES.items():
        path = episode_dir / filename
        if path.exists() and not force:
            print(f"Skipped existing {path.relative_to(PROJECT_ROOT)}")
            continue
        path.write_text(content.strip() + "\n", encoding="utf-8")
        print(f"Saved {path.relative_to(PROJECT_ROOT)}")

    captions_path = episode_dir / "captions.srt"
    if captions_path.exists() and not force:
        print(f"Skipped existing {captions_path.relative_to(PROJECT_ROOT)}")
    else:
        captions_path.write_text(generate_srt_from_script(script_path), encoding="utf-8")
        print(f"Saved {captions_path.relative_to(PROJECT_ROOT)}")
    print(f"Kept {script_path.relative_to(PROJECT_ROOT)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Quorvex YouTube episode production assets")
    parser.add_argument("--episode", "-e", default="001", help="Episode id, or 'all'")
    parser.add_argument("--catalog", type=Path, default=CATALOG_PATH)
    parser.add_argument("--force", action="store_true", help="Overwrite generated episode files")
    args = parser.parse_args()

    catalog = load_catalog(args.catalog)
    episode_ids = [episode.get("id") for episode in catalog.get("episodes", [])] if args.episode == "all" else [args.episode]

    for episode_id in episode_ids:
        find_episode(catalog, episode_id)
        if episode_id == "001":
            write_episode_001(args.force)
        else:
            raise SystemExit(f"No generator template is available for episode {episode_id}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
