from __future__ import annotations

from typing import Any

from app.navproxy.failsafe import (
    get_failsafe_coordinate_for_segment,
)
from app.navproxy.tooling.fer_compiler import (
    get_coordinate_distance_ft,
)


FEET_PER_MILE = 5280.0
SECONDS_PER_HOUR = 3600.0
ARRIVAL_TRANSITION_SECONDS = 10.0
LANDING_SECONDS = 15.0

def mph_to_feet_per_second(
    speed_mph: int | float,
) -> float:
    """Convert miles per hour to feet per second."""

    if speed_mph <= 0:
        raise ValueError(
            "Route speed_limit_mph must be greater than zero."
        )

    return (
        float(speed_mph)
        * FEET_PER_MILE
        / SECONDS_PER_HOUR
    )


def estimate_seconds_to_destination(
    *,
    compiler_ir: dict[str, Any],
    active_segment_index: int,
    current_coordinate: list[float],
) -> float:
    """Estimate remaining mission Route time using governed segment speeds."""

    segments = compiler_ir["mission"]["route_conformance_segments"]

    if (
        active_segment_index < 0
        or active_segment_index >= len(segments)
    ):
        raise ValueError(
            "Active Route segment index is outside the compiled mission."
        )

    total_seconds = 0.0

    for index in range(
        active_segment_index,
        len(segments),
    ):
        segment = segments[index]

        if index == active_segment_index:
            start_coordinate = current_coordinate
        else:
            start_coordinate = segment["start_coordinate"]

        end_coordinate = segment["end_coordinate"]

        distance_ft = get_coordinate_distance_ft(
            start_coordinate,
            end_coordinate,
        )

        speed_ft_per_second = mph_to_feet_per_second(
            segment["speed_limit_mph"]
        )

        total_seconds += (
            distance_ft / speed_ft_per_second
        )

    return (
        total_seconds
        + ARRIVAL_TRANSITION_SECONDS
        + LANDING_SECONDS
    )


def estimate_seconds_to_failsafe(
    *,
    compiler_ir: dict[str, Any],
    active_segment_index: int,
    current_coordinate: list[float],
) -> float:
    """Estimate time to the governed failsafe point for the active segment."""

    segments = compiler_ir["mission"]["route_conformance_segments"]

    if (
        active_segment_index < 0
        or active_segment_index >= len(segments)
    ):
        raise ValueError(
            "Active Route segment index is outside the compiled mission."
        )

    segment = segments[active_segment_index]

    failsafe_coordinate = get_failsafe_coordinate_for_segment(
        compiler_ir,
        segment,
    )

    distance_ft = get_coordinate_distance_ft(
        current_coordinate,
        failsafe_coordinate,
    )

    speed_ft_per_second = mph_to_feet_per_second(
        segment["speed_limit_mph"]
    )

    return distance_ft / speed_ft_per_second

