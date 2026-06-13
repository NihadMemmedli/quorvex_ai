import re
import unicodedata


def slugify(value: str, allow_unicode: bool = False) -> str:
    """
    Convert to ASCII if 'allow_unicode' is False. Convert spaces or repeated
    dashes to single dashes. Remove characters that aren't alphanumerics,
    underscores, or hyphens. Convert to lowercase. Also strip leading and
    trailing whitespace, dashes, and underscores.
    """
    value = str(value)
    if allow_unicode:
        value = unicodedata.normalize("NFKC", value)
    else:
        value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^\w\s-]", "", value.lower())
    return re.sub(r"[-\s]+", "-", value).strip("-_")


def clean_extracted_url(value: str | None) -> str | None:
    """Clean URL text captured from markdown or prose."""
    if value is None:
        return None
    cleaned = str(value).strip().strip("`'\"")
    cleaned = cleaned.rstrip("`'\".,;:)>")
    return cleaned or None
