"""
Playwright Coverage Integration

Integrates with Playwright's Coverage API to collect JavaScript and CSS
coverage data during test execution.
"""

import json
from typing import Any


class PlaywrightCoverage:
    """
    Collects and processes coverage data from Playwright tests.

    Uses Playwright's built-in Coverage API to track which JavaScript and CSS
    code is used during test execution.
    """

    @staticmethod
    def setup_coverage_script() -> str:
        """
        Generate JavaScript to start coverage collection.

        Returns:
            JavaScript code string to execute in the browser
        """
        return """
        // Start coverage collection
        async function startCoverage() {
            if (window.CSS && window.CSS.coverage) {
                await CSS.coverage.start();
            }
            if (window.JSCoverage) {
                await JSCoverage.start();
            }
        }
        startCoverage();
        """

    @staticmethod
    def collect_coverage_script() -> str:
        """
        Generate JavaScript to stop and collect coverage data.

        Returns:
            JavaScript code string to execute in the browser
        """
        return """
        // Stop coverage collection and return results
        async function collectCoverage() {
            const results = { js: [], css: [] };

            if (window.JSCoverage) {
                results.js = await JSCoverage.stop();
            }
            if (window.CSS && window.CSS.coverage) {
                results.css = await CSS.coverage.stop();
            }

            return JSON.stringify(results);
        }
        await collectCoverage();
        """

    @staticmethod
    def process_coverage_data(coverage_json: str) -> dict[str, Any]:
        """
        Process raw coverage data into statistics.

        Args:
            coverage_json: Raw coverage JSON from Playwright

        Returns:
            Processed coverage statistics
        """
        try:
            coverage_data = json.loads(coverage_json)
        except json.JSONDecodeError:
            return {"total_bytes": 0, "used_bytes": 0, "coverage_percentage": 0.0, "files": []}

        total_bytes = 0
        used_bytes = 0
        files = []

        # Process JavaScript coverage
        for entry in coverage_data.get("js", []):
            url = entry.get("url", "unknown")
            ranges = entry.get("ranges", [])
            text = entry.get("text", "")

            # Calculate coverage
            file_total = len(text)
            file_used = sum(r.get("end", 0) - r.get("start", 0) for r in ranges)

            total_bytes += file_total
            used_bytes += file_used

            files.append(
                {
                    "url": url,
                    "type": "javascript",
                    "total_bytes": file_total,
                    "used_bytes": file_used,
                    "coverage_percentage": (file_used / file_total * 100) if file_total > 0 else 0,
                }
            )

        # Process CSS coverage
        for entry in coverage_data.get("css", []):
            url = entry.get("url", "unknown")
            ranges = entry.get("ranges", [])
            text = entry.get("text", "")

            file_total = len(text)
            file_used = sum(r.get("end", 0) - r.get("start", 0) for r in ranges)

            total_bytes += file_total
            used_bytes += file_used

            files.append(
                {
                    "url": url,
                    "type": "css",
                    "total_bytes": file_total,
                    "used_bytes": file_used,
                    "coverage_percentage": (file_used / file_total * 100) if file_total > 0 else 0,
                }
            )

        return {
            "total_bytes": total_bytes,
            "used_bytes": used_bytes,
            "unused_bytes": total_bytes - used_bytes,
            "coverage_percentage": (used_bytes / total_bytes * 100) if total_bytes > 0 else 0,
            "files": files,
        }

    @staticmethod
    def generate_coverage_report(coverage_stats: dict[str, Any]) -> str:
        """
        Generate a human-readable coverage report.

        Args:
            coverage_stats: Processed coverage statistics

        Returns:
            Formatted report string
        """
        lines = [
            "## Code Coverage Report",
            "",
            f"**Total Coverage:** {coverage_stats['coverage_percentage']:.1f}%",
            f"**Used:** {coverage_stats['used_bytes']:,} bytes",
            f"**Unused:** {coverage_stats['unused_bytes']:,} bytes",
            "",
            "### Files",
            "",
        ]

        # Sort files by coverage percentage
        files = sorted(coverage_stats.get("files", []), key=lambda f: f["coverage_percentage"])

        for file_info in files[:20]:  # Top 20 files
            lines.append(
                f"- **{file_info['url']}** ({file_info['type']}): "
                f"{file_info['coverage_percentage']:.1f}% "
                f"({file_info['used_bytes']:,}/{file_info['total_bytes']:,} bytes)"
            )

        return "\n".join(lines)


class CoverageTracker:
    """
    Tracks element coverage during test execution.

    Records which selectors were successfully used during tests
    to build a coverage map.
    """

    def __init__(self):
        self.covered_elements: list[dict[str, Any]] = []
        self.failed_elements: list[dict[str, Any]] = []

    def record_element(
        self, action: str, selector: dict[str, Any], success: bool, url: str = None, error: str = None
    ) -> None:
        """
        Record an element interaction.

        Args:
            action: Action performed (click, fill, etc.)
            selector: Selector used
            success: Whether the action succeeded
            url: Page URL
            error: Error message if failed
        """
        record = {
            "action": action,
            "selector": selector,
            "url": url,
            "timestamp": json.dumps({"__iso__": True}),  # Use current time in real usage
        }

        if success:
            self.covered_elements.append(record)
        else:
            record["error"] = error
            self.failed_elements.append(record)

    def get_coverage_summary(self) -> dict[str, Any]:
        """
        Get a summary of coverage data.

        Returns:
            Coverage summary statistics
        """
        total = len(self.covered_elements) + len(self.failed_elements)
        successful = len(self.covered_elements)

        return {
            "total_interactions": total,
            "successful_interactions": successful,
            "failed_interactions": len(self.failed_elements),
            "success_rate": (successful / total * 100) if total > 0 else 0,
            "covered_elements": self.covered_elements,
            "failed_elements": self.failed_elements,
        }

    def get_covered_urls(self) -> list[str]:
        """
        Get list of URLs that were covered.

        Returns:
            List of unique URLs
        """
        urls = set()
        for element in self.covered_elements:
            if element.get("url"):
                urls.add(element["url"])
        return list(urls)

    def get_uncovered_selectors(self, all_selectors: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Find selectors that were not successfully covered.

        Args:
            all_selectors: List of all known selectors

        Returns:
            List of uncovered selectors
        """
        covered = set()
        for element in self.covered_elements:
            selector_str = json.dumps(element.get("selector", {}), sort_keys=True)
            covered.add(selector_str)

        uncovered = []
        for selector in all_selectors:
            selector_str = json.dumps(selector, sort_keys=True)
            if selector_str not in covered:
                uncovered.append(selector)

        return uncovered


def merge_coverage_reports(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Merge multiple coverage reports into one.

    Args:
        reports: List of coverage report dictionaries

    Returns:
        Merged coverage report
    """
    merged = {
        "total_elements": 0,
        "tested_elements": 0,
        "coverage_percentage": 0.0,
        "breakdown": {},
        "reports": reports,
    }

    for report in reports:
        summary = report.get("coverage_summary", {})
        merged["total_elements"] += summary.get("total_elements", 0)
        merged["tested_elements"] += summary.get("tested_elements", 0)

        # Merge breakdowns
        for element_type, stats in summary.get("breakdown", {}).items():
            if element_type not in merged["breakdown"]:
                merged["breakdown"][element_type] = {"total": 0, "tested": 0, "coverage": 0}
            merged["breakdown"][element_type]["total"] += stats.get("total", 0)
            merged["breakdown"][element_type]["tested"] += stats.get("tested", 0)

    # Calculate percentages
    for element_type in merged["breakdown"]:
        stats = merged["breakdown"][element_type]
        stats["coverage"] = stats["tested"] / stats["total"] * 100 if stats["total"] > 0 else 0

    merged["coverage_percentage"] = (
        merged["tested_elements"] / merged["total_elements"] * 100 if merged["total_elements"] > 0 else 0
    )

    return merged
