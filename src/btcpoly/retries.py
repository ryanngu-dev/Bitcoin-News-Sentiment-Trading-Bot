"""Retry with exponential backoff for later collectors. Phase 1 exports the helper."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


class RetryError(RuntimeError):
    pass


def retry(
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay: float = 0.25,
    max_delay: float = 4.0,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
    jitter: bool = True,
) -> T:
    last: BaseException | None = None
    for i in range(attempts):
        try:
            return fn()
        except retry_on as exc:  # noqa: PERF203 — explicit retry loop
            last = exc
            if i == attempts - 1:
                break
            delay = min(max_delay, base_delay * (2**i))
            if jitter:
                delay *= 0.5 + random.random()
            time.sleep(delay)
    raise RetryError(f"failed after {attempts} attempts: {last}") from last
