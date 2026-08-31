from __future__ import annotations

import time

import requests

from app.config.constants import (
    DEFAULT_API_BASE_URL,
    DEFAULT_API_TIMEOUT_SECONDS,
    ROUTE_SLOT_RETRY_COUNT,
    ROUTE_SLOT_RETRY_SECONDS,
)


class RouteSlotReservationError(RuntimeError):
    """Raised when NAVProxy cannot reserve a Route slot."""


def reserve_route_slot(
    *,
    flight_execution_id: str,
    route_id: str,
    flight_band_id: str,
) -> int | float:
    """
    Reserve a Route/Flight Band slot for a Flight Execution.
    """

    url = (
        f"{DEFAULT_API_BASE_URL.rstrip('/')}"
        f"/api/flight-executions/{flight_execution_id}"
        f"/route-slot"
    )

    payload = {
        "route_id": route_id,
        "flight_band_id": flight_band_id,
    }

    for attempt in range(ROUTE_SLOT_RETRY_COUNT):
        try:
            response = requests.post(
                url,
                json=payload,
                headers={"Accept": "application/json"},
                timeout=DEFAULT_API_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise RouteSlotReservationError(
                f"Could not reserve Route slot from {url}: {exc}"
            ) from exc

        try:
            result = response.json()
        except requests.JSONDecodeError as exc:
            raise RouteSlotReservationError(
                "The Route slot API returned invalid JSON."
            ) from exc

        assigned_altitude = result.get(
            "assigned_relative_altitude_ft"
        )

        if assigned_altitude is not None:
            return assigned_altitude

        if attempt < ROUTE_SLOT_RETRY_COUNT - 1:
            time.sleep(ROUTE_SLOT_RETRY_SECONDS)

    raise RouteSlotReservationError(
        "No Route slot was available after "
        f"{ROUTE_SLOT_RETRY_COUNT} attempts."
    )


