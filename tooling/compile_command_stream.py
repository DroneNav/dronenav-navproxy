"""Compile an ordered stream of declarative MAVLink commands.

Usage:

    python -m tooling.compile_command_stream \
        tooling/metadata/mavlink_commands.yaml \
        tooling/examples/takeoff_waypoint_stream.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml

from tooling.compile_command import compile_command


class CommandStreamCompilationError(ValueError):
    """Raised when a declarative command stream cannot be compiled."""


def load_yaml_file(path: str | Path) -> dict[str, Any]:
    """Load a YAML document and require a mapping at its root."""

    file_path = Path(path)

    try:
        with file_path.open("r", encoding="utf-8") as source_file:
            document = yaml.safe_load(source_file)
    except OSError as exc:
        raise CommandStreamCompilationError(
            f"Unable to read metadata file '{file_path}': {exc}"
        ) from exc
    except yaml.YAMLError as exc:
        raise CommandStreamCompilationError(
            f"Invalid YAML in metadata file '{file_path}': {exc}"
        ) from exc

    if not isinstance(document, dict):
        raise CommandStreamCompilationError(
            "The metadata document must contain a mapping at its root."
        )

    return document


def load_json_file(path: str | Path) -> dict[str, Any]:
    """Load a JSON document and require a mapping at its root."""

    file_path = Path(path)

    try:
        with file_path.open("r", encoding="utf-8") as source_file:
            document = json.load(source_file)
    except OSError as exc:
        raise CommandStreamCompilationError(
            f"Unable to read command stream file '{file_path}': {exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise CommandStreamCompilationError(
            f"Invalid JSON in command stream file '{file_path}': {exc}"
        ) from exc

    if not isinstance(document, dict):
        raise CommandStreamCompilationError(
            "The command stream document must contain an object at its root."
        )

    return document


def compile_command_stream(
    metadata: dict[str, Any],
    command_stream: dict[str, Any],
) -> dict[str, Any]:
    """Compile every command in an ordered declarative command stream."""

    flight_execution = command_stream.get("flight_execution")
    commands = command_stream.get("commands")

    if not isinstance(flight_execution, dict):
        raise CommandStreamCompilationError(
            "The command stream must contain a 'flight_execution' object."
        )

    if not isinstance(commands, list):
        raise CommandStreamCompilationError(
            "The command stream must contain a 'commands' array."
        )

    compiled_commands: list[dict[str, Any]] = []

    for sequence, command_instance in enumerate(commands):
        if not isinstance(command_instance, dict):
            raise CommandStreamCompilationError(
                f"Command at sequence {sequence} must be a JSON object."
            )

        try:
            compiled_command = compile_command(metadata, command_instance)
        except Exception as exc:
            raise CommandStreamCompilationError(
                f"Unable to compile command at sequence {sequence}: {exc}"
            ) from exc

        compiled_command["sequence"] = sequence
        compiled_commands.append(compiled_command)

    return {
        "flight_execution": flight_execution,
        "protocol": metadata.get("protocol"),
        "platform": metadata.get("platform"),
        "command_count": len(compiled_commands),
        "commands": compiled_commands,
    }


def main() -> int:
    """Command-line entry point."""

    if len(sys.argv) != 3:
        print(
            "Usage: python -m tooling.compile_command_stream "
            "<metadata.yaml> <command_stream.json>",
            file=sys.stderr,
        )
        return 2

    metadata_path = sys.argv[1]
    stream_path = sys.argv[2]

    try:
        metadata = load_yaml_file(metadata_path)
        command_stream = load_json_file(stream_path)

        compiled_stream = compile_command_stream(
            metadata=metadata,
            command_stream=command_stream,
        )
    except CommandStreamCompilationError as exc:
        print(f"Command stream compilation failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(compiled_stream, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

