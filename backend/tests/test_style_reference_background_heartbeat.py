from __future__ import annotations

import threading
import time

from novel_system.services.style_reference.background_heartbeat import periodic_heartbeat
from novel_system.services.style_reference.run_orchestrator import (
    shutdown_style_reference_run_executor,
    start_style_reference_run_worker,
)


def test_periodic_heartbeat_runs_and_stops() -> None:
    calls: list[float] = []

    with periodic_heartbeat(
        lambda: calls.append(time.monotonic()),
        interval_seconds=0.01,
        thread_name="test-style-heartbeat",
    ):
        deadline = time.monotonic() + 1
        while not calls and time.monotonic() < deadline:
            time.sleep(0.01)

    assert calls
    stopped_count = len(calls)
    time.sleep(0.03)
    assert len(calls) == stopped_count


def test_run_executor_can_restart_after_lifespan_shutdown(monkeypatch) -> None:
    from novel_system.services.style_reference import run_orchestrator as module

    calls: list[str] = []
    completed = threading.Event()

    def fake_worker(**kwargs) -> None:  # noqa: ANN003
        calls.append(kwargs["run_id"])
        completed.set()

    monkeypatch.setattr(module, "_background_run_worker", fake_worker)
    shutdown_style_reference_run_executor(wait=True)
    start_style_reference_run_worker(
        run_id="run-after-shutdown",
        book_id="book-after-shutdown",
        layer_values=["language"],
        llm_client=object(),
    )
    assert completed.wait(timeout=2)
    shutdown_style_reference_run_executor(wait=True)
    assert calls == ["run-after-shutdown"]
