from __future__ import annotations

import json

from sqlalchemy import text

from app.config.database import engine


METERS_TO_FEET = 1.0 / 0.3048


def estimate_route_duration_seconds(
    route,
    commanded_cruise_speed_ft_s,
) -> float:
    """Estimate Route duration using governed cruise speed."""

    if (
        isinstance(commanded_cruise_speed_ft_s, bool)
        or not isinstance(
            commanded_cruise_speed_ft_s,
            (int, float),
        )
        or commanded_cruise_speed_ft_s <= 0
    ):
        raise ValueError(
            "commanded_cruise_speed_ft_s must be positive."
        )

    geometry = route["geometry"]
    segment_attributes = route["segment_attributes"]
    coordinates = geometry["coordinates"]

    if len(coordinates) < 2:
        return 0.0

    if len(segment_attributes) != len(coordinates) - 1:
        raise ValueError(
            "Route segment_attributes length must equal "
            "the number of Route geometry segments"
        )

    with engine.connect() as connection:
        route_length_meters = connection.execute(
            text("""
                SELECT ST_Length(
                    ST_SetSRID(
                        ST_GeomFromGeoJSON(:geometry),
                        4326
                    )::geography
                )
            """),
            {
                "geometry": json.dumps(geometry),
            },
        ).scalar_one()

    route_length_ft = (
        float(route_length_meters) * METERS_TO_FEET
    )

    return route_length_ft / commanded_cruise_speed_ft_s


