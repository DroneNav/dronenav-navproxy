from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.navproxy.failsafe import (
    get_failsafe_coordinate_for_segment,
)

from app.navproxy.tooling.fer_compiler import (
    get_coordinate_distance_ft,
)

ARRIVAL_TRANSITION_SECONDS = 10.0
LANDING_SECONDS = 15.0



@dataclass(frozen=True)
class SegmentTiming:
    seconds_to_destination: float
    seconds_to_failsafe: float


class RouteTimingModel:
    def __init__(
        self,
        compiler_ir: dict[str, Any],
        commanded_cruise_speed_ft_s: float,
    ) -> None:
        if commanded_cruise_speed_ft_s <= 0:
            raise ValueError(
                "Commanded cruise speed must be positive."
            )

        self._segment_timings = (
            self._build_segment_timings(
                compiler_ir,
                commanded_cruise_speed_ft_s,
            )
        )

    def _build_segment_timings(
        self,
        compiler_ir: dict[str, Any],
        commanded_cruise_speed_ft_s: float,
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

            speed_ft_per_second = commanded_cruise_speed_ft_s

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

            failsafe_speed_ft_per_second = commanded_cruise_speed_ft_s

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


