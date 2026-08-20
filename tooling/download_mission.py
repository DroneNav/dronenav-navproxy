from __future__ import annotations

from typing import Any

from pymavlink import mavutil


class MissionDownloadError(RuntimeError):
    """Raised when the mission cannot be downloaded."""


def request_mission_count(
    connection: mavutil.mavfile,
    *,
    timeout: float,
) -> int:
    """Request the stored mission list and return its item count."""

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

    return int(response.count)


def request_mission_item(
    connection: mavutil.mavfile,
    *,
    sequence: int,
    timeout: float,
) -> Any:
    """Request one mission item using integer-coordinate mission format."""

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
        raise MissionDownloadError(
            "ArduPilot returned MISSION_ACK instead of the requested "
            f"mission item. Result={int(response.type)}."
        )

    if int(response.seq) != sequence:
        raise MissionDownloadError(
            "Received an unexpected mission sequence. "
            f"Expected {sequence}, received {response.seq}."
        )

    return response


def normalize_downloaded_item(
    message: Any,
) -> dict[str, Any]:
    """Normalize a downloaded mission item into a common representation."""

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
        "altitude": float(message.z),
    }


def acknowledge_download(
    connection: mavutil.mavfile,
) -> None:
    """Acknowledge successful receipt of the complete mission."""

    connection.mav.mission_ack_send(
        connection.target_system,
        connection.target_component,
        mavutil.mavlink.MAV_MISSION_ACCEPTED,
        mavutil.mavlink.MAV_MISSION_TYPE_MISSION,
    )


def download_mission(
    connection: mavutil.mavfile,
    *,
    timeout: float = 5.0,
) -> list[dict[str, Any]]:
    """Download and normalize the complete programmed mission."""

    count = request_mission_count(
        connection,
        timeout=timeout,
    )

    items: list[dict[str, Any]] = []

    for sequence in range(count):
        message = request_mission_item(
            connection,
            sequence=sequence,
            timeout=timeout,
        )

        items.append(
            normalize_downloaded_item(
                message,
            )
        )

    acknowledge_download(
        connection,
    )

    return items

