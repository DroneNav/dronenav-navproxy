

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def resolve_applicable_flight_band(
    flight_bands: list[dict[str, Any]],
    operational_timezone: str,
    current_datetime: datetime | None = None,
) -> dict[str, Any] | None:
    """
    Resolve the single Flight Band applicable to the operational snapshot.

    Phase 2 requires Flight Bands to be non-overlapping:
    - zero applicable bands returns None;
    - one applicable band is returned;
    - multiple applicable bands raise a configuration error.

    Flight Band days use Sunday=0 through Saturday=6.
    """

    if not isinstance(flight_bands, list):
        raise ValueError(
            "flight_bands must be a list."
        )

    if (
        not isinstance(operational_timezone, str)
        or not operational_timezone
    ):
        raise ValueError(
            "operational_timezone must be a non-empty string."
        )

    try:
        timezone_info = ZoneInfo(operational_timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(
            "operational_timezone is invalid."
        ) from exc

    if current_datetime is None:
        operational_datetime = datetime.now(timezone_info)
    else:
        if current_datetime.tzinfo is None:
            raise ValueError(
                "current_datetime must include timezone information."
            )

        operational_datetime = current_datetime.astimezone(
            timezone_info
        )

    current_day = (
        operational_datetime.weekday() + 1
    ) % 7

    current_time = operational_datetime.time().replace(
        second=0,
        microsecond=0,
        tzinfo=None,
    )

    applicable_bands: list[dict[str, Any]] = []

    for flight_band in flight_bands:
        if not isinstance(flight_band, dict):
            raise RuntimeError(
                "The Flight Band API returned an invalid record."
            )

        days = flight_band.get("days")
        start_time_value = flight_band.get("start_time")
        end_time_value = flight_band.get("end_time")

        if not isinstance(days, list):
            raise RuntimeError(
                "A Flight Band is missing its days array."
            )

        if current_day not in [
            int(day)
            for day in days
        ]:
            continue

        if (
            not isinstance(start_time_value, str)
            or not isinstance(end_time_value, str)
        ):
            raise RuntimeError(
                "A Flight Band is missing its operating times."
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
            raise RuntimeError(
                "Flight Band times must use HH:MM format."
            ) from exc

        if start_time <= current_time <= end_time:
            applicable_bands.append(flight_band)

    if not applicable_bands:
        return None

    if len(applicable_bands) > 1:
        raise RuntimeError(
            "Multiple Flight Bands apply to the current operational "
            "day and time. Overlapping Flight Bands are not supported "
            "during Phase 2."
        )

    return applicable_bands[0]

