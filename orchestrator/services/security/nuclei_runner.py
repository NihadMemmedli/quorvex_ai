"""
Nuclei Scanner Runner - Executes Nuclei binary via subprocess.

Parses JSONL output and maps results to SecurityFinding format.
Nuclei binary must be available in PATH or Docker container.
"""

import asyncio
import hashlib
import json
import logging
import os
import shutil

logger = logging.getLogger(__name__)

NUCLEI_TIMEOUT = int(os.environ.get("NUCLEI_TIMEOUT_SECONDS", "600"))


def _make_hash(scanner: str, finding_type: str, url: str, evidence_key: str = "") -> str:
    """Generate finding deduplication hash."""
    raw = f"{scanner}:{finding_type}:{url}:{evidence_key}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _nuclei_available() -> bool:
    """Check if nuclei binary is available."""
    return shutil.which("nuclei") is not None


def _map_nuclei_severity(severity: str) -> str:
    """Map Nuclei severity to our severity scale."""
    mapping = {
        "critical": "critical",
        "high": "high",
        "medium": "medium",
        "low": "low",
        "info": "info",
        "unknown": "info",
    }
    return mapping.get(severity.lower(), "info")


def _map_nuclei_category(tags: list[str]) -> str:
    """Map Nuclei template tags to OWASP category."""
    tag_set = set(t.lower() for t in tags)

    if tag_set & {"sqli", "sql-injection"}:
        return "owasp_a03"
    if tag_set & {"xss", "cross-site-scripting"}:
        return "owasp_a03"
    if tag_set & {"rce", "command-injection", "code-injection"}:
        return "owasp_a03"
    if tag_set & {"ssrf"}:
        return "owasp_a10"
    if tag_set & {"lfi", "rfi", "path-traversal", "file-inclusion"}:
        return "owasp_a01"
    if tag_set & {"auth", "authentication", "default-login", "weak-credentials"}:
        return "owasp_a07"
    if tag_set & {"exposure", "disclosure", "misconfig"}:
        return "owasp_a05"
    if tag_set & {"cve"}:
        return "owasp_a06"
    return "misconfiguration"


async def run_nuclei_scan(
    target_url: str,
    severity_filter: str | None = None,
    templates: list[str] | None = None,
    on_progress: callable | None = None,
) -> list[dict]:
    """Run Nuclei scan against target URL.

    Args:
        target_url: URL to scan
        severity_filter: Comma-separated severity filter (e.g., "critical,high")
        templates: Specific template IDs to run
        on_progress: Optional callback for progress updates

    Returns:
        List of finding dicts matching SecurityFinding schema
    """
    if not _nuclei_available():
        raise RuntimeError("Nuclei binary not found. Install nuclei or use Docker profile.")

    findings: list[dict] = []

    # Build command
    cmd = [
        "nuclei",
        "-u",
        target_url,
        "-jsonl",  # JSON Lines output
        "-silent",  # Suppress banner
        "-no-color",  # No ANSI colors
        "-timeout",
        "10",  # Per-request timeout
        "-retries",
        "1",
    ]

    if severity_filter:
        cmd.extend(["-severity", severity_filter])

    if templates:
        for t in templates:
            cmd.extend(["-t", t])

    logger.info(f"Starting Nuclei scan: {' '.join(cmd)}")

    if on_progress:
        await on_progress("Starting Nuclei scan...")

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout_lines = []

        # Read stdout line by line (JSONL format)
        async def read_output():
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                line_str = line.decode().strip()
                if line_str:
                    stdout_lines.append(line_str)

        try:
            await asyncio.wait_for(read_output(), timeout=NUCLEI_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning(f"Nuclei scan timed out after {NUCLEI_TIMEOUT}s")
            process.kill()
            await process.wait()

        await process.wait()

        # Parse JSONL output
        for line in stdout_lines:
            try:
                result = json.loads(line)
                info = result.get("info", {})
                tags = info.get("tags", [])
                template_id = result.get("template-id", result.get("templateID", "unknown"))
                matched_url = result.get("matched-at", result.get("matched", target_url))

                finding = {
                    "severity": _map_nuclei_severity(info.get("severity", "info")),
                    "finding_type": template_id,
                    "category": _map_nuclei_category(tags),
                    "title": info.get("name", template_id),
                    "description": info.get("description", f"Nuclei template {template_id} matched"),
                    "url": matched_url,
                    "evidence": result.get("extracted-results", result.get("matcher-name", "")),
                    "remediation": info.get("remediation", ""),
                    "reference_urls": info.get("reference", []),
                    "template_id": template_id,
                    "finding_hash": _make_hash("nuclei", template_id, matched_url),
                }

                # Convert evidence to string if it's a list
                if isinstance(finding["evidence"], list):
                    finding["evidence"] = "\n".join(str(e) for e in finding["evidence"])
                if isinstance(finding["reference_urls"], str):
                    finding["reference_urls"] = [finding["reference_urls"]]

                findings.append(finding)

            except json.JSONDecodeError:
                logger.debug(f"Skipping non-JSON Nuclei output: {line[:100]}")
                continue

        if on_progress:
            await on_progress(f"Nuclei scan complete: {len(findings)} findings")

        logger.info(f"Nuclei scan complete: {len(findings)} findings from {len(stdout_lines)} output lines")

    except FileNotFoundError:
        raise RuntimeError("Nuclei binary not found in PATH")
    except Exception as e:
        logger.error(f"Nuclei scan error: {e}")
        raise RuntimeError(f"Nuclei scan failed: {e}")

    return findings
