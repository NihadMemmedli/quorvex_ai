"""
Centralized Logging Configuration for Quorvex AI.

Provides:
- Consistent log format across all modules
- Rotating file handlers to prevent disk overflow
- Optional JSON format for structured logging
- Request logging middleware for FastAPI
"""

import json
import logging
import os
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Request ID context variable - accessible from any coroutine in the request chain
request_id_var: ContextVar[str] = ContextVar("request_id", default="")

# Default log directory
LOG_DIR = Path(__file__).parent.parent / "logs"


class JSONFormatter(logging.Formatter):
    """Format log records as JSON for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        # Get request ID from context
        req_id = request_id_var.get("")

        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        if req_id:
            log_data["request_id"] = req_id

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add extra fields
        if hasattr(record, "run_id"):
            log_data["run_id"] = record.run_id
        if hasattr(record, "duration_ms"):
            log_data["duration_ms"] = record.duration_ms

        return json.dumps(log_data)


class ColoredFormatter(logging.Formatter):
    """Colored console formatter for better readability."""

    COLORS = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        # Get color for level
        color = self.COLORS.get(record.levelname, "")

        # Format timestamp
        timestamp = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")

        # Include request ID if available
        req_id = request_id_var.get("")
        req_prefix = f"[{req_id}] " if req_id else ""

        # Build log line
        log_line = (
            f"{timestamp} | {color}{record.levelname:8}{self.RESET} | {req_prefix}{record.name} | {record.getMessage()}"
        )

        # Add exception info if present
        if record.exc_info:
            log_line += "\n" + self.formatException(record.exc_info)

        return log_line


def setup_logging(
    level: str = None,
    json_format: bool = None,
    log_file: str = "orchestrator.log",
    max_bytes: int = 50 * 1024 * 1024,  # 50 MB
    backup_count: int = 10,
    console: bool = True,
) -> logging.Logger:
    """
    Set up logging configuration.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
               Default from env LOG_LEVEL or INFO
        json_format: Use JSON format for logs (useful for log aggregation)
        log_file: Name of the log file
        max_bytes: Maximum log file size before rotation
        backup_count: Number of backup files to keep
        console: Whether to also log to console

    Returns:
        Root logger instance
    """
    # Get level from environment or default
    if level is None:
        level = os.environ.get("LOG_LEVEL", "INFO")

    numeric_level = getattr(logging, level.upper(), logging.INFO)

    # Auto-detect production environment for structured logging
    if json_format is None:
        json_format = os.environ.get("ENVIRONMENT") == "production"

    # Try to create log directory (may fail in Docker with mounted volumes)
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        pass  # Will fall back to console-only logging

    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Remove existing handlers
    root_logger.handlers.clear()

    # Create formatters
    if json_format:
        formatter = JSONFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )

    # File handler with rotation (optional - may fail with permission errors in Docker)
    file_path = LOG_DIR / log_file
    file_logging_enabled = False
    try:
        file_handler = RotatingFileHandler(file_path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
        file_logging_enabled = True
    except (PermissionError, OSError):
        # File logging unavailable - will use console only
        # This commonly happens in Docker with mounted volumes owned by root
        pass

    # Console handler
    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(numeric_level)
        # Use colored formatter for console if not JSON
        if json_format:
            console_handler.setFormatter(formatter)
        else:
            console_handler.setFormatter(ColoredFormatter())
        root_logger.addHandler(console_handler)

    # Reduce noise from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)

    if file_logging_enabled:
        root_logger.info(f"Logging initialized: level={level}, file={file_path}")
    else:
        root_logger.info(f"Logging initialized: level={level}, console-only (file logging unavailable)")

    return root_logger


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger with the specified name.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Logger instance
    """
    return logging.getLogger(name)


# --- FastAPI Request Logging Middleware ---


class RequestLoggingMiddleware:
    """
    FastAPI middleware for request/response logging.

    Logs:
    - Request method, path, and query params
    - Response status code
    - Request duration
    - Request ID for tracing
    """

    def __init__(self, app):
        self.app = app
        self.logger = logging.getLogger("api.request")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Generate request ID and set in context
        request_id = str(uuid.uuid4())[:8]
        token = request_id_var.set(request_id)
        start_time = time.time()

        # Extract request info
        method = scope["method"]
        path = scope["path"]
        query_string = scope.get("query_string", b"").decode()
        if query_string:
            path = f"{path}?{query_string}"

        # Log request start
        self.logger.info(f"[{request_id}] --> {method} {path}")

        # Track response status
        response_status = None

        async def send_wrapper(message):
            nonlocal response_status
            if message["type"] == "http.response.start":
                response_status = message["status"]
                # Add X-Request-ID header
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as e:
            self.logger.error(f"[{request_id}] Exception: {e}", exc_info=True)
            raise
        finally:
            # Calculate duration
            duration_ms = (time.time() - start_time) * 1000

            # Log response
            status = response_status or 500
            log_level = logging.INFO if status < 400 else logging.WARNING if status < 500 else logging.ERROR
            self.logger.log(log_level, f"[{request_id}] <-- {status} in {duration_ms:.1f}ms")
            request_id_var.reset(token)


# --- Context Logging ---


class LogContext:
    """
    Context manager for adding contextual info to logs.

    Example:
        with LogContext(run_id="123", stage="planning"):
            logger.info("Processing...")  # Will include run_id and stage
    """

    _context = {}

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.old_factory = None

    def __enter__(self):
        self.old_factory = logging.getLogRecordFactory()

        def record_factory(*args, **factory_kwargs):
            record = self.old_factory(*args, **factory_kwargs)
            for key, value in self.kwargs.items():
                setattr(record, key, value)
            return record

        logging.setLogRecordFactory(record_factory)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        logging.setLogRecordFactory(self.old_factory)


# Initialize logging on import if not already done
# This ensures logging is set up even for CLI usage
_initialized = False


def ensure_logging():
    """Ensure logging is initialized."""
    global _initialized
    if not _initialized:
        setup_logging(console=False)  # File only by default
        _initialized = True
