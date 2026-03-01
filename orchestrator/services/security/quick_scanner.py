"""
Quick Security Scanner - Python-native security checks using httpx.

Performs fast, non-invasive security checks:
- Security headers analysis
- Cookie security flags
- SSL/TLS certificate validation
- CORS misconfiguration detection
- Information disclosure probing
- Mixed content detection
"""

import hashlib
import logging
import socket
import ssl
from datetime import datetime
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)


def _make_hash(scanner: str, finding_type: str, url: str, evidence_key: str = "") -> str:
    """Generate finding deduplication hash."""
    raw = f"{scanner}:{finding_type}:{url}:{evidence_key}"
    return hashlib.sha256(raw.encode()).hexdigest()


async def run_quick_scan(target_url: str) -> list[dict]:
    """Run all quick security checks against target URL.

    Returns list of finding dicts with keys:
        severity, finding_type, category, title, description, url,
        evidence, remediation, reference_urls, finding_hash
    """
    findings: list[dict] = []

    logger.info(f"Starting quick security scan: {target_url}")

    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        verify=True,  # SSL verification on
    ) as client:
        try:
            response = await client.get(target_url)
        except httpx.ConnectError as e:
            logger.error(f"Cannot connect to {target_url}: {e}")
            raise RuntimeError(f"Cannot connect to target: {e}")
        except Exception as e:
            logger.error(f"Request failed for {target_url}: {e}")
            raise RuntimeError(f"Request failed: {e}")

        # Run all checks
        findings.extend(_check_security_headers(target_url, response))
        findings.extend(_check_cookie_security(target_url, response))
        findings.extend(_check_cors(target_url, response))
        findings.extend(_check_info_disclosure(target_url, response))
        findings.extend(await _check_sensitive_paths(client, target_url))

    # SSL checks (separate - uses socket, not httpx)
    findings.extend(_check_ssl(target_url))

    logger.info(f"Quick scan complete: {len(findings)} findings")
    return findings


def _check_security_headers(target_url: str, response: httpx.Response) -> list[dict]:
    """Check for missing or misconfigured security headers."""
    findings = []
    headers = response.headers

    # Required security headers and their checks
    header_checks = [
        {
            "header": "content-security-policy",
            "finding_type": "missing_csp",
            "severity": "medium",
            "title": "Missing Content-Security-Policy Header",
            "description": "The Content-Security-Policy header is not set. CSP helps prevent XSS, clickjacking, and other code injection attacks.",
            "remediation": "Add a Content-Security-Policy header. Start with: Content-Security-Policy: default-src 'self'; script-src 'self'",
            "reference_urls": ["https://developer.mozilla.org/en-US/docs/Web/HTTP/CSP"],
        },
        {
            "header": "strict-transport-security",
            "finding_type": "missing_hsts",
            "severity": "high" if target_url.startswith("https") else "info",
            "title": "Missing Strict-Transport-Security Header",
            "description": "HSTS is not enabled. This allows protocol downgrade attacks and cookie hijacking.",
            "remediation": "Add: Strict-Transport-Security: max-age=31536000; includeSubDomains",
            "reference_urls": ["https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Strict-Transport-Security"],
        },
        {
            "header": "x-frame-options",
            "finding_type": "missing_x_frame_options",
            "severity": "medium",
            "title": "Missing X-Frame-Options Header",
            "description": "X-Frame-Options is not set. The site may be vulnerable to clickjacking attacks.",
            "remediation": "Add: X-Frame-Options: DENY or X-Frame-Options: SAMEORIGIN",
            "reference_urls": ["https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/X-Frame-Options"],
        },
        {
            "header": "x-content-type-options",
            "finding_type": "missing_x_content_type_options",
            "severity": "low",
            "title": "Missing X-Content-Type-Options Header",
            "description": "X-Content-Type-Options is not set. Browsers may MIME-sniff responses, enabling XSS via content type confusion.",
            "remediation": "Add: X-Content-Type-Options: nosniff",
            "reference_urls": ["https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/X-Content-Type-Options"],
        },
        {
            "header": "referrer-policy",
            "finding_type": "missing_referrer_policy",
            "severity": "low",
            "title": "Missing Referrer-Policy Header",
            "description": "Referrer-Policy is not set. The full URL may be leaked to third parties via the Referer header.",
            "remediation": "Add: Referrer-Policy: strict-origin-when-cross-origin",
            "reference_urls": ["https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Referrer-Policy"],
        },
        {
            "header": "permissions-policy",
            "finding_type": "missing_permissions_policy",
            "severity": "low",
            "title": "Missing Permissions-Policy Header",
            "description": "Permissions-Policy (formerly Feature-Policy) is not set. Browser features like camera, microphone, geolocation are not restricted.",
            "remediation": "Add: Permissions-Policy: camera=(), microphone=(), geolocation=()",
            "reference_urls": ["https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Permissions-Policy"],
        },
    ]

    for check in header_checks:
        header_value = headers.get(check["header"])
        if not header_value:
            findings.append(
                {
                    "severity": check["severity"],
                    "finding_type": check["finding_type"],
                    "category": "misconfiguration",
                    "title": check["title"],
                    "description": check["description"],
                    "url": target_url,
                    "evidence": f"Header '{check['header']}' is missing from response",
                    "remediation": check["remediation"],
                    "reference_urls": check["reference_urls"],
                    "finding_hash": _make_hash("quick", check["finding_type"], target_url),
                }
            )

    # Check HSTS max-age if present
    hsts = headers.get("strict-transport-security", "")
    if hsts:
        try:
            max_age_str = [p.strip() for p in hsts.split(";") if "max-age" in p.lower()]
            if max_age_str:
                max_age = int(max_age_str[0].split("=")[1])
                if max_age < 31536000:  # Less than 1 year
                    findings.append(
                        {
                            "severity": "low",
                            "finding_type": "weak_hsts",
                            "category": "misconfiguration",
                            "title": "Weak HSTS Max-Age",
                            "description": f"HSTS max-age is {max_age} seconds ({max_age // 86400} days). Recommended minimum is 31536000 (1 year).",
                            "url": target_url,
                            "evidence": f"Strict-Transport-Security: {hsts}",
                            "remediation": "Increase max-age to at least 31536000 (1 year)",
                            "reference_urls": ["https://hstspreload.org/"],
                            "finding_hash": _make_hash("quick", "weak_hsts", target_url),
                        }
                    )
        except (ValueError, IndexError):
            pass

    return findings


def _check_cookie_security(target_url: str, response: httpx.Response) -> list[dict]:
    """Check Set-Cookie headers for security flags."""
    findings = []
    is_https = target_url.startswith("https")

    set_cookie_headers = response.headers.get_list("set-cookie") if hasattr(response.headers, "get_list") else []
    # httpx uses multi-dict; get all set-cookie values
    if not set_cookie_headers:
        set_cookie_headers = [v for k, v in response.headers.multi_items() if k.lower() == "set-cookie"]

    for cookie_str in set_cookie_headers:
        cookie_lower = cookie_str.lower()
        cookie_name = cookie_str.split("=")[0].strip() if "=" in cookie_str else "unknown"

        if "httponly" not in cookie_lower:
            findings.append(
                {
                    "severity": "medium",
                    "finding_type": "cookie_no_httponly",
                    "category": "misconfiguration",
                    "title": f"Cookie '{cookie_name}' Missing HttpOnly Flag",
                    "description": f"Cookie '{cookie_name}' does not have the HttpOnly flag. It can be accessed via JavaScript, enabling XSS-based session theft.",
                    "url": target_url,
                    "evidence": f"Set-Cookie: {cookie_str[:200]}",
                    "remediation": "Add the HttpOnly flag to prevent JavaScript access",
                    "reference_urls": ["https://owasp.org/www-community/HttpOnly"],
                    "finding_hash": _make_hash("quick", "cookie_no_httponly", target_url, cookie_name),
                }
            )

        if is_https and "secure" not in cookie_lower:
            findings.append(
                {
                    "severity": "high",
                    "finding_type": "cookie_no_secure",
                    "category": "misconfiguration",
                    "title": f"Cookie '{cookie_name}' Missing Secure Flag",
                    "description": f"Cookie '{cookie_name}' on HTTPS site does not have the Secure flag. It may be transmitted over unencrypted HTTP.",
                    "url": target_url,
                    "evidence": f"Set-Cookie: {cookie_str[:200]}",
                    "remediation": "Add the Secure flag to ensure cookies are only sent over HTTPS",
                    "reference_urls": ["https://owasp.org/www-community/controls/SecureCookieAttribute"],
                    "finding_hash": _make_hash("quick", "cookie_no_secure", target_url, cookie_name),
                }
            )

        if "samesite" not in cookie_lower:
            findings.append(
                {
                    "severity": "medium",
                    "finding_type": "cookie_no_samesite",
                    "category": "misconfiguration",
                    "title": f"Cookie '{cookie_name}' Missing SameSite Attribute",
                    "description": f"Cookie '{cookie_name}' does not set SameSite attribute. It may be sent in cross-site requests, enabling CSRF attacks.",
                    "url": target_url,
                    "evidence": f"Set-Cookie: {cookie_str[:200]}",
                    "remediation": "Add SameSite=Strict or SameSite=Lax attribute",
                    "reference_urls": ["https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Set-Cookie/SameSite"],
                    "finding_hash": _make_hash("quick", "cookie_no_samesite", target_url, cookie_name),
                }
            )

    return findings


def _check_cors(target_url: str, response: httpx.Response) -> list[dict]:
    """Check for permissive CORS configuration."""
    findings = []

    acao = response.headers.get("access-control-allow-origin", "")

    if acao == "*":
        acac = response.headers.get("access-control-allow-credentials", "").lower()
        severity = "high" if acac == "true" else "medium"

        findings.append(
            {
                "severity": severity,
                "finding_type": "cors_wildcard",
                "category": "misconfiguration",
                "title": "Permissive CORS: Wildcard Origin Allowed",
                "description": "Access-Control-Allow-Origin is set to '*', allowing any website to make cross-origin requests."
                + (
                    " Combined with Allow-Credentials: true, this could leak authenticated data."
                    if acac == "true"
                    else ""
                ),
                "url": target_url,
                "evidence": f"Access-Control-Allow-Origin: {acao}"
                + (f", Access-Control-Allow-Credentials: {acac}" if acac else ""),
                "remediation": "Restrict CORS to specific trusted origins instead of using wildcard",
                "reference_urls": ["https://developer.mozilla.org/en-US/docs/Web/HTTP/CORS"],
                "finding_hash": _make_hash("quick", "cors_wildcard", target_url),
            }
        )

    return findings


def _check_info_disclosure(target_url: str, response: httpx.Response) -> list[dict]:
    """Check for information disclosure in headers."""
    findings = []

    # Server header with version info
    server = response.headers.get("server", "")
    if server and any(c.isdigit() for c in server):
        findings.append(
            {
                "severity": "low",
                "finding_type": "server_version_disclosure",
                "category": "exposure",
                "title": "Server Version Disclosed",
                "description": f"The Server header reveals version information: '{server}'. This helps attackers identify known vulnerabilities.",
                "url": target_url,
                "evidence": f"Server: {server}",
                "remediation": "Remove or genericize the Server header to hide version information",
                "reference_urls": [
                    "https://owasp.org/www-project-web-security-testing-guide/latest/4-Web_Application_Security_Testing/01-Information_Gathering/02-Fingerprinting_Web_Server"
                ],
                "finding_hash": _make_hash("quick", "server_version_disclosure", target_url),
            }
        )

    # X-Powered-By header
    powered_by = response.headers.get("x-powered-by", "")
    if powered_by:
        findings.append(
            {
                "severity": "low",
                "finding_type": "x_powered_by_disclosure",
                "category": "exposure",
                "title": "Technology Stack Disclosed via X-Powered-By",
                "description": f"X-Powered-By header reveals: '{powered_by}'. This helps attackers target framework-specific vulnerabilities.",
                "url": target_url,
                "evidence": f"X-Powered-By: {powered_by}",
                "remediation": "Remove the X-Powered-By header",
                "reference_urls": [],
                "finding_hash": _make_hash("quick", "x_powered_by_disclosure", target_url),
            }
        )

    # X-AspNet-Version or X-AspNetMvc-Version
    for header_name in ["x-aspnet-version", "x-aspnetmvc-version"]:
        val = response.headers.get(header_name, "")
        if val:
            findings.append(
                {
                    "severity": "low",
                    "finding_type": "aspnet_version_disclosure",
                    "category": "exposure",
                    "title": f"ASP.NET Version Disclosed via {header_name}",
                    "description": f"Header reveals ASP.NET version: '{val}'.",
                    "url": target_url,
                    "evidence": f"{header_name}: {val}",
                    "remediation": f"Remove the {header_name} header",
                    "reference_urls": [],
                    "finding_hash": _make_hash("quick", "aspnet_version_disclosure", target_url, header_name),
                }
            )

    return findings


async def _check_sensitive_paths(client: httpx.AsyncClient, target_url: str) -> list[dict]:
    """Probe common sensitive paths for information exposure."""
    findings = []
    parsed = urlparse(target_url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    sensitive_paths = [
        {"path": "/.env", "description": "Environment configuration file", "severity": "critical"},
        {"path": "/.git/config", "description": "Git repository configuration", "severity": "high"},
        {"path": "/server-info", "description": "Apache server information", "severity": "medium"},
        {"path": "/server-status", "description": "Apache server status", "severity": "medium"},
        {"path": "/phpinfo.php", "description": "PHP information page", "severity": "high"},
        {"path": "/wp-config.php.bak", "description": "WordPress config backup", "severity": "critical"},
        {"path": "/debug", "description": "Debug endpoint", "severity": "medium"},
        {"path": "/.DS_Store", "description": "macOS directory metadata", "severity": "low"},
        {"path": "/robots.txt", "description": "Robots exclusion file", "severity": "info"},
        {"path": "/.well-known/security.txt", "description": "Security contact information", "severity": "info"},
    ]

    for probe in sensitive_paths:
        probe_url = f"{base}{probe['path']}"
        try:
            resp = await client.get(probe_url, follow_redirects=False)

            # robots.txt and security.txt: report as info if present
            if probe["path"] in ["/robots.txt", "/.well-known/security.txt"]:
                if resp.status_code == 200:
                    body_preview = resp.text[:200] if resp.text else ""
                    # For security.txt, report as info (it's a good practice to have one)
                    if probe["path"] == "/.well-known/security.txt":
                        findings.append(
                            {
                                "severity": "info",
                                "finding_type": "security_txt_found",
                                "category": "exposure",
                                "title": "security.txt Found (Good Practice)",
                                "description": "A security.txt file was found, providing security contact information.",
                                "url": probe_url,
                                "evidence": body_preview,
                                "remediation": "No action needed - this is a security best practice",
                                "reference_urls": ["https://securitytxt.org/"],
                                "finding_hash": _make_hash("quick", "security_txt_found", target_url),
                            }
                        )
                    else:
                        # Check robots.txt for sensitive paths
                        if any(
                            keyword in resp.text.lower()
                            for keyword in ["admin", "api", "internal", "private", "secret"]
                        ):
                            findings.append(
                                {
                                    "severity": "info",
                                    "finding_type": "robots_sensitive_paths",
                                    "category": "exposure",
                                    "title": "robots.txt Reveals Sensitive Paths",
                                    "description": "robots.txt contains references to potentially sensitive paths.",
                                    "url": probe_url,
                                    "evidence": body_preview,
                                    "remediation": "Review if disallowed paths should be public knowledge",
                                    "reference_urls": [],
                                    "finding_hash": _make_hash("quick", "robots_sensitive_paths", target_url),
                                }
                            )
                continue

            # For other sensitive files - report if accessible (2xx status)
            if 200 <= resp.status_code < 300:
                body_preview = resp.text[:500] if resp.text else ""
                # Skip if it looks like a custom 404 page
                if resp.status_code == 200 and len(resp.text) < 50:
                    continue
                # Additional check: .env files should have KEY=VALUE patterns
                if probe["path"] == "/.env" and "=" not in body_preview:
                    continue
                # .git/config should contain [core] section
                if probe["path"] == "/.git/config" and "[core]" not in body_preview:
                    continue

                findings.append(
                    {
                        "severity": probe["severity"],
                        "finding_type": "sensitive_path_exposed",
                        "category": "exposure",
                        "title": f"Sensitive File Exposed: {probe['path']}",
                        "description": f"{probe['description']} is publicly accessible at {probe_url}.",
                        "url": probe_url,
                        "evidence": f"HTTP {resp.status_code} - {body_preview[:200]}",
                        "remediation": f"Block access to {probe['path']} via web server configuration",
                        "reference_urls": [],
                        "finding_hash": _make_hash("quick", "sensitive_path_exposed", target_url, probe["path"]),
                    }
                )
        except httpx.HTTPError:
            continue  # Connection errors are expected for most probes

    return findings


def _check_ssl(target_url: str) -> list[dict]:
    """Check SSL/TLS certificate and configuration."""
    findings = []
    parsed = urlparse(target_url)

    if parsed.scheme != "https":
        findings.append(
            {
                "severity": "high",
                "finding_type": "no_https",
                "category": "misconfiguration",
                "title": "Site Not Using HTTPS",
                "description": "The target URL uses HTTP instead of HTTPS. All traffic is transmitted in plaintext.",
                "url": target_url,
                "evidence": f"URL scheme: {parsed.scheme}",
                "remediation": "Enable HTTPS with a valid TLS certificate",
                "reference_urls": ["https://letsencrypt.org/"],
                "finding_hash": _make_hash("quick", "no_https", target_url),
            }
        )
        return findings

    hostname = parsed.hostname
    port = parsed.port or 443

    try:
        context = ssl.create_default_context()
        with socket.create_connection((hostname, port), timeout=10) as sock:
            with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert = ssock.getpeercert()
                protocol = ssock.version()

                # Check certificate expiry
                if cert:
                    not_after_str = cert.get("notAfter", "")
                    if not_after_str:
                        try:
                            not_after = datetime.strptime(not_after_str, "%b %d %H:%M:%S %Y %Z")
                            days_until_expiry = (not_after - datetime.utcnow()).days

                            if days_until_expiry < 0:
                                findings.append(
                                    {
                                        "severity": "critical",
                                        "finding_type": "ssl_cert_expired",
                                        "category": "misconfiguration",
                                        "title": "SSL Certificate Expired",
                                        "description": f"The SSL certificate expired {abs(days_until_expiry)} days ago on {not_after_str}.",
                                        "url": target_url,
                                        "evidence": f"Certificate notAfter: {not_after_str}",
                                        "remediation": "Renew the SSL certificate immediately",
                                        "reference_urls": [],
                                        "finding_hash": _make_hash("quick", "ssl_cert_expired", target_url),
                                    }
                                )
                            elif days_until_expiry < 30:
                                findings.append(
                                    {
                                        "severity": "medium",
                                        "finding_type": "ssl_cert_expiring_soon",
                                        "category": "misconfiguration",
                                        "title": "SSL Certificate Expiring Soon",
                                        "description": f"The SSL certificate expires in {days_until_expiry} days (on {not_after_str}).",
                                        "url": target_url,
                                        "evidence": f"Certificate notAfter: {not_after_str}",
                                        "remediation": "Renew the SSL certificate before expiry",
                                        "reference_urls": [],
                                        "finding_hash": _make_hash("quick", "ssl_cert_expiring_soon", target_url),
                                    }
                                )
                        except ValueError:
                            pass

                # Check TLS version
                if protocol and protocol in ("TLSv1", "TLSv1.1"):
                    findings.append(
                        {
                            "severity": "high",
                            "finding_type": "outdated_tls",
                            "category": "misconfiguration",
                            "title": f"Outdated TLS Version: {protocol}",
                            "description": f"Server supports {protocol} which is deprecated and insecure.",
                            "url": target_url,
                            "evidence": f"TLS version: {protocol}",
                            "remediation": "Disable TLS 1.0 and 1.1, use TLS 1.2 or 1.3 only",
                            "reference_urls": ["https://datatracker.ietf.org/doc/rfc8996/"],
                            "finding_hash": _make_hash("quick", "outdated_tls", target_url),
                        }
                    )

    except ssl.SSLCertVerificationError as e:
        findings.append(
            {
                "severity": "high",
                "finding_type": "ssl_cert_invalid",
                "category": "misconfiguration",
                "title": "SSL Certificate Validation Failed",
                "description": f"SSL certificate verification failed: {e}",
                "url": target_url,
                "evidence": str(e),
                "remediation": "Install a valid SSL certificate from a trusted CA",
                "reference_urls": [],
                "finding_hash": _make_hash("quick", "ssl_cert_invalid", target_url),
            }
        )
    except (TimeoutError, ConnectionRefusedError, OSError) as e:
        logger.warning(f"SSL check failed for {target_url}: {e}")

    return findings
