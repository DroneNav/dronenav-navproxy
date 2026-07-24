"""
Download a mission from ArduPilot and compare mission item 1 with the
metadata-generated waypoint.

This is an isolated R&D verification tool. It does not alter the NAVProxy
runtime or execute the stored mission.

Example:

    python -m tooling.download_test_mission \
        tooling/metadata/mavlink_commands.yaml \
        tooling/examples/waypoint.json \
        --connection tcp:127.0.0.1:15762
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Any

from pymavlink import mavutil

from tooling.compile_command import (
    CommandMetadataError,
    CommandValidationError,
    compile_command,
    load_json_file,
    load_yaml_file,
)
from tooling.emit_mission_item_int import (
    MissionItemEmissionError,
    emit_mission_item_int,
)
from tooling.upload_test_mission import (
    MissionUploadError,
    connect_to_ardupilot,
)


class MissionDownloadError(RuntimeError):
    """Raised when the mission cannot be downloaded or verified."""


def request_mission_count(
    connection: mavutil.mavfile,
    *,
    timeout: float,
) -> int:
    """Request the stored mission list and return its item count."""

    print("Sending MISSION_REQUEST_LIST...")

    connection.mav.mission_request_list_send(
        connection.target_system,
        connection.target_component,
        mavutil.mavlink.MAV_MISSION_TYPE_MISSION,
    )

    response = connection.recv_match(
        type="MISSION_COUNT",
        blocking=True,
        timeout=timeout,
    )

    if response is None:
        raise MissionDownloadError(
            "Timed out waiting for MISSION_COUNT."
        )

    count = int(response.count)

    print(f"Received MISSION_COUNT count={count}.")

    return count


def request_mission_item(
    connection: mavutil.mavfile,
    *,
    sequence: int,
    timeout: float,
) -> Any:
    """Request one mission item using integer-coordinate mission format."""

    print(
        f"Sending MISSION_REQUEST_INT sequence={sequence}..."
    )

    connection.mav.mission_request_int_send(
        connection.target_system,
        connection.target_component,
        sequence,
        mavutil.mavlink.MAV_MISSION_TYPE_MISSION,
    )

    response = connection.recv_match(
        type=[
            "MISSION_ITEM_INT",
            "MISSION_ITEM",
            "MISSION_ACK",
        ],
        blocking=True,
        timeout=timeout,
    )

    if response is None:
        raise MissionDownloadError(
            f"Timed out waiting for mission item {sequence}."
        )

    response_type = response.get_type()

    if response_type == "MISSION_ACK":
        result = int(response.type)

        raise MissionDownloadError(
            "ArduPilot returned MISSION_ACK instead of the requested "
            f"mission item. Result={result}."
        )

    if int(response.seq) != sequence:
        raise MissionDownloadError(
            "Received an unexpected mission sequence. "
            f"Expected {sequence}, received {response.seq}."
        )

    print(
        f"Received {response_type} sequence={response.seq}."
    )

    return response


def acknowledge_download(
    connection: mavutil.mavfile,
) -> None:
    """Tell ArduPilot that the complete mission was received."""

    print("Sending MISSION_ACK MAV_MISSION_ACCEPTED...")

    connection.mav.mission_ack_send(
        connection.target_system,
        connection.target_component,
        mavutil.mavlink.MAV_MISSION_ACCEPTED,
        mavutil.mavlink.MAV_MISSION_TYPE_MISSION,
    )


def normalize_downloaded_item(message: Any) -> dict[str, Any]:
    """
    Convert either MISSION_ITEM_INT or legacy MISSION_ITEM into a common
    semantic representation.
    """

    message_type = message.get_type()

    if message_type == "MISSION_ITEM_INT":
        latitude = int(message.x) / 10_000_000
        longitude = int(message.y) / 10_000_000
        raw_x = int(message.x)
        raw_y = int(message.y)

    elif message_type == "MISSION_ITEM":
        latitude = float(message.x)
        longitude = float(message.y)
        raw_x = round(latitude * 10_000_000)
        raw_y = round(longitude * 10_000_000)

    else:
        raise MissionDownloadError(
            f"Unsupported downloaded message type: {message_type}"
        )

    return {
        "message_type": message_type,
        "seq": int(message.seq),
        "frame": int(message.frame),
        "command": int(message.command),
        "current": int(message.current),
        "autocontinue": int(message.autocontinue),
        "param1": float(message.param1),
        "param2": float(message.param2),
        "param3": float(message.param3),
        "param4": float(message.param4),
        "x": raw_x,
        "y": raw_y,
        "latitude": latitude,
        "longitude": longitude,
        "z": float(message.z),
        "mission_type": int(
            getattr(
                message,
                "mission_type",
                mavutil.mavlink.MAV_MISSION_TYPE_MISSION,
            )
        ),
    }


def build_expected_item(
    metadata_file: Path,
    command_file: Path,
    *,
    target_system: int,
    target_component: int,
) -> dict[str, Any]:
    """Compile the source files and emit the expected mission item."""

    metadata = load_yaml_file(metadata_file)
    command_instance = load_json_file(command_file)

    compiled_command = compile_command(
        metadata=metadata,
        command_instance=command_instance,
    )

    emitted = emit_mission_item_int(
        compiled_command,
        target_system=target_system,
        target_component=target_component,
        sequence=1,
    )

    return emitted


def float_matches(
    expected: float,
    actual: float,
    *,
    tolerance: float,
) -> bool:
    """Compare floating-point values with an absolute tolerance."""

    return math.isclose(
        float(expected),
        float(actual),
        rel_tol=0.0,
        abs_tol=tolerance,
    )


def compare_items(
    expected: dict[str, Any],
    actual: dict[str, Any],
) -> list[str]:
    """Compare expected and downloaded mission semantics."""

    differences: list[str] = []

    exact_fields = (
        "seq",
        "frame",
        "command",
        "autocontinue",
        "x",
        "y",
        "mission_type",
    )

    for field in exact_fields:
        expected_value = int(expected[field])
        actual_value = int(actual[field])

        if expected_value != actual_value:
            differences.append(
                f"{field}: expected {expected_value}, "
                f"received {actual_value}"
            )

    float_fields = (
        "param1",
        "param2",
        "param3",
        "param4",
        "z",
    )

    for field in float_fields:
        expected_value = float(expected[field])
        actual_value = float(actual[field])

        if not float_matches(
            expected_value,
            actual_value,
            tolerance=0.0001,
        ):
            differences.append(
                f"{field}: expected {expected_value}, "
                f"received {actual_value}"
            )

    return differences


def print_item(
    heading: str,
    item: dict[str, Any],
) -> None:
    """Print the mission fields relevant to semantic verification."""

    latitude = item.get(
        "latitude",
        int(item["x"]) / 10_000_000,
    )

    longitude = item.get(
        "longitude",
        int(item["y"]) / 10_000_000,
    )

    print()
    print(heading)
    print("-" * len(heading))
    print(f"sequence       = {item['seq']}")
    print(f"command        = {item['command']}")
    print(f"frame          = {item['frame']}")
    print(f"autocontinue   = {item['autocontinue']}")
    print(f"param1         = {item['param1']}")
    print(f"param2         = {item['param2']}")
    print(f"param3         = {item['param3']}")
    print(f"param4         = {item['param4']}")
    print(f"x              = {item['x']}")
    print(f"y              = {item['y']}")
    print(f"latitude       = {latitude}")
    print(f"longitude      = {longitude}")
    print(f"z              = {item['z']}")
    print(f"mission_type   = {item['mission_type']}")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download the ArduPilot mission and verify mission item 1 "
            "against a metadata-generated waypoint."
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
        "--connection",
        required=True,
        help=(
            "pymavlink connection string, such as "
            "'tcp:127.0.0.1:15762'."
        ),
    )

    parser.add_argument(
        "--source-system",
        type=int,
        default=255,
        help="Downloader MAVLink system ID. Default: 255.",
    )

    parser.add_argument(
        "--source-component",
        type=int,
        default=190,
        help="Downloader MAVLink component ID. Default: 190.",
    )

    parser.add_argument(
        "--heartbeat-timeout",
        type=float,
        default=15.0,
        help="Seconds to wait for the initial heartbeat. Default: 15.",
    )

    parser.add_argument(
        "--response-timeout",
        type=float,
        default=5.0,
        help="Seconds to wait for mission responses. Default: 5.",
    )

    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    connection = None

    try:
        connection = connect_to_ardupilot(
            arguments.connection,
            source_system=arguments.source_system,
            source_component=arguments.source_component,
            heartbeat_timeout=arguments.heartbeat_timeout,
        )

        expected = build_expected_item(
            arguments.metadata_file,
            arguments.command_file,
            target_system=connection.target_system,
            target_component=connection.target_component,
        )

        count = request_mission_count(
            connection,
            timeout=arguments.response_timeout,
        )

        if count != 2:
            raise MissionDownloadError(
                "This verification expects exactly one stored mission "
                f"item, but ArduPilot reported {count}."
            )

        downloaded_message = request_mission_item(
            connection,
            sequence=1,
            timeout=arguments.response_timeout,
        )

        actual = normalize_downloaded_item(
            downloaded_message
        )

        acknowledge_download(connection)

        print_item("Expected compiler output", expected)
        print_item("Downloaded ArduPilot item", actual)

        differences = compare_items(
            expected,
            actual,
        )

        print()

        if differences:
            print("VERIFICATION FAILED")

            for difference in differences:
                print(f"  - {difference}")

            return 1

        print(
            "SUCCESS: The mission downloaded from ArduPilot is "
            "semantically equivalent to the metadata-generated waypoint."
        )

        return 0

    except (
        CommandMetadataError,
        CommandValidationError,
        MissionItemEmissionError,
        MissionUploadError,
        MissionDownloadError,
        OSError,
    ) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    sys.exit(main())

