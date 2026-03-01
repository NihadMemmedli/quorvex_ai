from urllib.parse import urlparse


def derive_project_id_from_url(url: str) -> str:
    """
    Derive a project_id from a URL using standardized logic.

    The project_id should be the hostname to ensure consistency.
    Examples:
        https://my.gov.az -> my.gov.az
        https://the-internet.herokuapp.com/checkboxes -> the-internet.herokuapp.com
        http://localhost:3000 -> localhost
    """
    if not url:
        return "default"

    try:
        parsed = urlparse(url)
        hostname = parsed.netloc or parsed.path

        # Remove port number if present
        hostname = hostname.split(":")[0]

        # Remove www. prefix for cleaner IDs, but keep structure
        if hostname.startswith("www."):
            hostname = hostname[4:]

        return hostname.lower()
    except Exception:
        return "default"
