from __future__ import annotations

from pymavlink import mavutil


class MAVLinkConnectionError(RuntimeError):
    """Raised when a MAVLink connection cannot be established."""


def connect_to_ardupilot(
    connection_string: str,
    *,
    source_system: int,
    source_component: int,
    heartbeat_timeout: float,
) -> mavutil.mavfile:
    """Open a MAVLink connection and wait for ArduPilot's heartbeat."""

    connection = mavutil.mavlink_connection(
        connection_string,
        source_system=source_system,
        source_component=source_component,
        autoreconnect=True,
    )

    heartbeat = connection.wait_heartbeat(
        timeout=heartbeat_timeout,
    )

    if heartbeat is None:
        raise MAVLinkConnectionError(
            "Timed out waiting for an ArduPilot heartbeat."
        )

    connection.target_system = heartbeat.get_srcSystem()
    connection.target_component = heartbeat.get_srcComponent()

    if heartbeat.autopilot != mavutil.mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA:
        raise MAVLinkConnectionError(
            "The connected endpoint did not identify itself as ArduPilot. "
            f"autopilot={heartbeat.autopilot}"
        )

    return connection


