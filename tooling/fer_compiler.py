"""
Compile a Flight Execution Record (FER) into a DroneNav declarative
command stream.

This tool:

1. Loads a Flight Execution Record.
2. Validates the operational flight.
3. Compiles the FER into the DroneNav Intermediate Representation (IR).

Usage:

    python -m tooling.fer_compiler \
        tooling/examples/fer_019f6bc9-b635-7a7f-95d9-e1f15fdadfb6.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import requests

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config.constants import (
    DEFAULT_API_BASE_URL,
    DEFAULT_API_TIMEOUT_SECONDS,
    TRANSITION_DIAMETER_FT,
    MISSION_ALTITUDE_MARGIN_FT,
)

from app.navproxy.flight_band_resolver import resolve_applicable_flight_band


class FlightExecutionCompileError(ValueError):
    """Raised when a Flight Execution Record cannot be interpreted."""


def load_api_object(
    endpoint: str,
    object_name: str,
) -> dict[str, Any]:
    """Retrieve one required object from the DroneNav API."""

    url = f"{DEFAULT_API_BASE_URL.rstrip('/')}{endpoint}"

    try:
        response = requests.get(
            url,
            headers={"Accept": "application/json"},
            timeout=DEFAULT_API_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise FlightExecutionCompileError(
            f"Could not retrieve {object_name} from {url}: {exc}"
        ) from exc

    try:
        value = response.json()
    except requests.JSONDecodeError as exc:
        raise FlightExecutionCompileError(
            f"The API returned invalid JSON for {object_name}."
        ) from exc

    if not isinstance(value, dict):
        raise FlightExecutionCompileError(
            f"The API response for {object_name} must be a JSON object."
        )

    return value


def load_flight_execution(
    flight_execution_id: str,
) -> dict[str, Any]:
    """Retrieve one Flight Execution Record from the DroneNav API."""

    if not isinstance(flight_execution_id, str) or not flight_execution_id:
        raise FlightExecutionCompileError(
            "flight_execution_id must be a non-empty string."
        )

    response = load_api_object(
        endpoint=f"/api/flight-executions/{flight_execution_id}",
        object_name="Flight Execution Record",
    )

    flight_execution = response.get("flight_execution", response)

    if not isinstance(flight_execution, dict):
        raise FlightExecutionCompileError(
            "The Flight Execution API response must contain a JSON object."
        )

    return flight_execution


def load_departure_droneport(
    departure_droneport_id: str,
) -> dict[str, Any]:
    """Retrieve the departure DronePort referenced by the FER."""

    return load_api_object(
        endpoint=f"/api/droneports/{departure_droneport_id}",
        object_name="departure DronePort",
    )

def load_arrival_droneport(
    arrival_droneport_id: str,
) -> dict[str, Any]:
    """Retrieve the arrival DronePort referenced by the FER."""

    return load_api_object(
        endpoint=f"/api/droneports/{arrival_droneport_id}",
        object_name="arrival DronePort",
    )

def load_origin_site(
    origin_site_id: str,
) -> dict[str, Any]:
    """Retrieve the origin Site referenced by the FER."""

    return load_api_object(
        endpoint=f"/api/sites/{origin_site_id}",
        object_name="origin Site",
    )

def load_destination_site(
    destination_site_id: str,
) -> dict[str, Any]:
    """Retrieve the destination Site referenced by the FER."""

    return load_api_object(
        endpoint=f"/api/sites/{destination_site_id}",
        object_name="destination Site",
    )

def load_flight_bands(
    flight_class: str,
) -> list[dict[str, Any]]:
    """Retrieve active Flight Bands for the specified Flight Class."""

    response = load_api_object(
        endpoint=(
            f"/api/flight-bands"
            f"?operational_status=active"
            f"&flight_class={flight_class}"
        ),
        object_name="Flight Bands",
    )

    flight_bands = response.get("flight_bands")

    if not isinstance(flight_bands, list):
        raise FlightExecutionCompileError(
            "Flight Bands response is missing the flight_bands array."
        )

    return flight_bands

def extract_geometry(
    api_object: dict[str, Any],
    object_name: str,
) -> dict[str, Any]:
    """Extract and validate a GeoJSON geometry object."""

    geometry = api_object.get("geometry")

    if not isinstance(geometry, dict):
        raise FlightExecutionCompileError(
            f"{object_name} is missing its geometry object."
        )

    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")

    if not isinstance(geometry_type, str) or not geometry_type:
        raise FlightExecutionCompileError(
            f"{object_name} geometry is missing type."
        )

    if coordinates is None:
        raise FlightExecutionCompileError(
            f"{object_name} geometry is missing coordinates."
        )

    return geometry


def build_launch_position_assertion(
    flight_execution: dict[str, Any],
) -> dict[str, Any]:
    """
    Build exactly one launch-position assertion.

    A departure DronePort takes precedence over the origin Site.
    The origin Site is used only when no departure DronePort is specified.
    """

    departure_droneport_id = flight_execution.get(
        "departure_droneport_id"
    )

    if departure_droneport_id:
        if not isinstance(departure_droneport_id, str):
            raise FlightExecutionCompileError(
                "departure_droneport_id must be a string or null."
            )

        departure_droneport = load_departure_droneport(
            departure_droneport_id=departure_droneport_id,
        )

        geometry = extract_geometry(
            departure_droneport,
            "Departure DronePort",
        )

        if geometry["type"] != "Point":
            raise FlightExecutionCompileError(
                "Departure DronePort geometry must be Point."
            )

        diameter_ft = departure_droneport.get("droneport_diameter_ft")

        if (
            isinstance(diameter_ft, bool)
            or not isinstance(diameter_ft, (int, float))
            or diameter_ft <= 0
        ):
            raise FlightExecutionCompileError(
                "Departure DronePort must contain a positive diameter_ft."
            )

        return {
            "assertion_type": "NAV_ASSERT_POSITION_IN_GEOMETRY",
            "parameters": {
                "geometry_type": "circle",
                "coordinate": geometry["coordinates"],
                "diameter_ft": diameter_ft,
            },
        }

    origin_site_id = flight_execution.get("origin_site_id")

    if not isinstance(origin_site_id, str) or not origin_site_id:
        raise FlightExecutionCompileError(
            "Flight Execution Record is missing origin_site_id."
        )

    origin_site = load_origin_site(
        origin_site_id=origin_site_id,
    )

    geometry = extract_geometry(
        origin_site,
        "Origin Site",
    )

    if geometry["type"] not in {"Polygon", "MultiPolygon"}:
        raise FlightExecutionCompileError(
            "Origin Site geometry must be Polygon or MultiPolygon."
        )

    return {
        "assertion_type": "NAV_ASSERT_POSITION_IN_GEOMETRY",
        "parameters": {
            "geometry_type": "polygon",
            "coordinates": geometry["coordinates"],
        },
    }


def build_arrival_position_assertion(
    flight_execution: dict[str, Any],
) -> dict[str, Any]:
    """
    Build exactly one arrival-position assertion.

    An arrival DronePort takes precedence over the destination Site.
    The destination Site is used only when no arrival DronePort is specified.
    """

    arrival_droneport_id = flight_execution.get(
        "arrival_droneport_id"
    )

    if arrival_droneport_id:
        if not isinstance(arrival_droneport_id, str):
            raise FlightExecutionCompileError(
                "arrival_droneport_id must be a string or null."
            )

        arrival_droneport = load_arrival_droneport(
            arrival_droneport_id=arrival_droneport_id,
        )

        geometry = extract_geometry(
            arrival_droneport,
            "Arrival DronePort",
        )

        if geometry["type"] != "Point":
            raise FlightExecutionCompileError(
                "Arrival DronePort geometry must be Point."
            )

        diameter_ft = arrival_droneport.get(
            "droneport_diameter_ft"
        )

        if (
            isinstance(diameter_ft, bool)
            or not isinstance(diameter_ft, (int, float))
            or diameter_ft <= 0
        ):
            raise FlightExecutionCompileError(
                "Arrival DronePort must contain a positive diameter_ft."
            )

        return {
            "assertion_type": "NAV_ASSERT_ARRIVAL_IN_GEOMETRY",
            "parameters": {
                "geometry_type": "circle",
                "coordinate": geometry["coordinates"],
                "diameter_ft": diameter_ft,
            },
        }

    destination_site_id = flight_execution.get(
        "destination_site_id"
    )

    if (
        not isinstance(destination_site_id, str)
        or not destination_site_id
    ):
        raise FlightExecutionCompileError(
            "Flight Execution Record is missing destination_site_id."
        )

    destination_site = load_destination_site(
        destination_site_id=destination_site_id,
    )

    geometry = extract_geometry(
        destination_site,
        "Destination Site",
    )

    if geometry["type"] not in {"Polygon", "MultiPolygon"}:
        raise FlightExecutionCompileError(
            "Destination Site geometry must be Polygon or MultiPolygon."
        )

    return {
        "assertion_type": "NAV_ASSERT_ARRIVAL_IN_GEOMETRY",
        "parameters": {
            "geometry_type": "polygon",
            "coordinates": geometry["coordinates"],
        },
    }


def build_departure_time_assertion(
    flight_execution: dict[str, Any],
) -> dict[str, Any] | None:
    """
    Build a departure-time assertion.

    A null requested departure means departure is permitted at any
    date or time, so no assertion is generated.
    """

    requested_departure = flight_execution.get(
        "requested_departure_datetime"
    )

    if requested_departure is None:
        return None

    if not isinstance(requested_departure, str):
        raise FlightExecutionCompileError(
            "requested_departure_datetime must be an "
            "ISO-8601 string or null."
        )

    operational_timezone = flight_execution.get(
        "operational_timezone"
    )

    if not isinstance(operational_timezone, str) or not operational_timezone:
        raise FlightExecutionCompileError(
            "Flight Execution Record is missing "
            "operational_timezone."
        )

    try:
        departure_datetime = datetime.fromisoformat(
            requested_departure.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise FlightExecutionCompileError(
            "requested_departure_datetime is not a valid "
            "ISO-8601 datetime."
        ) from exc

    if departure_datetime.tzinfo is None:
        raise FlightExecutionCompileError(
            "requested_departure_datetime must contain "
            "a timezone offset."
        )

    try:
        timezone = ZoneInfo(operational_timezone)
    except ZoneInfoNotFoundError as exc:
        raise FlightExecutionCompileError(
            f"Unknown operational timezone: "
            f"{operational_timezone}"
        ) from exc

    local_departure = departure_datetime.astimezone(timezone)
    local_departure = local_departure.replace(microsecond=0)

    return {
        "assertion_type": "NAV_ASSERT_DEPARTURE_TIME",
        "parameters": {
            "departure_date": local_departure.date().isoformat(),
            "departure_time": local_departure.time().isoformat(),
        },
    }


def build_flight_band_assertion(
    flight_execution: dict[str, Any],
) -> dict[str, Any] | None:
    """
    Build the Flight Band preflight assertion for a corridor flight.

    Local Site flights do not contain Routes and do not use Flight Bands.
    Current Flight Band eligibility is evaluated during preflight.
    """

    route_ids = flight_execution.get("route_ids") or []

    if not route_ids:
        return None

    return {
        "assertion_type": "NAV_ASSERT_FLIGHT_BAND",
        "parameters": {
            "flight_class": flight_execution["flight_class"],
            "operational_timezone": (
                flight_execution["operational_timezone"]
            ),
        },
    }


def build_route_assertions(
    flight_execution: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Resolve all Route references in the Flight Execution Record.

    Each Route is represented in the IR as a Route-level linestring.
    Route ordering is preserved exactly as supplied by the FER.

    Segment width and altitude constraints are not emitted yet.
    """

    route_ids = flight_execution.get("route_ids") or []
    assertions: list[dict[str, Any]] = []

    for route_id in route_ids:
        route = load_api_object(
            endpoint=f"/api/routes/{route_id}",
            object_name="Route",
        )

        geometry = extract_geometry(
            route,
            "Route",
        )

        segment_attributes = route.get("segment_attributes")

        assertions.append(
            {
                "assertion_type": "NAV_ASSERT_ROUTE",
                "parameters": {
                    "route_id": route_id,  
                    "geometry_type": "linestring",
                    "coordinates": geometry["coordinates"],
                    "segment_attributes": segment_attributes,
                },
            }
        )

    return assertions


def build_route_waypoint_coordinates(
    route_assertions: list[dict[str, Any]],
) -> list[list[float]]:
    """
    Expand ordered Route assertions into one continuous waypoint path.

    The first Route contributes every coordinate. Each subsequent Route
    must begin at the preceding Route's final coordinate; that duplicated
    boundary coordinate is emitted only once.
    """

    waypoint_coordinates: list[list[float]] = []
    previous_route_endpoint: list[float] | None = None

    for route_index, route_assertion in enumerate(route_assertions):
        if not isinstance(route_assertion, dict):
            raise FlightExecutionCompileError(
                "Each Route assertion must be a JSON object."
            )

        if (
            route_assertion.get("assertion_type")
            != "NAV_ASSERT_ROUTE"
        ):
            raise FlightExecutionCompileError(
                "Route waypoint compilation received a non-Route assertion."
            )

        parameters = route_assertion.get("parameters")

        if not isinstance(parameters, dict):
            raise FlightExecutionCompileError(
                "Route assertion is missing its parameters object."
            )

        coordinates = parameters.get("coordinates")

        if not isinstance(coordinates, list) or len(coordinates) < 2:
            raise FlightExecutionCompileError(
                "Each Route must contain at least two coordinates."
            )

        route_coordinates: list[list[float]] = []

        for coordinate in coordinates:
            if (
                not isinstance(coordinate, list)
                or len(coordinate) < 2
                or isinstance(coordinate[0], bool)
                or not isinstance(coordinate[0], (int, float))
                or isinstance(coordinate[1], bool)
                or not isinstance(coordinate[1], (int, float))
            ):
                raise FlightExecutionCompileError(
                    "Each Route coordinate must contain numeric "
                    "longitude and latitude values."
                )

            route_coordinates.append([
                coordinate[0],
                coordinate[1],
            ])

        if route_index == 0:
            waypoint_coordinates.extend(route_coordinates)
        else:
            if previous_route_endpoint is None:
                raise FlightExecutionCompileError(
                    "Previous Route endpoint is unavailable."
                )

            transition_distance_ft = get_coordinate_distance_ft(
                previous_route_endpoint,
                route_coordinates[0],
            )

            if transition_distance_ft > TRANSITION_DIAMETER_FT:
                raise FlightExecutionCompileError(
                    "Ordered Routes are too far apart for a valid "
                    "Route transition."
                )

            waypoint_coordinates.extend(route_coordinates)

        previous_route_endpoint = route_coordinates[-1]

    return waypoint_coordinates


def build_route_waypoint_altitudes(
    route_assertions: list[dict[str, Any]],
    minimum_agl_ft: int | float,
) -> list[float]:
    """Build absolute altitude in meters for each Route waypoint."""

    waypoint_altitudes: list[float] = []

    for route_assertion in route_assertions:
        parameters = route_assertion["parameters"]
        coordinates = parameters["coordinates"]
        segment_attributes = parameters["segment_attributes"]

        if len(segment_attributes) != len(coordinates) - 1:
            raise FlightExecutionCompileError(
                "Route segment attributes do not match Route geometry."
            )

        first_ground_elevation_ft = (
            segment_attributes[0]["ground_elevation_ft"]
        )

        waypoint_altitudes.append(
            absolute_altitude_meters(
                first_ground_elevation_ft,
                minimum_agl_ft + MISSION_ALTITUDE_MARGIN_FT,
            )
        )

        for attributes in segment_attributes:
            waypoint_altitudes.append(
                absolute_altitude_meters(
                    attributes["ground_elevation_ft"],
                    minimum_agl_ft + MISSION_ALTITUDE_MARGIN_FT,
                )
            )

    return waypoint_altitudes


def build_route_waypoint_ranges(
    route_assertions: list[dict[str, Any]],
) -> list[dict[str, int]]:
    """Return flattened waypoint index ranges for ordered Routes."""

    ranges: list[dict[str, int]] = []
    waypoint_index = 0

    for route_index, route_assertion in enumerate(route_assertions):
        coordinates = route_assertion["parameters"]["coordinates"]

        start_index = waypoint_index
        end_index = waypoint_index + len(coordinates) - 1

        ranges.append({
            "route_index": route_index,
            "start_waypoint_index": start_index,
            "end_waypoint_index": end_index,
        })

        waypoint_index = end_index + 1

    return ranges


def build_route_speed_limits(
    route_assertions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return the entry and exit speed limits for each ordered Route."""

    route_speed_limits: list[dict[str, Any]] = []

    for route_index, route_assertion in enumerate(route_assertions):
        segment_attributes = (
            route_assertion["parameters"]["segment_attributes"]
        )

        route_speed_limits.append({
            "route_index": route_index,
            "entry_speed_limit_mph": (
                segment_attributes[0]["speed_limit_mph"]
            ),
            "exit_speed_limit_mph": (
                segment_attributes[-1]["speed_limit_mph"]
            ),
        })

    return route_speed_limits


def resolve_mission_altitude_band(
    flight_execution: dict[str, Any],
) -> tuple[int | float, int | float]:
    """
    Resolve the Phase 2 mission altitude band from the single applicable
    Flight Band.
    """

    flight_class = flight_execution.get("flight_class")
    operational_timezone = flight_execution.get(
        "operational_timezone"
    )

    if not isinstance(flight_class, str) or not flight_class:
        raise FlightExecutionCompileError(
            "Flight Execution Record is missing flight_class."
        )

    if (
        not isinstance(operational_timezone, str)
        or not operational_timezone
    ):
        raise FlightExecutionCompileError(
            "Flight Execution Record is missing operational_timezone."
        )

    flight_bands = load_flight_bands(
        flight_class=flight_class,
    )

    applicable_flight_band = resolve_applicable_flight_band(
        flight_bands=flight_bands,
        operational_timezone=operational_timezone,
    )

    if applicable_flight_band is None:
        raise FlightExecutionCompileError(
            "No active Flight Band permits mission compilation."
        )

    minimum_agl_ft = applicable_flight_band.get("min_agl_ft")
    maximum_agl_ft = applicable_flight_band.get("max_agl_ft")

    if (
        isinstance(minimum_agl_ft, bool)
        or not isinstance(minimum_agl_ft, (int, float))
        or minimum_agl_ft <= 0
    ):
        raise FlightExecutionCompileError(
            "Applicable Flight Band is missing a valid min_agl_ft."
        )

    if (
        isinstance(maximum_agl_ft, bool)
        or not isinstance(maximum_agl_ft, (int, float))
        or maximum_agl_ft <= minimum_agl_ft
    ):
        raise FlightExecutionCompileError(
            "Applicable Flight Band is missing a valid max_agl_ft."
        )

    return minimum_agl_ft, maximum_agl_ft


def build_mission_items(
    launch_assertion: dict[str, Any],
    waypoint_coordinates: list[list[float]],
    waypoint_altitudes: list[float],
    route_conformance_segments: list[dict[str, Any]],
    route_waypoint_ranges: list[dict[str, int]],
    route_speed_limits: list[dict[str, Any]],
    minimum_agl_ft: int | float,
    arrival_assertion: dict[str, Any],
    failsafe_branches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build the ordered DroneNav mission stream."""

    if not waypoint_coordinates:
        return []

    if len(waypoint_altitudes) != len(waypoint_coordinates):
        raise FlightExecutionCompileError(
            "Route waypoint altitude count does not match waypoint count."
        )

    if (
        isinstance(minimum_agl_ft, bool)
        or not isinstance(minimum_agl_ft, (int, float))
        or minimum_agl_ft <= 0
    ):
        raise FlightExecutionCompileError(
            "Mission minimum_agl_ft must be a positive number."
        )

    parameters = arrival_assertion.get("parameters")

    if not isinstance(parameters, dict):
        raise FlightExecutionCompileError(
            "Arrival assertion is missing its parameters object."
        )

    arrival_coordinate = parameters.get("coordinate")

    if (
        not isinstance(arrival_coordinate, list)
        or len(arrival_coordinate) < 2
    ):
        raise FlightExecutionCompileError(
            "Scheduled corridor flight requires an arrival coordinate."
        )

    departure_ground_elevation_ft = (
        route_conformance_segments[0]["ground_elevation_ft"]
    )

    takeoff_altitude_meters = absolute_altitude_meters(
        departure_ground_elevation_ft,
        minimum_agl_ft + MISSION_ALTITUDE_MARGIN_FT,
    )

    destination_ground_elevation_ft = (
        route_conformance_segments[-1]["ground_elevation_ft"]
    )

    landing_altitude_meters = absolute_altitude_meters(
        destination_ground_elevation_ft,
        0,
    )

    launch_parameters = launch_assertion.get("parameters")

    if not isinstance(launch_parameters, dict):
        raise FlightExecutionCompileError(
            "Launch assertion is missing its parameters object."
        )

    launch_coordinate = launch_parameters.get("coordinate")

    if (
        not isinstance(launch_coordinate, list)
        or len(launch_coordinate) < 2
    ):
        raise FlightExecutionCompileError(
            "Launch assertion is missing its coordinate."
        )

    mission_items: list[dict[str, Any]] = [
        {
            "sequence": 0,
            "command": "MAV_CMD_NAV_TAKEOFF",
            "parameters": {
            "latitude": launch_coordinate[1],
            "longitude": launch_coordinate[0],
            "altitude_meters": takeoff_altitude_meters,
            },
        }
    ]

    for waypoint_index, (coordinate, altitude_meters) in enumerate(
        zip(
            waypoint_coordinates,
            waypoint_altitudes,
        )
    ):
        mission_items.append({
            "sequence": len(mission_items),
            "waypoint_index": waypoint_index,
            "command": "MAV_CMD_NAV_WAYPOINT",
            "parameters": {
                "latitude": coordinate[1],
                "longitude": coordinate[0],
                "altitude_meters": altitude_meters,
            },
        })

    mission_items = insert_initial_route_speed(
        mission_items,
        route_conformance_segments,
    )

    mission_items = insert_route_transition_speeds(
        mission_items,
        route_waypoint_ranges,
        route_speed_limits,
        initial_speed_inserted=True,
    )

    mission_items.append({
        "sequence": len(mission_items),
        "command": "MAV_CMD_NAV_LAND",
        "parameters": {
            "latitude": arrival_coordinate[1],
            "longitude": arrival_coordinate[0],
            "altitude_meters": landing_altitude_meters,
        },
    })

    for branch in failsafe_branches:
        coordinate = branch["coordinate"]

        sequence = len(mission_items)

        mission_items.append({
            "sequence": sequence,
            "command": "MAV_CMD_NAV_LAND",
            "parameters": {
                "latitude": coordinate[1],
                "longitude": coordinate[0],
            },
        })

        branch["mission_sequence"] = sequence

    return mission_items


def build_departure_transition(
    launch_assertion: dict[str, Any],
    route_conformance_segments: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the departure DronePort-to-Route transition geometry."""

    launch_coordinate = launch_assertion["parameters"]["coordinate"]
    first_route_coordinate = (
        route_conformance_segments[0]["start_coordinate"]
    )

    return {
        "coordinate": build_transition_coordinate(
            launch_coordinate,
            first_route_coordinate,
        ),
        "diameter_ft": TRANSITION_DIAMETER_FT,
    }


def build_arrival_transition(
    arrival_assertion: dict[str, Any],
    route_conformance_segments: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the final Route-to-arrival DronePort transition geometry."""

    arrival_coordinate = arrival_assertion["parameters"]["coordinate"]
    last_route_coordinate = (
        route_conformance_segments[-1]["end_coordinate"]
    )

    return {
        "coordinate": build_transition_coordinate(
            last_route_coordinate,
            arrival_coordinate,
        ),
        "diameter_ft": TRANSITION_DIAMETER_FT,
    }


def build_route_transitions(
    route_assertions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build derived transition geometry between ordered Routes."""

    transitions: list[dict[str, Any]] = []

    for route_index in range(len(route_assertions) - 1):
        current_parameters = route_assertions[route_index]["parameters"]
        next_parameters = route_assertions[route_index + 1]["parameters"]

        current_segment_attributes = current_parameters["segment_attributes"]
        next_segment_attributes = next_parameters["segment_attributes"]

        from_speed_limit_mph = current_segment_attributes[-1]["speed_limit_mph"]
        to_speed_limit_mph = next_segment_attributes[0]["speed_limit_mph"]

        current_end = current_parameters["coordinates"][-1]
        next_start = next_parameters["coordinates"][0]

        transitions.append({
            "from_route_index": route_index,
            "to_route_index": route_index + 1,
            "coordinate": build_transition_coordinate(
                current_end,
                next_start,
            ),
            "diameter_ft": TRANSITION_DIAMETER_FT,
            "from_speed_limit_mph": from_speed_limit_mph,
            "to_speed_limit_mph": to_speed_limit_mph,
            "transition_speed_mph": min(
                from_speed_limit_mph,
                to_speed_limit_mph,
            ),
        })

    return transitions


def build_route_conformance_segments(
    route_assertions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build ordered Route segments for in-flight conformance evaluation."""

    conformance_segments: list[dict[str, Any]] = []

    for route_index, route_assertion in enumerate(route_assertions):
        parameters = route_assertion["parameters"]
        route_id = parameters["route_id"]
        coordinates = parameters["coordinates"]
        segment_attributes = parameters["segment_attributes"]

        for segment_index in range(len(coordinates) - 1):
            start_coordinate = coordinates[segment_index]
            end_coordinate = coordinates[segment_index + 1]
            attributes = segment_attributes[segment_index]

            conformance_segments.append({
                "route_id": route_id,
                "route_index": route_index,
                "route_segment_index": segment_index,
                "start_coordinate": start_coordinate,
                "end_coordinate": end_coordinate,
                "route_width_ft": attributes["route_width_ft"],
                "speed_limit_mph": attributes["speed_limit_mph"],
                "ground_elevation_ft": attributes["ground_elevation_ft"],
                "failsafe_coordinate": attributes.get("failsafe_coordinate"),
            })

    return conformance_segments


def interpret_flight_execution(
    document: dict[str, Any],
) -> dict[str, Any]:
    """
    Interpret a Flight Execution Record into an ordered NAVProxy command stream.
    """

    flight_execution = document.get("flight_execution")

    if not isinstance(flight_execution, dict):
        raise FlightExecutionCompileError(
            "Input JSON is missing the flight_execution object."
        )

    flight_execution_id = flight_execution.get("flight_execution_id")

    if not isinstance(flight_execution_id, str) or not flight_execution_id:
        raise FlightExecutionCompileError(
            "flight_execution is missing flight_execution_id."
        )

    assertions: list[dict[str, Any]] = []

    launch_assertion = build_launch_position_assertion(
        flight_execution=flight_execution,
    )

    assertions.append({
        "sequence": len(assertions),
        **launch_assertion,
    })

    departure_assertion = build_departure_time_assertion(
        flight_execution=flight_execution,
    )

    if departure_assertion is not None:
        assertions.append({
            "sequence": len(assertions),
            **departure_assertion,
        })

    flight_band_assertion = build_flight_band_assertion(
        flight_execution=flight_execution,
    )

    if flight_band_assertion is not None:
        assertions.append({
            "sequence": len(assertions),
            **flight_band_assertion,
        })

    arrival_assertion = build_arrival_position_assertion(
        flight_execution=flight_execution,
    )

    assertions.append({
        "sequence": len(assertions),
        **arrival_assertion,
    })

    route_assertions = build_route_assertions(
        flight_execution=flight_execution,
    )

    for route_assertion in route_assertions:
        assertions.append({
                "sequence": len(assertions),
                **route_assertion,
        })

    waypoint_coordinates = build_route_waypoint_coordinates(
        route_assertions
    )

    minimum_agl_ft, maximum_agl_ft = resolve_mission_altitude_band(
        flight_execution
    )

    waypoint_altitudes = build_route_waypoint_altitudes(
        route_assertions,
        minimum_agl_ft,
    )

    route_waypoint_ranges = build_route_waypoint_ranges(
        route_assertions
    )

    route_speed_limits = build_route_speed_limits(
        route_assertions
    )

    route_conformance_segments = build_route_conformance_segments(
        route_assertions
    )

    launch_parameters = launch_assertion["parameters"]
    departure_coordinate = launch_parameters["coordinate"]

    failsafe_branches = build_failsafe_branches(
        route_conformance_segments,
        departure_coordinate,
    )

    route_transitions = build_route_transitions(
        route_assertions
    )

    departure_transition = build_departure_transition(
        launch_assertion,
        route_conformance_segments,
    )

    arrival_transition = build_arrival_transition(
        arrival_assertion,
        route_conformance_segments,
    )

    mission_items = build_mission_items(
        launch_assertion=launch_assertion,
        waypoint_coordinates=waypoint_coordinates,
        waypoint_altitudes=waypoint_altitudes,
        route_conformance_segments=route_conformance_segments,
        route_waypoint_ranges=route_waypoint_ranges,
        route_speed_limits=route_speed_limits,
        minimum_agl_ft=minimum_agl_ft,
        arrival_assertion=arrival_assertion,
        failsafe_branches=failsafe_branches,
    )

    failsafe_jump_map = build_failsafe_jump_map(
        mission_items=mission_items,
        route_waypoint_ranges=route_waypoint_ranges,
        route_conformance_segments=route_conformance_segments,
        failsafe_branches=failsafe_branches,
    )

    return {
        "flight_execution_id": flight_execution_id,
        "assertions": assertions,
        "mission": {
            "minimum_agl_ft": minimum_agl_ft,
            "maximum_agl_ft": maximum_agl_ft,
            "route_waypoint_ranges": route_waypoint_ranges,
            "route_conformance_segments": route_conformance_segments,
            "departure_transition": departure_transition,
            "route_transitions": route_transitions,
            "route_speed_limits": route_speed_limits,
            "failsafe_branches": failsafe_branches,
            "failsafe_jump_map": failsafe_jump_map,
            "arrival_transition": arrival_transition,
            "mission_items": mission_items,
        },
    }


def compile_flight_execution(
    flight_execution: dict[str, Any],
) -> dict[str, Any]:
    """Compile an already-loaded FER into the NAVProxy IR."""

    if not isinstance(flight_execution, dict):
        raise FlightExecutionCompileError(
            "flight_execution must be a JSON object."
        )

    return interpret_flight_execution(
        document={"flight_execution": flight_execution},
    )


def load_and_compile_flight_execution(
    flight_execution_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load one FER from the API and compile it into the NAVProxy IR."""

    flight_execution = load_flight_execution(
        flight_execution_id=flight_execution_id,
    )

    compiler_ir = compile_flight_execution(
        flight_execution=flight_execution,
    )

    return flight_execution, compiler_ir


def load_json(path: Path) -> dict[str, Any]:
    """Load a JSON object from disk."""

    try:
        with path.open("r", encoding="utf-8") as input_file:
            value = json.load(input_file)
    except FileNotFoundError as exc:
        raise FlightExecutionCompileError(
            f"Input file not found: {path}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise FlightExecutionCompileError(
            f"Invalid JSON in {path}: {exc}"
        ) from exc
    except OSError as exc:
        raise FlightExecutionCompileError(
            f"Could not read input file {path}: {exc}"
        ) from exc

    if not isinstance(value, dict):
        raise FlightExecutionCompileError(
            f"Expected a JSON object in {path}."
        )

    return value


def build_transition_coordinate(
    first_coordinate: list[float],
    second_coordinate: list[float],
) -> list[float]:
    """Return the midpoint between two transition coordinates."""

    return [
        (first_coordinate[0] + second_coordinate[0]) / 2,
        (first_coordinate[1] + second_coordinate[1]) / 2,
    ]


def insert_initial_route_speed(
    mission_items: list[dict[str, Any]],
    route_conformance_segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Insert the initial Route cruise speed after the first Route segment."""

    if not route_conformance_segments:
        return mission_items

    first_speed_limit_mph = (
        route_conformance_segments[0]["speed_limit_mph"]
    )

    speed_item = build_change_speed_item(
        first_speed_limit_mph
    )

    # TAKEOFF is sequence 0.
    # Waypoint 1 enters the first Route.
    # Waypoint 2 completes the first Route segment.
    # Apply cruise speed after that point.
    insert_index = 3

    mission_items.insert(
        insert_index,
        speed_item,
    )

    for sequence, item in enumerate(mission_items):
        item["sequence"] = sequence

    return mission_items

def insert_route_transition_speeds(
    mission_items: list[dict[str, Any]],
    route_waypoint_ranges: list[dict[str, int]],
    route_speed_limits: list[dict[str, Any]],
    *,
    initial_speed_inserted: bool,
) -> list[dict[str, Any]]:
    """Insert speed changes around Route-to-Route transitions."""

    if len(route_waypoint_ranges) < 2:
        return mission_items

    inserted_count = 1 if initial_speed_inserted else 0

    for route_index in range(len(route_waypoint_ranges) - 1):
        current_speed = route_speed_limits[route_index][
            "exit_speed_limit_mph"
        ]
        next_speed = route_speed_limits[route_index + 1][
            "entry_speed_limit_mph"
        ]

        if next_speed == current_speed:
            continue

        current_range = route_waypoint_ranges[route_index]
        next_range = route_waypoint_ranges[route_index + 1]

        if next_speed < current_speed:
            insert_index = (
                current_range["end_waypoint_index"]
                + 1
                + inserted_count
            )
        else:
            insert_index = (
                next_range["start_waypoint_index"]
                + 2
                + inserted_count
            )

        mission_items.insert(
            insert_index,
            build_change_speed_item(next_speed),
        )

        inserted_count += 1

    for sequence, item in enumerate(mission_items):
        item["sequence"] = sequence

    return mission_items


def mph_to_meters_per_second(
    value: int | float,
) -> float:
    """Convert miles per hour to meters per second."""

    return value * 0.44704


def absolute_altitude_meters(
    ground_elevation_ft: int | float,
    agl_ft: int | float,
) -> float:
    """Return absolute flight altitude in meters."""

    return (
        ground_elevation_ft
        + agl_ft
    ) * 0.3048


def build_change_speed_item(
    speed_limit_mph: int | float,
) -> dict[str, Any]:
    """Build a MAVLink speed-change mission item."""

    return {
        "command": "MAV_CMD_DO_CHANGE_SPEED",
        "parameters": {
            "speed_type": 1,
            "speed_meters_per_second": mph_to_meters_per_second(
                speed_limit_mph
            ),
            "throttle_percent": -1,
            "absolute": 0,
        },
    }


def get_coordinate_distance_ft(
    first_coordinate: list[float],
    second_coordinate: list[float],
) -> float:
    """Return the geodesic distance between two coordinates in feet."""

    endpoint = (
        f"{DEFAULT_API_BASE_URL.rstrip('/')}"
        f"/api/routes/coordinate-distance"
    )

    try:
        response = requests.post(
            endpoint,
            json={
                "first_latitude": first_coordinate[1],
                "first_longitude": first_coordinate[0],
                "second_latitude": second_coordinate[1],
                "second_longitude": second_coordinate[0],
            },
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=DEFAULT_API_TIMEOUT_SECONDS,
        )

        response.raise_for_status()
        result = response.json()

    except requests.RequestException as exc:
        raise FlightExecutionCompileError(
            f"Could not calculate Route transition distance: {exc}"
        ) from exc

    except requests.JSONDecodeError as exc:
        raise FlightExecutionCompileError(
            "Route transition distance API returned invalid JSON."
        ) from exc

    distance_ft = result.get("distance_ft")

    if isinstance(distance_ft, bool) or not isinstance(
        distance_ft,
        (int, float),
    ):
        raise FlightExecutionCompileError(
            "Route transition distance API response is missing distance_ft."
        )

    return float(distance_ft)


def build_failsafe_branches(
    route_conformance_segments: list[dict[str, Any]],
    departure_coordinate: list[float],
) -> list[dict[str, Any]]:
    """Build unique failsafe recovery branches and segment assignments."""

    branches: list[dict[str, Any]] = []
    branch_indexes: dict[tuple[float, float], int] = {}

    for flat_segment_index, segment in enumerate(route_conformance_segments):
        coordinate = segment.get("failsafe_coordinate")

        if coordinate is None:
            coordinate = departure_coordinate

        coordinate_key = (
            float(coordinate[0]),
            float(coordinate[1]),
        )

        branch_index = branch_indexes.get(coordinate_key)

        if branch_index is None:
            branch_index = len(branches)
            branch_indexes[coordinate_key] = branch_index

            branches.append({
                "branch_index": branch_index,
                "coordinate": [
                    coordinate_key[0],
                    coordinate_key[1],
                ],
                "route_segment_indexes": [],
            })

        branches[branch_index]["route_segment_indexes"].append(
            flat_segment_index
        )

    return branches


def build_failsafe_jump_map(
    mission_items: list[dict[str, Any]],
    route_waypoint_ranges: list[dict[str, int]],
    route_conformance_segments: list[dict[str, Any]],
    failsafe_branches: list[dict[str, Any]],
) -> list[dict[str, int]]:
    """Build compressed NAV mission-index ranges for failsafe recovery."""

    segment_to_recovery: dict[int, int] = {}

    for branch in failsafe_branches:
        recovery_mission_sequence = branch.get(
            "mission_sequence"
        )

        if not isinstance(recovery_mission_sequence, int):
            raise FlightExecutionCompileError(
                "Failsafe branch is missing mission_sequence."
            )

        for flat_segment_index in branch["route_segment_indexes"]:
            segment_to_recovery[flat_segment_index] = (
                recovery_mission_sequence
            )

    nav_assignments: list[tuple[int, int]] = []

    for item in mission_items:
        if item.get("command") != "MAV_CMD_NAV_WAYPOINT":
            continue

        waypoint_index = item.get("waypoint_index")

        if not isinstance(waypoint_index, int):
            continue

        flat_segment_index = None

        for waypoint_range in route_waypoint_ranges:
            if (
                waypoint_range["start_waypoint_index"]
                <= waypoint_index
                <= waypoint_range["end_waypoint_index"]
            ):
                route_index = waypoint_range["route_index"]

                route_waypoint_index = (
                    waypoint_index
                    - waypoint_range["start_waypoint_index"]
                )

                route_segment_index = max(
                    0,
                    route_waypoint_index - 1,
                )

                for index, segment in enumerate(
                    route_conformance_segments
                ):
                    if (
                        segment["route_index"] == route_index
                        and segment["route_segment_index"]
                        == route_segment_index
                    ):
                        flat_segment_index = index
                        break

                break

        if flat_segment_index is None:
            raise FlightExecutionCompileError(
                "Internal compiler consistency error: "
                "NAV waypoint could not be mapped to a Route segment."
            )

        recovery_mission_sequence = segment_to_recovery.get(
            flat_segment_index
        )

        if recovery_mission_sequence is None:
            raise FlightExecutionCompileError(
                "Internal compiler consistency error: "
                "Route segment has no compiled failsafe recovery branch."
            )

        nav_assignments.append((
            item["sequence"],
            recovery_mission_sequence,
        ))

    if not nav_assignments:
        return []

    jump_map: list[dict[str, int]] = []

    range_start = 0
    current_recovery = nav_assignments[0][1]

    for mission_sequence, recovery_mission_sequence in nav_assignments[1:]:
        if recovery_mission_sequence == current_recovery:
            continue

        jump_map.append({
            "start_mission_sequence": range_start,
            "end_mission_sequence": mission_sequence - 1,
            "recovery_mission_sequence": current_recovery,
        })

        range_start = mission_sequence
        current_recovery = recovery_mission_sequence

    first_failsafe_sequence = min(
        branch["mission_sequence"]
        for branch in failsafe_branches
    )

    final_happy_path_sequence = (
        first_failsafe_sequence - 2
    )

    jump_map.append({
        "start_mission_sequence": range_start,
        "end_mission_sequence": final_happy_path_sequence,
        "recovery_mission_sequence": current_recovery,
    })

    return jump_map


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Interpret a DroneNav Flight Execution Record into an "
            "operational NAVProxy command stream."
        )
    )

    parser.add_argument(
        "flight_execution",
        type=Path,
        help=(
            "Path to JSON containing the flight_execution object."
        ),
    )

    return parser.parse_args()


def main() -> int:
    if len(sys.argv) < 2:
        print(
            "Usage: python -m tooling.fer_compiler "
            "<flight_execution_record.json>",
            file=sys.stderr,
        )
        return 2

    arguments = parse_arguments()

    try:
        document = load_json(arguments.flight_execution)

        flight_execution = document.get("flight_execution")

        if not isinstance(flight_execution, dict):
            raise FlightExecutionCompileError(
                "Input JSON is missing the flight_execution object."
            )

        assertion_stream = compile_flight_execution(
            flight_execution=flight_execution,
        )

        json.dump(assertion_stream, sys.stdout, indent=2)
        sys.stdout.write("\n")

        return 0

    except FlightExecutionCompileError as exc:
        print(f"Compile error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


