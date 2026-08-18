"""Small lifecycle helper for long in-process style-reference workers."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager


logger = logging.getLogger(__name__)


@contextmanager
def periodic_heartbeat(
    beat: Callable[[], None],
    *,
    interval_seconds: float,
    thread_name: str,
) -> Iterator[None]:
    """Run ``beat`` periodically until the guarded operation finishes.

    A heartbeat failure is logged and retried on the next interval: a short
    SQLite busy window must not abort the LLM call it is protecting. Ownership
    is still enforced by the conditional update inside each ``beat`` callback.
    """

    stop = threading.Event()
    interval = max(0.01, float(interval_seconds))

    def loop() -> None:
        while not stop.wait(interval):
            try:
                beat()
            except Exception:  # pragma: no cover - final background boundary
                logger.exception("style-reference heartbeat failed in %s", thread_name)

    thread = threading.Thread(target=loop, name=thread_name, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=min(5.0, interval + 0.5))
