"""
Emit an ArduPilot-compatible MAVLink MISSION_ITEM_INT representation.

This tool does not connect to an aircraft and does not alter the existing
NAVProxy runtime. It converts a validated command description into the exact
field structure expected by MAVLink MISSION_ITEM_INT.

Usage from the NAVProxy project directory:

    python -m tooling.emit_mission_item_int \
        tooling/mavlink_commands.yaml \
        tooling/waypoint.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

from tooling.compile_command import (
    CommandMetadataError,
    CommandValidationError,
    compile_command,
    load_json_file,
    load_yaml_file,
)


# MAVLink enum values from the common message set.
MAV_FRAME_GLOBAL_RELATIVE_ALT = 3
MAV_MISSION_TYPE_MISSION = 0

INT32_MIN = -(2**31)
INT32_MAX = (2**31) - 1


class MissionItemEmissionError(ValueError):
    """Raised when a compiled command cannot become MISSION_ITEM_INT."""


def find_parameter(
    compiled_command: dict[str, Any],
    name: str,
) -> Any:
    """Return a compiled parameter value by metadata name."""

    for parameter in compiled_command["parameters"]:
        if parameter["name"] == name:
            return parameter["value"]

    raise MissionItemEmissionError(
        f"Compiled command does not contain parameter '{name}'."
    )


def encode_global_coordinate(
    value: float,
    coordinate_name: str,
) -> int:
    """
    Encode latitude or longitude as a MAVLink degree-E7 integer.

    MISSION_ITEM_INT stores global latitude and longitude as degrees
    multiplied by 10^7.
    """

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MissionItemEmissionError(
            f"{coordinate_name} must be numeric."
        )

    if not math.isfinite(value):
        raise MissionItemEmissionError(
            f"{coordinate_name} must be finite."
        )

    encoded_value = round(float(value) * 10_000_000)

    if encoded_value < INT32_MIN or encoded_value > INT32_MAX:
        raise MissionItemEmissionError(
            f"{coordinate_name} cannot be represented as an int32."
        )

    return encoded_value


def emit_mission_item_int(
    compiled_command: dict[str, Any],
    *,
    target_system: int = 1,
    target_component: int = 1,
    sequence: int = 0,
    frame: int = MAV_FRAME_GLOBAL_RELATIVE_ALT,
    current: int = 0,
    autocontinue: int = 1,
    mission_type: int = MAV_MISSION_TYPE_MISSION,
) -> dict[str, Any]:
    """
    Convert MAV_CMD_NAV_WAYPOINT into MISSION_ITEM_INT fields.
    """

    if compiled_command["command"] != "MAV_CMD_NAV_WAYPOINT":
        raise MissionItemEmissionError(
            "This first emitter supports only MAV_CMD_NAV_WAYPOINT."
        )

    validate_uint8("target_system", target_system)
    validate_uint8("target_component", target_component)
    validate_uint16("sequence", sequence)
    validate_uint8("frame", frame)
    validate_flag("current", current)
    validate_flag("autocontinue", autocontinue)
    validate_uint8("mission_type", mission_type)

    hold_time = find_parameter(
        compiled_command,
        "hold_time_seconds",
    )
    acceptance_radius = find_parameter(
        compiled_command,
        "acceptance_radius_meters",
    )
    pass_radius = find_parameter(
        compiled_command,
        "pass_radius_meters",
    )
    yaw = find_parameter(
        compiled_command,
        "yaw_degrees",
    )
    latitude = find_parameter(
        compiled_command,
        "latitude",
    )
    longitude = find_parameter(
        compiled_command,
        "longitude",
    )
    altitude = find_parameter(
        compiled_command,
        "altitude_meters",
    )

    return {
        "message": "MISSION_ITEM_INT",
        "target_system": target_system,
        "target_component": target_component,
        "seq": sequence,
        "frame": frame,
        "command": compiled_command["command_id"],
        "current": current,
        "autocontinue": autocontinue,
        "param1": float(hold_time),
        "param2": float(acceptance_radius),
        "param3": float(pass_radius),
        "param4": float(yaw),
        "x": encode_global_coordinate(latitude, "latitude"),
        "y": encode_global_coordinate(longitude, "longitude"),
        "z": float(altitude),
        "mission_type": mission_type,
    }


def validate_uint8(name: str, value: int) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        or value > 255
    ):
        raise MissionItemEmissionError(
            f"{name} must be an integer from 0 through 255."
        )


def validate_uint16(name: str, value: int) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        or value > 65535
    ):
        raise MissionItemEmissionError(
            f"{name} must be an integer from 0 through 65535."
        )


def validate_flag(name: str, value: int) -> None:
    if value not in {0, 1}:
        raise MissionItemEmissionError(
            f"{name} must be either 0 or 1."
        )


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compile a waypoint and emit MAVLink "
            "MISSION_ITEM_INT fields."
        )
    )

    parser.add_argument(
        "metadata_file",
        type=Path,
        help="Path to MAVLink command metadata YAML.",
    )

    parser.add_argument(
        "command_file",
        type=Path,
        help="Path to the waypoint JSON file.",
    )

    parser.add_argument(
        "--target-system",
        type=int,
        default=1,
        help="MAVLink target system ID. Default: 1.",
    )

    parser.add_argument(
        "--target-component",
        type=int,
        default=1,
        help="MAVLink target component ID. Default: 1.",
    )

    parser.add_argument(
        "--sequence",
        type=int,
        default=0,
        help="Mission sequence number. Default: 0.",
    )

    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()

    try:
        metadata = load_yaml_file(arguments.metadata_file)
        command_instance = load_json_file(arguments.command_file)

        compiled_command = compile_command(
            metadata=metadata,
            command_instance=command_instance,
        )

        mission_item = emit_mission_item_int(
            compiled_command,
            target_system=arguments.target_system,
            target_component=arguments.target_component,
            sequence=arguments.sequence,
        )

        print(json.dumps(mission_item, indent=2))
        return 0

    except (
        CommandMetadataError,
        CommandValidationError,
        MissionItemEmissionError,
    ) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

