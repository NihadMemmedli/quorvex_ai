"""
Test Credentials Management

Provides encrypted storage and retrieval of test credentials (like LOGIN_USERNAME,
LOGIN_PASSWORD) that are used in spec files via {{PLACEHOLDER}} syntax.

Credentials are stored encrypted in Project.settings.credentials and merged with
.env values at runtime, with project credentials taking precedence.
"""

import base64
import hashlib
import logging
import os

from cryptography.fernet import Fernet, InvalidToken
from sqlmodel import Session

from .models_db import Project
from .security import JWT_SECRET_KEY

logger = logging.getLogger(__name__)


def _get_fernet_key() -> bytes:
    """
    Derive a Fernet-compatible key from JWT_SECRET_KEY.

    Fernet requires exactly 32 url-safe base64-encoded bytes.
    We use SHA-256 to derive a consistent key from the JWT secret.
    """
    # Use SHA-256 to get a 32-byte key from any length secret
    key_bytes = hashlib.sha256(JWT_SECRET_KEY.encode()).digest()
    # Fernet wants base64-encoded key
    return base64.urlsafe_b64encode(key_bytes)


def _get_fernet() -> Fernet:
    """Get a Fernet instance for encryption/decryption."""
    return Fernet(_get_fernet_key())


def encrypt_credential(value: str) -> str:
    """
    Encrypt a credential value using Fernet symmetric encryption.

    Args:
        value: The plaintext credential value

    Returns:
        Base64-encoded encrypted string
    """
    if not value:
        return ""

    fernet = _get_fernet()
    encrypted = fernet.encrypt(value.encode())
    return encrypted.decode()


def decrypt_credential(encrypted: str) -> str:
    """
    Decrypt an encrypted credential value.

    Args:
        encrypted: The encrypted credential string

    Returns:
        The plaintext credential value, or empty string if decryption fails
    """
    if not encrypted:
        return ""

    try:
        fernet = _get_fernet()
        decrypted = fernet.decrypt(encrypted.encode())
        return decrypted.decode()
    except InvalidToken:
        logger.warning("Failed to decrypt credential - invalid token")
        return ""
    except Exception as e:
        logger.warning(f"Failed to decrypt credential: {e}")
        return ""


def mask_credential(value: str) -> str:
    """
    Mask a credential value for display, showing only last 4 characters.

    Examples:
        "secretpassword123" -> "****3"
        "abc" -> "****" (too short)
        "" -> ""

    Args:
        value: The plaintext credential value

    Returns:
        Masked string like "****1234"
    """
    if not value:
        return ""

    if len(value) <= 4:
        return "****"

    return "****" + value[-4:]


def get_project_credentials(project_id: str, session: Session) -> dict[str, str]:
    """
    Get decrypted credentials from a project's settings.

    Args:
        project_id: The project ID to get credentials for
        session: Database session

    Returns:
        Dict of credential key -> decrypted value
    """
    project = session.get(Project, project_id)
    if not project or not project.settings:
        return {}

    encrypted_creds = project.settings.get("credentials", {})
    if not encrypted_creds:
        return {}

    decrypted = {}
    for key, encrypted_value in encrypted_creds.items():
        decrypted_value = decrypt_credential(encrypted_value)
        if decrypted_value:
            decrypted[key] = decrypted_value

    return decrypted


def get_env_credentials() -> dict[str, str]:
    """
    Get credential values from environment variables (.env file).

    Looks for common credential patterns like:
    - LOGIN_USERNAME, LOGIN_PASSWORD
    - TEST_USERNAME, TEST_PASSWORD
    - Any *_USERNAME, *_PASSWORD pattern

    Returns:
        Dict of credential key -> value from environment
    """
    credentials = {}

    # Common credential environment variable patterns
    env_patterns = [
        "LOGIN_USERNAME",
        "LOGIN_PASSWORD",
        "TEST_USERNAME",
        "TEST_PASSWORD",
        "ADMIN_USERNAME",
        "ADMIN_PASSWORD",
        "USER_EMAIL",
        "USER_PASSWORD",
    ]

    for key in env_patterns:
        value = os.environ.get(key)
        if value:
            credentials[key] = value

    # Also look for any *_USERNAME, *_PASSWORD, *_EMAIL, *_TOKEN patterns
    for key, value in os.environ.items():
        if value and any(
            pattern in key for pattern in ["_USERNAME", "_PASSWORD", "_EMAIL", "_TOKEN", "_API_KEY", "_SECRET"]
        ):
            # Skip internal API keys
            if key in ["ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY", "JWT_SECRET_KEY"]:
                continue
            credentials[key] = value

    return credentials


def get_merged_credentials(project_id: str, session: Session) -> dict[str, str]:
    """
    Get merged credentials from project settings and environment.

    Project credentials take precedence over .env values.

    Args:
        project_id: The project ID
        session: Database session

    Returns:
        Dict of credential key -> value (project overrides env)
    """
    # Start with environment credentials
    merged = get_env_credentials()

    # Override with project-specific credentials
    if project_id and project_id != "default":
        project_creds = get_project_credentials(project_id, session)
        merged.update(project_creds)
    else:
        # For default project, still check for credentials
        project_creds = get_project_credentials("default", session)
        merged.update(project_creds)

    return merged


def set_project_credential(project_id: str, key: str, value: str, session: Session) -> bool:
    """
    Set (add or update) a credential for a project.

    Args:
        project_id: The project ID
        key: The credential key (e.g., "LOGIN_PASSWORD")
        value: The plaintext credential value
        session: Database session

    Returns:
        True if successful
    """
    project = session.get(Project, project_id)
    if not project:
        return False

    # Initialize settings if needed
    if not project.settings:
        project.settings = {}

    # Initialize credentials dict if needed
    if "credentials" not in project.settings:
        project.settings["credentials"] = {}

    # Encrypt and store
    encrypted_value = encrypt_credential(value)
    project.settings["credentials"][key] = encrypted_value

    # Mark settings as modified (SQLModel/SQLAlchemy needs this for JSON columns)
    from sqlalchemy.orm.attributes import flag_modified

    flag_modified(project, "settings")

    session.add(project)
    session.commit()

    return True


def delete_project_credential(project_id: str, key: str, session: Session) -> bool:
    """
    Delete a credential from a project.

    Args:
        project_id: The project ID
        key: The credential key to delete
        session: Database session

    Returns:
        True if deleted, False if not found
    """
    project = session.get(Project, project_id)
    if not project or not project.settings:
        return False

    credentials = project.settings.get("credentials", {})
    if key not in credentials:
        return False

    del project.settings["credentials"][key]

    # Mark settings as modified
    from sqlalchemy.orm.attributes import flag_modified

    flag_modified(project, "settings")

    session.add(project)
    session.commit()

    return True


def list_project_credentials(project_id: str, session: Session, include_env: bool = True) -> list[dict[str, str]]:
    """
    List all credentials for a project with masked values.

    Args:
        project_id: The project ID
        session: Database session
        include_env: Whether to include .env credentials in the list

    Returns:
        List of dicts with keys: key, masked_value, source
    """
    result = []
    seen_keys = set()

    # Get project credentials first (they take precedence)
    project = session.get(Project, project_id)
    if project and project.settings:
        encrypted_creds = project.settings.get("credentials", {})
        for key, encrypted_value in encrypted_creds.items():
            decrypted = decrypt_credential(encrypted_value)
            result.append({"key": key, "masked_value": mask_credential(decrypted), "source": "project"})
            seen_keys.add(key)

    # Add .env credentials that aren't overridden
    if include_env:
        env_creds = get_env_credentials()
        for key, value in env_creds.items():
            if key not in seen_keys:
                result.append({"key": key, "masked_value": mask_credential(value), "source": "env"})

    # Sort by key name
    result.sort(key=lambda x: x["key"])

    return result
