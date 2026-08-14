
from dataclasses import dataclass

import requests

from app.config.constants import (
    DEFAULT_API_BASE_URL,
    DEFAULT_API_TIMEOUT_SECONDS,
)


@dataclass
class ActualPathSampler:
    """Incrementally reduce telemetry positions into an actual flight path."""

    tolerance_ft: float

    def __post_init__(self) -> None:
        self._anchor: list[float] | None = None
        self._candidate: list[float] | None = None


    def telemetry_coordinate(self, telemetry) -> list[float]:
        """Return one telemetry position in GeoJSON coordinate order."""

        return [
            telemetry.longitude,
            telemetry.latitude,
        ]

    def add(self, telemetry) -> list[list[float]]:
        """Accept telemetry and return any coordinates ready to persist."""

        coordinate = self.telemetry_coordinate(telemetry)

        if self._anchor is None:
            self._anchor = coordinate
            return []

        if self._candidate is None:
            if coordinate == self._anchor:
                return []

            self._candidate = coordinate
            return [
                self._anchor,
                self._candidate,
            ]

        deviation_ft = self.candidate_deviation_ft(
            coordinate,
        )

        if deviation_ft > self.tolerance_ft:
            retained = self._candidate

            self._anchor = self._candidate
            self._candidate = coordinate

            return [retained]

        self._candidate = coordinate

        return []

    def finish(self) -> list[list[float]]:
        """Return any final coordinate that must be persisted."""

        if self._candidate is None:
            return []

        final_coordinate = self._candidate
        self._anchor = self._candidate
        self._candidate = None

        return [final_coordinate]

    def candidate_deviation_ft(
        self,
        newest_coordinate: list[float],
    ) -> float:
        """Return candidate distance from the anchor-to-newest segment."""

        if self._anchor is None or self._candidate is None:
            return 0.0

        endpoint = (
            f"{DEFAULT_API_BASE_URL.rstrip('/')}"
            f"/api/routes/segment-conformance"
        )

        response = requests.post(
            endpoint,
            json={
                "latitude": self._candidate[1],
                "longitude": self._candidate[0],
                "start_latitude": self._anchor[1],
                "start_longitude": self._anchor[0],
                "end_latitude": newest_coordinate[1],
                "end_longitude": newest_coordinate[0],
                "route_width_ft": 1,
            },
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=DEFAULT_API_TIMEOUT_SECONDS,
        )

        response.raise_for_status()

        result = response.json()

        return float(result["distance_ft"])

