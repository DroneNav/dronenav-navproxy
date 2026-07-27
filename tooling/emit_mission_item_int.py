"""
Emit an ArduPilot-compatible MAVLink MISSION_ITEM_INT representation.

This tool does not connect to an aircraft and does not alter the existing
NAVProxy runtime. It compiles a declarative command and emits the exact field
structure required by MAVLink MISSION_ITEM_INT.

Usage from the NAVProxy project directory:

Usage:

    python -m tooling.emit_mission_item_int \
        tooling/examples/<command_name>.json
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
MAVLINK_FRAME_VALUES = {
    "MAV_FRAME_GLOBAL_RELATIVE_ALT": 3,
}

MAV_MISSION_TYPE_MISSION = 0

INT32_MIN = -(2**31)
INT32_MAX = (2**31) - 1


class MissionItemEmissionError(ValueError):
    """Raised when a compiled command cannot become MISSION_ITEM_INT."""


def encode_float(value: Any, parameter_name: str) -> float:
    """Encode a numeric parameter as a finite floating-point value."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MissionItemEmissionError(
            f"Parameter '{parameter_name}' must be numeric for float encoding."
        )

    encoded_value = float(value)

    if not math.isfinite(encoded_value):
        raise MissionItemEmissionError(
            f"Parameter '{parameter_name}' must be finite."
        )

    return encoded_value


def encode_integer(value: Any, parameter_name: str) -> int:
    """Encode a parameter as an integer."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise MissionItemEmissionError(
            f"Parameter '{parameter_name}' must be an integer."
        )

    return value


def encode_degree_e7(value: Any, parameter_name: str) -> int:
    """
    Encode a global coordinate as a MAVLink degree-E7 integer.

    MISSION_ITEM_INT stores global latitude and longitude as degrees
    multiplied by 10^7.
    """

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MissionItemEmissionError(
            f"Parameter '{parameter_name}' must be numeric for "
            "degree-E7 encoding."
        )

    numeric_value = float(value)

    if not math.isfinite(numeric_value):
        raise MissionItemEmissionError(
            f"Parameter '{parameter_name}' must be finite."
        )

    encoded_value = round(numeric_value * 10_000_000)

    if encoded_value < INT32_MIN or encoded_value > INT32_MAX:
        raise MissionItemEmissionError(
            f"Parameter '{parameter_name}' cannot be represented as an int32."
        )

    return encoded_value


def encode_parameter(
    value: Any,
    encoding: str,
    parameter_name: str,
) -> int | float:
    """Encode a parameter according to its compiled emission metadata."""

    if value is None:
        raise MissionItemEmissionError(
            f"Parameter '{parameter_name}' has no value. A parameter mapped "
            "to MISSION_ITEM_INT must be required or define a default."
        )

    if encoding == "float":
        return encode_float(value, parameter_name)

    if encoding == "integer":
        return encode_integer(value, parameter_name)

    if encoding == "degree_e7":
        return encode_degree_e7(value, parameter_name)

    raise MissionItemEmissionError(
        f"Parameter '{parameter_name}' uses unsupported encoding "
        f"'{encoding}'."
    )


def resolve_frame(frame_name: Any) -> int:
    """Resolve a MAVLink frame name from compiled emission metadata."""

    if not isinstance(frame_name, str) or not frame_name:
        raise MissionItemEmissionError(
            "Compiled command emission metadata must contain a frame name."
        )

    try:
        return MAVLINK_FRAME_VALUES[frame_name]
    except KeyError as exc:
        raise MissionItemEmissionError(
            f"Unsupported MAVLink frame '{frame_name}'."
        ) from exc


def emit_mission_item_int(
    compiled_command: dict[str, Any],
    *,
    target_system: int = 1,
    target_component: int = 1,
    sequence: int = 0,
    current: int = 0,
    autocontinue: int = 1,
    mission_type: int = MAV_MISSION_TYPE_MISSION,
) -> dict[str, Any]:
    """
    Convert a compiled command into MAVLink MISSION_ITEM_INT fields.

    Command-specific field mappings and encodings are obtained entirely from
    the compiled intermediate representation.
    """

    validate_uint8("target_system", target_system)
    validate_uint8("target_component", target_component)
    validate_uint16("sequence", sequence)
    validate_flag("current", current)
    validate_flag("autocontinue", autocontinue)
    validate_uint8("mission_type", mission_type)

    emission = compiled_command.get("emission")

    if not isinstance(emission, dict):
        raise MissionItemEmissionError(
            "Compiled command does not contain valid emission metadata."
        )

    message_name = emission.get("message")

    if message_name != "MISSION_ITEM_INT":
        raise MissionItemEmissionError(
            f"Unsupported emission message '{message_name}'."
        )

    frame = resolve_frame(emission.get("frame"))

    command_id = compiled_command.get("command_id")

    if (
        isinstance(command_id, bool)
        or not isinstance(command_id, int)
        or command_id < 0
        or command_id > 65535
    ):
        raise MissionItemEmissionError(
            "Compiled command ID must be an integer from 0 through 65535."
        )

    parameters = compiled_command.get("parameters")

    if not isinstance(parameters, list):
        raise MissionItemEmissionError(
            "Compiled command parameters must be a list."
        )

    # Complete MISSION_ITEM_INT envelope. Parameter fields begin with their
    # native zero values and are populated from compiled emission metadata.
    mission_item: dict[str, Any] = {
        "message": "MISSION_ITEM_INT",
        "target_system": target_system,
        "target_component": target_component,
        "seq": sequence,
        "frame": frame,
        "command": command_id,
        "current": current,
        "autocontinue": autocontinue,
        "param1": 0.0,
        "param2": 0.0,
        "param3": 0.0,
        "param4": 0.0,
        "x": 0,
        "y": 0,
        "z": 0.0,
        "mission_type": mission_type,
    }

    emitted_fields: set[str] = set()

    for parameter in parameters:
        if not isinstance(parameter, dict):
            raise MissionItemEmissionError(
                "Compiled command contains an invalid parameter record."
            )

        parameter_name = parameter.get("name")

        if not isinstance(parameter_name, str) or not parameter_name:
            raise MissionItemEmissionError(
                "Compiled parameter does not contain a valid name."
            )

        parameter_emission = parameter.get("emit")

        if not isinstance(parameter_emission, dict):
            raise MissionItemEmissionError(
                f"Parameter '{parameter_name}' does not contain valid "
                "emission metadata."
            )

        destination_field = parameter_emission.get("field")
        encoding = parameter_emission.get("encoding")

        if destination_field not in {
            "param1",
            "param2",
            "param3",
            "param4",
            "x",
            "y",
            "z",
        }:
            raise MissionItemEmissionError(
                f"Parameter '{parameter_name}' maps to unsupported "
                f"MISSION_ITEM_INT field '{destination_field}'."
            )

        if destination_field in emitted_fields:
            raise MissionItemEmissionError(
                f"More than one parameter maps to MISSION_ITEM_INT field "
                f"'{destination_field}'."
            )

        if not isinstance(encoding, str) or not encoding:
            raise MissionItemEmissionError(
                f"Parameter '{parameter_name}' does not define an encoding."
            )

        mission_item[destination_field] = encode_parameter(
            value=parameter.get("value"),
            encoding=encoding,
            parameter_name=parameter_name,
        )

        emitted_fields.add(destination_field)

    return mission_item


def validate_uint8(name: str, value: int) -> None:
    """Validate an unsigned 8-bit integer."""

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
    """Validate an unsigned 16-bit integer."""

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
    """Validate a MAVLink binary flag."""

    if isinstance(value, bool) or value not in {0, 1}:
        raise MissionItemEmissionError(
            f"{name} must be either 0 or 1."
        )


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Compile a declarative command and emit MAVLink "
            "MISSION_ITEM_INT fields."
        )
    )

    parser.add_argument(
        "command_file",
        type=Path,
        help="Path to the declarative command JSON file.",
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
    """Compile the command and emit MISSION_ITEM_INT fields."""

    arguments = parse_arguments()

    try:
        metadata_path = (
            Path(__file__).parent
            / "metadata"
            / "mavlink_commands.yaml"
        )

        metadata = load_yaml_file(metadata_path)
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

