from __future__ import annotations

from typing import Iterator

from pymavlink import mavutil

from app.navproxy.simulator import TelemetryReading


def request_message_interval(
    connection: mavutil.mavfile,
    *,
    message_id: int,
    frequency_hz: float,
) -> None:
    """Request a MAVLink message at a specific frequency."""

    interval_us = int(
        1_000_000 / frequency_hz
    )

    connection.mav.command_long_send(
        connection.target_system,
        connection.target_component,
        mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL,
        0,
        message_id,
        interval_us,
        0,
        0,
        0,
        0,
        0,
    )

class MavlinkTelemetrySource:
    """Produce normalized NAVProxy telemetry from a MAVLink flight controller."""

    def __init__(
        self,
        connection: mavutil.mavfile,
    ) -> None:
        self.connection = connection

        request_message_interval(
            connection,
            message_id=mavutil.mavlink.MAVLINK_MSG_ID_GLOBAL_POSITION_INT,
            frequency_hz=5.0,
        )

        request_message_interval(
            connection,
            message_id=mavutil.mavlink.MAVLINK_MSG_ID_MISSION_CURRENT,
            frequency_hz=2.0,
        )


    def iter_telemetry(self) -> Iterator[TelemetryReading]:
        """Yield normalized telemetry readings from the flight controller."""

        armed = False
        mission_sequence: int | None = None

        while True:
            message = self.connection.recv_match(
                type=[
                    "HEARTBEAT",
                    "GLOBAL_POSITION_INT",
                    "MISSION_CURRENT",
                ],
                blocking=True,
                timeout=5.0,
            )

            if message is None:
                continue

            message_type = message.get_type()

            if message_type == "HEARTBEAT":
                armed = bool(
                    int(message.base_mode)
                    & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
                )
                continue

            if message_type == "MISSION_CURRENT":
                mission_sequence = int(message.seq)
                continue

            if message_type != "GLOBAL_POSITION_INT":
                continue

            yield TelemetryReading(
                latitude=int(message.lat) / 10_000_000,
                longitude=int(message.lon) / 10_000_000,
                relative_altitude_ft=(
                    float(message.relative_alt) / 1000.0 / 0.3048
                ),
                absolute_altitude_ft=(
                    float(message.alt) / 1000.0 / 0.3048
                ),
                armed=armed,
                heartbeat_active=True,
                mission_sequence=mission_sequence,
            )

