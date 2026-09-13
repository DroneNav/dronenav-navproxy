from __future__ import annotations

import requests

from app.config.constants import (
    DEFAULT_API_BASE_URL,
    DEFAULT_API_TIMEOUT_SECONDS,
)


class DronePortLandingAssignmentError(RuntimeError):
    """Raised when NAVProxy cannot obtain a landing-space assignment."""


def assign_droneport_landing_space(
    *,
    flight_execution_id: str,
) -> dict:
    """
    Obtain the landing-space assignment for a Flight Execution.
    """

    url = (
        f"{DEFAULT_API_BASE_URL.rstrip('/')}"
        f"/api/flight-executions/{flight_execution_id}"
        f"/landing-space"
    )

    try:
        response = requests.post(
            url,
            headers={"Accept": "application/json"},
            timeout=DEFAULT_API_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise DronePortLandingAssignmentError(
            f"Could not request DronePort landing-space assignment "
            f"from {url}: {exc}"
        ) from exc

    try:
        result = response.json()
    except requests.JSONDecodeError as exc:
        raise DronePortLandingAssignmentError(
            "The DronePort landing-space assignment API "
            "returned invalid JSON."
        ) from exc

    if result.get("assigned") is not True:
        raise DronePortLandingAssignmentError(
            "The DronePort landing-space assignment API "
            "did not return an assignment."
        )

    landing_space_id = result.get("landing_space_id")
    arrival_droneport_id = result.get(
        "arrival_droneport_id"
    )
    longitude = result.get("longitude")
    latitude = result.get("latitude")
    heading_degrees = result.get("heading_degrees")

    if not isinstance(landing_space_id, str) or not landing_space_id:
        raise DronePortLandingAssignmentError(
            "Landing-space assignment is missing landing_space_id."
        )

    if (
        not isinstance(arrival_droneport_id, str)
        or not arrival_droneport_id
    ):
        raise DronePortLandingAssignmentError(
            "Landing-space assignment is missing arrival_droneport_id."
        )

    if (
        isinstance(longitude, bool)
        or not isinstance(longitude, (int, float))
        or longitude < -180
        or longitude > 180
    ):
        raise DronePortLandingAssignmentError(
            "Landing-space assignment contains invalid longitude."
        )

    if (
        isinstance(latitude, bool)
        or not isinstance(latitude, (int, float))
        or latitude < -90
        or latitude > 90
    ):
        raise DronePortLandingAssignmentError(
            "Landing-space assignment contains invalid latitude."
        )

    if (
        isinstance(heading_degrees, bool)
        or not isinstance(heading_degrees, (int, float))
        or heading_degrees < 0
        or heading_degrees >= 360
    ):
        raise DronePortLandingAssignmentError(
            "Landing-space assignment contains invalid heading_degrees."
        )

    return {
        "landing_space_id": landing_space_id,
        "arrival_droneport_id": arrival_droneport_id,
        "coordinate": [
            float(longitude),
            float(latitude),
        ],
        "heading_degrees": float(heading_degrees),
        "charging_capable": bool(
            result.get("charging_capable", False)
        ),
    }

