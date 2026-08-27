from __future__ import annotations

from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt
from datetime import datetime


FEET_PER_METER = 3.280839895


def distance_ft(
    latitude_1: float,
    longitude_1: float,
    latitude_2: float,
    longitude_2: float,
) -> float:
    """Return great-circle distance between two coordinates in feet."""

    earth_radius_m = 6371008.8

    lat_1 = radians(latitude_1)
    lon_1 = radians(longitude_1)
    lat_2 = radians(latitude_2)
    lon_2 = radians(longitude_2)

    delta_lat = lat_2 - lat_1
    delta_lon = lon_2 - lon_1

    a = (
        sin(delta_lat / 2.0) ** 2
        + cos(lat_1)
        * cos(lat_2)
        * sin(delta_lon / 2.0) ** 2
    )

    central_angle = 2.0 * asin(
        sqrt(a)
    )

    return (
        earth_radius_m
        * central_angle
        * FEET_PER_METER
    )


@dataclass
class EnergyHealthEstimate:
    health: str | None
    battery_percent: float | None
    estimated_destination_percent: float | None
    estimated_failsafe_percent: float | None
    reserve_percent: float


class EnergyHealthModel:
    """Estimate mission-contextual energy health from observed battery usage."""

    def __init__(
        self,
        *,
        reserve_percent: float = 10.0,
        minimum_consumed_percent: float = 1.0,
        minimum_elapsed_seconds: float = 10.0,
    ) -> None:
        self.reserve_percent = reserve_percent
        self.minimum_consumed_percent = minimum_consumed_percent
        self.minimum_elapsed_seconds = minimum_elapsed_seconds

        self._initial_battery_percent: float | None = None
        self._initial_observed_at: datetime | None = None

    def update(
        self,
        *,
        observed_at: datetime,
        battery_percent: float | None,
        seconds_to_destination: float,
        seconds_to_failsafe: float,
    ) -> EnergyHealthEstimate:
        """Update observed consumption and return current energy health."""

        if battery_percent is None:
            return EnergyHealthEstimate(
                health=None,
                battery_percent=None,
                estimated_destination_percent=None,
                estimated_failsafe_percent=None,
                reserve_percent=self.reserve_percent,
            )

        if self._initial_battery_percent is None:
            self._initial_battery_percent = battery_percent
            self._initial_observed_at = observed_at

            return EnergyHealthEstimate(
                health=None,
                battery_percent=battery_percent,
                estimated_destination_percent=None,
                estimated_failsafe_percent=None,
                reserve_percent=self.reserve_percent,
            )

        if self._initial_observed_at is None:
            return EnergyHealthEstimate(
                health=None,
                battery_percent=battery_percent,
                estimated_destination_percent=None,
                estimated_failsafe_percent=None,
                reserve_percent=self.reserve_percent,
            )

        elapsed_seconds = (
            observed_at - self._initial_observed_at
        ).total_seconds()

        consumed_percent = max(
            0.0,
            self._initial_battery_percent - battery_percent,
        )

        if (
            consumed_percent < self.minimum_consumed_percent
            or elapsed_seconds < self.minimum_elapsed_seconds
        ):
            return EnergyHealthEstimate(
                health=None,
                battery_percent=battery_percent,
                estimated_destination_percent=None,
                estimated_failsafe_percent=None,
                reserve_percent=self.reserve_percent,
            )

        percent_per_second = (
            consumed_percent
            / elapsed_seconds
        )

        estimated_destination_percent = (
            seconds_to_destination
            * percent_per_second
        )

        estimated_failsafe_percent = (
            seconds_to_failsafe
            * percent_per_second
        )

        if (
            battery_percent
            >= estimated_destination_percent
            + self.reserve_percent
        ):
            health = "healthy"

        elif (
            battery_percent
            >= estimated_failsafe_percent
            + self.reserve_percent
        ):
            health = "degraded"

        else:
            health = "critical"

        return EnergyHealthEstimate(
            health=health,
            battery_percent=battery_percent,
            estimated_destination_percent=(
                estimated_destination_percent
            ),
            estimated_failsafe_percent=(
                estimated_failsafe_percent
            ),
            reserve_percent=self.reserve_percent,
        )
