import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.utils.agent_report import _build_custom_agent_structured_report


def test_custom_agent_report_uses_structured_json_block():
    output = """
Done.

```json
{
  "structured_report": {
    "summary": "Checked the login flow.",
    "scope": "Login",
    "pages_checked": [{"url": "/login", "status": "loaded"}],
    "findings": [{"title": "Invalid password error is missing", "severity": "high", "page": "/login"}],
    "test_ideas": [{"title": "Invalid password validation", "priority": "high", "steps": ["Open login"], "expected": "Error shown"}],
    "requirements": [{
      "title": "Login must show invalid password feedback",
      "description": "Users should see a visible error when an invalid password is submitted.",
      "category": "authentication",
      "priority": "high",
      "acceptance_criteria": ["Invalid password attempts show a visible error"],
      "page": "/login",
      "evidence": "No error message",
      "confidence": 0.82
    }],
    "evidence": [{"type": "note", "label": "Observation", "value": "No error message"}],
    "follow_up_actions": [{"label": "Create regression spec", "action": "create_spec", "target": "F-001"}]
  }
}
```
"""

    report = _build_custom_agent_structured_report(output, {"prompt": "test login"}, [])

    assert report["parse_status"] == "structured"
    assert report["summary"] == "Checked the login flow."
    assert report["pages_checked"][0]["url"] == "/login"
    assert report["findings"][0]["id"] == "F-001"
    assert report["test_ideas"][0]["id"] == "T-001"
    assert report["requirements"][0]["id"] == "R-001"
    assert report["requirements"][0]["category"] == "authentication"
    assert report["requirements"][0]["priority"] == "high"
    assert report["requirements"][0]["acceptance_criteria"] == ["Invalid password attempts show a visible error"]
    assert report["requirements"][0]["confidence"] == 0.82


def test_custom_agent_report_recovers_plain_text_findings():
    output = """
# Deep Testing Report
| Page | Status |
|---|---|
| `/az/sitemap` | JS crash: e_: INSUFFICIENT_PATH |
| `/regulatory-legal-documents` | Renders empty body with no content |
| `/support` | Loads, FAQ tab works |
"""

    report = _build_custom_agent_structured_report(output, {"prompt": "test public pages", "url": "https://example.test"}, [])

    assert report["parse_status"] == "heuristic"
    assert any(page["url"] == "/support" for page in report["pages_checked"])
    assert len(report["findings"]) >= 2
    assert report["findings"][0]["id"].startswith("F-")
    assert len(report["test_ideas"]) == len(report["findings"])
    assert report["requirements"] == []
