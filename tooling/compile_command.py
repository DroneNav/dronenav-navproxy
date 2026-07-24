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
    """Validate the protocol metadata structure."""

    commands = metadata.get("commands")

    if not isinstance(commands, dict) or not commands:
        raise CommandMetadataError(
            "Metadata must contain a non-empty 'commands' mapping."
        )

    for command_name, command_definition in commands.items():
        if not isinstance(command_name, str) or not command_name:
            raise CommandMetadataError(
                "Every command must have a non-empty string name."
            )

        if not isinstance(command_definition, dict):
            raise CommandMetadataError(
                f"Command '{command_name}' must be a mapping."
            )

        command_id = command_definition.get("id")

        if not isinstance(command_id, int):
            raise CommandMetadataError(
                f"Command '{command_name}' must have an integer 'id'."
            )

        parameters = command_definition.get("parameters", [])

        if not isinstance(parameters, list):
            raise CommandMetadataError(
                f"Command '{command_name}' parameters must be a list."
            )

        parameter_names: set[str] = set()
        parameter_positions: set[int] = set()

        for parameter in parameters:
            if not isinstance(parameter, dict):
                raise CommandMetadataError(
                    f"Command '{command_name}' contains an invalid parameter."
                )

            name = parameter.get("name")
            position = parameter.get("position")
            parameter_type = parameter.get("type")

            if not isinstance(name, str) or not name:
                raise CommandMetadataError(
                    f"Command '{command_name}' has a parameter without a "
                    "valid name."
                )

            if name in parameter_names:
                raise CommandMetadataError(
                    f"Command '{command_name}' has duplicate parameter "
                    f"name '{name}'."
                )

            if not isinstance(position, int) or position < 1:
                raise CommandMetadataError(
                    f"Parameter '{name}' in command '{command_name}' must "
                    "have a positive integer position."
                )

            if position in parameter_positions:
                raise CommandMetadataError(
                    f"Command '{command_name}' has duplicate parameter "
                    f"position {position}."
                )

            if parameter_type not in {"integer", "number", "string", "boolean"}:
                raise CommandMetadataError(
                    f"Parameter '{name}' in command '{command_name}' has "
                    f"unsupported type '{parameter_type}'."
                )

            parameter_names.add(name)
            parameter_positions.add(position)


def compile_command(
    metadata: dict[str, Any],
    command_instance: dict[str, Any],
) -> dict[str, Any]:
    """
    Validate a command instance and produce an ordered command record.
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
        parameter["name"] for parameter in parameter_definitions
    }

    unknown_parameters = set(supplied_parameters) - known_parameter_names

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
                "value": value,
            }
        )

    return {
        "protocol": metadata.get("protocol"),
        "platform": metadata.get("platform"),
        "command": command_name,
        "command_id": command_definition["id"],
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
        valid = isinstance(value, int) and not isinstance(value, bool)

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

    except (CommandMetadataError, CommandValidationError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

