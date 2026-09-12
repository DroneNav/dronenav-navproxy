from __future__ import annotations

import time

import requests

from app.config.constants import (
    DEFAULT_API_BASE_URL,
    DEFAULT_API_TIMEOUT_SECONDS,
)


class DronePortLaunchAuthorizationError(RuntimeError):
    """Raised when NAVProxy cannot obtain DronePort launch authorization."""


def wait_for_droneport_launch_authorization(
    *,
    flight_execution_id: str,
) -> None:
    """
    Wait until the API authorizes launch from the departure DronePort.
    """

    url = (
        f"{DEFAULT_API_BASE_URL.rstrip('/')}"
        f"/api/flight-executions/{flight_execution_id}"
        f"/launch-authorization"
    )

    while True:
        try:
            response = requests.post(
                url,
                headers={"Accept": "application/json"},
                timeout=DEFAULT_API_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise DronePortLaunchAuthorizationError(
                f"Could not request DronePort launch authorization "
                f"from {url}: {exc}"
            ) from exc

        try:
            result = response.json()
        except requests.JSONDecodeError as exc:
            raise DronePortLaunchAuthorizationError(
                "The DronePort launch authorization API "
                "returned invalid JSON."
            ) from exc

        if result.get("authorized") is True:
            return

        retry_after_seconds = result.get(
            "retry_after_seconds"
        )

        if retry_after_seconds is None:
            raise DronePortLaunchAuthorizationError(
                "Launch authorization was denied without "
                "retry_after_seconds."
            )

        try:
            retry_after_seconds = int(retry_after_seconds)
        except (TypeError, ValueError) as exc:
            raise DronePortLaunchAuthorizationError(
                "Invalid retry_after_seconds returned by "
                "launch authorization API."
            ) from exc

        if retry_after_seconds < 1:
            retry_after_seconds = 1

        time.sleep(retry_after_seconds)

