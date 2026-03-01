"""
Progress Reporter - Reports pipeline stage progress to backend API.

This module provides a simple interface for the CLI and pipeline stages
to report their progress to the backend API for real-time UI updates.
"""

import logging
import os
from pathlib import Path

# Try to import requests, but don't fail if not available
try:
    import requests

    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

logger = logging.getLogger(__name__)

# API base URL (can be overridden via environment)
API_BASE_URL = os.environ.get("PLAYWRIGHT_AGENT_API_URL", "http://localhost:8001")


class ProgressReporter:
    """
    Reports pipeline progress to the backend API.

    Stages:
    - planning: Native planner exploring the application
    - generating: Native generator creating test code
    - testing: Running the generated test
    - healing: Fixing test failures (attempts 1-3 native, 4+ ralph)
    """

    def __init__(self, run_id: str, api_url: str = None):
        """
        Initialize the progress reporter.

        Args:
            run_id: The unique run ID to report progress for
            api_url: Optional API base URL (default: http://localhost:8001)
        """
        self.run_id = run_id
        self.api_url = api_url or API_BASE_URL
        self._enabled = REQUESTS_AVAILABLE and bool(run_id)

        if not REQUESTS_AVAILABLE:
            logger.warning("requests library not available, progress reporting disabled")

    def report(self, stage: str, message: str = None, healing_attempt: int = None) -> bool:
        """
        Report progress to the backend API.

        Args:
            stage: Current stage ("planning", "generating", "testing", "healing")
            message: Optional detailed status message
            healing_attempt: Optional healing attempt number (1, 2, 3, etc.)

        Returns:
            True if report was sent successfully, False otherwise
        """
        if not self._enabled:
            return False

        try:
            payload = {"stage": stage}
            if message:
                payload["message"] = message
            if healing_attempt is not None:
                payload["healing_attempt"] = healing_attempt

            response = requests.post(
                f"{self.api_url}/runs/{self.run_id}/progress",
                json=payload,
                timeout=5,  # Don't block too long
            )

            if response.status_code == 200:
                logger.debug(f"Progress reported: {stage} - {message}")
                return True
            else:
                logger.warning(f"Failed to report progress: {response.status_code}")
                return False

        except requests.exceptions.Timeout:
            logger.warning("Progress report timed out")
            return False
        except requests.exceptions.ConnectionError:
            # Backend might not be running (CLI mode)
            logger.debug("Backend not available for progress reporting")
            return False
        except Exception as e:
            logger.warning(f"Error reporting progress: {e}")
            return False

    def planning(self, message: str = "Exploring application structure..."):
        """Report planning stage."""
        return self.report("planning", message)

    def generating(self, message: str = "Creating test code..."):
        """Report generation stage."""
        return self.report("generating", message)

    def testing(self, message: str = "Running test..."):
        """Report testing stage."""
        return self.report("testing", message)

    def healing(self, attempt: int, message: str = None):
        """Report healing stage with attempt number."""
        if message is None:
            if attempt <= 3:
                message = f"Native healing attempt {attempt}/3..."
            else:
                message = f"Ralph healing attempt {attempt}..."
        return self.report("healing", message, healing_attempt=attempt)


# Global convenience function
_reporter: ProgressReporter | None = None


def init_progress_reporter(run_id: str, api_url: str = None) -> ProgressReporter:
    """
    Initialize the global progress reporter.

    Args:
        run_id: The unique run ID to report progress for
        api_url: Optional API base URL

    Returns:
        ProgressReporter instance
    """
    global _reporter
    _reporter = ProgressReporter(run_id, api_url)
    return _reporter


def get_progress_reporter() -> ProgressReporter | None:
    """Get the global progress reporter instance."""
    return _reporter


def report_progress(stage: str, message: str = None, healing_attempt: int = None) -> bool:
    """
    Report progress using the global reporter.

    This is a convenience function that can be called from anywhere
    after init_progress_reporter() has been called.

    Args:
        stage: Current stage
        message: Optional status message
        healing_attempt: Optional healing attempt number

    Returns:
        True if reported successfully, False otherwise
    """
    if _reporter:
        return _reporter.report(stage, message, healing_attempt)
    return False


def extract_run_id_from_path(run_dir: Path) -> str | None:
    """
    Extract run ID from run directory path.

    The run_dir is typically: runs/2024-01-15_10-30-00
    The run_id is the directory name.

    Args:
        run_dir: Path to the run directory

    Returns:
        Run ID string or None
    """
    if run_dir and isinstance(run_dir, Path):
        return run_dir.name
    elif run_dir and isinstance(run_dir, str):
        return Path(run_dir).name
    return None
