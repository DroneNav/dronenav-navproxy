"""Upload an ArduPilot geofence using the MAVLink mission protocol."""

from __future__ import annotations

from typing import Any

from pymavlink import mavutil

from app.navproxy.tooling.upload_mission import (
    DEFAULT_CONNECTION,
    connect_vehicle,
    upload_mission,
)


def main() -> int:
    """Connect to ArduPilot for a standalone geofence upload test."""

    connection = connect_vehicle(
        DEFAULT_CONNECTION,
        10.0,
    )

    print(
        "Connected to ArduPilot: "
        f"system={connection.target_system} "
        f"component={connection.target_component}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

