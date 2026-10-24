from app.config.database import engine
from app.models.intersection_state_model import (
    select_flight_intersection_state,
)
from app.models.route_occupancy_state_model import (
    select_route_occupancy_state,
)

from app.config.constants import AIRCRAFT_SEPARATION_DISTANCE_FT

import math


def calculate_coordinate_distance_ft(
    first_coordinate: list[float],
    second_coordinate: list[float],
) -> float:
    """Calculate surface distance in feet between [longitude, latitude] points."""

    earth_radius_ft = 20925524.9

    lon1, lat1 = map(math.radians, first_coordinate)
    lon2, lat2 = map(math.radians, second_coordinate)

    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(delta_lon / 2) ** 2
    )

    return (
        2.0
        * earth_radius_ft
        * math.asin(math.sqrt(min(1.0, max(0.0, a))))
    )


def interpolate_coordinate(
    start_coordinate: list[float],
    end_coordinate: list[float],
    fraction: float,
) -> list[float]:
    """Interpolate between two [longitude, latitude] coordinates."""

    return [
        start_coordinate[0]
        + (end_coordinate[0] - start_coordinate[0]) * fraction,
        start_coordinate[1]
        + (end_coordinate[1] - start_coordinate[1]) * fraction,
    ]


def calculate_intersection_queue_coordinate(
    *,
    holding_coordinate: list[float],
    hold_position: int,
    route_index: int,
    route_segments: list[dict],
) -> list[float] | None:
    """Calculate a fixed HOLD coordinate along the incoming Route."""

    if hold_position < 1:
        raise ValueError("HOLD position must be at least 1.")

    if hold_position == 1:
        return holding_coordinate

    segments = sorted(
        (
            segment
            for segment in route_segments
            if segment["route_index"] == route_index
        ),
        key=lambda segment: segment["route_segment_index"],
        reverse=True,
    )

    remaining_distance_ft = (
        (hold_position - 1) * AIRCRAFT_SEPARATION_DISTANCE_FT
    )

    current_coordinate = holding_coordinate

    for segment in segments:
        start_coordinate = segment["operational_start_coordinate"]
        end_coordinate = segment["operational_end_coordinate"]

        segment_end = (
            current_coordinate
            if current_coordinate is not None
            else end_coordinate
        )

        segment_distance_ft = calculate_coordinate_distance_ft(
            start_coordinate,
            segment_end,
        )

        if segment_distance_ft >= remaining_distance_ft:
            fraction = (
                1.0 - remaining_distance_ft / segment_distance_ft
                if segment_distance_ft > 0
                else 0.0
            )

            return interpolate_coordinate(
                start_coordinate,
                segment_end,
                fraction,
            )

        remaining_distance_ft -= segment_distance_ft
        current_coordinate = None

    return None


def calculate_queue_approach_speed(
    distance_to_holding_ft: float,
    cruise_speed_ft_s: float,
    deceleration_ft_s2: float,
    stopping_margin_ft: float,
) -> float:
    """Calculate target approach speed in feet per second."""

    available_distance_ft = max(
        0.0,
        distance_to_holding_ft - stopping_margin_ft,
    )

    return min(
        cruise_speed_ft_s,
        math.sqrt(
            2.0 * deceleration_ft_s2 * available_distance_ft
        ),
    )


def get_flight_intersection_state(
    *,
    route_node_id,
    flight_band_id,
    assigned_relative_altitude_ft,
    flight_execution_id,
):
    """Read the intersection state assigned to this FER."""

    with engine.connect() as connection:
        return select_flight_intersection_state(
            connection,
            route_node_id=route_node_id,
            flight_band_id=flight_band_id,
            assigned_relative_altitude_ft=assigned_relative_altitude_ft,
            flight_execution_id=flight_execution_id,
        )


def get_flight_intersection_hold_position(
    *,
    route_id,
    flight_execution_id,
) -> int | None:
    """Return the assigned intersection HOLD queue position."""

    with engine.connect() as connection:
        occupancy = select_route_occupancy_state(
            connection,
            route_id=route_id,
            flight_execution_id=flight_execution_id,
        )

    if occupancy is None:
        return None

    if occupancy["intersection_hold_route_node_id"] is None:
        return None

    return occupancy["intersection_hold_position"]


def get_managed_intersection_for_segment(
    compiler_ir: dict,
    segment: dict,
) -> dict | None:
    """Find the managed intersection approached by this Route segment."""
    for intersection in compiler_ir["mission"].get(
        "managed_intersections", []
    ):
        if intersection["from_route_index"] == segment["route_index"]:
            return intersection

    return None


def should_hold_for_intersection(
    intersection_state: str | None,
) -> bool:
    """Return whether intersection occupancy has not been assigned."""
    return intersection_state not in ("reserved", "occupied")


