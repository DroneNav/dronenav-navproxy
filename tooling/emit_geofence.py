"""Emit ArduPilot-compatible MAVLink geofence items."""

from __future__ import annotations

from typing import Any

from app.navproxy.tooling.emit_mission_item_int import (
    MAV_MISSION_TYPE_FENCE,
    emit_mission_item_int,
)

from app.navproxy.tooling.build_mavlink_packet import (
    build_mavlink_message,
)


def emit_geofence(
    compiled_commands: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Emit compiled geofence commands as MAVLink fence items."""

    return [
        emit_mission_item_int(
            compiled_command,
            sequence=sequence,
            mission_type=MAV_MISSION_TYPE_FENCE,
        )
        for sequence, compiled_command in enumerate(compiled_commands)
    ]


def build_geofence_messages(
    geofence_items: list[dict[str, Any]],
) -> dict[int, Any]:
    """Build native pymavlink messages for the emitted geofence items."""

    return {
        item["seq"]: build_mavlink_message(item)
        for item in geofence_items
    }


