"""Emit an ordered MAVLink mission stream.

This module:

1. Loads the MAVLink command metadata.
2. Loads a declarative command stream.
3. Compiles each command using the existing command compiler.
4. Emits each compiled command using the existing single-command emitter.
5. Assigns contiguous MAVLink mission sequence numbers.

Usage:

Usage:

    python -m tooling.mavlink_emitter \
        tooling/examples/fer_<uuid>.json

"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml

from app.navproxy.tooling.mavlink_compiler import compile_mavlink_command_stream
from app.navproxy.tooling.emit_mission_item_int import emit_mission_item_int


class MissionStreamEmissionError(ValueError):
    """Raised when a compiled command stream cannot be emitted."""


def load_yaml_file(path: str | Path) -> dict[str, Any]:
    """Load a YAML document and require an object at its root."""

    file_path = Path(path)

    try:
        with file_path.open("r", encoding="utf-8") as source_file:
            document = yaml.safe_load(source_file)
    except OSError as exc:
        raise MissionStreamEmissionError(
            f"Unable to read metadata file '{file_path}': {exc}"
        ) from exc
    except yaml.YAMLError as exc:
        raise MissionStreamEmissionError(
            f"Invalid YAML in metadata file '{file_path}': {exc}"
        ) from exc

    if not isinstance(document, dict):
        raise MissionStreamEmissionError(
            "The metadata document must contain an object at its root."
        )

    return document


def load_json_file(path: str | Path) -> dict[str, Any]:
    """Load a JSON document and require an object at its root."""

    file_path = Path(path)

    try:
        with file_path.open("r", encoding="utf-8") as source_file:
            document = json.load(source_file)
    except OSError as exc:
        raise MissionStreamEmissionError(
            f"Unable to read command stream file '{file_path}': {exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise MissionStreamEmissionError(
            f"Invalid JSON in command stream file '{file_path}': {exc}"
        ) from exc

    if not isinstance(document, dict):
        raise MissionStreamEmissionError(
            "The command stream document must contain an object at its root."
        )

    return document


def emit_mission_stream(
    compiled_stream: dict[str, Any],
) -> dict[str, Any]:
    """Emit an ordered list of native MAVLink mission items."""

    compiled_commands = compiled_stream.get("commands")

    if not isinstance(compiled_commands, list):
        raise MissionStreamEmissionError(
            "The compiled command stream must contain a 'commands' array."
        )

    if not compiled_commands:
        raise MissionStreamEmissionError(
            "The compiled command stream must contain at least one command."
        )

    mission_items: list[dict[str, Any]] = []

    for expected_sequence, compiled_command in enumerate(compiled_commands):
        if not isinstance(compiled_command, dict):
            raise MissionStreamEmissionError(
                f"Compiled command at index {expected_sequence} "
                "must be an object."
            )

        sequence = compiled_command.get("sequence")

        if sequence is None:
            raise MissionStreamEmissionError(
                f"Compiled command at index {expected_sequence} "
                "does not contain a sequence number."
            )

        if not isinstance(sequence, int):
            raise MissionStreamEmissionError(
                f"Sequence for command at index {expected_sequence} "
                "must be an integer."
            )

        if sequence != expected_sequence:
            raise MissionStreamEmissionError(
                "Command stream sequence is not contiguous: "
                f"expected {expected_sequence}, received {sequence}."
            )

        command_name = compiled_command.get("command", "<unknown>")

        try:
            mission_item = emit_mission_item_int(compiled_command)
        except Exception as exc:
            raise MissionStreamEmissionError(
                f"Unable to emit command '{command_name}' "
                f"at sequence {sequence}: {exc}"
            ) from exc

        if not isinstance(mission_item, dict):
            raise MissionStreamEmissionError(
                f"Emitter returned an invalid result for command "
                f"'{command_name}' at sequence {sequence}."
            )

        emitted_message = mission_item.get("message")

        if emitted_message != "MISSION_ITEM_INT":
            raise MissionStreamEmissionError(
                f"Command '{command_name}' at sequence {sequence} emitted "
                f"unsupported message type '{emitted_message}'."
            )

        mission_item["seq"] = sequence
        mission_items.append(mission_item)

    return {
        "protocol": compiled_stream.get("protocol"),
        "platform": compiled_stream.get("platform"),
        "mission_type": 0,
        "item_count": len(mission_items),
        "items": mission_items,
    }


def main() -> int:
    """Run the complete command-stream compilation and emission pipeline."""

    if len(sys.argv) != 2:
        print(
            "Usage: python -m tooling.mavlink_emitter "
            "<fer_*.json>",
            file=sys.stderr,
        )
        return 2

    command_stream_path = sys.argv[1]

    metadata_path = (
        Path(__file__).parent
        / "metadata"
        / "mavlink_commands.yaml"
    )

    try:
        metadata = load_yaml_file(metadata_path)
        declarative_stream = load_json_file(command_stream_path)

        compiled_stream = compile_mavlink_command_stream(
            metadata,
            declarative_stream,
        )

        emitted_stream = emit_mission_stream(compiled_stream)

    except Exception as exc:
        print(
            f"Mission stream emission failed: {exc}",
            file=sys.stderr,
        )
        return 1

    print(json.dumps(emitted_stream, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

