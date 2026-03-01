"""
RTM (Requirements Traceability Matrix) Generator Workflow

Matches requirements to test specifications to create a traceability matrix.
Uses semantic similarity and content analysis to determine which tests
cover which requirements.

The RTM provides:
- Coverage visibility (which requirements have tests)
- Gap analysis (which requirements need tests)
- Test-requirement mapping for audit/compliance
"""

import asyncio
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

# Add orchestrator to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load Claude credentials and SDK
import logging

from load_env import setup_claude_env

setup_claude_env()

from memory.exploration_store import get_exploration_store
from utils.agent_runner import AgentRunner

logger = logging.getLogger(__name__)


@dataclass
class TestSpecInfo:
    """Information about a test specification."""

    name: str
    path: str
    content: str
    steps: list[str]
    expected_outcomes: list[str]
    url: str | None = None


@dataclass
class RtmMapping:
    """A mapping between a requirement and a test."""

    requirement_id: int
    requirement_code: str
    requirement_title: str
    test_spec_name: str
    test_spec_path: str
    mapping_type: str  # full, partial, suggested
    confidence: float
    coverage_notes: str | None = None
    gap_notes: str | None = None


@dataclass
class RtmGenerationResult:
    """Result of RTM generation."""

    mappings: list[RtmMapping]
    total_requirements: int
    covered_requirements: int
    partial_requirements: int
    uncovered_requirements: int
    coverage_percentage: float
    gaps: list[dict[str, Any]]  # Requirements without tests


class RtmGenerator:
    """
    RTM Generator that matches requirements to test specifications.

    Uses:
    1. Semantic similarity between requirement descriptions and test steps
    2. Element/selector matching
    3. URL/page matching
    4. Category alignment
    """

    def __init__(self, project_id: str = "default"):
        self.project_id = project_id
        self.store = get_exploration_store(project_id=project_id)
        self.specs_dir = Path(__file__).resolve().parent.parent.parent / "specs"

    async def generate_rtm(
        self, specs_paths: list[str] | None = None, use_ai_matching: bool = True
    ) -> RtmGenerationResult:
        """
        Generate RTM by matching requirements to test specs.

        Args:
            specs_paths: Optional list of spec paths to consider (defaults to all in specs/)
            use_ai_matching: Whether to use AI for intelligent matching

        Returns:
            RtmGenerationResult with all mappings
        """
        logger.info("=" * 80)
        logger.info("RTM GENERATION")
        logger.info("=" * 80)
        logger.info("")

        # Load requirements
        requirements = self.store.get_requirements()
        logger.info(f"   Requirements: {len(requirements)}")

        if not requirements:
            logger.warning("   No requirements found. Run requirements generation first.")
            return RtmGenerationResult(
                mappings=[],
                total_requirements=0,
                covered_requirements=0,
                partial_requirements=0,
                uncovered_requirements=0,
                coverage_percentage=0.0,
                gaps=[],
            )

        # Load test specs
        specs = self._load_test_specs(specs_paths)
        logger.info(f"   Test Specs: {len(specs)}")
        logger.info("")

        # Generate mappings
        if use_ai_matching and specs:
            logger.info("Using AI for intelligent matching...")
            mappings = await self._match_with_ai(requirements, specs)
        else:
            logger.info("Using heuristic matching...")
            mappings = self._match_heuristically(requirements, specs)

        # Clear existing RTM entries before storing new ones to avoid duplicates
        cleared = self.store.clear_rtm_for_project(self.project_id)
        if cleared:
            logger.info(f"Cleared {cleared} existing RTM entries for project {self.project_id}")

        # Store mappings
        logger.info(f"Storing {len(mappings)} RTM mappings...")

        for mapping in mappings:
            self.store.store_rtm_entry(
                requirement_id=mapping.requirement_id,
                test_spec_name=mapping.test_spec_name,
                test_spec_path=mapping.test_spec_path,
                mapping_type=mapping.mapping_type,
                confidence=mapping.confidence,
                coverage_notes=mapping.coverage_notes,
                gap_notes=mapping.gap_notes,
            )

        # Calculate statistics
        req_ids_covered = set()
        req_ids_partial = set()

        for m in mappings:
            if m.mapping_type == "full":
                req_ids_covered.add(m.requirement_id)
            elif m.mapping_type == "partial":
                req_ids_partial.add(m.requirement_id)

        # Requirements with partial but not full coverage
        req_ids_partial = req_ids_partial - req_ids_covered

        total = len(requirements)
        covered = len(req_ids_covered)
        partial = len(req_ids_partial)
        uncovered = total - covered - partial

        coverage_pct = (covered / total * 100) if total > 0 else 0.0

        # Identify gaps
        gaps = []
        covered_or_partial_ids = req_ids_covered | req_ids_partial
        for req in requirements:
            if req.id not in covered_or_partial_ids:
                gaps.append(
                    {
                        "requirement_id": req.id,
                        "requirement_code": req.req_code,
                        "title": req.title,
                        "category": req.category,
                        "priority": req.priority,
                        "suggested_test": self._suggest_test_for_requirement(req),
                    }
                )

        result = RtmGenerationResult(
            mappings=mappings,
            total_requirements=total,
            covered_requirements=covered,
            partial_requirements=partial,
            uncovered_requirements=uncovered,
            coverage_percentage=coverage_pct,
            gaps=gaps,
        )

        logger.info("RTM Generation Complete!")
        logger.info(f"   Total Requirements: {total}")
        logger.info(f"   Fully Covered: {covered} ({coverage_pct:.1f}%)")
        logger.info(f"   Partially Covered: {partial}")
        logger.info(f"   Uncovered: {uncovered}")
        logger.info(f"   Gaps Identified: {len(gaps)}")

        return result

    def _load_test_specs(self, paths: list[str] | None = None) -> list[TestSpecInfo]:
        """Load and parse test specifications."""
        specs = []

        if paths:
            spec_files = [Path(p) for p in paths if Path(p).exists()]
        else:
            # Load all .md files from specs directory
            spec_files = list(self.specs_dir.glob("**/*.md"))

        for spec_file in spec_files:
            try:
                content = spec_file.read_text()
                spec_info = self._parse_spec_content(name=spec_file.stem, path=str(spec_file), content=content)
                if spec_info:
                    specs.append(spec_info)
            except Exception as e:
                logger.warning(f"   Error loading {spec_file}: {e}")

        return specs

    def _parse_spec_content(self, name: str, path: str, content: str) -> TestSpecInfo | None:
        """Parse a spec file to extract steps and expected outcomes."""
        steps = []
        expected_outcomes = []
        url = None

        lines = content.split("\n")
        in_steps = False
        in_expected = False

        for line in lines:
            line_lower = line.lower().strip()

            # Detect URL
            url_match = re.search(r"(https?://[^\s]+)", line)
            if url_match and not url:
                url = url_match.group(1)

            # Detect section headers
            if "## steps" in line_lower or "## test steps" in line_lower:
                in_steps = True
                in_expected = False
                continue
            elif "## expected" in line_lower or "## outcome" in line_lower or "## results" in line_lower:
                in_steps = False
                in_expected = True
                continue
            elif line.startswith("## "):
                in_steps = False
                in_expected = False
                continue

            # Collect content
            if in_steps and line.strip():
                # Numbered steps
                step_match = re.match(r"^\d+\.\s*(.+)", line.strip())
                if step_match:
                    steps.append(step_match.group(1))
                elif line.strip().startswith("- "):
                    steps.append(line.strip()[2:])

            if in_expected and line.strip():
                if line.strip().startswith("- "):
                    expected_outcomes.append(line.strip()[2:])
                elif re.match(r"^\d+\.", line.strip()):
                    expected_outcomes.append(re.sub(r"^\d+\.\s*", "", line.strip()))

        # Only return if we found meaningful content
        if steps or expected_outcomes:
            return TestSpecInfo(
                name=name, path=path, content=content, steps=steps, expected_outcomes=expected_outcomes, url=url
            )

        return None

    async def _match_with_ai(self, requirements: list, specs: list[TestSpecInfo]) -> list[RtmMapping]:
        """Use AI to intelligently match requirements to specs."""

        # Build requirement summaries
        req_summaries = []
        for req in requirements:
            req_summaries.append(
                {
                    "id": req.id,
                    "code": req.req_code,
                    "title": req.title,
                    "description": req.description,
                    "category": req.category,
                    "acceptance_criteria": req.acceptance_criteria,
                }
            )

        # Build spec summaries
        spec_summaries = []
        for spec in specs:
            spec_summaries.append(
                {
                    "name": spec.name,
                    "path": spec.path,
                    "steps": spec.steps[:10],  # Limit steps
                    "expected_outcomes": spec.expected_outcomes[:5],
                    "url": spec.url,
                }
            )

        prompt = f"""You are a QA Engineer matching requirements to test specifications.

## Requirements
```json
{json.dumps(req_summaries, indent=2)}
```

## Test Specifications
```json
{json.dumps(spec_summaries, indent=2)}
```

## Your Task

For each requirement, determine which test specifications (if any) cover it.

Consider:
1. Do the test steps address the requirement's functionality?
2. Do the expected outcomes match the acceptance criteria?
3. Is the coverage complete (full) or only partial?

## Output Format

Output a JSON array of mappings:

```json
{{
  "mappings": [
    {{
      "requirement_id": 1,
      "requirement_code": "REQ-001",
      "test_spec_name": "login-test",
      "mapping_type": "full|partial|suggested",
      "confidence": 0.95,
      "coverage_notes": "Test covers login success and failure scenarios",
      "gap_notes": "Missing test for session expiration"
    }}
  ]
}}
```

**Mapping Types:**
- `full`: Test fully covers the requirement (all acceptance criteria tested)
- `partial`: Test covers some but not all of the requirement
- `suggested`: Test might cover the requirement but needs review

**Confidence:**
- 0.9-1.0: Very confident in mapping
- 0.7-0.9: Confident but some uncertainty
- 0.5-0.7: Possible match, needs review
- Below 0.5: Weak match, likely not covering

Generate the mappings now. Include mappings for all requirements that have matching tests:
"""

        mappings = []
        result_text = ""

        try:
            runner = AgentRunner(
                timeout_seconds=300,
                allowed_tools=[],
                log_tools=False,
            )
            result = await runner.run(prompt)

            if not result.success:
                error_msg = result.error or "Unknown error"
                logger.error(f"RTM AI matching failed: {error_msg}")
                return self._match_heuristically(requirements, specs)

            result_text = result.output

        except Exception as e:
            error_str = str(e).lower()
            if "cancel scope" in error_str or "cancelled" in error_str:
                logger.info("SDK cleanup warning (ignored)")
            else:
                logger.error(f"RTM generation error: {e}")
                return self._match_heuristically(requirements, specs)

        # Parse mappings from response (runs regardless of cancel scope)
        if result_text:
            mappings = self._parse_mappings_response(result_text, requirements, specs)

        return mappings

    def _parse_mappings_response(
        self, response_text: str, requirements: list, specs: list[TestSpecInfo]
    ) -> list[RtmMapping]:
        """Parse RTM mappings from AI response."""
        from utils.json_utils import extract_json_from_markdown

        mappings = []

        # Build lookup dictionaries
        req_by_id = {r.id: r for r in requirements}
        req_by_code = {r.req_code: r for r in requirements}
        spec_by_name = {s.name: s for s in specs}

        raw_mappings = None

        # Strategy 1: Use robust extract_json_from_markdown utility
        try:
            data = extract_json_from_markdown(response_text)
            if isinstance(data, dict) and "mappings" in data:
                raw_mappings = data["mappings"]
            elif isinstance(data, list):
                raw_mappings = data
        except (ValueError, json.JSONDecodeError):
            pass

        # Strategy 2: Fallback - try extracting from multiple code blocks
        if not raw_mappings:
            json_pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
            matches = re.findall(json_pattern, response_text)
            for json_str in matches:
                try:
                    data = json.loads(json_str.strip())
                    if isinstance(data, dict) and "mappings" in data:
                        raw_mappings = data["mappings"]
                        break
                    elif isinstance(data, list):
                        raw_mappings = data
                        break
                except json.JSONDecodeError:
                    continue

        if not raw_mappings:
            return mappings

        for m in raw_mappings:
            if not isinstance(m, dict):
                continue

            # Find requirement
            req_id = m.get("requirement_id")
            req_code = m.get("requirement_code")
            req = req_by_id.get(req_id) or req_by_code.get(req_code)

            if not req:
                continue

            # Find spec
            spec_name = m.get("test_spec_name")
            spec = spec_by_name.get(spec_name)

            if not spec:
                # Try partial match
                for s in specs:
                    if spec_name and spec_name.lower() in s.name.lower():
                        spec = s
                        break

            if not spec:
                continue

            mapping = RtmMapping(
                requirement_id=req.id,
                requirement_code=req.req_code,
                requirement_title=req.title,
                test_spec_name=spec.name,
                test_spec_path=spec.path,
                mapping_type=m.get("mapping_type", "suggested"),
                confidence=m.get("confidence", 0.5),
                coverage_notes=m.get("coverage_notes"),
                gap_notes=m.get("gap_notes"),
            )
            mappings.append(mapping)

        return mappings

    def _match_heuristically(self, requirements: list, specs: list[TestSpecInfo]) -> list[RtmMapping]:
        """Match requirements to specs using heuristic rules."""
        mappings = []

        for req in requirements:
            req_keywords = self._extract_keywords(f"{req.title} {req.description} {' '.join(req.acceptance_criteria)}")

            best_match = None
            best_score = 0

            for spec in specs:
                spec_keywords = self._extract_keywords(
                    f"{spec.name} {' '.join(spec.steps)} {' '.join(spec.expected_outcomes)}"
                )

                # Calculate keyword overlap
                if req_keywords and spec_keywords:
                    overlap = len(req_keywords & spec_keywords)
                    score = overlap / max(len(req_keywords), 1)

                    if score > best_score:
                        best_score = score
                        best_match = spec

            if best_match and best_score > 0.2:
                mapping_type = "full" if best_score > 0.6 else "partial" if best_score > 0.4 else "suggested"

                mapping = RtmMapping(
                    requirement_id=req.id,
                    requirement_code=req.req_code,
                    requirement_title=req.title,
                    test_spec_name=best_match.name,
                    test_spec_path=best_match.path,
                    mapping_type=mapping_type,
                    confidence=best_score,
                    coverage_notes=f"Matched by keyword overlap ({best_score:.0%})",
                )
                mappings.append(mapping)

        return mappings

    def _extract_keywords(self, text: str) -> set:
        """Extract significant keywords from text."""
        # Remove common words and extract meaningful terms
        stop_words = {
            "the",
            "a",
            "an",
            "is",
            "are",
            "was",
            "were",
            "be",
            "been",
            "being",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "could",
            "should",
            "may",
            "might",
            "must",
            "shall",
            "can",
            "need",
            "to",
            "of",
            "in",
            "for",
            "on",
            "with",
            "at",
            "by",
            "from",
            "as",
            "or",
            "and",
            "but",
            "if",
            "then",
            "than",
            "so",
            "such",
            "that",
            "this",
            "these",
            "those",
            "it",
            "its",
            "they",
            "their",
            "them",
            "we",
            "our",
            "us",
            "you",
            "your",
            "i",
            "my",
            "me",
            "when",
            "where",
            "which",
            "who",
            "what",
            "how",
            "why",
            "all",
            "each",
            "every",
            "both",
            "few",
            "more",
            "some",
            "any",
            "no",
            "not",
            "only",
            "same",
            "other",
        }

        words = re.findall(r"\b[a-z]+\b", text.lower())
        keywords = {w for w in words if len(w) > 2 and w not in stop_words}

        return keywords

    def _suggest_test_for_requirement(self, req) -> dict[str, Any]:
        """Generate a suggested test outline for an uncovered requirement."""
        return {
            "name": f"test-{req.req_code.lower()}",
            "description": f"Test for: {req.title}",
            "steps": [f"Test step for: {criterion}" for criterion in req.acceptance_criteria[:5]]
            if req.acceptance_criteria
            else [f"Verify: {req.title}"],
            "priority": req.priority,
        }

    def export_rtm(self, format: str = "markdown") -> str:
        """
        Export the RTM to a specified format.

        Args:
            format: Export format (markdown, csv, html)

        Returns:
            Formatted RTM string
        """
        rtm = self.store.get_full_rtm()

        if format == "markdown":
            return self._export_markdown(rtm)
        elif format == "csv":
            return self._export_csv(rtm)
        elif format == "html":
            return self._export_html(rtm)
        else:
            raise ValueError(f"Unknown format: {format}")

    def _export_markdown(self, rtm: list[dict]) -> str:
        """Export RTM as Markdown."""
        lines = [
            "# Requirements Traceability Matrix",
            "",
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
            "## Summary",
            "",
        ]

        # Calculate stats
        total = len(rtm)
        covered = sum(1 for r in rtm if r["coverage_status"] == "covered")
        partial = sum(1 for r in rtm if r["coverage_status"] == "partial")
        uncovered = sum(1 for r in rtm if r["coverage_status"] == "uncovered")

        lines.extend(
            [
                f"- **Total Requirements**: {total}",
                f"- **Fully Covered**: {covered}",
                f"- **Partially Covered**: {partial}",
                f"- **Uncovered**: {uncovered}",
                f"- **Coverage**: {(covered / total * 100):.1f}%" if total > 0 else "- **Coverage**: N/A",
                "",
                "## Traceability Matrix",
                "",
                "| Requirement | Title | Priority | Status | Tests |",
                "|-------------|-------|----------|--------|-------|",
            ]
        )

        for entry in rtm:
            req = entry["requirement"]
            tests = entry["tests"]
            status = entry["coverage_status"]

            status_emoji = {"covered": "✅", "partial": "🔶", "uncovered": "❌", "suggested": "💡"}.get(status, "❓")

            test_names = ", ".join(t["spec_name"] for t in tests) if tests else "-"

            lines.append(
                f"| {req['code']} | {req['title'][:40]}{'...' if len(req['title']) > 40 else ''} | "
                f"{req['priority']} | {status_emoji} {status} | {test_names} |"
            )

        # Add gaps section
        gaps = [r for r in rtm if r["coverage_status"] == "uncovered"]
        if gaps:
            lines.extend(
                [
                    "",
                    "## Coverage Gaps",
                    "",
                    "The following requirements do not have test coverage:",
                    "",
                ]
            )
            for entry in gaps:
                req = entry["requirement"]
                lines.append(f"- **{req['code']}**: {req['title']} ({req['priority']} priority)")

        return "\n".join(lines)

    def _export_csv(self, rtm: list[dict]) -> str:
        """Export RTM as CSV."""
        lines = ["Requirement Code,Title,Category,Priority,Coverage Status,Test Specs,Confidence"]

        for entry in rtm:
            req = entry["requirement"]
            tests = entry["tests"]
            status = entry["coverage_status"]

            test_names = "; ".join(t["spec_name"] for t in tests) if tests else ""
            avg_confidence = sum(t["confidence"] for t in tests) / len(tests) if tests else 0

            # Escape quotes in title
            title = req["title"].replace('"', '""')

            lines.append(
                f'"{req["code"]}","{title}","{req["category"]}","{req["priority"]}",'
                f'"{status}","{test_names}",{avg_confidence:.2f}'
            )

        return "\n".join(lines)

    def _export_html(self, rtm: list[dict]) -> str:
        """Export RTM as HTML."""
        # Calculate stats
        total = len(rtm)
        covered = sum(1 for r in rtm if r["coverage_status"] == "covered")
        partial = sum(1 for r in rtm if r["coverage_status"] == "partial")
        uncovered = sum(1 for r in rtm if r["coverage_status"] == "uncovered")
        coverage_pct = (covered / total * 100) if total > 0 else 0

        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Requirements Traceability Matrix</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 20px; }}
        h1 {{ color: #333; }}
        .stats {{ display: flex; gap: 20px; margin: 20px 0; }}
        .stat {{ padding: 15px; background: #f5f5f5; border-radius: 8px; }}
        .stat-value {{ font-size: 24px; font-weight: bold; }}
        table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
        th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
        th {{ background: #4CAF50; color: white; }}
        tr:nth-child(even) {{ background: #f9f9f9; }}
        .covered {{ color: #4CAF50; }}
        .partial {{ color: #FF9800; }}
        .uncovered {{ color: #f44336; }}
        .priority-high {{ font-weight: bold; }}
        .priority-critical {{ font-weight: bold; color: #f44336; }}
    </style>
</head>
<body>
    <h1>Requirements Traceability Matrix</h1>
    <p>Generated: {datetime.now().strftime("%Y-%m-%d %H:%M")}</p>

    <div class="stats">
        <div class="stat">
            <div class="stat-value">{total}</div>
            <div>Total Requirements</div>
        </div>
        <div class="stat">
            <div class="stat-value covered">{covered}</div>
            <div>Fully Covered</div>
        </div>
        <div class="stat">
            <div class="stat-value partial">{partial}</div>
            <div>Partially Covered</div>
        </div>
        <div class="stat">
            <div class="stat-value uncovered">{uncovered}</div>
            <div>Uncovered</div>
        </div>
        <div class="stat">
            <div class="stat-value">{coverage_pct:.1f}%</div>
            <div>Coverage</div>
        </div>
    </div>

    <table>
        <tr>
            <th>Code</th>
            <th>Title</th>
            <th>Category</th>
            <th>Priority</th>
            <th>Status</th>
            <th>Tests</th>
        </tr>
"""

        for entry in rtm:
            req = entry["requirement"]
            tests = entry["tests"]
            status = entry["coverage_status"]

            status_class = status
            priority_class = f"priority-{req['priority']}" if req["priority"] in ["high", "critical"] else ""
            test_names = ", ".join(t["spec_name"] for t in tests) if tests else "-"

            html += f"""        <tr>
            <td>{req["code"]}</td>
            <td class="{priority_class}">{req["title"]}</td>
            <td>{req["category"]}</td>
            <td>{req["priority"]}</td>
            <td class="{status_class}">{status}</td>
            <td>{test_names}</td>
        </tr>
"""

        html += """    </table>
</body>
</html>"""

        return html


async def generate_rtm(
    project_id: str = "default", specs_paths: list[str] | None = None, use_ai_matching: bool = True
) -> RtmGenerationResult:
    """
    Convenience function to generate RTM.

    Args:
        project_id: Project ID
        specs_paths: Optional list of spec paths
        use_ai_matching: Whether to use AI matching

    Returns:
        RtmGenerationResult
    """
    generator = RtmGenerator(project_id=project_id)
    return await generator.generate_rtm(specs_paths, use_ai_matching)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate Requirements Traceability Matrix")
    parser.add_argument("--project", default="default", help="Project ID")
    parser.add_argument("--specs", nargs="+", help="Specific spec paths to include")
    parser.add_argument("--no-ai", action="store_true", help="Use heuristic matching instead of AI")
    parser.add_argument("--export", choices=["markdown", "csv", "html"], help="Export format")
    parser.add_argument("--output", help="Output file path")

    args = parser.parse_args()

    async def main():
        result = await generate_rtm(project_id=args.project, specs_paths=args.specs, use_ai_matching=not args.no_ai)

        logger.info(f"RTM Generated: {result.coverage_percentage:.1f}% coverage")

        if args.export:
            generator = RtmGenerator(project_id=args.project)
            exported = generator.export_rtm(format=args.export)

            if args.output:
                Path(args.output).write_text(exported)
                logger.info(f"Exported to: {args.output}")
            else:
                print(exported)

    try:
        from orchestrator.logging_config import setup_logging

        setup_logging()
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Stopped by user")
    except Exception as e:
        if "cancel scope" in str(e).lower():
            pass
        else:
            raise
