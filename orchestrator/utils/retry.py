"""
Retry utilities with exponential backoff for resilient operations.

Usage:
    @retry(max_attempts=3, exceptions=(ConnectionError, TimeoutError))
    def my_function():
        ...

    @async_retry(max_attempts=3, backoff_factor=2.0)
    async def my_async_function():
        ...
"""

import asyncio
import functools
import logging
import random
import time
from collections.abc import Callable
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Default exceptions to retry
TRANSIENT_EXCEPTIONS: tuple[type[Exception], ...] = (
    ConnectionError,
    TimeoutError,
    OSError,
)


def retry(
    max_attempts: int = 3,
    backoff_factor: float = 2.0,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    jitter: bool = True,
    exceptions: tuple[type[Exception], ...] = TRANSIENT_EXCEPTIONS,
    on_retry: Callable[[Exception, int], None] | None = None,
) -> Callable:
    """
    Decorator that retries a function with exponential backoff.

    Args:
        max_attempts: Maximum number of attempts (including the first try)
        backoff_factor: Multiplier for delay between attempts (e.g., 2.0 doubles the delay)
        initial_delay: Initial delay in seconds before first retry
        max_delay: Maximum delay cap in seconds
        jitter: Add randomness to delay to prevent thundering herd
        exceptions: Tuple of exception types to catch and retry
        on_retry: Optional callback called before each retry with (exception, attempt_number)

    Returns:
        Decorated function with retry logic

    Example:
        @retry(max_attempts=5, exceptions=(requests.RequestException,))
        def fetch_data(url):
            return requests.get(url)
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exception: Exception | None = None
            delay = initial_delay

            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    if attempt == max_attempts:
                        logger.error(f"Function {func.__name__} failed after {max_attempts} attempts: {e}")
                        raise

                    # Calculate delay with optional jitter
                    actual_delay = min(delay, max_delay)
                    if jitter:
                        actual_delay = actual_delay * (0.5 + random.random())

                    logger.warning(
                        f"Function {func.__name__} failed on attempt {attempt}/{max_attempts}: {e}. "
                        f"Retrying in {actual_delay:.2f}s..."
                    )

                    # Call optional retry callback
                    if on_retry:
                        on_retry(e, attempt)

                    time.sleep(actual_delay)
                    delay *= backoff_factor

            # This should never be reached, but just in case
            if last_exception:
                raise last_exception

        return wrapper

    return decorator


def async_retry(
    max_attempts: int = 3,
    backoff_factor: float = 2.0,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    jitter: bool = True,
    exceptions: tuple[type[Exception], ...] = TRANSIENT_EXCEPTIONS,
    on_retry: Callable[[Exception, int], None] | None = None,
) -> Callable:
    """
    Decorator that retries an async function with exponential backoff.

    Args:
        max_attempts: Maximum number of attempts (including the first try)
        backoff_factor: Multiplier for delay between attempts
        initial_delay: Initial delay in seconds before first retry
        max_delay: Maximum delay cap in seconds
        jitter: Add randomness to delay
        exceptions: Tuple of exception types to catch and retry
        on_retry: Optional callback called before each retry

    Returns:
        Decorated async function with retry logic

    Example:
        @async_retry(max_attempts=3)
        async def fetch_data(url):
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    return await response.json()
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            last_exception: Exception | None = None
            delay = initial_delay

            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    if attempt == max_attempts:
                        logger.error(f"Async function {func.__name__} failed after {max_attempts} attempts: {e}")
                        raise

                    # Calculate delay with optional jitter
                    actual_delay = min(delay, max_delay)
                    if jitter:
                        actual_delay = actual_delay * (0.5 + random.random())

                    logger.warning(
                        f"Async function {func.__name__} failed on attempt {attempt}/{max_attempts}: {e}. "
                        f"Retrying in {actual_delay:.2f}s..."
                    )

                    # Call optional retry callback
                    if on_retry:
                        on_retry(e, attempt)

                    await asyncio.sleep(actual_delay)
                    delay *= backoff_factor

            # This should never be reached, but just in case
            if last_exception:
                raise last_exception

        return wrapper

    return decorator


class RateLimiter:
    """
    Simple rate limiter using token bucket algorithm.

    Usage:
        limiter = RateLimiter(rate=50, per=60)  # 50 requests per 60 seconds

        async def make_request():
            await limiter.acquire()
            # ... make API call
    """

    def __init__(self, rate: int, per: float = 60.0):
        """
        Initialize rate limiter.

        Args:
            rate: Maximum number of requests allowed
            per: Time period in seconds (default: 60 seconds)
        """
        self.rate = rate
        self.per = per
        self.tokens = rate
        self.last_update = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """
        Acquire a token, waiting if necessary.
        """
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_update

            # Refill tokens based on elapsed time
            self.tokens = min(self.rate, self.tokens + elapsed * (self.rate / self.per))
            self.last_update = now

            if self.tokens < 1:
                # Calculate wait time
                wait_time = (1 - self.tokens) * (self.per / self.rate)
                logger.debug(f"Rate limit reached, waiting {wait_time:.2f}s")
                await asyncio.sleep(wait_time)
                self.tokens = 0
            else:
                self.tokens -= 1

    def acquire_sync(self) -> None:
        """
        Synchronous version of acquire.
        """
        now = time.monotonic()
        elapsed = now - self.last_update

        # Refill tokens based on elapsed time
        self.tokens = min(self.rate, self.tokens + elapsed * (self.rate / self.per))
        self.last_update = now

        if self.tokens < 1:
            # Calculate wait time
            wait_time = (1 - self.tokens) * (self.per / self.rate)
            logger.debug(f"Rate limit reached, waiting {wait_time:.2f}s")
            time.sleep(wait_time)
            self.tokens = 0
        else:
            self.tokens -= 1


# Pre-configured rate limiter for OpenAI API (50 requests per minute)
openai_rate_limiter = RateLimiter(rate=50, per=60)


# Convenience function for OpenAI embedding calls
@async_retry(
    max_attempts=5,
    backoff_factor=2.0,
    initial_delay=2.0,
    max_delay=120.0,
    exceptions=(
        ConnectionError,
        TimeoutError,
        Exception,  # Catch rate limit errors too
    ),
)
async def resilient_embedding_call(func, *args, **kwargs):
    """
    Wrapper for embedding API calls with rate limiting and retry.

    Usage:
        result = await resilient_embedding_call(
            openai_client.embeddings.create,
            model="text-embedding-ada-002",
            input="Hello world"
        )
    """
    await openai_rate_limiter.acquire()
    return await func(*args, **kwargs)


# Synchronous version for non-async contexts
@retry(
    max_attempts=5,
    backoff_factor=2.0,
    initial_delay=2.0,
    max_delay=120.0,
    exceptions=(
        ConnectionError,
        TimeoutError,
        Exception,
    ),
)
def resilient_embedding_call_sync(func, *args, **kwargs):
    """
    Synchronous wrapper for embedding API calls with rate limiting and retry.
    """
    openai_rate_limiter.acquire_sync()
    return func(*args, **kwargs)
