"""Initial simulated flight-controller integration for NAVProxy development."""

from __future__ import annotations
from dataclasses import dataclass

import logging
import time
from typing import Any, Iterator


LOGGER = logging.getLogger(__name__)

@dataclass(frozen=True)
class TelemetryReading:
    """One simulated radio telemetry observation."""

    latitude: float
    longitude: float
    relative_altitude_ft: float
    armed: bool
    heartbeat_active: bool
    mission_sequence: int | None = None



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

    def iter_telemetry(
        self,
        compiler_ir: dict[str, Any],
    ) -> Iterator[TelemetryReading]:
        """Yield simulated telemetry that follows the compiled mission."""

        assertions = compiler_ir.get("assertions")
        mission = compiler_ir.get("mission")

        if not isinstance(assertions, list):
            raise ValueError(
                "Compiler IR is missing the assertions array."
            )

        if not isinstance(mission, dict):
            raise ValueError(
                "Compiler IR is missing the mission object."
            )

        mission_items = mission.get("mission_items")

        if not isinstance(mission_items, list):
            raise ValueError(
                "Compiler IR mission is missing the mission_items array."
            )


    def run_flight(self) -> None:
        LOGGER.info(
            "Aircraft is in flight for %s second(s).",
            self.flight_seconds,
        )
        time.sleep(self.flight_seconds)

