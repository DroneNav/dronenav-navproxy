from __future__ import annotations

from typing import Any

from pymavlink import mavutil

from app.navproxy.tooling.build_scheduled_mission import (
    build_scheduled_mission,
)
from app.navproxy.tooling.upload_mission import (
    upload_mission,
    validate_emitted_mission,
)


def build_ardupilot_mission_items(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Reserve ArduPilot mission sequence 0 for its managed Home item."""

    if not items:
        raise ValueError(
            "Scheduled mission must contain at least one mission item."
        )

    ardupilot_items: list[dict[str, Any]] = []

    home_slot = dict(items[0])
    home_slot["seq"] = 0
    ardupilot_items.append(home_slot)

    for sequence, item in enumerate(items, start=1):
        shifted_item = dict(item)
        shifted_item["seq"] = sequence
        ardupilot_items.append(shifted_item)

    return ardupilot_items


def program_scheduled_mission(
    *,
    connection: mavutil.mavfile,
    compiler_ir: dict[str, Any],
) -> None:
    """Program the scheduled DroneNav mission on an ArduPilot flight controller."""

    emitted_stream = build_scheduled_mission(
        compiler_ir,
    )

    items = validate_emitted_mission(
        emitted_stream,
    )

    items = build_ardupilot_mission_items(
        items
    )

    mission_type = int(
        emitted_stream.get(
            "mission_type",
            mavutil.mavlink.MAV_MISSION_TYPE_MISSION,
        )
    )

    upload_mission(
        connection=connection,
        items=items,
        mission_type=mission_type,
    )


