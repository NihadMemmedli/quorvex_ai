"""
Security Analyzer - AI-powered security finding analysis.

Uses Claude agent to:
1. Analyze security scan findings and provide prioritized remediation
2. Generate security specs from exploration session data
3. Perform trend analysis across multiple scan runs

Follows the same pattern as requirements_generator.py using AgentRunner.
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

# Setup path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from load_env import setup_claude_env
from logging_config import get_logger, setup_logging
from utils.agent_runner import AgentRunner
from utils.json_utils import extract_json_from_markdown

logger = get_logger(__name__)


async def analyze_findings(
    findings: list[dict[str, Any]],
    target_url: str,
    scan_type: str = "quick",
) -> dict[str, Any]:
    """Analyze security findings and generate prioritized remediation plan.

    Args:
        findings: List of SecurityFinding dicts from the scan
        target_url: The scanned URL
        scan_type: Type of scan performed

    Returns:
        Dict with keys: summary, priority_actions, remediation_plan, risk_score
    """
    setup_claude_env()

    if not findings:
        return {
            "summary": "No findings to analyze.",
            "priority_actions": [],
            "remediation_plan": [],
            "risk_score": 0,
        }

    # Build findings summary for the prompt
    findings_text = _format_findings_for_prompt(findings)

    # Severity counts
    severity_counts: dict[str, int] = {}
    for f in findings:
        sev = f.get("severity", "info")
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    prompt = f"""Analyze the following security scan results for {target_url} and provide a prioritized remediation plan.

## Scan Type: {scan_type}

## Severity Summary
- Critical: {severity_counts.get("critical", 0)}
- High: {severity_counts.get("high", 0)}
- Medium: {severity_counts.get("medium", 0)}
- Low: {severity_counts.get("low", 0)}
- Info: {severity_counts.get("info", 0)}

## Findings
{findings_text}

## Instructions
Analyze these findings and respond with a JSON object:

```json
{{
    "summary": "Brief executive summary of the security posture (2-3 sentences)",
    "risk_score": <1-100 integer, where 100 is highest risk>,
    "priority_actions": [
        {{
            "priority": 1,
            "title": "Action title",
            "description": "What to do and why",
            "affected_findings": ["finding titles..."],
            "effort": "low|medium|high",
            "impact": "critical|high|medium|low"
        }}
    ],
    "remediation_plan": [
        {{
            "category": "Category name (e.g., Headers, Cookies, SSL)",
            "items": [
                {{
                    "finding": "Finding title",
                    "severity": "critical|high|medium|low|info",
                    "fix": "Specific remediation step",
                    "code_example": "Optional code snippet if applicable"
                }}
            ]
        }}
    ],
    "false_positive_candidates": [
        {{
            "finding": "Finding title",
            "reason": "Why this might be a false positive"
        }}
    ]
}}
```

Focus on actionable, specific remediation steps. Group related fixes together. Identify potential false positives.
"""

    runner = AgentRunner(
        timeout_seconds=120,
        allowed_tools=[],  # No tools needed for analysis
        log_tools=False,
    )
    result = await runner.run(prompt)

    if not result.success:
        error_msg = result.error or "Unknown error"
        if result.timed_out:
            raise RuntimeError(f"AI analysis timed out: {error_msg}")
        raise RuntimeError(f"AI analysis failed: {error_msg}")

    result_text = result.output

    if not result_text or not result_text.strip():
        raise RuntimeError("AI analysis returned empty result")

    try:
        parsed = extract_json_from_markdown(result_text)
        if isinstance(parsed, dict):
            return parsed
    except Exception as e:
        logger.warning(f"Failed to parse AI analysis as JSON: {e}")

    # Return raw text as summary if JSON parsing fails
    return {
        "summary": result_text[:1000],
        "priority_actions": [],
        "remediation_plan": [],
        "risk_score": 50,
    }


async def generate_security_spec(
    session_id: str,
    flows: list[dict[str, Any]],
    api_endpoints: list[dict[str, Any]],
    entry_url: str,
) -> str:
    """Generate a security test spec from exploration session data.

    Args:
        session_id: Exploration session ID
        flows: Discovered flows from exploration
        api_endpoints: Discovered API endpoints
        entry_url: Entry URL of the exploration

    Returns:
        Markdown spec content
    """
    setup_claude_env()

    # Format exploration data
    flows_text = ""
    for f in flows[:20]:  # Limit to 20 flows
        flows_text += f"- {f.get('flow_name', 'Unknown')}: {f.get('description', 'No description')}\n"
        flows_text += f"  Category: {f.get('flow_category', 'unknown')}, Steps: {f.get('step_count', 0)}\n"

    endpoints_text = ""
    for ep in api_endpoints[:30]:  # Limit to 30 endpoints
        endpoints_text += f"- {ep.get('method', 'GET')} {ep.get('url', '')}\n"
        if ep.get("response_status"):
            endpoints_text += f"  Status: {ep['response_status']}\n"

    prompt = f"""Generate a security test specification for the application at {entry_url}.

## Discovered Flows
{flows_text or "No flows discovered."}

## Discovered API Endpoints
{endpoints_text or "No API endpoints discovered."}

## Instructions
Create a markdown security test specification that covers:
1. Authentication and session security testing
2. Authorization and access control testing
3. Input validation and injection testing
4. API security testing for discovered endpoints
5. CORS and header security verification

Format as a markdown document with:
- Title: "Security Scan: [Application Name]"
- Target URL
- Scan Type (recommend appropriate type)
- Description
- Specific security checks to perform based on the discovered flows and endpoints

Keep it concise and actionable.
"""

    runner = AgentRunner(
        timeout_seconds=90,
        allowed_tools=[],
        log_tools=False,
    )
    result = await runner.run(prompt)

    if not result.success:
        error_msg = result.error or "Unknown error"
        raise RuntimeError(f"Security spec generation failed: {error_msg}")

    result_text = result.output

    if not result_text or not result_text.strip():
        raise RuntimeError("AI returned empty spec")

    return result_text


async def trend_analysis(
    runs: list[dict[str, Any]],
    project_name: str = "Project",
) -> dict[str, Any]:
    """Analyze vulnerability trends across multiple scan runs.

    Args:
        runs: List of SecurityScanRun dicts with severity counts
        project_name: Project name for context

    Returns:
        Dict with trend analysis results
    """
    setup_claude_env()

    if len(runs) < 2:
        return {
            "summary": "Not enough data for trend analysis. At least 2 scan runs are needed.",
            "trends": [],
            "recommendations": [],
        }

    runs_text = ""
    for r in runs[:20]:  # Limit to 20 runs
        runs_text += f"- {r.get('created_at', 'Unknown date')} ({r.get('scan_type', 'unknown')} scan of {r.get('target_url', 'unknown')})\n"
        runs_text += f"  Critical: {r.get('critical_count', 0)}, High: {r.get('high_count', 0)}, Medium: {r.get('medium_count', 0)}, Low: {r.get('low_count', 0)}, Info: {r.get('info_count', 0)}\n"
        runs_text += f"  Total: {r.get('total_findings', 0)}, Status: {r.get('status', 'unknown')}\n\n"

    prompt = f"""Analyze the security scan trends for {project_name}.

## Scan History (most recent first)
{runs_text}

## Instructions
Provide a trend analysis in JSON format:

```json
{{
    "summary": "Overall security trend analysis (2-3 sentences)",
    "trend_direction": "improving|stable|degrading",
    "trends": [
        {{
            "metric": "Metric name (e.g., 'Critical findings')",
            "direction": "up|down|stable",
            "details": "Explanation"
        }}
    ],
    "recommendations": [
        "Actionable recommendation based on the trends"
    ],
    "areas_of_concern": [
        "Specific area that needs attention"
    ]
}}
```
"""

    runner = AgentRunner(
        timeout_seconds=90,
        allowed_tools=[],
        log_tools=False,
    )
    result = await runner.run(prompt)

    if not result.success:
        error_msg = result.error or "Unknown error"
        if result.timed_out:
            logger.warning(f"Trend analysis timed out: {error_msg}")
        else:
            raise RuntimeError(f"Trend analysis failed: {error_msg}")

    result_text = result.output

    if not result_text or not result_text.strip():
        return {"summary": "Analysis failed to produce results", "trends": [], "recommendations": []}

    try:
        parsed = extract_json_from_markdown(result_text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    return {"summary": result_text[:1000], "trends": [], "recommendations": []}


def _format_findings_for_prompt(findings: list[dict[str, Any]]) -> str:
    """Format findings list into readable text for AI prompt."""
    text = ""
    for i, f in enumerate(findings[:50], 1):  # Limit to 50 findings
        text += f"\n### Finding {i}: [{f.get('severity', 'info').upper()}] {f.get('title', 'Unknown')}\n"
        text += f"- **Type**: {f.get('finding_type', 'unknown')}\n"
        text += f"- **Category**: {f.get('category', 'unknown')}\n"
        text += f"- **URL**: {f.get('url', 'N/A')}\n"
        if f.get("description"):
            text += f"- **Description**: {f['description'][:300]}\n"
        if f.get("evidence"):
            text += f"- **Evidence**: {f['evidence'][:200]}\n"
        if f.get("remediation"):
            text += f"- **Current Remediation**: {f['remediation'][:200]}\n"
    return text


if __name__ == "__main__":
    setup_logging()
    # Test with sample data
    sample_findings = [
        {
            "severity": "high",
            "finding_type": "missing_hsts",
            "category": "misconfiguration",
            "title": "Missing HSTS Header",
            "description": "Strict-Transport-Security header not set",
            "url": "https://example.com",
            "evidence": "Header missing from response",
            "remediation": "Add HSTS header",
        }
    ]
    result = asyncio.run(analyze_findings(sample_findings, "https://example.com"))
    print(json.dumps(result, indent=2))
