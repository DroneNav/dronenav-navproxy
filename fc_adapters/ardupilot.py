from __future__ import annotations

from pymavlink import mavutil

import struct


NAVIGATION_HEALTH_MIN_FIX_TYPE = 3
NAVIGATION_HEALTH_MIN_SATELLITES = 6
NAVIGATION_HEALTH_MAX_EPH = 250
NAVIGATION_HEALTH_MAX_EPV = 400

FAILSAFE_RECOVERY_ENTRY_STRUCT = struct.Struct("<HHH")
FAILSAFE_RECOVERY_COUNT_STRUCT = struct.Struct("<H")
FAILSAFE_RECOVERY_MAX_BYTES = 1024



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

def encode_failsafe_recovery_map(
    jump_map: list[dict[str, int]],
) -> bytes:
    """Encode the compiled failsafe jump map for ArduPilot storage."""

    if not jump_map:
        raise ValueError("Failsafe recovery jump map is empty.")

    payload = bytearray()

    payload.extend(
        FAILSAFE_RECOVERY_COUNT_STRUCT.pack(
            len(jump_map)
        )
    )

    for entry in jump_map:
        start_index = (
            int(entry["start_mission_sequence"]) + 1
        )

        end_index = (
            int(entry["end_mission_sequence"]) + 1
        )

        recovery_index = (
            int(entry["recovery_mission_sequence"]) + 1
        )

        if not (
            0 <= start_index <= 0xFFFF
            and 0 <= end_index <= 0xFFFF
            and 0 <= recovery_index <= 0xFFFF
        ):
            raise ValueError(
                "Failsafe recovery mission index exceeds uint16 range."
            )

        if end_index < start_index:
            raise ValueError(
                "Failsafe recovery range end precedes start."
            )

        payload.extend(
            FAILSAFE_RECOVERY_ENTRY_STRUCT.pack(
                start_index,
                end_index,
                recovery_index,
            )
        )

    if len(payload) > FAILSAFE_RECOVERY_MAX_BYTES:
        raise ValueError(
            "Failsafe recovery jump map exceeds ArduPilot storage capacity."
        )

    return bytes(payload)


def decode_failsafe_recovery_map(
    payload: bytes,
) -> list[dict[str, int]]:
    """Decode an ArduPilot failsafe recovery map payload."""

    if len(payload) < FAILSAFE_RECOVERY_COUNT_STRUCT.size:
        raise ValueError(
            "Failsafe recovery payload is too short."
        )

    entry_count = FAILSAFE_RECOVERY_COUNT_STRUCT.unpack_from(
        payload,
        0,
    )[0]

    if entry_count == 0:
        raise ValueError(
            "Failsafe recovery payload contains no entries."
        )

    expected_length = (
        FAILSAFE_RECOVERY_COUNT_STRUCT.size
        + entry_count
        * FAILSAFE_RECOVERY_ENTRY_STRUCT.size
    )

    if len(payload) != expected_length:
        raise ValueError(
            "Failsafe recovery payload length does not match entry count."
        )

    jump_map: list[dict[str, int]] = []

    offset = FAILSAFE_RECOVERY_COUNT_STRUCT.size

    for _ in range(entry_count):
        (
            start_index,
            end_index,
            recovery_index,
        ) = FAILSAFE_RECOVERY_ENTRY_STRUCT.unpack_from(
            payload,
            offset,
        )

        if end_index < start_index:
            raise ValueError(
                "Failsafe recovery range end precedes start."
            )

        jump_map.append({
            "start_mission_sequence": start_index,
            "end_mission_sequence": end_index,
            "recovery_mission_sequence": recovery_index,
        })

        offset += FAILSAFE_RECOVERY_ENTRY_STRUCT.size

    return jump_map

