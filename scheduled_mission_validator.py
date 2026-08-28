from __future__ import annotations

from pymavlink import mavutil

from app.navproxy.tooling.download_mission import download_mission

from typing import Any


class ScheduledMissionValidationError(RuntimeError):
    """Raised when the programmed FC mission does not match the approved mission."""


def normalize_ardupilot_mission_sequence(
    sequence: int,
) -> int:
    """Convert an ArduPilot mission sequence to DroneNav mission indexing."""

    return sequence - 1


def expected_command_id(
    command_name: str,
) -> int:
    """Resolve a compiled MAVLink command name to its numeric command ID."""

    try:
        return int(
            getattr(
                mavutil.mavlink,
                command_name,
            )
        )
    except AttributeError as exc:
        raise ScheduledMissionValidationError(
            f"Unsupported compiled MAVLink command: {command_name}."
        ) from exc


def validate_position_command(
    *,
    expected_item: dict[str, Any],
    downloaded_item: dict[str, Any],
    coordinate_tolerance_degrees: float = 0.000001,
    altitude_tolerance_meters: float = 0.1,
) -> None:
    """Validate a positional mission command."""

    parameters = expected_item["parameters"]

    expected_latitude = float(parameters["latitude"])
    expected_longitude = float(parameters["longitude"])

    actual_latitude = float(downloaded_item["latitude"])
    actual_longitude = float(downloaded_item["longitude"])

    if abs(actual_latitude - expected_latitude) > coordinate_tolerance_degrees:
        raise ScheduledMissionValidationError(
            "Programmed mission latitude does not match compiled mission. "
            f"Sequence {expected_item['sequence']}: "
            f"expected {expected_latitude}, received {actual_latitude}."
        )

    if abs(actual_longitude - expected_longitude) > coordinate_tolerance_degrees:
        raise ScheduledMissionValidationError(
            "Programmed mission longitude does not match compiled mission. "
            f"Sequence {expected_item['sequence']}: "
            f"expected {expected_longitude}, received {actual_longitude}."
        )

    if "altitude_meters" in parameters:
        expected_altitude = float(parameters["altitude_meters"])
        actual_altitude = float(downloaded_item["altitude"])

        if abs(actual_altitude - expected_altitude) > altitude_tolerance_meters:
            raise ScheduledMissionValidationError(
                "Programmed mission altitude does not match compiled mission. "
                f"Sequence {expected_item['sequence']}: "
                f"expected {expected_altitude} m, received {actual_altitude} m."
            )


def validate_speed_command(
    *,
    expected_item: dict[str, Any],
    downloaded_item: dict[str, Any],
    speed_tolerance_meters_per_second: float = 0.01,
) -> None:
    """Validate a speed-change mission command."""

    parameters = expected_item["parameters"]

    expected_speed_type = float(parameters["speed_type"])
    expected_speed = float(parameters["speed_meters_per_second"])
    expected_throttle = float(parameters["throttle_percent"])
    expected_absolute = float(parameters["absolute"])

    actual_speed_type = float(downloaded_item["param1"])
    actual_speed = float(downloaded_item["param2"])
    actual_throttle = float(downloaded_item["param3"])
    actual_absolute = float(downloaded_item["param4"])

    if actual_speed_type != expected_speed_type:
        raise ScheduledMissionValidationError(
            "Programmed mission speed type does not match compiled mission. "
            f"Sequence {expected_item['sequence']}: "
            f"expected {expected_speed_type}, received {actual_speed_type}."
        )

    if abs(actual_speed - expected_speed) > speed_tolerance_meters_per_second:
        raise ScheduledMissionValidationError(
            "Programmed mission speed does not match compiled mission. "
            f"Sequence {expected_item['sequence']}: "
            f"expected {expected_speed} m/s, received {actual_speed} m/s."
        )

    if actual_throttle != expected_throttle:
        raise ScheduledMissionValidationError(
            "Programmed mission throttle does not match compiled mission. "
            f"Sequence {expected_item['sequence']}: "
            f"expected {expected_throttle}, received {actual_throttle}."
        )

    if actual_absolute != expected_absolute:
        raise ScheduledMissionValidationError(
            "Programmed mission speed absolute flag does not match compiled mission. "
            f"Sequence {expected_item['sequence']}: "
            f"expected {expected_absolute}, received {actual_absolute}."
        )


def expected_frame_id(
    command_name: str,
) -> int:
    """Return the expected MAVLink frame for a scheduled mission command."""

    if command_name in {
        "MAV_CMD_NAV_TAKEOFF",
        "MAV_CMD_NAV_WAYPOINT",
        "MAV_CMD_NAV_LAND",
    }:
        return int(
            mavutil.mavlink.MAV_FRAME_GLOBAL
        )

    if command_name == "MAV_CMD_DO_CHANGE_SPEED":
        return int(
            mavutil.mavlink.MAV_FRAME_MISSION
        )

    raise ScheduledMissionValidationError(
        f"Unsupported compiled MAVLink command frame: {command_name}."
    )


def validate_scheduled_mission(
    *,
    compiler_ir: dict[str, Any],
    downloaded_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Validate the programmed FC mission against scheduled mission semantics."""

    mission = compiler_ir["mission"]
    expected_items = mission["mission_items"]

    expected_downloaded_count = len(expected_items) + 1

    if len(downloaded_items) != expected_downloaded_count:
        raise ScheduledMissionValidationError(
            "Programmed mission item count does not match ArduPilot mission layout. "
            f"Expected {expected_downloaded_count}, "
            f"received {len(downloaded_items)}."
        )

    downloaded_items = downloaded_items[1:]

    for expected_item, downloaded_item in zip(
        expected_items,
        downloaded_items,
    ):
        expected_sequence = int(
            expected_item["sequence"]
        )

        downloaded_sequence = normalize_ardupilot_mission_sequence(
            int(downloaded_item["seq"])
        )

        if downloaded_sequence != expected_sequence:
            raise ScheduledMissionValidationError(
                "Programmed mission sequence does not match compiled mission. "
                f"Expected sequence {expected_sequence}, "
                f"received {downloaded_sequence}."
            )

        expected_command = expected_command_id(
            expected_item["command"]
        )

        downloaded_command = int(
            downloaded_item["command"]
        )

        if downloaded_command != expected_command:
            raise ScheduledMissionValidationError(
                "Programmed mission command does not match compiled mission. "
                f"Sequence {expected_sequence}: "
                f"expected {expected_item['command']} "
                f"({expected_command}), "
                f"received command ID {downloaded_command}."
            )

        if expected_item["command"] in {
            "MAV_CMD_NAV_TAKEOFF",
            "MAV_CMD_NAV_WAYPOINT",
            "MAV_CMD_NAV_LAND",
        }:
            validate_position_command(
                expected_item=expected_item,
                downloaded_item=downloaded_item,
            )

        if expected_item["command"] == "MAV_CMD_DO_CHANGE_SPEED":
            validate_speed_command(
                expected_item=expected_item,
                downloaded_item=downloaded_item,
            )

        if expected_item["command"] != "MAV_CMD_DO_CHANGE_SPEED":
            expected_frame = expected_frame_id(
                expected_item["command"]
            )

            downloaded_frame = int(
                downloaded_item["frame"]
            )

            if downloaded_frame != expected_frame:
                raise ScheduledMissionValidationError(
                    "Programmed mission frame does not match compiled mission. "
                    f"Sequence {expected_sequence}: "
                    f"expected frame {expected_frame}, "
                    f"received frame {downloaded_frame}."
                )

        downloaded_current = int(
            downloaded_item["current"]
        )

        if downloaded_current != 0:
            raise ScheduledMissionValidationError(
                "Programmed mission current flag is invalid. "
                f"Sequence {expected_sequence}: "
                f"expected 0, received {downloaded_current}."
            )

        downloaded_autocontinue = int(
            downloaded_item["autocontinue"]
        )

        if downloaded_autocontinue != 1:
            raise ScheduledMissionValidationError(
                "Programmed mission autocontinue flag is invalid. "
                f"Sequence {expected_sequence}: "
                f"expected 1, received {downloaded_autocontinue}."
            )

    return downloaded_items


def validate_programmed_scheduled_mission(
    *,
    connection: mavutil.mavfile,
    compiler_ir: dict[str, Any],
    timeout: float = 5.0,
) -> list[dict[str, Any]]:
    """Read back and validate the scheduled mission programmed on the FC."""

    downloaded_items = download_mission(
        connection,
        timeout=timeout,
    )

    return validate_scheduled_mission(
               compiler_ir=compiler_ir,
               downloaded_items=downloaded_items,
           )


