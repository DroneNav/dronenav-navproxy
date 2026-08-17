from __future__ import annotations

import logging

LOGGER = logging.getLogger(__name__)


class ReusableFlightSimulator:
    """Simulate flight-controller behavior for a reusable Flight Execution."""

    def __init__(
        self,
        preflight_seconds: int,
        flight_seconds: int,
    ) -> None:
        self.preflight_seconds = preflight_seconds
        self.flight_seconds = flight_seconds

    def get_current_position(self) -> tuple[float, float]:
        """Return the simulated aircraft's current latitude and longitude."""
        """   Zone...  """
        return (
            34.0778,
            -84.3015,
        )
        
        """
        return (
            34.0784,
            -84.3010,
        )
        """
        """  Outside, neither Zone nor Site...
        return (
            34.0850,
            -84.3100,
        )
        """
