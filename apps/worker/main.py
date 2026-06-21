"""Background worker for lightweight ScholarMind maintenance tasks."""

from __future__ import annotations

import logging
import signal
import time
from pathlib import Path
from threading import Event

from packages.ai.idle_processor import start_idle_processor, stop_idle_processor
from packages.logging_setup import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

_HEALTH_FILE = Path("/tmp/worker_heartbeat")
_HEARTBEAT_SECONDS = 60

stop_event = Event()


def _write_heartbeat() -> None:
    try:
        _HEALTH_FILE.write_text(str(time.time()))
    except OSError:
        pass


def run_worker() -> None:
    """Run the lightweight background worker."""

    def _graceful_stop(*_: object) -> None:
        logger.info("Stopping ScholarMind worker...")
        stop_event.set()

    signal.signal(signal.SIGINT, _graceful_stop)
    signal.signal(signal.SIGTERM, _graceful_stop)

    logger.info("Starting ScholarMind worker: idle processor only")
    _write_heartbeat()
    start_idle_processor()
    try:
        while not stop_event.wait(_HEARTBEAT_SECONDS):
            _write_heartbeat()
    finally:
        stop_idle_processor()
        _write_heartbeat()
        logger.info("ScholarMind worker stopped")


if __name__ == "__main__":
    run_worker()
