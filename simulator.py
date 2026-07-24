"""Initial simulated flight-controller integration for NAVProxy development."""

from __future__ import annotations

import logging
import time

LOGGER = logging.getLogger(__name__)


class FlightSimulator:
    """Simulate the pre-flight and in-flight portions of one execution."""

    def __init__(self, preflight_seconds: int, flight_seconds: int) -> None:
        self.preflight_seconds = preflight_seconds
        self.flight_seconds = flight_seconds

    def run_preflight(self) -> None:
        LOGGER.info(
            "Pre-flight checks in progress for %s second(s).",
            self.preflight_seconds,
        )
        time.sleep(self.preflight_seconds)

    def run_flight(self) -> None:
        LOGGER.info(
            "Aircraft is in flight for %s second(s).",
            self.flight_seconds,
        )
        time.sleep(self.flight_seconds)

