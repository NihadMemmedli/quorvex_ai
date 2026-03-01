"""
Coverage Package

Provides coverage tracking and analysis capabilities for the AI test automation system.
"""

from .playwright_coverage import CoverageTracker, PlaywrightCoverage, merge_coverage_reports

__all__ = ["PlaywrightCoverage", "CoverageTracker", "merge_coverage_reports"]
