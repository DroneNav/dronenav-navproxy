
import requests


from app.config.constants import (
    DEFAULT_API_BASE_URL,
    DEFAULT_API_TIMEOUT_SECONDS,
)


def start_actual_path(
    flight_execution_id: str,
    flight_id: str,
    coordinates: list[list[float]],
) -> None:
    """Create an actual path using its first two sampled coordinates."""

    if len(coordinates) != 2:
        raise ValueError(
            "Actual path creation requires exactly two coordinates."
        )

    endpoint = (
        f"{DEFAULT_API_BASE_URL.rstrip('/')}"
        f"/api/actual-paths/{flight_execution_id}"
    )

    response = requests.post(
        endpoint,
        json={
            "flight_id": flight_id,
            "geometry": {
                "type": "LineString",
                "coordinates": coordinates,
            },
        },
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        timeout=DEFAULT_API_TIMEOUT_SECONDS,
    )

    response.raise_for_status()


def update_actual_path(
    flight_execution_id: str,
    flight_id: str,
    coordinates: list[list[float]] | None = None,
    status: str | None = None,
) -> None:
    """Append sampled coordinates and optionally update actual-path status."""

    endpoint = (
        f"{DEFAULT_API_BASE_URL.rstrip('/')}"
        f"/api/actual-paths/{flight_execution_id}"
    )

    payload = {
        "flight_id": flight_id,
    }

    if coordinates:
        payload["coordinates"] = coordinates

    if status is not None:
        payload["status"] = status

    response = requests.patch(
        endpoint,
        json=payload,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        timeout=DEFAULT_API_TIMEOUT_SECONDS,
    )

    response.raise_for_status()


def complete_actual_path(
    flight_execution_id: str,
    flight_id: str,
    coordinates: list[list[float]] | None = None,
) -> None:
    """Complete actual-path recording, optionally appending final points."""

    update_actual_path(
        flight_execution_id=flight_execution_id,
        flight_id=flight_id,
        coordinates=coordinates,
        status="complete",
    )


