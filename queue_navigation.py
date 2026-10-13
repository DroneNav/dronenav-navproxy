from app.config.database import engine
from app.models.intersection_state_model import (
    select_flight_intersection_state,
)

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
    return intersection_state != "occupied"


