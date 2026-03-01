"""
ZAP DAST Client - Wraps OWASP ZAP Python API for automated security scanning.

Requires: python-owasp-zap-v2.4 package and running ZAP daemon.
ZAP daemon should be running on the configured host:port.
"""

import asyncio
import hashlib
import logging
import os
import time

from circuitbreaker import circuit
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

ZAP_HOST = os.environ.get("ZAP_HOST", "localhost")
ZAP_PORT = int(os.environ.get("ZAP_PORT", "8090"))
ZAP_API_KEY = os.environ.get("ZAP_API_KEY", "")
ZAP_TIMEOUT = int(os.environ.get("SECURITY_SCAN_TIMEOUT", "1800"))


def _make_hash(scanner: str, finding_type: str, url: str, evidence_key: str = "") -> str:
    """Generate finding deduplication hash."""
    raw = f"{scanner}:{finding_type}:{url}:{evidence_key}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _get_zap():
    """Get ZAP API client instance."""
    try:
        from zapv2 import ZAPv2
    except ImportError:
        raise RuntimeError("python-owasp-zap-v2.4 not installed. Install with: pip install python-owasp-zap-v2.4")

    proxy_url = f"http://{ZAP_HOST}:{ZAP_PORT}"
    return ZAPv2(apikey=ZAP_API_KEY, proxies={"http": proxy_url, "https": proxy_url})


def _check_zap_available() -> bool:
    """Check if ZAP daemon is reachable."""
    try:
        zap = _get_zap()
        _ = zap.core.version
        return True
    except Exception:
        return False


def _map_zap_risk(risk: str) -> str:
    """Map ZAP risk level to our severity scale."""
    mapping = {
        "3": "high",  # High
        "2": "medium",  # Medium
        "1": "low",  # Low
        "0": "info",  # Informational
    }
    return mapping.get(str(risk), "info")


def _map_zap_category(cweid: int) -> str:
    """Map CWE ID to OWASP category."""
    cwe_owasp = {
        # Injection
        89: "owasp_a03",
        78: "owasp_a03",
        90: "owasp_a03",
        77: "owasp_a03",
        # XSS
        79: "owasp_a03",
        # Broken Auth
        287: "owasp_a07",
        384: "owasp_a07",
        613: "owasp_a07",
        # Sensitive Data
        311: "owasp_a02",
        319: "owasp_a02",
        312: "owasp_a02",
        # XXE
        611: "owasp_a05",
        # Broken Access Control
        284: "owasp_a01",
        285: "owasp_a01",
        639: "owasp_a01",
        # Security Misconfiguration
        16: "owasp_a05",
        2: "owasp_a05",
        # SSRF
        918: "owasp_a10",
    }
    return cwe_owasp.get(cweid, "misconfiguration")


@circuit(failure_threshold=5, recovery_timeout=60, expected_exception=Exception)
async def run_zap_scan(
    target_url: str,
    scan_policy: str | None = None,
    spider_enabled: bool = True,
    active_scan_enabled: bool = True,
    on_progress: callable | None = None,
) -> list[dict]:
    """Run ZAP DAST scan (spider + passive + active).

    Args:
        target_url: URL to scan
        scan_policy: ZAP scan policy name (optional)
        spider_enabled: Whether to run the spider
        active_scan_enabled: Whether to run active scan
        on_progress: Optional async callback for progress updates

    Returns:
        List of finding dicts matching SecurityFinding schema
    """
    if not _check_zap_available():
        raise RuntimeError(
            f"ZAP daemon not reachable at {ZAP_HOST}:{ZAP_PORT}. "
            "Start ZAP with: docker compose --profile security up -d zap"
        )

    zap = _get_zap()
    findings: list[dict] = []
    start_time = time.time()

    logger.info(f"Starting ZAP scan: {target_url}")

    # Open URL in ZAP
    if on_progress:
        await on_progress("Opening target URL in ZAP...")
    zap.urlopen(target_url)
    await asyncio.sleep(2)  # Wait for passive scan

    # Spider (crawl)
    if spider_enabled:
        if on_progress:
            await on_progress("Running ZAP spider...")

        spider_id = zap.spider.scan(target_url)

        while True:
            if time.time() - start_time > ZAP_TIMEOUT:
                logger.warning("ZAP spider timed out")
                zap.spider.stop(spider_id)
                break

            progress = int(zap.spider.status(spider_id))
            if on_progress:
                await on_progress(f"Spider progress: {progress}%")

            if progress >= 100:
                break
            await asyncio.sleep(2)

        logger.info(f"Spider found {len(zap.spider.results(spider_id))} URLs")

    # Wait for passive scan to complete
    if on_progress:
        await on_progress("Waiting for passive scan to complete...")

    while int(zap.pscan.records_to_scan) > 0:
        if time.time() - start_time > ZAP_TIMEOUT:
            break
        await asyncio.sleep(1)

    # Active scan
    if active_scan_enabled:
        if on_progress:
            await on_progress("Running ZAP active scan...")

        scan_kwargs = {"url": target_url}
        if scan_policy:
            scan_kwargs["scanpolicyname"] = scan_policy

        ascan_id = zap.ascan.scan(**scan_kwargs)

        while True:
            if time.time() - start_time > ZAP_TIMEOUT:
                logger.warning("ZAP active scan timed out")
                zap.ascan.stop(ascan_id)
                break

            progress = int(zap.ascan.status(ascan_id))
            if on_progress:
                await on_progress(f"Active scan progress: {progress}%")

            if progress >= 100:
                break
            await asyncio.sleep(5)

    # Collect alerts (findings)
    if on_progress:
        await on_progress("Collecting findings...")

    alerts = zap.core.alerts(baseurl=target_url)

    for alert in alerts:
        cweid = int(alert.get("cweid", 0))
        alert_ref = alert.get("alertRef", alert.get("pluginid", ""))

        finding = {
            "severity": _map_zap_risk(alert.get("risk", "0")),
            "finding_type": f"zap_{alert_ref}",
            "category": _map_zap_category(cweid),
            "title": alert.get("name", alert.get("alert", "Unknown ZAP Finding")),
            "description": alert.get("description", ""),
            "url": alert.get("url", target_url),
            "evidence": alert.get("evidence", ""),
            "remediation": alert.get("solution", ""),
            "reference_urls": [r for r in alert.get("reference", "").split("\n") if r.strip()],
            "zap_alert_ref": alert_ref,
            "zap_cweid": cweid if cweid > 0 else None,
            "finding_hash": _make_hash("zap", f"zap_{alert_ref}", alert.get("url", target_url)),
        }
        findings.append(finding)

    elapsed = int(time.time() - start_time)
    logger.info(f"ZAP scan complete in {elapsed}s: {len(findings)} findings")

    if on_progress:
        await on_progress(f"ZAP scan complete: {len(findings)} findings in {elapsed}s")

    return findings


@circuit(failure_threshold=5, recovery_timeout=60, expected_exception=Exception)
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)
async def get_zap_version() -> str | None:
    """Get ZAP version for health check."""
    zap = _get_zap()
    return zap.core.version
