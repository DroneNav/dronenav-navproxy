"""Compile, emit, and upload a declarative MAVLink mission stream.

The uploader is command-agnostic. It performs only these responsibilities:

1. Load command metadata and a declarative command stream.
2. Compile the stream using the existing stream compiler.
3. Emit native MISSION_ITEM_INT dictionaries using the existing stream emitter.
4. Upload the emitted items using the MAVLink mission protocol.

Usage:

    python -m tooling.upload_mission \
        tooling/metadata/mavlink_commands.yaml \
        tooling/examples/takeoff_waypoint_stream.json \
        tcp:127.0.0.1:15762
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

from pymavlink import mavutil

from app.navproxy.tooling.mavlink_compiler import (
    compile_mavlink_command_stream,
    load_json_file,
    load_yaml_file,
)
from app.navproxy.tooling.mavlink_emitter import (
    emit_mission_stream,
)

class MissionUploadError(RuntimeError):
    """Raised when a MAVLink mission cannot be uploaded."""


DEFAULT_CONNECTION = "tcp:127.0.0.1:15762"
DEFAULT_HEARTBEAT_TIMEOUT_SECONDS = 15.0
DEFAULT_REQUEST_TIMEOUT_SECONDS = 5.0
DEFAULT_UPLOAD_TIMEOUT_SECONDS = 60.0
DEFAULT_MAX_COUNT_RETRIES = 3


def validate_emitted_mission(
    emitted_stream: dict[str, Any],
) -> list[dict[str, Any]]:
    """Validate and return the native mission items."""

    items = emitted_stream.get("items")

    if not isinstance(items, list):
        raise MissionUploadError(
            "The emitted mission stream must contain an 'items' array."
        )

    if not items:
        raise MissionUploadError(
            "The emitted mission stream must contain at least one item."
        )

    for expected_sequence, item in enumerate(items):
        if not isinstance(item, dict):
            raise MissionUploadError(
                f"Mission item at index {expected_sequence} must be an object."
            )

        message_type = item.get("message")

        if message_type != "MISSION_ITEM_INT":
            raise MissionUploadError(
                f"Mission item {expected_sequence} has unsupported "
                f"message type '{message_type}'."
            )

        sequence = item.get("seq")

        if sequence != expected_sequence:
            raise MissionUploadError(
                "Mission sequence is not contiguous: "
                f"expected {expected_sequence}, received {sequence}."
            )

    return items


def connect_vehicle(
    connection_string: str,
    heartbeat_timeout_seconds: float,
) -> mavutil.mavfile:
    """Connect to the vehicle and wait for its heartbeat."""

    connection = mavutil.mavlink_connection(
        connection_string,
        autoreconnect=False,
    )

    heartbeat = connection.wait_heartbeat(
        timeout=heartbeat_timeout_seconds,
    )

    if heartbeat is None:
        raise MissionUploadError(
            "Timed out waiting for a vehicle heartbeat."
        )

    return connection


def send_mission_count(
    connection: mavutil.mavfile,
    item_count: int,
    mission_type: int,
) -> None:
    """Announce the number of mission items available for upload."""

    connection.mav.mission_count_send(
        connection.target_system,
        connection.target_component,
        item_count,
        mission_type,
    )


def send_mission_item_int(
    connection: mavutil.mavfile,
    item: dict[str, Any],
) -> None:
    """Send one emitted native MISSION_ITEM_INT."""

    connection.mav.mission_item_int_send(
        int(item["target_system"]),
        int(item["target_component"]),
        int(item["seq"]),
        int(item["frame"]),
        int(item["command"]),
        int(item["current"]),
        int(item["autocontinue"]),
        float(item["param1"]),
        float(item["param2"]),
        float(item["param3"]),
        float(item["param4"]),
        int(item["x"]),
        int(item["y"]),
        float(item["z"]),
        int(item["mission_type"]),
    )


def describe_ack_result(result: int) -> str:
    """Return a readable MAV_MISSION_RESULT name when available."""

    enum_entries = mavutil.mavlink.enums.get("MAV_MISSION_RESULT", {})
    enum_entry = enum_entries.get(result)

    if enum_entry is None:
        return f"UNKNOWN_RESULT_{result}"

    return enum_entry.name


def upload_mission(
    connection: mavutil.mavfile,
    items: list[dict[str, Any]],
    mission_type: int = 0,
    request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    upload_timeout_seconds: float = DEFAULT_UPLOAD_TIMEOUT_SECONDS,
    max_count_retries: int = DEFAULT_MAX_COUNT_RETRIES,
) -> None:
    """Upload native mission items using the MAVLink mission protocol."""

    item_count = len(items)
    upload_started_at = time.monotonic()
    count_attempts = 0
    sent_sequences: set[int] = set()

    send_mission_count(
        connection=connection,
        item_count=item_count,
        mission_type=mission_type,
    )
    count_attempts += 1

    while True:
        elapsed_seconds = time.monotonic() - upload_started_at

        if elapsed_seconds > upload_timeout_seconds:
            raise MissionUploadError(
                "Mission upload timed out after "
                f"{upload_timeout_seconds:.1f} seconds."
            )

        message = connection.recv_match(
            type=[
                "MISSION_REQUEST_INT",
                "MISSION_REQUEST",
                "MISSION_ACK",
            ],
            blocking=True,
            timeout=request_timeout_seconds,
        )

        if message is None:
            if not sent_sequences and count_attempts < max_count_retries:
                count_attempts += 1

                print(
                    "No mission request received; resending "
                    f"MISSION_COUNT ({count_attempts}/{max_count_retries})."
                )

                send_mission_count(
                    connection=connection,
                    item_count=item_count,
                    mission_type=mission_type,
                )
                continue

            raise MissionUploadError(
                "Timed out waiting for the next mission request or "
                "MISSION_ACK."
            )

        message_type = message.get_type()

        if message_type in {"MISSION_REQUEST_INT", "MISSION_REQUEST"}:
            requested_sequence = int(message.seq)

            if requested_sequence < 0 or requested_sequence >= item_count:
                raise MissionUploadError(
                    "Vehicle requested invalid mission sequence "
                    f"{requested_sequence}; valid range is "
                    f"0 through {item_count - 1}."
                )

            requested_mission_type = int(
                getattr(message, "mission_type", mission_type)
            )

            if requested_mission_type != mission_type:
                raise MissionUploadError(
                    "Vehicle requested mission type "
                    f"{requested_mission_type}, but this upload is mission "
                    f"type {mission_type}."
                )

            item = items[requested_sequence]

            # Use the connected vehicle as the actual destination.
            item_to_send = dict(item)
            item_to_send["target_system"] = connection.target_system
            item_to_send["target_component"] = connection.target_component
            item_to_send["mission_type"] = mission_type

            send_mission_item_int(
                connection=connection,
                item=item_to_send,
            )

            sent_sequences.add(requested_sequence)
            continue

        if message_type == "MISSION_ACK":
            result = int(message.type)
            result_name = describe_ack_result(result)

            if result != mavutil.mavlink.MAV_MISSION_ACCEPTED:
                raise MissionUploadError(
                    "Vehicle rejected the mission: "
                    f"{result_name} ({result})."
                )

            missing_sequences = sorted(
                set(range(item_count)) - sent_sequences
            )

            if missing_sequences:
                raise MissionUploadError(
                    "Vehicle acknowledged the mission before requesting "
                    f"all items. Missing sequences: {missing_sequences}."
                )

            print(
                "Mission upload accepted by the vehicle: "
                f"{result_name} ({result})."
            )
            return


def build_emitted_mission(
    metadata_path: str | Path,
    command_stream_path: str | Path,
) -> dict[str, Any]:
    """Run the existing compiler and emitter pipeline."""

    metadata = load_yaml_file(metadata_path)
    declarative_stream = load_json_file(command_stream_path)

    compiled_stream = compile_mavlink_command_stream(
        metadata,
        declarative_stream,
    )

    return emit_mission_stream(compiled_stream)


def main() -> int:
    """Command-line entry point."""

    if len(sys.argv) not in {3, 4}:
        print(
            "Usage: python -m tooling.upload_mission "
            "<metadata.yaml> <command_stream.json> "
            "[connection_string]",
            file=sys.stderr,
        )
        return 2

    metadata_path = sys.argv[1]
    command_stream_path = sys.argv[2]

    connection_string = (
        sys.argv[3]
        if len(sys.argv) == 4
        else DEFAULT_CONNECTION
    )

    try:
        emitted_stream = build_emitted_mission(
            metadata_path=metadata_path,
            command_stream_path=command_stream_path,
        )

        items = validate_emitted_mission(emitted_stream)

        mission_type = int(
            emitted_stream.get(
                "mission_type",
                mavutil.mavlink.MAV_MISSION_TYPE_MISSION,
            )
        )

        connection = connect_vehicle(
            connection_string=connection_string,
            heartbeat_timeout_seconds=(
                DEFAULT_HEARTBEAT_TIMEOUT_SECONDS
            ),
        )

        upload_mission(
            connection=connection,
            items=items,
            mission_type=mission_type,
        )

    except Exception as exc:
        print(f"Mission upload failed: {exc}", file=sys.stderr)
        return 1

    print("Mission upload complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

