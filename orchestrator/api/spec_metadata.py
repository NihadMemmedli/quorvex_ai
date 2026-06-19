from typing import Any


def clean_metadata_tags(tags: Any, *, lowercase: bool = False) -> list[str]:
    """Normalize seed/user tags while preserving first-seen ordering."""
    if not isinstance(tags, list):
        return []

    cleaned: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        if not isinstance(tag, str):
            continue
        value = tag.strip()
        if not value:
            continue
        if lowercase:
            value = value.lower()
        key = value.casefold()
        if key in seen:
            continue
        cleaned.append(value)
        seen.add(key)
    return cleaned


def merge_metadata_tags(existing_tags: list[str], seed_tags: list[str]) -> list[str]:
    merged = clean_metadata_tags(existing_tags)
    seen = {tag.casefold() for tag in merged}
    for tag in clean_metadata_tags(seed_tags, lowercase=True):
        if tag.casefold() in seen:
            continue
        merged.append(tag)
        seen.add(tag.casefold())
    return merged
