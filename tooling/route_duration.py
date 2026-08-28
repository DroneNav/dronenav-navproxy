from __future__ import annotations

import json

from sqlalchemy import text

from app.config.database import engine


METERS_PER_MILE = 1609.344
SECONDS_PER_HOUR = 3600.0


def estimate_route_duration_seconds(route) -> float:
    """Estimate the traversal duration for one Route."""

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
        result = connection.execute(
            text("""
                WITH route_points AS (
                    SELECT
                        (point).path[1] AS point_index,
                        (point).geom::geography AS geography
                    FROM (
                        SELECT
                            ST_DumpPoints(
                                ST_SetSRID(
                                    ST_GeomFromGeoJSON(:geometry),
                                    4326
                                )
                            ) AS point
                    ) AS dumped
                ),
                route_segments AS (
                    SELECT
                        point_index,
                        geography,
                        LEAD(geography) OVER (
                            ORDER BY point_index
                        ) AS next_geography
                    FROM route_points
                ),
                segment_distances AS (
                    SELECT
                        point_index,
                        ST_Distance(
                            geography,
                            next_geography
                        ) AS distance_meters
                    FROM route_segments
                    WHERE next_geography IS NOT NULL
                )
                SELECT COALESCE(
                    SUM(
                        segment_distances.distance_meters
                        / :meters_per_mile
                        / (
                            CAST(
                                :segment_attributes AS jsonb
                            )->(segment_distances.point_index - 1)
                            ->>'speed_limit_mph'
                        )::double precision
                        * :seconds_per_hour
                    ),
                    0
                ) AS duration_seconds
                FROM segment_distances
            """),
            {
                "geometry": json.dumps(geometry),
                "segment_attributes": json.dumps(segment_attributes),
                "meters_per_mile": METERS_PER_MILE,
                "seconds_per_hour": SECONDS_PER_HOUR,
            },
        )

        return float(result.scalar_one())

