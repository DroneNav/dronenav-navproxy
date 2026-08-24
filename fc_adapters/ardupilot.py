from __future__ import annotations

from pymavlink import mavutil

NAVIGATION_HEALTH_MIN_FIX_TYPE = 3
NAVIGATION_HEALTH_MIN_SATELLITES = 6
NAVIGATION_HEALTH_MAX_EPH = 250
NAVIGATION_HEALTH_MAX_EPV = 400


def is_flight_controller_heartbeat(
    message,
    *,
    target_system: int,
) -> bool:
    """Return whether this HEARTBEAT belongs to the target ArduPilot FC."""

    return (
        message.get_srcSystem() == target_system
        and message.autopilot
        == mavutil.mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA
    )


def battery_percent_from_sys_status(
    message,
) -> float | None:
    """Normalize ArduPilot SYS_STATUS battery remaining to percent."""

    battery_remaining = int(message.battery_remaining)

    if battery_remaining < 0:
        return None

    return float(battery_remaining)


def navigation_health_from_gps(
    *,
    fix_type: int | None,
    satellites_visible: int | None,
    eph: int | None,
    epv: int | None,
) -> str | None:
    """Normalize ArduPilot GPS quality into DroneNav navigation health."""

    if (
        fix_type is None
        or satellites_visible is None
        or eph is None
        or epv is None
    ):
        return None

    if fix_type < NAVIGATION_HEALTH_MIN_FIX_TYPE:
        return "unusable"

    if (
        satellites_visible < NAVIGATION_HEALTH_MIN_SATELLITES
        or eph > NAVIGATION_HEALTH_MAX_EPH
        or epv > NAVIGATION_HEALTH_MAX_EPV
    ):
        return "degraded"

    return "healthy"


def vehicle_health_from_sys_status(
    message,
) -> str | None:
    """Normalize ArduPilot SYS_STATUS sensor health into DroneNav vehicle health."""

    enabled = int(
        message.onboard_control_sensors_enabled
    )

    healthy = int(
        message.onboard_control_sensors_health
    )

    if enabled == 0:
        return None

    unhealthy_enabled = enabled & ~healthy

    if unhealthy_enabled:
        return "degraded"

    return "healthy"

