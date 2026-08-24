from __future__ import annotations

import time
import select
import socket

from typing import Iterator

from pymavlink import mavutil

from app.navproxy.simulator import TelemetryReading

from app.config.constants import (
    HEARTBEAT_LOSS_TIMEOUT_SECONDS,
    HEARTBEAT_RECOVERY_WINDOW_SECONDS,
)

from app.navproxy.fc_adapters.ardupilot import (
    battery_percent_from_sys_status,
    is_flight_controller_heartbeat,
    navigation_health_from_gps,
    vehicle_health_from_sys_status,
)


class HeartbeatRecoveryExpired(RuntimeError):
    """Raised when flight-controller heartbeat does not recover in time."""


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
        connection_string: str,
    ) -> None:
        self.connection = connection
        self.connection_string = connection_string
        self.just_reconnected = False

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

        request_message_interval(
            connection,
            message_id=mavutil.mavlink.MAVLINK_MSG_ID_SYS_STATUS,
            frequency_hz=1.0,
        )

        request_message_interval(
            connection,
            message_id=mavutil.mavlink.MAVLINK_MSG_ID_GPS_RAW_INT,
            frequency_hz=1.0,
        )


    def reconnect(self) -> bool:
        """Attempt to reestablish the MAVLink connection."""

        try:
            connection = mavutil.mavlink_connection(
                self.connection_string,
                autoreconnect=False,
            )

            heartbeat = connection.wait_heartbeat(
                timeout=1.0,
            )

            if heartbeat is None:
                connection.close()
                return False

            self.connection = connection
            self.just_reconnected = True

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

            request_message_interval(
                connection,
                message_id=mavutil.mavlink.MAVLINK_MSG_ID_SYS_STATUS,
                frequency_hz=1.0,
            )

            request_message_interval(
                connection,
                message_id=mavutil.mavlink.MAVLINK_MSG_ID_GPS_RAW_INT,
                frequency_hz=1.0,
            )

            return True

        except (ConnectionError, OSError):
            return False


    def consume_reconnect_flag(self) -> bool:
        """Return and clear the one-time reconnect indicator."""

        reconnected = self.just_reconnected
        self.just_reconnected = False

        return reconnected


    def reconnect_pending(self) -> bool:
        """Return whether post-reconnect mission resynchronization is pending."""

        return self.just_reconnected


    def connection_closed(self) -> bool:
        """Return True when the MAVLink TCP peer has closed the connection."""

        port = getattr(
            self.connection,
            "port",
            None,
        )

        if not isinstance(port, socket.socket):
            return False

        readable, _, _ = select.select(
            [port],
            [],
            [],
            0,
        )

        if not readable:
            return False

        try:
            data = port.recv(
                1,
                socket.MSG_PEEK,
            )
        except BlockingIOError:
            return False
        except OSError:
            return True

        return data == b""


    def iter_telemetry(self) -> Iterator[TelemetryReading]:
        """Yield normalized telemetry readings from the flight controller."""

        armed = False
        mission_sequence: int | None = None
        last_heartbeat_at = time.monotonic()
        heartbeat_lost_at: float | None = None
        battery_percent: float | None = None
        gps_fix_type: int | None = None
        gps_satellites_visible: int | None = None
        gps_eph: int | None = None
        gps_epv: int | None = None
        navigation_health: str | None = None
        vehicle_health: str | None = None

        while True:
            if heartbeat_lost_at is not None:
                if self.reconnect():
                    last_heartbeat_at = time.monotonic()
                    heartbeat_lost_at = None
                    mission_sequence = None
                    battery_percent = None
                    navigation_health = None
                    vehicle_health = None
                    continue

                recovery_age = (
                    time.monotonic()
                    - heartbeat_lost_at
                )

                if recovery_age >= HEARTBEAT_RECOVERY_WINDOW_SECONDS:
                    raise HeartbeatRecoveryExpired(
                        "Flight-controller heartbeat recovery window expired."
                    )

                time.sleep(1.0)
                continue

            if self.connection_closed():
                heartbeat_lost_at = time.monotonic()
                continue

            try:
                message = self.connection.recv_match(
                    type=[
                        "HEARTBEAT",
                        "GLOBAL_POSITION_INT",
                        "MISSION_CURRENT",
                        "SYS_STATUS",
                        "GPS_RAW_INT",
                    ],
                    blocking=False,
                )

            except (ConnectionError, OSError):
                message = None

                if heartbeat_lost_at is None:
                    heartbeat_lost_at = time.monotonic()

            heartbeat_age = (
                time.monotonic()
                - last_heartbeat_at
            )

            if (
                heartbeat_age >= HEARTBEAT_LOSS_TIMEOUT_SECONDS
                and heartbeat_lost_at is None
            ):
                heartbeat_lost_at = time.monotonic()
                continue

            if message is None:
                time.sleep(0.1)
                continue

            message_type = message.get_type()

            if message_type == "HEARTBEAT":
                if not is_flight_controller_heartbeat(
                    message,
                    target_system=self.connection.target_system,
                ):
                    continue

                last_heartbeat_at = time.monotonic()
                heartbeat_lost_at = None
                armed = bool(
                    int(message.base_mode)
                    & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
                )
                continue

            if message_type == "MISSION_CURRENT":
                mission_sequence = int(message.seq)
                continue

            if message_type == "SYS_STATUS":
                battery_percent = battery_percent_from_sys_status(
                    message
                )
                vehicle_health = vehicle_health_from_sys_status(
                    message
                )
                continue

            if message_type == "GPS_RAW_INT":
                gps_fix_type = int(message.fix_type)
                gps_satellites_visible = int(message.satellites_visible)
                gps_eph = int(message.eph)
                gps_epv = int(message.epv)

                navigation_health = navigation_health_from_gps(
                    fix_type=gps_fix_type,
                    satellites_visible=gps_satellites_visible,
                    eph=gps_eph,
                    epv=gps_epv,
                )

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
                battery_percent=battery_percent,
                navigation_health=navigation_health,
                vehicle_health=vehicle_health,
            )

