from __future__ import annotations

import requests

from app.config.constants import (
    DEFAULT_API_BASE_URL,
    DEFAULT_API_TIMEOUT_SECONDS,
)


class IntersectionReservationError(RuntimeError):
    """Raised when NAVProxy cannot request an intersection reservation."""


def reserve_intersection(
    *,
    flight_execution_id: str,
    route_node_id: str,
    flight_band_id: str,
    assigned_relative_altitude_ft: int,
    from_route_id: str,
    to_route_id: str,
) -> str | None:
    """
    Request an intersection reservation for a Flight Execution.
    """

    url = (
        f"{DEFAULT_API_BASE_URL.rstrip('/')}"
        f"/api/flight-executions/{flight_execution_id}"
        f"/intersection"
    )

    payload = {
        "route_node_id": route_node_id,
        "flight_band_id": flight_band_id,
        "assigned_relative_altitude_ft": (
            assigned_relative_altitude_ft
        ),
        "from_route_id": from_route_id,
        "to_route_id": to_route_id,
    }

    try:
        response = requests.post(
            url,
            json=payload,
            headers={"Accept": "application/json"},
            timeout=DEFAULT_API_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise IntersectionReservationError(
            "Could not request intersection reservation "
            f"from {url}: {exc}"
        ) from exc

    try:
        result = response.json()
    except requests.JSONDecodeError as exc:
        raise IntersectionReservationError(
            "The intersection reservation API returned "
            "invalid JSON."
        ) from exc

    if result.get("reserved") is not True:
        return None

    intersection_state_id = result.get(
        "intersection_state_id"
    )

    if not intersection_state_id:
        raise IntersectionReservationError(
            "Intersection reservation succeeded without "
            "an intersection_state_id."
        )

    return str(intersection_state_id)


