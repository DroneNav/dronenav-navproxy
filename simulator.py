"""Initial simulated flight-controller integration for NAVProxy development."""

from __future__ import annotations
from dataclasses import dataclass

import logging
import time
from typing import Any, Iterator
from datetime import datetime, timedelta, timezone


LOGGER = logging.getLogger(__name__)

@dataclass(frozen=True)
class TelemetryReading:
    """One simulated radio telemetry observation."""

    observed_at: datetime
    latitude: float
    longitude: float
    relative_altitude_ft: float
    armed: bool
    heartbeat_active: bool
    mission_sequence: int | None = None
    absolute_altitude_ft: float | None = None

    battery_percent: float | None = None
    energy_health: str | None = None
    navigation_health: str | None = None
    vehicle_health: str | None = None



class FlightSimulator:
    """Simulate the pre-flight and in-flight portions of one execution."""

    def __init__(self, preflight_seconds: int, flight_seconds: int) -> None:
        self.preflight_seconds = preflight_seconds
        self.flight_seconds = flight_seconds


    def wait_for_preflight_delay(self) -> None:
        """Wait for the configured simulated preflight delay."""

        LOGGER.debug(
            "Simulated preflight delay for %s second(s).",
            self.preflight_seconds,
        )
        time.sleep(self.preflight_seconds)


    def run_flight(
        self,
        compiler_ir: dict[str, Any],
    ) -> Iterator[TelemetryReading]:
        """Run the simulated flight and yield telemetry readings."""

        readings = list(self.iter_telemetry(compiler_ir))

        if not readings:
            return

        delay_seconds = self.flight_seconds / len(readings)

        for reading in readings:
            yield reading
            time.sleep(delay_seconds)


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

        waypoint_items = [
            item
            for item in mission_items
            if (
                isinstance(item, dict)
                and item.get("command") == "MAV_CMD_NAV_WAYPOINT"
            )
        ]

        flight_sample_count = len(waypoint_items) + 2

        sample_interval_seconds = (
            self.flight_seconds / max(flight_sample_count, 1)
        )

        simulated_start_at = datetime.now(timezone.utc)
        sample_index = 0

        launch_assertion = next(
            (
                assertion
                for assertion in assertions
                if isinstance(assertion, dict)
                and assertion.get("assertion_type")
                == "NAV_ASSERT_POSITION_IN_GEOMETRY"
            ),
            None,
        )

        if launch_assertion is None:
            raise ValueError(
                "Compiler IR is missing the launch position assertion."
            )

        launch_parameters = launch_assertion.get("parameters")

        if not isinstance(launch_parameters, dict):
            raise ValueError(
                "Launch position assertion is missing its parameters object."
            )

        launch_coordinate = launch_parameters.get("coordinate")

        if (
            not isinstance(launch_coordinate, list)
            or len(launch_coordinate) < 2
        ):
            raise ValueError(
                "Launch position assertion is missing its coordinate."
            )

        launch_longitude = launch_coordinate[0]
        launch_latitude = launch_coordinate[1]

        yield TelemetryReading(
            observed_at=(simulated_start_at + timedelta(seconds=(sample_index * sample_interval_seconds))),
            latitude=launch_latitude,
            longitude=launch_longitude,
            relative_altitude_ft=0.0,
            armed=False,
            heartbeat_active=True,
            battery_percent=max(0.0, 100.0 - (sample_index * 2.0)),
        )

        sample_index += 1

        for mission_item in mission_items:
            if not isinstance(mission_item, dict):
                continue

            if mission_item.get("command") != "MAV_CMD_NAV_TAKEOFF":
                continue

            parameters = mission_item.get("parameters")

            if not isinstance(parameters, dict):
                continue

            altitude_meters = parameters.get("altitude_meters")

            if not isinstance(altitude_meters, (int, float)):
                continue

            yield TelemetryReading(
                observed_at=(simulated_start_at + timedelta(seconds=(sample_index * sample_interval_seconds))),
                latitude=launch_latitude,
                longitude=launch_longitude,
                relative_altitude_ft=float(mission["minimum_agl_ft"]),
                armed=True,
                heartbeat_active=True,
                battery_percent=max(0.0, 100.0 - (sample_index * 2.0)),
                mission_sequence=mission_item.get("sequence"),
            )

            sample_index += 1

            break

        for mission_item in mission_items:
            if not isinstance(mission_item, dict):
                continue

            if mission_item.get("command") != "MAV_CMD_NAV_WAYPOINT":
                continue

            parameters = mission_item.get("parameters")

            if not isinstance(parameters, dict):
                continue

            latitude = parameters.get("latitude")
            longitude = parameters.get("longitude")
            altitude_meters = parameters.get("altitude_meters")

            if (
                not isinstance(latitude, (int, float))
                or not isinstance(longitude, (int, float))
                or not isinstance(altitude_meters, (int, float))
            ):
                continue

            yield TelemetryReading(
                observed_at=(simulated_start_at + timedelta(seconds=(sample_index * sample_interval_seconds))),
                latitude=latitude,
                longitude=longitude,
                relative_altitude_ft=float(mission["minimum_agl_ft"]),
                armed=True,
                heartbeat_active=True,
                battery_percent=max(0.0, 100.0 - (sample_index * 2.0)),
                mission_sequence=mission_item.get("sequence"),
            )

            sample_index += 1

        for mission_item in mission_items:
            if not isinstance(mission_item, dict):
                continue

            if mission_item.get("command") != "MAV_CMD_NAV_LAND":
                continue

            parameters = mission_item.get("parameters")

            if not isinstance(parameters, dict):
                continue

            latitude = parameters.get("latitude")
            longitude = parameters.get("longitude")

            if (
                not isinstance(latitude, (int, float))
                or not isinstance(longitude, (int, float))
            ):
                continue

            yield TelemetryReading(
                observed_at=(simulated_start_at + timedelta(seconds=(sample_index * sample_interval_seconds))),
                latitude=latitude,
                longitude=longitude,
                relative_altitude_ft=0.0,
                armed=True,
                heartbeat_active=True,
                battery_percent=max(0.0, 100.0 - (sample_index * 2.0)),
                mission_sequence=mission_item.get("sequence"),
            )

            sample_index += 1

            yield TelemetryReading(
                observed_at=(simulated_start_at + timedelta(seconds=(sample_index * sample_interval_seconds))),
                latitude=latitude,
                longitude=longitude,
                relative_altitude_ft=0.0,
                armed=False,
                heartbeat_active=True,
                battery_percent=max(0.0, 100.0 - (sample_index * 2.0)),
                mission_sequence=mission_item.get("sequence"),
            )

            break



