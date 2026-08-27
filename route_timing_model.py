from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.navproxy.failsafe import (
    get_failsafe_coordinate_for_segment,
)

from app.navproxy.tooling.fer_compiler import (
    get_coordinate_distance_ft,
)

FEET_PER_MILE = 5280.0
SECONDS_PER_HOUR = 3600.0

ARRIVAL_TRANSITION_SECONDS = 10.0
LANDING_SECONDS = 15.0


def mph_to_feet_per_second(
    speed_mph: int | float,
) -> float:
    return (
        float(speed_mph)
        * FEET_PER_MILE
        / SECONDS_PER_HOUR
    )


@dataclass(frozen=True)
class SegmentTiming:
    seconds_to_destination: float
    seconds_to_failsafe: float


class RouteTimingModel:
    def __init__(
        self,
        compiler_ir: dict[str, Any],
    ) -> None:
        self._segment_timings = (
            self._build_segment_timings(
                compiler_ir
            )
        )


    def _build_segment_timings(
        self,
        compiler_ir: dict[str, Any],
    ) -> dict[int, SegmentTiming]:

        segments = compiler_ir["mission"][
            "route_conformance_segments"
        ]

        timings: dict[int, SegmentTiming] = {}

        segment_durations: list[float] = []

        for segment in segments:
            distance_ft = get_coordinate_distance_ft(
                segment["start_coordinate"],
                segment["end_coordinate"],
            )

            speed_ft_per_second = (
                mph_to_feet_per_second(
                    segment["speed_limit_mph"]
                )
            )

            segment_durations.append(
                distance_ft / speed_ft_per_second
            )

        remaining_seconds = (
            ARRIVAL_TRANSITION_SECONDS
            + LANDING_SECONDS
        )

        destination_times: list[float] = []

        for duration in reversed(segment_durations):
            remaining_seconds += duration
            destination_times.insert(
                0,
                remaining_seconds,
            )

        for index, segment in enumerate(segments):

            failsafe_coordinate = (
                get_failsafe_coordinate_for_segment(
                    compiler_ir,
                    segment,
                )
            )

            failsafe_distance_ft = (
                get_coordinate_distance_ft(
                    segment["start_coordinate"],
                    failsafe_coordinate,
                )
            )

            failsafe_speed_ft_per_second = (
                mph_to_feet_per_second(
                    segment["speed_limit_mph"]
                )
            )

            timings[index] = SegmentTiming(
                seconds_to_destination=(
                    destination_times[index]
                ),
                seconds_to_failsafe=(
                    failsafe_distance_ft
                    / failsafe_speed_ft_per_second
                ),
            )

        return timings


    def get_seconds_to_destination(
        self,
        segment_index: int,
    ) -> float:

        return self._segment_timings[
            segment_index
        ].seconds_to_destination


    def get_seconds_to_failsafe(
        self,
        segment_index: int,
    ) -> float:

        return self._segment_timings[
            segment_index
        ].seconds_to_failsafe


