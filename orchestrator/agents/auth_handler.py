"""
Authentication Handler for Exploratory Testing Agent.

Supports three authentication modes:
1. credentials - Agent fills login form with username/password
2. session - Agent uses existing cookies/localStorage
3. none - No authentication required
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any


class AuthHandler:
    """
    Handles authentication for exploratory testing.

    Supports:
    - Credentials-based login (agent fills form)
    - Session-based auth (uses existing cookies/storage)
    - No authentication (public pages)
    """

    def __init__(self, storage_dir: Path | None = None):
        """
        Initialize AuthHandler.

        Args:
            storage_dir: Directory to store session data
        """
        self.storage_dir = storage_dir or Path("orchestrator/sessions")
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    async def authenticate(self, agent, auth_config: dict[str, Any], base_url: str) -> dict[str, Any]:
        """
        Perform authentication based on config type.

        Args:
            agent: The agent instance (for browser access)
            auth_config: Authentication configuration
            base_url: Base URL of the application

        Returns:
            Dict with authentication result
        """
        auth_type = auth_config.get("type", "none")

        if auth_type == "credentials":
            return await self._login_with_credentials(agent, auth_config, base_url)
        elif auth_type == "session":
            return await self._load_session(agent, auth_config, base_url)
        else:
            return {"success": True, "type": "none", "message": "No authentication required"}

    async def _login_with_credentials(self, agent, auth_config: dict[str, Any], base_url: str) -> dict[str, Any]:
        """
        Login by filling the login form with credentials.

        The agent will:
        1. Navigate to login URL
        2. Fill username/password fields
        3. Click login button
        4. Verify successful login
        """
        login_url = auth_config.get("login_url", "/login")
        credentials = auth_config.get("credentials", {})
        username = credentials.get("username", "")
        password = credentials.get("password", "")

        if not username or not password:
            return {"success": False, "type": "credentials", "error": "Missing username or password"}

        # Construct full URL
        full_login_url = f"{base_url}{login_url}" if not login_url.startswith("http") else login_url

        # Instructions for the agent to perform login
        login_instructions = f"""
AUTHENTICATION REQUIRED:
1. Navigate to: {full_login_url}
2. Find and fill the username field with: {username}
3. Find and fill the password field with: [PROVIDED_PASSWORD]
4. Click the login/submit button
5. Wait for navigation/redirect
6. Verify you are logged in (look for user menu, profile link, etc.)

IMPORTANT: After successful login, proceed with the exploration task.

The password will be provided in the test_data as PASSWORD.
"""

        return {
            "success": True,
            "type": "credentials",
            "instructions": login_instructions,
            "username": username,
            "login_url": full_login_url,
        }

    async def _load_session(self, agent, auth_config: dict[str, Any], base_url: str) -> dict[str, Any]:
        """
        Load existing session from cookies/localStorage.

        Session data can be provided:
        1. Directly in auth_config (cookies + storage)
        2. From a previously saved session file
        """
        # Check if session data is provided directly
        if "cookies" in auth_config:
            return self._load_session_from_config(auth_config)

        # Check if session_id is provided to load from storage
        session_id = auth_config.get("session_id")
        if session_id:
            return await self._load_session_from_file(session_id)

        return {
            "success": False,
            "type": "session",
            "error": "No session data provided. Include 'cookies' and 'storage' in config, or provide 'session_id'",
        }

    def _load_session_from_config(self, auth_config: dict[str, Any]) -> dict[str, Any]:
        """Load session from config data."""
        cookies = auth_config.get("cookies", [])
        storage = auth_config.get("storage", {})

        return {
            "success": True,
            "type": "session",
            "cookies": cookies,
            "storage": storage,
            "instructions": """
SESSION AUTHENTICATION:
- Cookies and localStorage data will be loaded before exploration
- You are already authenticated
- Proceed directly with exploration

To load the session:
1. Navigate to the base URL
2. Apply all cookies to the browser context
3. Load localStorage data
4. Verify authentication (check for user-specific elements)
5. Proceed with exploration
""",
        }

    async def _load_session_from_file(self, session_id: str) -> dict[str, Any]:
        """Load session from stored file."""
        session_file = self.storage_dir / f"{session_id}.json"

        if not session_file.exists():
            return {"success": False, "type": "session", "error": f"Session file not found: {session_file}"}

        try:
            session_data = json.loads(session_file.read_text())
            return {
                "success": True,
                "type": "session",
                "session_id": session_id,
                "cookies": session_data.get("cookies", []),
                "storage": session_data.get("storage", {}),
                "instructions": f"""
SESSION AUTHENTICATION:
- Loading session from file: {session_id}
- Session created at: {session_data.get("created_at")}
- Proceed directly with exploration after loading session
""",
            }
        except Exception as e:
            return {"success": False, "type": "session", "error": f"Failed to load session: {str(e)}"}

    async def save_session(self, session_id: str, cookies: list[dict], storage: dict[str, Any]) -> dict[str, Any]:
        """
        Save session data for future use.

        Args:
            session_id: Unique identifier for the session
            cookies: List of cookie objects
            storage: localStorage data

        Returns:
            Dict with save result
        """
        session_data = {
            "session_id": session_id,
            "created_at": datetime.now().isoformat(),
            "cookies": cookies,
            "storage": storage,
        }

        session_file = self.storage_dir / f"{session_id}.json"

        try:
            session_file.write_text(json.dumps(session_data, indent=2))
            return {"success": True, "session_id": session_id, "file": str(session_file)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_sessions(self) -> list[dict[str, Any]]:
        """List all saved sessions."""
        sessions = []

        for session_file in self.storage_dir.glob("*.json"):
            try:
                session_data = json.loads(session_file.read_text())
                sessions.append(
                    {
                        "session_id": session_data.get("session_id", session_file.stem),
                        "created_at": session_data.get("created_at"),
                        "file": str(session_file),
                    }
                )
            except Exception:
                pass

        return sorted(sessions, key=lambda x: x.get("created_at", ""), reverse=True)

    def delete_session(self, session_id: str) -> bool:
        """Delete a saved session."""
        session_file = self.storage_dir / f"{session_id}.json"

        if session_file.exists():
            session_file.unlink()
            return True
        return False


# Helper functions for agent prompt building


def build_auth_prompt_section(auth_config: dict[str, Any], auth_handler_result: dict[str, Any]) -> str:
    """
    Build the authentication section for the agent prompt.

    Args:
        auth_config: Original auth configuration
        auth_handler_result: Result from AuthHandler.authenticate()

    Returns:
        String section for agent prompt
    """
    if not auth_handler_result.get("success"):
        return "\nAUTHENTICATION: Skipped (configuration error)\n"

    auth_type = auth_handler_result.get("type")
    instructions = auth_handler_result.get("instructions", "")

    if auth_type == "credentials":
        return f"""
{instructions}

TEST DATA:
- PASSWORD: Use the password from your test_data configuration

IMPORTANT: Complete authentication BEFORE starting exploration.
"""

    elif auth_type == "session":
        return f"""
{instructions}

To apply the session:
1. First navigate to the base URL
2. Then use browser context methods to apply cookies and localStorage
3. Verify authentication was successful
4. Proceed with exploration

Session data:
- Cookies: {len(auth_handler_result.get("cookies", []))} cookies provided
- Storage keys: {list(auth_handler_result.get("storage", {}).keys())}
"""

    else:  # none
        return "\nAUTHENTICATION: Not required - proceed with exploration\n"


def get_auth_test_data(auth_config: dict[str, Any]) -> dict[str, str]:
    """
    Get test data values needed for authentication.

    Args:
        auth_config: Authentication configuration

    Returns:
        Dict with test data values
    """
    test_data = {}

    if auth_config.get("type") == "credentials":
        credentials = auth_config.get("credentials", {})
        test_data["PASSWORD"] = credentials.get("password", "")
        test_data["USERNAME"] = credentials.get("username", "")

    return test_data
