"""
Compile a declarative command instance using protocol metadata.

This is an isolated NAVProxy tooling experiment. It does not modify or invoke
the existing NAVProxy flight-launch runtime.

Usage from the NAVProxy project root:

    python -m tooling.compile_command \
        tooling/mavlink_commands.yaml \
        tooling/waypoint.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml


SUPPORTED_PARAMETER_TYPES = {
    "integer",
    "number",
    "string",
    "boolean",
}

SUPPORTED_EMISSION_MESSAGES = {
    "MISSION_ITEM_INT",
}

SUPPORTED_EMISSION_FIELDS = {
    "param1",
    "param2",
    "param3",
    "param4",
    "x",
    "y",
    "z",
}

SUPPORTED_EMISSION_ENCODINGS = {
    "float",
    "integer",
    "degree_e7",
}

SUPPORTED_MAVLINK_FRAMES = {
    "MAV_FRAME_GLOBAL_RELATIVE_ALT",
    "MAV_FRAME_GLOBAL",
}


class CommandMetadataError(ValueError):
    """Raised when protocol metadata is malformed."""


class CommandValidationError(ValueError):
    """Raised when command content does not satisfy its metadata definition."""


def load_yaml_file(path: Path) -> dict[str, Any]:
    """Load and return a YAML document."""

    try:
        with path.open("r", encoding="utf-8") as file:
            data = yaml.safe_load(file)
    except FileNotFoundError as exc:
        raise CommandMetadataError(
            f"Metadata file was not found: {path}"
        ) from exc
    except yaml.YAMLError as exc:
        raise CommandMetadataError(
            f"Metadata file is not valid YAML: {path}"
        ) from exc

    if not isinstance(data, dict):
        raise CommandMetadataError(
            "The metadata root must be a YAML mapping."
        )

    return data


def load_json_file(path: Path) -> dict[str, Any]:
    """Load and return a JSON document."""

    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except FileNotFoundError as exc:
        raise CommandValidationError(
            f"Command file was not found: {path}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise CommandValidationError(
            f"Command file is not valid JSON: {path}"
        ) from exc

    if not isinstance(data, dict):
        raise CommandValidationError(
            "The command root must be a JSON object."
        )

    return data


def validate_metadata(metadata: dict[str, Any]) -> None:
    """Validate the complete protocol metadata structure."""

    protocol = metadata.get("protocol")
    platform = metadata.get("platform")
    commands = metadata.get("commands")

    if not isinstance(protocol, str) or not protocol:
        raise CommandMetadataError(
            "Metadata must contain a non-empty 'protocol' value."
        )

    if not isinstance(platform, str) or not platform:
        raise CommandMetadataError(
            "Metadata must contain a non-empty 'platform' value."
        )

    if not isinstance(commands, dict) or not commands:
        raise CommandMetadataError(
            "Metadata must contain a non-empty 'commands' mapping."
        )

    command_ids: set[int] = set()

    for command_name, command_definition in commands.items():
        validate_command_definition(
            command_name=command_name,
            command_definition=command_definition,
            command_ids=command_ids,
        )


def validate_command_definition(
    *,
    command_name: Any,
    command_definition: Any,
    command_ids: set[int],
) -> None:
    """Validate one command definition from the metadata."""

    if not isinstance(command_name, str) or not command_name:
        raise CommandMetadataError(
            "Every command must have a non-empty string name."
        )

    if not isinstance(command_definition, dict):
        raise CommandMetadataError(
            f"Command '{command_name}' must be a mapping."
        )

    command_id = command_definition.get("id")

    if not isinstance(command_id, int) or isinstance(command_id, bool):
        raise CommandMetadataError(
            f"Command '{command_name}' must have an integer 'id'."
        )

    if command_id < 0:
        raise CommandMetadataError(
            f"Command '{command_name}' must have a non-negative 'id'."
        )

    if command_id in command_ids:
        raise CommandMetadataError(
            f"Command ID {command_id} is defined more than once."
        )

    command_ids.add(command_id)

    validate_command_emission(
        command_name=command_name,
        emission=command_definition.get("emission"),
    )

    parameters = command_definition.get("parameters", [])

    if not isinstance(parameters, list):
        raise CommandMetadataError(
            f"Command '{command_name}' parameters must be a list."
        )

    parameter_names: set[str] = set()
    parameter_positions: set[int] = set()
    emission_fields: set[str] = set()

    for parameter_definition in parameters:
        validate_parameter_definition(
            command_name=command_name,
            parameter_definition=parameter_definition,
            parameter_names=parameter_names,
            parameter_positions=parameter_positions,
            emission_fields=emission_fields,
        )


def validate_command_emission(
    *,
    command_name: str,
    emission: Any,
) -> None:
    """Validate command-level native emission metadata."""

    if not isinstance(emission, dict):
        raise CommandMetadataError(
            f"Command '{command_name}' must contain an 'emission' mapping."
        )

    message = emission.get("message")
    frame = emission.get("frame")

    if message not in SUPPORTED_EMISSION_MESSAGES:
        raise CommandMetadataError(
            f"Command '{command_name}' has unsupported emission message "
            f"'{message}'."
        )

    if frame not in SUPPORTED_MAVLINK_FRAMES:
        raise CommandMetadataError(
            f"Command '{command_name}' has unsupported emission frame "
            f"'{frame}'."
        )

    unknown_keys = set(emission) - {
        "message",
        "frame",
    }

    if unknown_keys:
        unknown_list = ", ".join(sorted(unknown_keys))
        raise CommandMetadataError(
            f"Command '{command_name}' emission contains unsupported "
            f"field(s): {unknown_list}"
        )


def validate_parameter_definition(
    *,
    command_name: str,
    parameter_definition: Any,
    parameter_names: set[str],
    parameter_positions: set[int],
    emission_fields: set[str],
) -> None:
    """Validate one command parameter definition."""

    if not isinstance(parameter_definition, dict):
        raise CommandMetadataError(
            f"Command '{command_name}' contains an invalid parameter."
        )

    name = parameter_definition.get("name")
    position = parameter_definition.get("position")
    parameter_type = parameter_definition.get("type")
    required = parameter_definition.get("required", False)

    if not isinstance(name, str) or not name:
        raise CommandMetadataError(
            f"Command '{command_name}' has a parameter without a valid name."
        )

    if name in parameter_names:
        raise CommandMetadataError(
            f"Command '{command_name}' has duplicate parameter name '{name}'."
        )

    if (
        not isinstance(position, int)
        or isinstance(position, bool)
        or position < 1
    ):
        raise CommandMetadataError(
            f"Parameter '{name}' in command '{command_name}' must have a "
            "positive integer position."
        )

    if position in parameter_positions:
        raise CommandMetadataError(
            f"Command '{command_name}' has duplicate parameter "
            f"position {position}."
        )

    if parameter_type not in SUPPORTED_PARAMETER_TYPES:
        raise CommandMetadataError(
            f"Parameter '{name}' in command '{command_name}' has unsupported "
            f"type '{parameter_type}'."
        )

    if not isinstance(required, bool):
        raise CommandMetadataError(
            f"Parameter '{name}' in command '{command_name}' must have a "
            "boolean 'required' value."
        )

    minimum = parameter_definition.get("minimum")
    maximum = parameter_definition.get("maximum")

    validate_numeric_limit(
        command_name=command_name,
        parameter_name=name,
        parameter_type=parameter_type,
        limit_name="minimum",
        value=minimum,
    )

    validate_numeric_limit(
        command_name=command_name,
        parameter_name=name,
        parameter_type=parameter_type,
        limit_name="maximum",
        value=maximum,
    )

    if (
        minimum is not None
        and maximum is not None
        and minimum > maximum
    ):
        raise CommandMetadataError(
            f"Parameter '{name}' in command '{command_name}' has a minimum "
            "greater than its maximum."
        )

    validate_parameter_emission(
        command_name=command_name,
        parameter_name=name,
        parameter_type=parameter_type,
        emission=parameter_definition.get("emit"),
        emission_fields=emission_fields,
    )

    if "default" in parameter_definition:
        try:
            validate_parameter_value(
                command_name=command_name,
                parameter_definition=parameter_definition,
                value=parameter_definition["default"],
            )
        except CommandValidationError as exc:
            raise CommandMetadataError(
                f"Invalid default for parameter '{name}' in command "
                f"'{command_name}': {exc}"
            ) from exc

    parameter_names.add(name)
    parameter_positions.add(position)


def validate_numeric_limit(
    *,
    command_name: str,
    parameter_name: str,
    parameter_type: str,
    limit_name: str,
    value: Any,
) -> None:
    """Validate a minimum or maximum parameter constraint."""

    if value is None:
        return

    if parameter_type not in {"integer", "number"}:
        raise CommandMetadataError(
            f"Parameter '{parameter_name}' in command '{command_name}' cannot "
            f"define '{limit_name}' because its type is '{parameter_type}'."
        )

    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
    ):
        raise CommandMetadataError(
            f"Parameter '{parameter_name}' in command '{command_name}' has "
            f"a non-numeric '{limit_name}' value."
        )


def validate_parameter_emission(
    *,
    command_name: str,
    parameter_name: str,
    parameter_type: str,
    emission: Any,
    emission_fields: set[str],
) -> None:
    """Validate the native emission mapping for one parameter."""

    if not isinstance(emission, dict):
        raise CommandMetadataError(
            f"Parameter '{parameter_name}' in command '{command_name}' must "
            "contain an 'emit' mapping."
        )

    field = emission.get("field")
    encoding = emission.get("encoding")

    if field not in SUPPORTED_EMISSION_FIELDS:
        raise CommandMetadataError(
            f"Parameter '{parameter_name}' in command '{command_name}' maps "
            f"to unsupported emission field '{field}'."
        )

    if field in emission_fields:
        raise CommandMetadataError(
            f"Command '{command_name}' maps more than one parameter to "
            f"emission field '{field}'."
        )

    if encoding not in SUPPORTED_EMISSION_ENCODINGS:
        raise CommandMetadataError(
            f"Parameter '{parameter_name}' in command '{command_name}' uses "
            f"unsupported emission encoding '{encoding}'."
        )

    validate_encoding_compatibility(
        command_name=command_name,
        parameter_name=parameter_name,
        parameter_type=parameter_type,
        field=field,
        encoding=encoding,
    )

    unknown_keys = set(emission) - {
        "field",
        "encoding",
    }

    if unknown_keys:
        unknown_list = ", ".join(sorted(unknown_keys))
        raise CommandMetadataError(
            f"Parameter '{parameter_name}' in command '{command_name}' emit "
            f"mapping contains unsupported field(s): {unknown_list}"
        )

    emission_fields.add(field)


def validate_encoding_compatibility(
    *,
    command_name: str,
    parameter_name: str,
    parameter_type: str,
    field: str,
    encoding: str,
) -> None:
    """Validate that an emission encoding is appropriate for its parameter."""

    if encoding in {"float", "degree_e7"}:
        if parameter_type not in {"integer", "number"}:
            raise CommandMetadataError(
                f"Parameter '{parameter_name}' in command '{command_name}' "
                f"uses encoding '{encoding}', which requires a numeric type."
            )

    if encoding == "integer" and parameter_type != "integer":
        raise CommandMetadataError(
            f"Parameter '{parameter_name}' in command '{command_name}' uses "
            "'integer' encoding but is not declared as type 'integer'."
        )

    if encoding == "degree_e7" and field not in {"x", "y"}:
        raise CommandMetadataError(
            f"Parameter '{parameter_name}' in command '{command_name}' uses "
            "'degree_e7' encoding but does not map to field 'x' or 'y'."
        )

    if field in {"param1", "param2", "param3", "param4", "z"}:
        if encoding != "float":
            raise CommandMetadataError(
                f"Emission field '{field}' in command '{command_name}' "
                "must use 'float' encoding."
            )


def compile_command(
    metadata: dict[str, Any],
    command_instance: dict[str, Any],
) -> dict[str, Any]:
    """
    Validate a command instance and produce an ordered command record.

    The compiled record preserves the command and parameter emission metadata
    required by a later native emitter.
    """

    validate_metadata(metadata)

    command_name = command_instance.get("command")

    if not isinstance(command_name, str) or not command_name:
        raise CommandValidationError(
            "The command instance must contain a non-empty 'command' value."
        )

    commands = metadata["commands"]

    if command_name not in commands:
        raise CommandValidationError(
            f"Unknown command '{command_name}'."
        )

    supplied_parameters = command_instance.get("parameters", {})

    if not isinstance(supplied_parameters, dict):
        raise CommandValidationError(
            "'parameters' must be a JSON object."
        )

    command_definition = commands[command_name]
    parameter_definitions = command_definition.get("parameters", [])

    known_parameter_names = {
        parameter["name"]
        for parameter in parameter_definitions
    }

    unknown_parameters = (
        set(supplied_parameters)
        - known_parameter_names
    )

    if unknown_parameters:
        unknown_list = ", ".join(sorted(unknown_parameters))
        raise CommandValidationError(
            f"Unknown parameter(s) for '{command_name}': {unknown_list}"
        )

    compiled_parameters: list[dict[str, Any]] = []

    for parameter_definition in sorted(
        parameter_definitions,
        key=lambda item: item["position"],
    ):
        parameter_name = parameter_definition["name"]
        required = parameter_definition.get("required", False)

        if parameter_name in supplied_parameters:
            value = supplied_parameters[parameter_name]
        elif "default" in parameter_definition:
            value = parameter_definition["default"]
        elif required:
            raise CommandValidationError(
                f"Required parameter '{parameter_name}' is missing."
            )
        else:
            value = None

        validate_parameter_value(
            command_name=command_name,
            parameter_definition=parameter_definition,
            value=value,
        )

        compiled_parameters.append(
            {
                "position": parameter_definition["position"],
                "name": parameter_name,
                "type": parameter_definition["type"],
                "value": value,
                "emit": dict(parameter_definition["emit"]),
            }
        )

    return {
        "protocol": metadata["protocol"],
        "platform": metadata["platform"],
        "command": command_name,
        "command_id": command_definition["id"],
        "emission": dict(command_definition["emission"]),
        "parameters": compiled_parameters,
    }


def validate_parameter_value(
    command_name: str,
    parameter_definition: dict[str, Any],
    value: Any,
) -> None:
    """Validate one parameter value against its declared metadata type."""

    parameter_name = parameter_definition["name"]
    parameter_type = parameter_definition["type"]
    required = parameter_definition.get("required", False)

    if value is None:
        if required:
            raise CommandValidationError(
                f"Parameter '{parameter_name}' for '{command_name}' "
                "cannot be null."
            )

        return

    valid = False

    if parameter_type == "integer":
        valid = (
            isinstance(value, int)
            and not isinstance(value, bool)
        )

    elif parameter_type == "number":
        valid = (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
        )

    elif parameter_type == "string":
        valid = isinstance(value, str)

    elif parameter_type == "boolean":
        valid = isinstance(value, bool)

    if not valid:
        raise CommandValidationError(
            f"Parameter '{parameter_name}' for '{command_name}' must be "
            f"of type '{parameter_type}'."
        )

    minimum = parameter_definition.get("minimum")
    maximum = parameter_definition.get("maximum")

    if minimum is not None and value < minimum:
        raise CommandValidationError(
            f"Parameter '{parameter_name}' must be at least {minimum}."
        )

    if maximum is not None and value > maximum:
        raise CommandValidationError(
            f"Parameter '{parameter_name}' must not exceed {maximum}."
        )


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Validate and compile a command instance using protocol metadata."
        )
    )

    parser.add_argument(
        "metadata_file",
        type=Path,
        help="Path to the protocol metadata YAML file.",
    )

    parser.add_argument(
        "command_file",
        type=Path,
        help="Path to the command instance JSON file.",
    )

    return parser.parse_args()


def main() -> int:
    """Run the command compiler."""

    arguments = parse_arguments()

    try:
        metadata = load_yaml_file(arguments.metadata_file)
        command_instance = load_json_file(arguments.command_file)

        compiled_command = compile_command(
            metadata=metadata,
            command_instance=command_instance,
        )

        print(json.dumps(compiled_command, indent=2))
        return 0

    except (
        CommandMetadataError,
        CommandValidationError,
    ) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

