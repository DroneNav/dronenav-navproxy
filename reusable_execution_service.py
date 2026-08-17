from __future__ import annotations

import logging
from typing import Any

import requests

from app.config.constants import (
    DEFAULT_API_BASE_URL,
    DEFAULT_API_TIMEOUT_SECONDS,
)

from .geofence import build_geofence_commands
from .reusable_simulator import ReusableFlightSimulator
from .tooling.compile_geofence import compile_geofence_commands
from .tooling.emit_geofence import emit_geofence

from pymavlink import mavutil

from .tooling.upload_mission import (
    DEFAULT_CONNECTION,
    connect_vehicle,
    upload_mission,
)
from .tooling.mavlink_parameters import (
    read_parameter,
    set_parameter,
)
from .flight_log_service import (
    FlightProcessContext,
    append_flight_log,
)


LOGGER = logging.getLogger(__name__)


def load_flight_execution(
    flight_execution_id: str,
) -> dict[str, Any]:
    """Load the Flight Execution Record."""

    endpoint = (
        f"{DEFAULT_API_BASE_URL.rstrip('/')}"
        f"/api/flight-executions/{flight_execution_id}"
    )

    response = requests.get(
        endpoint,
        headers={
            "Accept": "application/json",
        },
        timeout=DEFAULT_API_TIMEOUT_SECONDS,
    )

    response.raise_for_status()

    value = response.json()

    return value.get("flight_execution", value)


def run_reusable_navproxy_process(
    flight_execution_id: str,
    flight_id: str,
    preflight_seconds: int,
    flight_seconds: int,
) -> None:
    """Run one reusable NAVProxy flight process."""

    LOGGER.info(
        "Reusable NAVProxy execution started: execution=%s flight=%s",
        flight_execution_id,
        flight_id,
    )

    flight_execution = load_flight_execution(
        flight_execution_id,
    )

    LOGGER.debug(
        "Flight Execution loaded: execution=%s",
        flight_execution_id,
    )

    site_id = flight_execution["origin_site_id"]

    site_package = load_site_package(
        site_id,
    )

    LOGGER.debug(
        "Site package loaded: site=%s zones=%d",
        site_id,
        len(site_package["zones"]),
    )

    simulator = ReusableFlightSimulator(
        preflight_seconds=preflight_seconds,
        flight_seconds=flight_seconds,
    )

    latitude, longitude = simulator.get_current_position()

    LOGGER.debug(
        "Reusable preflight FC position: latitude=%s longitude=%s",
        latitude,
        longitude,
    )

    governing_geometry = resolve_governing_geometry(
        site_package,
        latitude,
        longitude,
    )

    assert_position_in_governing_geometry(
        governing_geometry,
    )

    LOGGER.debug(
        "Governing geometry: %s",
        governing_geometry,
    )

    geofence_definition = build_geofence_definition(
        governing_geometry,
    )

    LOGGER.debug(
        "Geofence definition: %s",
        geofence_definition,
    )

    geofence_commands = build_geofence_commands(
        geofence_definition,
    )

    LOGGER.debug(
        "Geofence commands: count=%d",
        len(geofence_commands),
    )

    compiled_geofence_commands = compile_geofence_commands(
        geofence_commands,
    )

    LOGGER.debug(
        "Geofence commands compiled: count=%d",
        len(compiled_geofence_commands),
    )

    geofence_items = emit_geofence(
        compiled_geofence_commands,
    )

    LOGGER.debug(
        "Geofence items emitted: count=%d",
        len(geofence_items),
    )

    connection = connect_vehicle(
        DEFAULT_CONNECTION,
        10.0,
    )

    upload_mission(
        connection,
        items=geofence_items,
        mission_type=mavutil.mavlink.MAV_MISSION_TYPE_FENCE,
    )

    LOGGER.info(
        "Geofence uploaded successfully: execution=%s items=%d",
        flight_execution_id,
        len(geofence_items),
    )

    maximum_altitude_meters = feet_to_meters(
        geofence_definition["maximum_altitude_ft"]
    )

    set_parameter(
        connection,
        "FENCE_ALT_MAX_TP",
        0.0,
        timeout_seconds=5.0,
    )

    set_parameter(
        connection,
        "FENCE_ALT_MAX",
        maximum_altitude_meters,
        timeout_seconds=5.0,
    )

    verified_altitude_meters = read_parameter(
        connection,
        "FENCE_ALT_MAX",
        timeout_seconds=5.0,
    )

    if abs(verified_altitude_meters - maximum_altitude_meters) > 0.01:
        raise RuntimeError(
            "FENCE_ALT_MAX verification failed: "
            f"expected={maximum_altitude_meters} "
            f"actual={verified_altitude_meters}"
        )

    LOGGER.info(
        "Fence altitude configured: execution=%s altitude_m=%.2f",
        flight_execution_id,
        verified_altitude_meters,
    )

    set_parameter(
        connection,
        "FENCE_TYPE",
        5.0,
        timeout_seconds=5.0,
    )

    verified_fence_type = read_parameter(
        connection,
        "FENCE_TYPE",
        timeout_seconds=5.0,
    )

    if verified_fence_type != 5.0:
        raise RuntimeError(
            "FENCE_TYPE verification failed: "
            f"expected=5.0 actual={verified_fence_type}"
        )

    LOGGER.info(
        "Fence type configured: execution=%s fence_type=%s",
        flight_execution_id,
        verified_fence_type,
    )

    set_parameter(
        connection,
        "FENCE_ENABLE",
        1.0,
        timeout_seconds=5.0,
    )

    verified_fence_enable = read_parameter(
        connection,
        "FENCE_ENABLE",
        timeout_seconds=5.0,
    )

    if verified_fence_enable != 1.0:
        raise RuntimeError(
            "FENCE_ENABLE verification failed: "
            f"expected=1.0 actual={verified_fence_enable}"
        )

    LOGGER.info(
        "Fence enabled: execution=%s fence_enable=%s",
        flight_execution_id,
        verified_fence_enable,
    )

    context = FlightProcessContext(
        flight_execution_id=flight_execution_id,
        flight_id=flight_id,
        lifecycle_phase="pre_flight",
    )

    append_flight_log(
        context=context,
        lifecycle_phase="pre_flight",
        event_type="geofence_configured",
        event_status="completed",
        message=(
            "Reusable preflight configured and enabled the governed geofence "
            "on the flight controller."
        ),
        details={
            "geofence_item_count": len(geofence_items),
            "maximum_altitude_ft": geofence_definition["maximum_altitude_ft"],
            "maximum_altitude_meters": verified_altitude_meters,
            "fence_type": verified_fence_type,
            "fence_enabled": verified_fence_enable,
            "governing_geometry_type": governing_geometry["geometry_type"],
        },
    )


def resolve_governing_geometry(
    site_package: dict[str, Any],
    latitude: float,
    longitude: float,
) -> dict[str, Any] | None:
    """Resolve the geometry governing the reusable flight."""

    site = site_package["site"]
    zones = site_package["zones"]

    for zone in zones:
        if zone["zone_type"] != "inclusion":
            continue

        if evaluate_zone_containment(
            zone["zone_id"],
            latitude,
            longitude,
        ):
            return {
                "geometry_type": "zone",
                "geometry": zone["geometry"],
                "maximum_altitude_ft": zone["maximum_altitude_ft"],
                "ground_elevation_ft": min(attribute["ground_elevation_ft"]
                    for attribute in zone["zone_attributes"]),
                "zone_id": zone["zone_id"],
                "restricted_zones": [],
            }

    site_id = site["site_id"]

    if evaluate_site_containment(
        site_id,
        latitude,
        longitude,
    ):
        return {
            "geometry_type": "site",
            "geometry": site["geometry"],
            "maximum_altitude_ft": site["maximum_altitude_ft"],
            "ground_elevation_ft": min(attribute["ground_elevation_ft"]
                for attribute in site["site_attributes"]),
            "site_id": site_id,
            "restricted_zones": [
                zone
                for zone in zones
                if zone["zone_type"] == "restricted"
            ],
        }

    return None


def load_site_package(
    site_id: str,
) -> dict[str, Any]:
    """Load the Site and its Zones."""

    endpoint = (
        f"{DEFAULT_API_BASE_URL.rstrip('/')}"
        f"/api/sites/{site_id}/package"
    )

    response = requests.get(
        endpoint,
        headers={
            "Accept": "application/json",
        },
        timeout=DEFAULT_API_TIMEOUT_SECONDS,
    )

    response.raise_for_status()

    return response.json()


def evaluate_zone_containment(
    zone_id: str,
    latitude: float,
    longitude: float,
) -> bool:
    """Return whether the aircraft is inside the Zone."""

    endpoint = (
        f"{DEFAULT_API_BASE_URL.rstrip('/')}"
        f"/api/zones/{zone_id}/point-containment"
    )

    response = requests.post(
        endpoint,
        json={
            "latitude": latitude,
            "longitude": longitude,
        },
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        timeout=DEFAULT_API_TIMEOUT_SECONDS,
    )

    response.raise_for_status()

    return response.json()["inside"]


def evaluate_site_containment(
    site_id: str,
    latitude: float,
    longitude: float,
) -> bool:
    """Return whether the aircraft is inside the Site."""

    endpoint = (
        f"{DEFAULT_API_BASE_URL.rstrip('/')}"
        f"/api/sites/{site_id}/point-containment"
    )

    response = requests.post(
        endpoint,
        json={
            "latitude": latitude,
            "longitude": longitude,
        },
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        timeout=DEFAULT_API_TIMEOUT_SECONDS,
    )

    response.raise_for_status()

    return response.json()["inside"]


def assert_position_in_governing_geometry(
    governing_geometry: dict[str, Any] | None,
) -> None:
    """Assert that the aircraft is within authorized flight geometry."""

    if governing_geometry is None:
        raise RuntimeError(
            "Aircraft is outside the authorized flight geometry."
        )


def build_geofence_definition(
    governing_geometry: dict[str, Any],
) -> dict[str, Any]:
    """Build the geofence definition from the governing geometry."""

    return {
        "inclusion_geometry": governing_geometry["geometry"],
        "maximum_altitude_ft": (
            governing_geometry["ground_elevation_ft"]
            + governing_geometry["maximum_altitude_ft"]
        ),
        "exclusion_geometries": [
            zone["geometry"]
            for zone in governing_geometry["restricted_zones"]
        ],
    }

def feet_to_meters(value: float) -> float:
    """Convert feet to meters."""

    return value * 0.3048


