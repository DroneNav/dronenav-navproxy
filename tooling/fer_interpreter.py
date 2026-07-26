from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import requests

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_API_BASE_URL = "https://api.dronenav.org"
API_TIMEOUT_SECONDS = 10


class FlightExecutionCompileError(ValueError):
    """Raised when a Flight Execution Record cannot be interpreted."""


def load_api_object(
    api_base_url: str,
    endpoint: str,
    object_name: str,
) -> dict[str, Any]:
    """Retrieve one required object from the DroneNav API."""

    url = f"{api_base_url.rstrip('/')}{endpoint}"

    try:
        response = requests.get(
            url,
            headers={"Accept": "application/json"},
            timeout=API_TIMEOUT_SECONDS,
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


def load_departure_droneport(
    api_base_url: str,
    departure_droneport_id: str,
) -> dict[str, Any]:
    """Retrieve the departure DronePort referenced by the FER."""

    return load_api_object(
        api_base_url=api_base_url,
        endpoint=f"/api/droneports/{departure_droneport_id}",
        object_name="departure DronePort",
    )

def load_arrival_droneport(
    api_base_url: str,
    arrival_droneport_id: str,
) -> dict[str, Any]:
    """Retrieve the arrival DronePort referenced by the FER."""

    return load_api_object(
        api_base_url=api_base_url,
        endpoint=f"/api/droneports/{arrival_droneport_id}",
        object_name="arrival DronePort",
    )

def load_origin_site(
    api_base_url: str,
    origin_site_id: str,
) -> dict[str, Any]:
    """Retrieve the origin Site referenced by the FER."""

    return load_api_object(
        api_base_url=api_base_url,
        endpoint=f"/api/sites/{origin_site_id}",
        object_name="origin Site",
    )

def load_destination_site(
    api_base_url: str,
    destination_site_id: str,
) -> dict[str, Any]:
    """Retrieve the destination Site referenced by the FER."""

    return load_api_object(
        api_base_url=api_base_url,
        endpoint=f"/api/sites/{destination_site_id}",
        object_name="destination Site",
    )

def load_flight_bands(
    api_base_url: str,
    flight_class: str,
) -> list[dict[str, Any]]:
    """Retrieve active Flight Bands for the specified Flight Class."""

    response = load_api_object(
        api_base_url=api_base_url,
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
    api_base_url: str,
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
            api_base_url=api_base_url,
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
            "command": "NAV_ASSERT_POSITION_IN_GEOMETRY",
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
        api_base_url=api_base_url,
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
        "command": "NAV_ASSERT_POSITION_IN_GEOMETRY",
        "parameters": {
            "geometry_type": "polygon",
            "coordinates": geometry["coordinates"],
        },
    }


def build_arrival_position_assertion(
    flight_execution: dict[str, Any],
    api_base_url: str,
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
            api_base_url=api_base_url,
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
            "command": "NAV_ASSERT_ARRIVAL_IN_GEOMETRY",
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
        api_base_url=api_base_url,
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
        "command": "NAV_ASSERT_ARRIVAL_IN_GEOMETRY",
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
        "command": "NAV_ASSERT_DEPARTURE_TIME",
        "parameters": {
            "departure_date": local_departure.date().isoformat(),
            "departure_time": local_departure.time().isoformat(),
        },
    }


def build_flight_band_assertion(
    flight_execution: dict[str, Any],
    api_base_url: str,
) -> dict[str, Any] | None:
    """
    Build the applicable Flight Band assertion for a corridor flight.

    Local Site flights do not contain Routes and do not use Flight Bands.
    Flight Bands are evaluated in the priority order returned by the API.
    """

    route_ids = flight_execution.get("route_ids") or []

    if not route_ids:
        return None

    requested_departure = flight_execution.get(
        "requested_departure_datetime"
    )

    if not isinstance(requested_departure, str):
        raise FlightExecutionCompileError(
            "Corridor flights require requested_departure_datetime."
        )

    operational_timezone = flight_execution.get(
        "operational_timezone"
    )

    if not isinstance(operational_timezone, str) or not operational_timezone:
        raise FlightExecutionCompileError(
            "Corridor flights require operational_timezone."
        )

    flight_class = flight_execution.get("flight_class")

    if not isinstance(flight_class, str) or not flight_class:
        raise FlightExecutionCompileError(
            "Corridor flights require flight_class."
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
            f"Unknown operational timezone: {operational_timezone}"
        ) from exc

    local_departure = departure_datetime.astimezone(timezone)

    # Flight Band days use Sunday=0 through Saturday=6.
    departure_day = (local_departure.weekday() + 1) % 7
    departure_time = local_departure.time().replace(
        second=0,
        microsecond=0,
    )

    flight_bands = load_flight_bands(
        api_base_url=api_base_url,
        flight_class=flight_class,
    )

    for flight_band in flight_bands:
        if not isinstance(flight_band, dict):
            raise FlightExecutionCompileError(
                "Each Flight Band must be a JSON object."
            )

        days = flight_band.get("days")
        start_time_value = flight_band.get("start_time")
        end_time_value = flight_band.get("end_time")

        if not isinstance(days, list):
            raise FlightExecutionCompileError(
                "Flight Band is missing its days array."
            )

        if departure_day not in days:
            continue

        if (
            not isinstance(start_time_value, str)
            or not isinstance(end_time_value, str)
        ):
            raise FlightExecutionCompileError(
                "Flight Band start_time and end_time must be strings."
            )

        try:
            start_time = datetime.strptime(
                start_time_value,
                "%H:%M",
            ).time()

            end_time = datetime.strptime(
                end_time_value,
                "%H:%M",
            ).time()
        except ValueError as exc:
            raise FlightExecutionCompileError(
                "Flight Band times must use HH:MM format."
            ) from exc

        if not start_time <= departure_time <= end_time:
            continue

        min_agl_ft = flight_band.get("min_agl_ft")
        max_agl_ft = flight_band.get("max_agl_ft")

        if (
            isinstance(min_agl_ft, bool)
            or not isinstance(min_agl_ft, (int, float))
            or isinstance(max_agl_ft, bool)
            or not isinstance(max_agl_ft, (int, float))
            or max_agl_ft <= min_agl_ft
        ):
            raise FlightExecutionCompileError(
                "Flight Band contains invalid altitude limits."
            )

        return {
            "command": "NAV_ASSERT_FLIGHT_BAND",
            "parameters": {
                "min_agl_ft": min_agl_ft,
                "max_agl_ft": max_agl_ft,
            },
        }

    raise FlightExecutionCompileError(
        "No active Flight Band applies to the corridor flight's "
        "class and departure time."
    )


def build_route_assertions(
    flight_execution: dict[str, Any],
    api_base_url: str,
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
            api_base_url=api_base_url,
            endpoint=f"/api/routes/{route_id}",
            object_name="Route",
        )

        geometry = extract_geometry(
            route,
            "Route",
        )

        assertions.append(
            {
                "command": "NAV_ASSERT_ROUTE",
                "parameters": {
                    "geometry_type": "linestring",
                    "coordinates": geometry["coordinates"],
                },
            }
        )

    return assertions


def interpret_flight_execution(
    document: dict[str, Any],
    api_base_url: str,
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

    commands: list[dict[str, Any]] = []

    launch_assertion = build_launch_position_assertion(
        flight_execution=flight_execution,
        api_base_url=api_base_url,
    )

    commands.append({
        "sequence": len(commands),
        **launch_assertion,
    })

    departure_assertion = build_departure_time_assertion(
        flight_execution=flight_execution,
    )

    if departure_assertion is not None:
        commands.append({
            "sequence": len(commands),
            **departure_assertion,
        })

    flight_band_assertion = build_flight_band_assertion(
        flight_execution=flight_execution,
        api_base_url=api_base_url,
    )

    if flight_band_assertion is not None:
        commands.append({
            "sequence": len(commands),
            **flight_band_assertion,
        })

    arrival_assertion = build_arrival_position_assertion(
        flight_execution=flight_execution,
        api_base_url=api_base_url,
    )

    commands.append({
        "sequence": len(commands),
        **arrival_assertion,
    })

    route_assertions = build_route_assertions(
        flight_execution=flight_execution,
        api_base_url=api_base_url,
    )

    for route_assertion in route_assertions:
        commands.append({
                "sequence": len(commands),
                **route_assertion,
        })

    return {
        "flight_execution_id": flight_execution_id,
        "commands": commands,
    }


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

    parser.add_argument(
        "--api-base-url",
        default=DEFAULT_API_BASE_URL,
        help=(
            "DroneNav API base URL. "
            f"Default: {DEFAULT_API_BASE_URL}"
        ),
    )

    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()

    try:
        document = load_json(arguments.flight_execution)

        command_stream = interpret_flight_execution(
            document=document,
            api_base_url=arguments.api_base_url,
        )

        json.dump(command_stream, sys.stdout, indent=2)
        sys.stdout.write("\n")

        return 0

    except FlightExecutionCompileError as exc:
        print(f"Compile error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

