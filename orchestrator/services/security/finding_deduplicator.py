"""
Finding Deduplicator - Cross-scanner deduplication for security findings.

Uses SHA256 hashing to identify duplicate findings across different scanners
(quick, nuclei, zap). Prevents the same vulnerability from being reported
multiple times when multiple scanners detect it.
"""

import hashlib
import logging

logger = logging.getLogger(__name__)


def compute_finding_hash(scanner: str, finding_type: str, url: str, evidence_key: str = "") -> str:
    """Generate a deduplication hash for a finding.

    The hash is based on scanner + finding_type + url + evidence_key.
    This means the same issue found by different scanners will have different hashes
    (by design - we want to know which scanner found what).

    For cross-scanner dedup, use compute_cross_scanner_hash() instead.
    """
    raw = f"{scanner}:{finding_type}:{url}:{evidence_key}"
    return hashlib.sha256(raw.encode()).hexdigest()


def compute_cross_scanner_hash(finding_type: str, url: str) -> str:
    """Generate a cross-scanner dedup hash.

    Strips the scanner identifier so findings from different scanners
    that represent the same issue can be identified as duplicates.
    """
    # Normalize finding types across scanners
    normalized_type = _normalize_finding_type(finding_type)
    # Normalize URL (strip query params and fragments)
    normalized_url = _normalize_url(url)

    raw = f"cross:{normalized_type}:{normalized_url}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _normalize_finding_type(finding_type: str) -> str:
    """Normalize finding types across scanners for dedup comparison."""
    # Map common equivalences
    type_map = {
        # Missing headers
        "missing_csp": "missing_csp",
        "10038": "missing_csp",  # ZAP plugin ID for CSP
        "missing_hsts": "missing_hsts",
        "10035": "missing_hsts",  # ZAP HSTS
        "missing_x_frame_options": "missing_x_frame_options",
        "10020": "missing_x_frame_options",  # ZAP X-Frame-Options
        "missing_x_content_type_options": "missing_x_content_type_options",
        "10021": "missing_x_content_type_options",  # ZAP X-Content-Type-Options
        # Cookie issues
        "cookie_no_httponly": "cookie_no_httponly",
        "10010": "cookie_no_httponly",  # ZAP
        "cookie_no_secure": "cookie_no_secure",
        "10011": "cookie_no_secure",  # ZAP
        # Info disclosure
        "server_version_disclosure": "server_info_disclosure",
        "10036": "server_info_disclosure",  # ZAP Server Leaks
    }

    # Strip scanner prefix if present
    clean_type = finding_type
    for prefix in ["zap_", "nuclei_"]:
        if clean_type.startswith(prefix):
            clean_type = clean_type[len(prefix) :]

    return type_map.get(clean_type, clean_type)


def _normalize_url(url: str) -> str:
    """Normalize URL for comparison (strip query params and fragment)."""
    from urllib.parse import urlparse, urlunparse

    parsed = urlparse(url)
    # Keep scheme, netloc, path only
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def deduplicate_findings(findings: list[dict], existing_hashes: set[str] = None) -> list[dict]:
    """Remove duplicate findings within a list and against existing hashes.

    Args:
        findings: List of finding dicts with 'finding_hash' key
        existing_hashes: Set of finding_hash values already in DB

    Returns:
        Deduplicated list of findings
    """
    if existing_hashes is None:
        existing_hashes = set()

    seen = set()
    unique_findings = []
    duplicates_removed = 0

    for finding in findings:
        h = finding.get("finding_hash", "")
        if h and h not in seen and h not in existing_hashes:
            seen.add(h)
            unique_findings.append(finding)
        else:
            duplicates_removed += 1

    if duplicates_removed > 0:
        logger.info(f"Deduplication removed {duplicates_removed} duplicate findings")

    return unique_findings


def merge_scanner_findings(
    quick_findings: list[dict],
    nuclei_findings: list[dict],
    zap_findings: list[dict],
) -> list[dict]:
    """Merge findings from all scanners with cross-scanner dedup.

    Priority: ZAP > Nuclei > Quick (keep the more detailed finding)
    """
    # Build cross-scanner hash map
    cross_hash_map: dict[str, dict] = {}

    # Process in priority order (lowest first, higher overwrites)
    for scanner_name, findings_list in [("quick", quick_findings), ("nuclei", nuclei_findings), ("zap", zap_findings)]:
        for finding in findings_list:
            cross_hash = compute_cross_scanner_hash(
                finding.get("finding_type", ""),
                finding.get("url", ""),
            )

            if cross_hash in cross_hash_map:
                existing = cross_hash_map[cross_hash]
                # Keep the one with higher severity
                severity_order = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}
                existing_sev = severity_order.get(existing.get("severity", "info"), 0)
                new_sev = severity_order.get(finding.get("severity", "info"), 0)

                if new_sev >= existing_sev:
                    cross_hash_map[cross_hash] = finding
                    logger.debug(
                        f"Cross-scanner dedup: keeping {scanner_name} finding over {existing.get('scanner', 'unknown')}"
                    )
            else:
                cross_hash_map[cross_hash] = finding

    merged = list(cross_hash_map.values())
    total_input = len(quick_findings) + len(nuclei_findings) + len(zap_findings)
    logger.info(f"Merged {total_input} findings into {len(merged)} unique findings")

    return merged
