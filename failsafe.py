"""Platform-neutral NAVProxy failsafe evaluation."""

from __future__ import annotations

import logging
from typing import Any

from dataclasses import dataclass

from app.navproxy.simulator import TelemetryReading


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class FailsafeDecision:
    """One NAVProxy failsafe decision."""

    action: str
    reason: str | None = None


def evaluate_failsafe(
    telemetry: TelemetryReading,
) -> FailsafeDecision:
    """Evaluate normalized telemetry for a NAVProxy failsafe condition."""

    if telemetry.navigation_health == "unusable":
        return FailsafeDecision(
            action="land_now",
            reason="Navigation integrity is unusable.",
        )

    if telemetry.navigation_health == "degraded":
        return FailsafeDecision(
            action="abort_to_failsafe",
            reason="Navigation integrity has degraded below the governed threshold.",
        )

    if telemetry.energy_health == "critical":
        return FailsafeDecision(
            action="land_now",
            reason="Critical energy condition detected.",
        )

    if telemetry.energy_health == "degraded":
        return FailsafeDecision(
            action="abort_to_failsafe",
            reason="Energy reserve has degraded below the governed threshold.",
        )

    if telemetry.vehicle_health == "critical":
        return FailsafeDecision(
            action="land_now",
            reason="Critical vehicle-health condition detected.",
        )

    if telemetry.vehicle_health == "degraded":
        return FailsafeDecision(
            action="abort_to_failsafe",
            reason="Vehicle health has degraded below the governed threshold.",
        )

    return FailsafeDecision(
        action="continue",
    )


def get_failsafe_coordinate_for_segment(
    compiler_ir: dict[str, Any],
    segment: dict[str, Any],
) -> list[float]:
    """Return the governed failsafe coordinate for a Route segment."""

    failsafe_coordinate = segment.get(
        "failsafe_coordinate"
    )

    if (
        isinstance(failsafe_coordinate, list)
        and len(failsafe_coordinate) == 2
    ):
        return failsafe_coordinate

    assertions = compiler_ir.get("assertions", [])

    for assertion in assertions:
        if (assertion.get("assertion_type") != "NAV_ASSERT_POSITION_IN_GEOMETRY"):
            continue

        parameters = assertion.get("parameters")

        if not isinstance(parameters, dict):
            continue

        coordinate = parameters.get("coordinate")

        if (
            isinstance(coordinate, list)
            and len(coordinate) == 2
        ):
            LOGGER.debug(
                "Failsafe coordinate missing for Route segment; "
                "using departure coordinate fallback: "
                "route_id=%s route_segment_index=%s",
                segment.get("route_id"),
                segment.get("route_segment_index"),
            )

            return coordinate

    raise ValueError(
        "Unable to resolve failsafe recovery coordinate."
    )


def get_failsafe_mission_sequence_for_segment(
    compiler_ir: dict[str, Any],
    segment: dict[str, Any],
) -> int:
    """Return the preloaded failsafe LAND sequence for a Route segment."""

    flat_segment_index = segment.get("flat_segment_index")

    if not isinstance(flat_segment_index, int):
        raise ValueError(
            "Route segment is missing flat_segment_index."
        )

    failsafe_branches = compiler_ir["mission"]["failsafe_branches"]

    for branch in failsafe_branches:
        route_segment_indexes = branch.get(
            "route_segment_indexes",
            [],
        )

        if flat_segment_index not in route_segment_indexes:
            continue

        mission_sequence = branch.get("mission_sequence")

        if not isinstance(mission_sequence, int):
            raise ValueError(
                "Failsafe branch is missing mission_sequence."
            )

        return mission_sequence

    raise ValueError(
        "Unable to resolve failsafe recovery mission sequence."
    )


def is_failsafe_mission_sequence(
    compiler_ir: dict[str, Any],
    mission_sequence: int,
) -> bool:
    """Return whether a DroneNav mission sequence is a failsafe LAND."""

    failsafe_branches = compiler_ir["mission"]["failsafe_branches"]

    for branch in failsafe_branches:
        if branch.get("mission_sequence") == mission_sequence:
            return True

    return False

