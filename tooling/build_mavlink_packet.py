"""
Compile a declarative waypoint into a real MAVLink 2 MISSION_ITEM_INT packet.

This tool:

1. Loads the YAML command metadata.
2. Loads the JSON waypoint.
3. Compiles and validates the waypoint.
4. Emits MISSION_ITEM_INT fields.
5. Creates a real pymavlink message object.
6. Serializes the message into MAVLink 2 binary bytes.

It does not connect to ArduPilot or alter the NAVProxy runtime.

Run from the navproxy directory:

    python -m tooling.build_mavlink_packet \
        metadata/mavlink_commands.yaml \
        examples/waypoint.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pymavlink.dialects.v20 import common as mavlink2

from app.navproxy.tooling.compile_command import (
    CommandMetadataError,
    CommandValidationError,
    compile_command,
    load_json_file,
    load_yaml_file,
)
from app.navproxy.tooling.emit_mission_item_int import (
    MissionItemEmissionError,
    emit_mission_item_int,
)


class PacketBuildError(ValueError):
    """Raised when a MAVLink packet cannot be constructed."""


def build_mavlink_message(
    mission_item: dict[str, Any],
) -> mavlink2.MAVLink_mission_item_int_message:
    """Create a real pymavlink MISSION_ITEM_INT message."""

    try:
        return mavlink2.MAVLink_mission_item_int_message(
            target_system=mission_item["target_system"],
            target_component=mission_item["target_component"],
            seq=mission_item["seq"],
            frame=mission_item["frame"],
            command=mission_item["command"],
            current=mission_item["current"],
            autocontinue=mission_item["autocontinue"],
            param1=mission_item["param1"],
            param2=mission_item["param2"],
            param3=mission_item["param3"],
            param4=mission_item["param4"],
            x=mission_item["x"],
            y=mission_item["y"],
            z=mission_item["z"],
            mission_type=mission_item["mission_type"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise PacketBuildError(
            f"Could not construct MISSION_ITEM_INT: {exc}"
        ) from exc


def serialize_message(
    message: mavlink2.MAVLink_mission_item_int_message,
    *,
    source_system: int = 255,
    source_component: int = 190,
) -> bytes:
    """
    Serialize the message into a complete MAVLink 2 packet.

    System 255 and component 190 conventionally represent a ground-control
    application. They are configurable here because NAVProxy may later use
    its own component identity.
    """

    if not 0 <= source_system <= 255:
        raise PacketBuildError(
            "source_system must be between 0 and 255."
        )

    if not 0 <= source_component <= 255:
        raise PacketBuildError(
            "source_component must be between 0 and 255."
        )

    mavlink = mavlink2.MAVLink(
        file=None,
        srcSystem=source_system,
        srcComponent=source_component,
    )

    return message.pack(mavlink)


def parse_packet(packet: bytes) -> Any:
    """
    Parse the generated packet again.

    This round-trip verifies that pymavlink recognizes the serialized bytes
    as a valid MAVLink message.
    """

    parser = mavlink2.MAVLink(file=None)

    decoded_message = None

    for byte in packet:
        result = parser.parse_char(bytes([byte]))

        if result is not None:
            decoded_message = result

    if decoded_message is None:
        raise PacketBuildError(
            "The generated packet could not be parsed back into a message."
        )

    return decoded_message


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compile a waypoint and serialize it as a MAVLink 2 "
            "MISSION_ITEM_INT packet."
        )
    )

    parser.add_argument(
        "metadata_file",
        type=Path,
        help="Path to the MAVLink command metadata YAML file.",
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
        help="Target ArduPilot system ID. Default: 1.",
    )

    parser.add_argument(
        "--target-component",
        type=int,
        default=1,
        help="Target ArduPilot component ID. Default: 1.",
    )

    parser.add_argument(
        "--source-system",
        type=int,
        default=255,
        help="Source MAVLink system ID. Default: 255.",
    )

    parser.add_argument(
        "--source-component",
        type=int,
        default=190,
        help="Source MAVLink component ID. Default: 190.",
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

        message = build_mavlink_message(mission_item)

        packet = serialize_message(
            message,
            source_system=arguments.source_system,
            source_component=arguments.source_component,
        )

        decoded_message = parse_packet(packet)

        result = {
            "compiled_command": compiled_command,
            "mission_item": mission_item,
            "mavlink_message_type": message.get_type(),
            "mavlink_message_id": message.get_msgId(),
            "packet_length_bytes": len(packet),
            "packet_hex": packet.hex(" "),
            "round_trip_message": decoded_message.to_dict(),
        }

        print(json.dumps(result, indent=2))
        return 0

    except (
        CommandMetadataError,
        CommandValidationError,
        MissionItemEmissionError,
        PacketBuildError,
    ) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

