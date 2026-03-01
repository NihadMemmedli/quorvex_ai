"""
SDK Configuration - Configures Claude Agent SDK buffer size.
Must be imported BEFORE any SDK query calls.
"""

import warnings

SDK_BUFFER_SIZE_MB = 50
SDK_BUFFER_SIZE_BYTES = SDK_BUFFER_SIZE_MB * 1024 * 1024
_configured = False


def configure_sdk_buffer():
    """Increase SDK buffer size for large browser snapshots. Idempotent."""
    global _configured

    if _configured:
        return False

    try:
        import claude_agent_sdk._internal.transport.subprocess_cli as transport

        transport._DEFAULT_MAX_BUFFER_SIZE = SDK_BUFFER_SIZE_BYTES
        _configured = True
        return True
    except (ImportError, AttributeError) as e:
        warnings.warn(f"SDK buffer config failed (SDK version change?): {e}", RuntimeWarning, stacklevel=2)
        return False
    except Exception as e:
        warnings.warn(f"SDK buffer config failed: {e}", RuntimeWarning, stacklevel=2)
        return False


# Auto-configure on import
configure_sdk_buffer()
