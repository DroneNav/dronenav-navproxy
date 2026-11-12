#!/usr/bin/env python3
"""Backfill missing Route Nodes at qualifying managed turns."""

import argparse

from app.config.constants import (
    MINIMUM_TURN_ANGLE_DEG,
    MAXIMUM_TURN_ANGLE_DEG,
)
from app.models.route_model import (
    select_routes,
    select_route_node_connections,
)
from app.services.geometry_service import calculate_turn_angle
from app.services.route_service import amend_route_existing_waypoint


def backfill_managed_turn_nodes(apply=False):
    routes = select_routes()

    candidates = 0
    created = 0
    failed = 0

    for route in routes:
        if route["direction"] != 2:
            continue

        if route["maximum_aircraft_capacity"] == 1:
            continue

        route_id = route["route_id"]
        coordinates = route["geometry"]["coordinates"]

        existing_connections = select_route_node_connections(
            route_id
        )

        connected_indices = {
            connection["waypoint_index"]
            for connection in existing_connections
        }

        for waypoint_index in range(1, len(coordinates) - 1):
            if waypoint_index in connected_indices:
                continue

            try:
                angle = calculate_turn_angle(
                    coordinates[waypoint_index - 1],
                    coordinates[waypoint_index],
                    coordinates[waypoint_index + 1],
                )
            except ValueError as error:
                print(
                    f"SKIP route={route_id} "
                    f"waypoint={waypoint_index}: {error}"
                )
                continue

            if not (
                MINIMUM_TURN_ANGLE_DEG
                <= angle
                <= MAXIMUM_TURN_ANGLE_DEG
            ):
                continue

            candidates += 1

            print(
                f"{'APPLY' if apply else 'DRY-RUN'} "
                f"route={route_id} "
                f"waypoint={waypoint_index} "
                f"angle={angle:.2f}"
            )

            if not apply:
                continue

            try:
                result, error = amend_route_existing_waypoint(
                    route_id,
                    waypoint_index,
                )

                if error:
                    raise RuntimeError(error)

                created += 1

                print(f"  CREATED: {result}")

            except Exception as error:
                failed += 1
                print(f"  FAILED: {error}")

    print()
    print("Backfill summary")
    print(f"  Candidates: {candidates}")
    print(f"  Created:    {created}")
    print(f"  Failed:     {failed}")


def main():
    parser = argparse.ArgumentParser(
        description="Backfill managed-turn Route Nodes."
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help="Create missing Route Nodes (default: dry-run).",
    )

    args = parser.parse_args()

    backfill_managed_turn_nodes(apply=args.apply)


if __name__ == "__main__":
    main()

