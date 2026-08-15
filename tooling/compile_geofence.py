from __future__ import annotations

from pathlib import Path
from typing import Any

from app.navproxy.tooling.compile_command import compile_command
from app.navproxy.tooling.mavlink_compiler import load_yaml_file

MAVLINK_METADATA_PATH = (
    Path(__file__).parent
    / "metadata"
    / "mavlink_commands.yaml"
)



def compile_geofence_commands(
    commands: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compile geofence commands using the shared MAVLink metadata."""

    metadata = load_yaml_file(
        MAVLINK_METADATA_PATH,
    )

    return [
        compile_command(
            metadata,
            command,
        )
        for command in commands
    ]


