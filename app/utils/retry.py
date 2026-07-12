"""Async retry utility with exponential backoff and jitter."""
import asyncio
import logging
import random
from typing import Any, Callable, Tuple, Type

logger = logging.getLogger(__name__)


async def async_retry(
    coro_fn: Callable[..., Any],
    *args: Any,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    retryable_exceptions: Tuple[Type[BaseException], ...] = (Exception,),
    rate_limit_min_delay: float = 20.0,
    **kwargs: Any,
) -> Any:
    """Run an async callable with exponential backoff retry.

    Retries only on transient errors (network, API rate-limit, timeout).
    The caller's outer try/except remains as the final fallback.

    Args:
        coro_fn: Async callable to retry.
        *args: Positional arguments forwarded to coro_fn.
        max_attempts: Total number of attempts (default 3).
        base_delay: Base delay in seconds; doubles each attempt (default 1.0).
        max_delay: Cap on retry delay in seconds (default 30.0).
        retryable_exceptions: Exception types that trigger a retry (default all).
        rate_limit_min_delay: Minimum backoff (seconds) when the caught exception
            looks like an HTTP 429 (duck-typed via a `.code` attribute, e.g.
            google.genai.errors.APIError). Provider rate-limit windows reset on
            the order of a minute, not milliseconds, so the normal exponential
            backoff is too short to usefully wait one out.
        **kwargs: Keyword arguments forwarded to coro_fn.

    Returns:
        Result from the first successful call.

    Raises:
        The last exception when all attempts are exhausted.
    """
    fn_name = getattr(coro_fn, "__name__", repr(coro_fn))
    last_exc: BaseException | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            return await coro_fn(*args, **kwargs)
        except retryable_exceptions as exc:
            last_exc = exc
            if attempt == max_attempts:
                logger.warning(
                    "[retry] %s exhausted %d/%d attempts: %s",
                    fn_name,
                    attempt,
                    max_attempts,
                    exc,
                )
                raise
            # Exponential backoff with full jitter
            delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
            if getattr(exc, "code", None) == 429:
                delay = max(delay, rate_limit_min_delay)
            delay += random.uniform(0, delay * 0.2)  # ±20% jitter
            logger.warning(
                "[retry] %s attempt %d/%d failed: %s — retrying in %.1fs",
                fn_name,
                attempt,
                max_attempts,
                exc,
                delay,
            )
            await asyncio.sleep(delay)

    raise last_exc  # unreachable but satisfies type checkers
