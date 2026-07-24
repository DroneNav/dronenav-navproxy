"""
Upload a two-item ArduPilot test mission containing a home placeholder and
one metadata-generated waypoint using the MAVLink mission protocol.

This is an isolated R&D tool. It does not alter the NAVProxy runtime.

The upload sequence is:

    HEARTBEAT
        ↓
    MISSION_COUNT
        ↓
    MISSION_REQUEST_INT
        ↓
    MISSION_ITEM_INT
        ↓
    MISSION_ACK

WARNING:

Uploading this test mission replaces the mission currently stored by the
connected ArduPilot instance. Use this only with ArduPilot SITL.

Example:

    python -m tooling.upload_test_mission \
        tooling/metadata/mavlink_commands.yaml \
        tooling/examples/waypoint.json \
        --connection tcp:127.0.0.1:5760 \
        --confirm-upload
"""

from __future__ import annotations

import argparse
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


class MissionUploadError(RuntimeError):
    """Raised when the ArduPilot mission upload fails."""


MISSION_RESULT_NAMES = {
    mavutil.mavlink.MAV_MISSION_ACCEPTED: "MAV_MISSION_ACCEPTED",
    mavutil.mavlink.MAV_MISSION_ERROR: "MAV_MISSION_ERROR",
    mavutil.mavlink.MAV_MISSION_UNSUPPORTED_FRAME:
        "MAV_MISSION_UNSUPPORTED_FRAME",
    mavutil.mavlink.MAV_MISSION_UNSUPPORTED:
        "MAV_MISSION_UNSUPPORTED",
    mavutil.mavlink.MAV_MISSION_NO_SPACE: "MAV_MISSION_NO_SPACE",
    mavutil.mavlink.MAV_MISSION_INVALID: "MAV_MISSION_INVALID",
    mavutil.mavlink.MAV_MISSION_INVALID_PARAM1:
        "MAV_MISSION_INVALID_PARAM1",
    mavutil.mavlink.MAV_MISSION_INVALID_PARAM2:
        "MAV_MISSION_INVALID_PARAM2",
    mavutil.mavlink.MAV_MISSION_INVALID_PARAM3:
        "MAV_MISSION_INVALID_PARAM3",
    mavutil.mavlink.MAV_MISSION_INVALID_PARAM4:
        "MAV_MISSION_INVALID_PARAM4",
    mavutil.mavlink.MAV_MISSION_INVALID_PARAM5_X:
        "MAV_MISSION_INVALID_PARAM5_X",
    mavutil.mavlink.MAV_MISSION_INVALID_PARAM6_Y:
        "MAV_MISSION_INVALID_PARAM6_Y",
    mavutil.mavlink.MAV_MISSION_INVALID_PARAM7:
        "MAV_MISSION_INVALID_PARAM7",
    mavutil.mavlink.MAV_MISSION_INVALID_SEQUENCE:
        "MAV_MISSION_INVALID_SEQUENCE",
    mavutil.mavlink.MAV_MISSION_DENIED: "MAV_MISSION_DENIED",
}


def mission_result_name(result: int) -> str:
    """Return a readable name for a MAV_MISSION_RESULT value."""

    return MISSION_RESULT_NAMES.get(
        result,
        f"UNKNOWN_MISSION_RESULT_{result}",
    )


def connect_to_ardupilot(
    connection_string: str,
    *,
    source_system: int,
    source_component: int,
    heartbeat_timeout: float,
) -> mavutil.mavfile:
    """Open a MAVLink connection and wait for ArduPilot's heartbeat."""

    print(f"Connecting to {connection_string}...")

    try:
        connection = mavutil.mavlink_connection(
            connection_string,
            source_system=source_system,
            source_component=source_component,
            autoreconnect=True,
        )
    except Exception as exc:
        raise MissionUploadError(
            f"Unable to open MAVLink connection: {exc}"
        ) from exc

    heartbeat = connection.wait_heartbeat(
        timeout=heartbeat_timeout,
    )

    if heartbeat is None:
        raise MissionUploadError(
            "Timed out waiting for an ArduPilot heartbeat."
        )

    connection.target_system = heartbeat.get_srcSystem()
    connection.target_component = heartbeat.get_srcComponent()

    print(
        "Heartbeat received from "
        f"system={connection.target_system}, "
        f"component={connection.target_component}, "
        f"vehicle_type={heartbeat.type}, "
        f"autopilot={heartbeat.autopilot}"
    )

    if heartbeat.autopilot != mavutil.mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA:
        raise MissionUploadError(
            "The connected endpoint did not identify itself as ArduPilot. "
            f"autopilot={heartbeat.autopilot}"
        )

    return connection


def build_mission_item(
    compiled_command: dict[str, Any],
    *,
    target_system: int,
    target_component: int,
) -> Any:
    """Build the pymavlink MISSION_ITEM_INT object requested by ArduPilot."""

    emitted = emit_mission_item_int(
        compiled_command,
        target_system=target_system,
        target_component=target_component,
        sequence=1,
    )

    return mavutil.mavlink.MAVLink_mission_item_int_message(
        target_system=emitted["target_system"],
        target_component=emitted["target_component"],
        seq=emitted["seq"],
        frame=emitted["frame"],
        command=emitted["command"],
        current=emitted["current"],
        autocontinue=emitted["autocontinue"],
        param1=emitted["param1"],
        param2=emitted["param2"],
        param3=emitted["param3"],
        param4=emitted["param4"],
        x=emitted["x"],
        y=emitted["y"],
        z=emitted["z"],
        mission_type=emitted["mission_type"],
    )


def send_mission_count(
    connection: mavutil.mavfile,
    *,
    count: int,
) -> None:
    """Tell ArduPilot how many mission items will be uploaded."""

    print(f"Sending MISSION_COUNT count={count}...")

    connection.mav.mission_count_send(
        connection.target_system,
        connection.target_component,
        count,
        mavutil.mavlink.MAV_MISSION_TYPE_MISSION,
    )


def build_home_item(
    *,
    target_system: int,
    target_component: int,
) -> Any:
    """Build the sequence-zero home placeholder used by ArduPilot."""

    return mavutil.mavlink.MAVLink_mission_item_int_message(
        target_system=target_system,
        target_component=target_component,
        seq=0,
        frame=mavutil.mavlink.MAV_FRAME_GLOBAL,
        command=mavutil.mavlink.MAV_CMD_NAV_WAYPOINT,
        current=1,
        autocontinue=1,
        param1=0.0,
        param2=0.0,
        param3=0.0,
        param4=0.0,
        x=0,
        y=0,
        z=0.0,
        mission_type=mavutil.mavlink.MAV_MISSION_TYPE_MISSION,
    )


def upload_mission(
    connection: mavutil.mavfile,
    mission_items: dict[int, Any],
    *,
    request_timeout: float,
    ack_timeout: float,
    retries: int,
) -> None:
    """Upload all mission items requested by ArduPilot."""

    expected_sequences = set(mission_items)

    if expected_sequences != set(range(len(mission_items))):
        raise MissionUploadError(
            "Mission item sequence numbers must be contiguous and start at 0."
        )

    for attempt in range(1, retries + 2):
        send_mission_count(
            connection,
            count=len(mission_items),
        )

        print(
            "Waiting for mission requests "
            f"(attempt {attempt}/{retries + 1})..."
        )

        sent_sequences: set[int] = set()

        while True:
            timeout = (
                ack_timeout
                if sent_sequences == expected_sequences
                else request_timeout
            )

            response = connection.recv_match(
                type=[
                    "MISSION_REQUEST_INT",
                    "MISSION_REQUEST",
                    "MISSION_ACK",
                ],
                blocking=True,
                timeout=timeout,
            )

            if response is None:
                if attempt <= retries:
                    print(
                        "Mission upload response timed out; "
                        "restarting upload."
                    )
                    break

                if sent_sequences == expected_sequences:
                    raise MissionUploadError(
                        "Timed out waiting for MISSION_ACK."
                    )

                missing = sorted(expected_sequences - sent_sequences)
                raise MissionUploadError(
                    "Timed out waiting for ArduPilot to request mission "
                    f"sequence(s) {missing}."
                )

            if response.get_type() == "MISSION_ACK":
                result = int(response.type)
                result_name = mission_result_name(result)

                print(
                    f"Received MISSION_ACK: {result_name} ({result})."
                )

                if result != mavutil.mavlink.MAV_MISSION_ACCEPTED:
                    raise MissionUploadError(
                        "ArduPilot rejected the mission: "
                        f"{result_name} ({result})"
                    )

                if sent_sequences != expected_sequences:
                    missing = sorted(expected_sequences - sent_sequences)
                    raise MissionUploadError(
                        "ArduPilot accepted the upload before requesting "
                        f"mission sequence(s) {missing}."
                    )

                print("ArduPilot accepted the generated mission.")
                return

            requested_sequence = int(response.seq)

            print(
                f"Received {response.get_type()} "
                f"for sequence={requested_sequence}."
            )

            if requested_sequence not in mission_items:
                raise MissionUploadError(
                    "ArduPilot requested unexpected mission sequence "
                    f"{requested_sequence}; expected "
                    f"{sorted(expected_sequences)}."
                )

            print(
                "Sending MISSION_ITEM_INT "
                f"sequence={requested_sequence}..."
            )

            connection.mav.send(
                mission_items[requested_sequence]
            )

            sent_sequences.add(requested_sequence)

    raise MissionUploadError(
        "Mission upload ended without acceptance."
    )

def verify_uploaded_mission_count(
    connection: mavutil.mavfile,
    *,
    expected_count: int,
    timeout: float,
) -> None:
    """Request the stored mission list and verify its item count."""

    print("Requesting stored mission count for verification...")

    connection.mav.mission_request_list_send(
        connection.target_system,
        connection.target_component,
        mavutil.mavlink.MAV_MISSION_TYPE_MISSION,
    )

    count_message = connection.recv_match(
        type="MISSION_COUNT",
        blocking=True,
        timeout=timeout,
    )

    if count_message is None:
        raise MissionUploadError(
            "Upload was accepted, but stored mission count "
            "could not be verified."
        )

    stored_count = int(count_message.count)

    print(f"ArduPilot reports stored mission count={stored_count}.")

    if stored_count != expected_count:
        raise MissionUploadError(
            f"Expected {expected_count} stored mission items, but "
            f"ArduPilot reported {stored_count}."
        )


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Upload a home placeholder and one metadata-generated waypoint to ArduPilot SITL."
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
            "'tcp:127.0.0.1:5760' or 'udp:127.0.0.1:14550'."
        ),
    )

    parser.add_argument(
        "--source-system",
        type=int,
        default=255,
        help="Uploader MAVLink system ID. Default: 255.",
    )

    parser.add_argument(
        "--source-component",
        type=int,
        default=190,
        help="Uploader MAVLink component ID. Default: 190.",
    )

    parser.add_argument(
        "--heartbeat-timeout",
        type=float,
        default=15.0,
        help="Seconds to wait for the initial heartbeat. Default: 15.",
    )

    parser.add_argument(
        "--request-timeout",
        type=float,
        default=5.0,
        help="Seconds to wait for each mission request. Default: 5.",
    )

    parser.add_argument(
        "--ack-timeout",
        type=float,
        default=5.0,
        help="Seconds to wait for MISSION_ACK. Default: 5.",
    )

    parser.add_argument(
        "--retries",
        type=int,
        default=2,
        help="Number of upload retries after the first attempt. Default: 2.",
    )

    parser.add_argument(
        "--confirm-upload",
        action="store_true",
        help=(
            "Required safety acknowledgment that the connected "
            "SITL mission will be replaced."
        ),
    )

    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()

    if not arguments.confirm_upload:
        print(
            "Error: mission upload was not authorized. "
            "Re-run with --confirm-upload after confirming that "
            "the connection points to ArduPilot SITL.",
            file=sys.stderr,
        )
        return 2

    if arguments.retries < 0:
        print(
            "Error: --retries cannot be negative.",
            file=sys.stderr,
        )
        return 2

    connection = None

    try:
        metadata = load_yaml_file(arguments.metadata_file)
        command_instance = load_json_file(arguments.command_file)

        compiled_command = compile_command(
            metadata=metadata,
            command_instance=command_instance,
        )

        connection = connect_to_ardupilot(
            arguments.connection,
            source_system=arguments.source_system,
            source_component=arguments.source_component,
            heartbeat_timeout=arguments.heartbeat_timeout,
        )

        home_item = build_home_item(
            target_system=connection.target_system,
            target_component=connection.target_component,
        )

        mission_item = build_mission_item(
            compiled_command,
            target_system=connection.target_system,
            target_component=connection.target_component,
        )

        mission_items = {
            0: home_item,
            1: mission_item,
        }

        upload_mission(
            connection,
            mission_items,
            request_timeout=arguments.request_timeout,
            ack_timeout=arguments.ack_timeout,
            retries=arguments.retries,
        )

        verify_uploaded_mission_count(
            connection,
            expected_count=len(mission_items),
            timeout=arguments.ack_timeout,
        )

        print(
            "SUCCESS: The YAML-generated waypoint was accepted "
            "and stored by ArduPilot."
        )

        return 0

    except (
        CommandMetadataError,
        CommandValidationError,
        MissionItemEmissionError,
        MissionUploadError,
        OSError,
    ) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    sys.exit(main())

