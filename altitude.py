"""NAVProxy altitude and terrain calculations."""

from __future__ import annotations

import math


def segment_progress(
    latitude: float,
    longitude: float,
    start_coordinate: list[float],
    end_coordinate: list[float],
) -> float:
    """Return aircraft progress along a Route segment, clamped to 0.0..1.0."""

    start_longitude, start_latitude = start_coordinate
    end_longitude, end_latitude = end_coordinate

    reference_latitude_radians = math.radians(
        (start_latitude + end_latitude) / 2.0
    )

    x = (
        (longitude - start_longitude)
        * math.cos(reference_latitude_radians)
    )
    y = latitude - start_latitude

    segment_x = (
        (end_longitude - start_longitude)
        * math.cos(reference_latitude_radians)
    )
    segment_y = end_latitude - start_latitude

    segment_length_squared = (
        segment_x * segment_x
        + segment_y * segment_y
    )

    if segment_length_squared == 0.0:
        return 0.0

    progress = (
        x * segment_x
        + y * segment_y
    ) / segment_length_squared

    return max(0.0, min(1.0, progress))


def interpolate_ground_elevation_ft(
    progress: float,
    start_ground_elevation_ft: float,
    end_ground_elevation_ft: float,
) -> float:
    """Interpolate ground elevation along a Route segment."""

    return (
        start_ground_elevation_ft
        + progress
        * (
            end_ground_elevation_ft
            - start_ground_elevation_ft
        )
    )


