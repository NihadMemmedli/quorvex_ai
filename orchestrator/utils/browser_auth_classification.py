"""Helpers for deciding when saved browser auth should be suppressed."""

from __future__ import annotations

import re


_LOGIN_LOGOUT_RE = re.compile(
    r"\b("
    r"log\s*in|login|sign\s*in|signin|sign-in|"
    r"log\s*out|logout|sign\s*out|signout|sign-out"
    r")\b",
    re.IGNORECASE,
)

_AUTHENTICATED_PRECONDITION_RE = re.compile(
    r"\b("
    r"already\s+(?:logged\s*in|authenticated|signed\s*in)|"
    r"(?:logged\s*in|authenticated|signed\s*in)\s+user|"
    r"user\s+is\s+(?:logged\s*in|authenticated|signed\s*in)|"
    r"requires\s+(?:login|authentication|authenticated\s+session)|"
    r"with\s+(?:a\s+)?(?:saved\s+)?(?:authenticated\s+)?session"
    r")\b",
    re.IGNORECASE,
)

_NEGATIVE_AUTH_RE = re.compile(
    r"\b("
    r"unauthenticated|not\s+(?:logged\s*in|authenticated|signed\s*in)|"
    r"anonymous|guest|session\s+expired|invalid\s+session|auth(?:entication)?\s+failure"
    r")\b",
    re.IGNORECASE,
)


def is_login_logout_spec(spec_name: str, spec_content: str) -> bool:
    """Return true only for specs that exercise login/logout or denied auth flows.

    Saved auth should stay enabled for ordinary authenticated-user scenarios even
    when titles contain broad words like "auth", "authenticated", or "mygov-id".
    """

    title_context = f"{spec_name}\n{spec_content[:2000]}"
    if _AUTHENTICATED_PRECONDITION_RE.search(title_context):
        return False
    return bool(_LOGIN_LOGOUT_RE.search(title_context) or _NEGATIVE_AUTH_RE.search(title_context))
