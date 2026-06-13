import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.cli import _extract_target_url


def test_extract_target_url_strips_markdown_backticks():
    content = "Target URL: `https://pre.wetravel.to/user/my_trips?view=List`"

    assert _extract_target_url(content) == "https://pre.wetravel.to/user/my_trips?view=List"


def test_extract_target_url_from_observed_url_table_is_clean():
    content = """
| Page | URL |
|------|-----|
| My Trips | `https://pre.wetravel.to/user/my_trips?view=List` |
"""

    assert _extract_target_url(content) == "https://pre.wetravel.to/user/my_trips?view=List"


def test_extract_target_url_strips_trailing_prose_punctuation():
    content = "Navigate to https://example.test/checkout)."

    assert _extract_target_url(content) == "https://example.test/checkout"
