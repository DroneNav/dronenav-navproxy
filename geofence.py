from __future__ import annotations

from typing import Any


def build_polygon_vertex_commands(
    *,
    command: str,
    geometry: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build MAVLink fence vertex command definitions for one polygon."""

    coordinates = geometry["coordinates"][0]

    if coordinates[0] == coordinates[-1]:
        coordinates = coordinates[:-1]

    vertex_count = len(coordinates)

    return [
        {
            "command": command,
            "parameters": {
                "vertex_count": vertex_count,
                "latitude": latitude,
                "longitude": longitude,
            },
        }
        for longitude, latitude in coordinates
    ]


def build_geofence_commands(
    geofence_definition: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build all horizontal geofence command definitions."""

    commands = build_polygon_vertex_commands(
        command="MAV_CMD_NAV_FENCE_POLYGON_VERTEX_INCLUSION",
        geometry=geofence_definition["inclusion_geometry"],
    )

    for geometry in geofence_definition["exclusion_geometries"]:
        commands.extend(
            build_polygon_vertex_commands(
                command="MAV_CMD_NAV_FENCE_POLYGON_VERTEX_EXCLUSION",
                geometry=geometry,
            )
        )

    return commands



