
from __future__ import annotations

import time

from pymavlink import mavutil


class ScheduledFlightStartError(RuntimeError):
    """Raised when ArduPilot cannot be started into the scheduled mission."""


def set_stabilize_mode(
    connection: mavutil.mavfile,
) -> None:
    """Command ArduPilot into STABILIZE mode before arming."""

    mode_mapping = connection.mode_mapping()

    if "STABILIZE" not in mode_mapping:
        raise ScheduledFlightStartError(
            "ArduPilot does not report a STABILIZE flight mode."
        )

    connection.set_mode(
        mode_mapping["STABILIZE"]
    )

    deadline = time.monotonic() + 5.0

    while time.monotonic() < deadline:
        response = connection.recv_match(
            type="HEARTBEAT",
            blocking=True,
            timeout=1.0,
        )

        if response is None:
            continue

        mode = mavutil.mode_string_v10(response)

        if mode == "STABILIZE":
            return

    raise ScheduledFlightStartError(
        "ArduPilot did not enter STABILIZE mode within 5 seconds."
    )


def set_auto_mode(
    connection: mavutil.mavfile,
) -> None:
    """Command ArduPilot into AUTO mode."""

    mode_mapping = connection.mode_mapping()

    if "AUTO" not in mode_mapping:
        raise ScheduledFlightStartError(
            "ArduPilot does not report an AUTO flight mode."
        )

    connection.set_mode(
        mode_mapping["AUTO"]
    )

    deadline = time.monotonic() + 5.0

    while time.monotonic() < deadline:
        response = connection.recv_match(
            type="HEARTBEAT",
            blocking=True,
            timeout=1.0,
        )

        if response is None:
            continue

        mode = mavutil.mode_string_v10(response)

        if mode == "AUTO":
            return

    raise ScheduledFlightStartError(
        "ArduPilot did not enter AUTO mode within 5 seconds."
    )


def arm_vehicle(
    connection: mavutil.mavfile,
) -> None:
    """Arm the ArduPilot vehicle."""

    connection.mav.command_long_send(
        connection.target_system,
        connection.target_component,
        mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
        0,
        1,
        0,
        0,
        0,
        0,
        0,
        0,
    )

    deadline = time.monotonic() + 5.0

    while time.monotonic() < deadline:
        response = connection.recv_match(
            type="HEARTBEAT",
            blocking=True,
            timeout=1.0,
        )

        if response is None:
            continue

        armed = bool(
            int(response.base_mode)
            & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
        )

        if armed:
            return

    raise ScheduledFlightStartError(
        "ArduPilot did not arm within 5 seconds of the arming request."
    )


def disarm_vehicle(
    connection: mavutil.mavfile,
) -> None:
    """Request disarm and verify the aircraft is disarmed."""

    connection.mav.command_long_send(
        connection.target_system,
        connection.target_component,
        mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
    )

    deadline = time.monotonic() + 5.0

    while time.monotonic() < deadline:
        response = connection.recv_match(
            type="HEARTBEAT",
            blocking=True,
            timeout=1.0,
        )

        if response is None:
            continue

        armed = bool(
            int(response.base_mode)
            & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
        )

        if not armed:
            return

    raise ScheduledFlightStartError(
        "ArduPilot did not confirm disarm within 5 seconds."
    )


def start_mission(
    connection: mavutil.mavfile,
) -> None:
    """Command ArduPilot to begin the programmed mission."""

    connection.mav.command_long_send(
        connection.target_system,
        connection.target_component,
        mavutil.mavlink.MAV_CMD_MISSION_START,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
    )

    response = connection.recv_match(
        type="COMMAND_ACK",
        blocking=True,
        timeout=5.0,
    )

    if response is None:
        raise ScheduledFlightStartError(
            "Timed out waiting for MAV_CMD_MISSION_START acknowledgment."
        )

    if int(response.command) != mavutil.mavlink.MAV_CMD_MISSION_START:
        raise ScheduledFlightStartError(
            "Received acknowledgment for the wrong MAVLink command."
        )

    if int(response.result) != mavutil.mavlink.MAV_RESULT_ACCEPTED:
        raise ScheduledFlightStartError(
            "ArduPilot rejected MAV_CMD_MISSION_START. "
            f"Result={int(response.result)}."
        )


def set_governed_cruise_speed(
    connection: mavutil.mavfile,
    commanded_cruise_speed_ft_s: float,
) -> None:
    """Configure and acknowledge the governed cruise speed."""

    if commanded_cruise_speed_ft_s <= 0:
        raise ScheduledFlightStartError(
            "Commanded cruise speed must be positive."
        )

    connection.mav.command_long_send(
        connection.target_system,
        connection.target_component,
        mavutil.mavlink.MAV_CMD_DO_CHANGE_SPEED,
        0,
        1,
        commanded_cruise_speed_ft_s * 0.3048,
        -1,
        0,
        0,
        0,
        0,
    )

    deadline = time.monotonic() + 5.0

    while time.monotonic() < deadline:
        response = connection.recv_match(
            type="COMMAND_ACK",
            blocking=True,
            timeout=1.0,
        )

        if response is None:
            continue

        if int(response.command) != mavutil.mavlink.MAV_CMD_DO_CHANGE_SPEED:
            continue

        if int(response.result) != mavutil.mavlink.MAV_RESULT_ACCEPTED:
            raise ScheduledFlightStartError(
                "ArduPilot rejected governed cruise speed. "
                f"Result={int(response.result)}."
            )

        return

    raise ScheduledFlightStartError(
        "Timed out waiting for governed cruise speed acknowledgment."
    )


def start_scheduled_flight(
    connection: mavutil.mavfile,
    commanded_cruise_speed_ft_s: float,
) -> None:
    """Start execution of the programmed scheduled mission."""

    set_stabilize_mode(
        connection,
    )

    try:
        arm_vehicle(
            connection,
        )
    except Exception as exc:
        try:
            disarm_vehicle(
                connection,
            )
        except Exception as disarm_exc:
            raise ScheduledFlightStartError(
                "Aircraft arming failed, "
                "and disarm could not be confirmed."
            ) from disarm_exc

        raise ScheduledFlightStartError(
            "Aircraft arming failed. Aircraft confirmed disarmed."
        ) from exc

    try:
        set_auto_mode(
            connection,
        )
    except Exception as exc:
        try:
            disarm_vehicle(
                connection,
            )
        except Exception as disarm_exc:
            raise ScheduledFlightStartError(
                "AUTO mode transition failed, "
                "and aircraft disarm could not be confirmed."
            ) from disarm_exc

        raise ScheduledFlightStartError(
            "AUTO mode transition failed. Aircraft disarmed."
        ) from exc

    try:
        set_governed_cruise_speed(
            connection,
            commanded_cruise_speed_ft_s,
        )
    except Exception as exc:
        try:
            disarm_vehicle(
                connection,
            )
        except Exception as disarm_exc:
            raise ScheduledFlightStartError(
                "Governed cruise speed configuration failed, "
                "and aircraft disarm could not be confirmed."
            ) from disarm_exc

        raise ScheduledFlightStartError(
            "Governed cruise speed configuration failed. "
            "Aircraft disarmed."
        ) from exc

    start_mission(
        connection,
    )

