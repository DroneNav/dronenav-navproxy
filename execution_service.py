"""Coordinate one NAVProxy-controlled flight execution."""

from __future__ import annotations

import logging

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

import requests

from .actual_path_sampler import ActualPathSampler
from .actual_path_service import (
    complete_actual_path,
    start_actual_path,
    update_actual_path,
)

from app.config.constants import (
    DEFAULT_API_BASE_URL,
    DEFAULT_API_TIMEOUT_SECONDS,
    LAUNCH_WINDOW_EXPIRES_MINUTES,
    LAUNCH_WINDOW_PREFLIGHT_MINUTES,
)

from . import constants
from .drupal_update_status import notify_flight_plan_status
from .flight_log_service import (
    FlightProcessContext,
    append_flight_log,
    get_requested_departure_datetime,
)
from .settings import (
    DEFAULT_FLIGHT_SECONDS,
    DEFAULT_PREFLIGHT_SECONDS,
    FLIGHT_PLAN_STATUS_ACTIVE,
    FLIGHT_PLAN_STATUS_COMPLETED,
    FLIGHT_PLAN_STATUS_SUBMITTED,
)
from .simulator import FlightSimulator, TelemetryReading
from .tooling.fer_compiler import (
    FlightExecutionCompileError,
    load_and_compile_flight_execution,
    load_flight_bands,
)
from .flight_band_resolver import resolve_applicable_flight_band

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class AssertionResult:
    """Result returned by one NAVProxy assertion."""

    command: str
    passed: bool
    message: str


@dataclass(frozen=True)
class PreflightResult:
    """Combined result of all executed preflight assertions."""

    flight_execution_uuid: str
    status: constants.PreflightStatus
    assertion_results: tuple[AssertionResult, ...]

@dataclass(frozen=True)
class PostflightResult:
    """Combined result of all executed post-flight assertions."""

    flight_execution_uuid: str
    status: constants.PostflightStatus
    assertion_results: tuple[AssertionResult, ...]


def run_navproxy_process(
    flight_execution_id: str,
    flight_id: str,
    preflight_seconds: int = DEFAULT_PREFLIGHT_SECONDS,
    flight_seconds: int = DEFAULT_FLIGHT_SECONDS,
) -> None:
    """Run one NAVProxy-controlled simulated aircraft flight."""

    simulator = FlightSimulator(
        preflight_seconds=_validate_wait_seconds(
            "preflight_seconds",
            preflight_seconds,
        ),
        flight_seconds=_validate_wait_seconds(
            "flight_seconds",
            flight_seconds,
        ),
    )

    try:
        flight_execution, compiler_ir = load_and_compile_flight_execution(
            flight_execution_id=flight_execution_id,
        )
    except FlightExecutionCompileError:
        release_flight_execution(
            flight_execution_id,
        )

        LOGGER.exception(
            "NAVProxy Flight Execution compilation failed: "
            "execution=%s flight=%s",
            flight_execution_id,
            flight_id,
        )

        return

    context = FlightProcessContext(
        flight_execution_id=flight_execution_id,
        flight_id=flight_id,
        lifecycle_phase="pre_flight",
        flight_execution=flight_execution,
        compiler_ir=compiler_ir,
    )

    requested_departure_datetime = get_requested_departure_datetime(
        context.flight_execution_id,
    )

    LOGGER.info(
        "NAVProxy execution started: execution=%s flight=%s assertions=%d",
        context.flight_execution_id,
        context.flight_id,
        len(compiler_ir.get("assertions", [])),
    )

    preflight_result = execute_preflight(context)

    record_preflight_result(
        context,
        preflight_result,
    )

    if preflight_result.status != constants.PreflightStatus.PASSED:

        release_flight_execution(
            context.flight_execution_id,
        )

        LOGGER.warning(
            "NAVProxy execution stopped during preflight: "
            "execution=%s flight=%s",
            context.flight_execution_id,
            context.flight_id,
        )
        return

    simulator.run_preflight()

    _start_flight(context)

    context = replace(
        context,
        lifecycle_phase="in_flight",
    )

    actual_path_sampler = ActualPathSampler(
        tolerance_ft=5.0,
    )

    for telemetry in simulator.run_flight(context.compiler_ir):
        LOGGER.debug(
            "Telemetry: lat=%s lon=%s alt_ft=%s armed=%s heartbeat=%s sequence=%s",
            telemetry.latitude,
            telemetry.longitude,
            telemetry.relative_altitude_ft,
            telemetry.armed,
            telemetry.heartbeat_active,
            telemetry.mission_sequence,
        )

        sampled_coordinates = actual_path_sampler.add(
            telemetry,
        )

        if len(sampled_coordinates) == 2:
            start_actual_path(
                flight_execution_id=context.flight_execution_id,
                flight_id=context.flight_id,
                coordinates=sampled_coordinates,
            )

        elif sampled_coordinates:
            update_actual_path(
                flight_execution_id=context.flight_execution_id,
                flight_id=context.flight_id,
                coordinates=sampled_coordinates,
            )

        if context.active_operational_element == "departure_transition":
            transition = context.compiler_ir["mission"]["departure_transition"]

            inside_transition = evaluate_transition_point_containment(
                telemetry,
                transition,
            )

            if inside_transition:
                continue

            context = replace(
                context,
                active_operational_element="route",
            )

            LOGGER.info(
                "Transitioned from departure transition to Route authority."
            )

        segment = get_route_conformance_segment(
            context.compiler_ir,
            context.active_route_segment_index,
        )

        route_transition = None

        if (
            segment is not None
            and is_last_segment_of_route(
                context.compiler_ir,
                segment,
            )
        ):
            route_transition = get_route_transition_for_segment(
                context.compiler_ir,
                segment,
            )

        if route_transition is not None:
            inside_route_transition = evaluate_transition_point_containment(
                telemetry,
                route_transition,
            )

            if inside_route_transition:
                continue

        if segment is not None:
            crossed = evaluate_route_segment_boundary_crossing(
                telemetry,
                segment,
            )

            if ( crossed and context.active_route_segment_index
                 < len(context.compiler_ir["mission"]["route_conformance_segments"]) - 1 ):

                context = replace(
                    context,
                    active_route_segment_index=(
                        context.active_route_segment_index + 1
                    ),
                )

                LOGGER.debug(
                    "Advanced to Route segment %s",
                    context.active_route_segment_index,
                )

                segment = get_route_conformance_segment(
                    context.compiler_ir,
                    context.active_route_segment_index,
                )

        if (
            context.active_operational_element == "route"
            and segment is not None
            and segment["flat_segment_index"]
            == len(
                context.compiler_ir["mission"]["route_conformance_segments"]
            ) - 1
        ):
            transition = context.compiler_ir["mission"]["arrival_transition"]

            inside_transition = evaluate_transition_point_containment(
                telemetry,
                transition,
            )

            if inside_transition:
                context = replace(
                    context,
                    active_operational_element="arrival_transition",
                )

                LOGGER.info(
                    "Transitioned from Route authority to arrival transition."
                )

                continue


        if (
            context.active_operational_element == "route"
            and segment is not None
        ):
            conformance = evaluate_route_conformance(
                telemetry,
                segment,
            )

            if not conformance["inside"]:
                LOGGER.warning(
                    "Route conformance violation: "
                    "centerline_offset_ft=%s allowed_offset_ft=%s sequence=%s",
                    conformance["distance_ft"],
                    conformance["half_width_ft"],
                    telemetry.mission_sequence,
                )
                append_flight_log(
                    context=context,
                    lifecycle_phase="in_flight",
                    event_type="Route Deviation",
                    event_status="Violation",
                    message="Aircraft moved outside the authorized flight route.",
                    details={
                        "centerline_offset_ft": conformance["distance_ft"],
                        "allowed_offset_ft": conformance["half_width_ft"],
                        "latitude": telemetry.latitude,
                        "longitude": telemetry.longitude,
                    },
                )

        if (
            context.active_operational_element == "route"
            and segment is not None
            and segment["flat_segment_index"] > 0
            and segment["flat_segment_index"]
            < len(
                context.compiler_ir["mission"]["route_conformance_segments"]
            ) - 1
        ):
            vertical_conformance = evaluate_vertical_conformance(
                context.compiler_ir,
                telemetry,
            )

            if not vertical_conformance:
                LOGGER.warning(
                    "Vertical conformance violation: "
                    "altitude_ft=%s minimum_agl_ft=%s maximum_agl_ft=%s "
                    "sequence=%s lat=%s lon=%s",
                    telemetry.relative_altitude_ft,
                    context.compiler_ir["mission"]["minimum_agl_ft"],
                    context.compiler_ir["mission"]["maximum_agl_ft"],
                    telemetry.mission_sequence,
                    telemetry.latitude,
                    telemetry.longitude,
                )
                append_flight_log(
                    context=context,
                    lifecycle_phase="in_flight",
                    event_type="Altitude Deviation",
                    event_status="Violation",
                    message="Aircraft moved outside the authorized altitude range.",
                    details={
                        "aircraft_altitude_ft": telemetry.relative_altitude_ft,
                        "minimum_altitude_ft": (
                            context.compiler_ir["mission"]["minimum_agl_ft"]
                        ),
                        "maximum_altitude_ft": (
                            context.compiler_ir["mission"]["maximum_agl_ft"]
                        ),
                        "latitude": telemetry.latitude,
                        "longitude": telemetry.longitude,
                    },
                )


    final_coordinates = actual_path_sampler.finish()

    complete_actual_path(
        flight_execution_id=context.flight_execution_id,
        flight_id=context.flight_id,
        coordinates=final_coordinates or None,
    )

    context = replace(
        context,
        lifecycle_phase="post_flight",
    )

    postflight_result = execute_postflight(
        context
    )

    record_postflight_result(
        context,
        postflight_result,
    )

    if (
        postflight_result.status
        != constants.PostflightStatus.PASSED
    ):
        notify_flight_plan_status(
            flight_execution_id=context.flight_execution_id,
            status=FLIGHT_PLAN_STATUS_COMPLETED,
        )

        LOGGER.warning(
            "NAVProxy execution stopped during post-flight: "
            "execution=%s flight=%s",
            context.flight_execution_id,
            context.flight_id,
        )
        return

    flight_log_id = append_flight_log(
        context=context,
        lifecycle_phase="post_flight",
        event_type="flight_completed",
        event_status="completed",
        message="The flight completed normally.",
    )

    LOGGER.debug(
        "Flight Log entry created: %s",
        flight_log_id,
    )

    callback_status = (
        FLIGHT_PLAN_STATUS_SUBMITTED
        if requested_departure_datetime is None
        else FLIGHT_PLAN_STATUS_COMPLETED
    )

    notify_flight_plan_status(
        flight_execution_id=context.flight_execution_id,
        status=callback_status,
    )

    LOGGER.info(
        "NAVProxy execution completed: execution=%s flight=%s",
        context.flight_execution_id,
        context.flight_id,
    )


def _start_flight(context: FlightProcessContext) -> None:
    """Record takeoff and notify Drupal that the flight is active."""

    flight_log_id = append_flight_log(
        context=context,
        lifecycle_phase="in_flight",
        event_type="takeoff",
        event_status="started",
        message="The aircraft departed and the flight is underway.",
    )

    LOGGER.info(
        "Takeoff recorded: flight=%s log_entry=%s",
        context.flight_id,
        flight_log_id,
    )

    notify_flight_plan_status(
        flight_execution_id=context.flight_execution_id,
        status=FLIGHT_PLAN_STATUS_ACTIVE,
    )


def _validate_wait_seconds(name: str, value: Any) -> int:
    """Validate and normalize a simulator wait duration."""

    try:
        normalized_value = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer.") from exc

    if normalized_value < 0:
        raise ValueError(f"{name} must not be negative.")

    return normalized_value


def get_route_conformance_segment(
    compiler_ir: dict[str, Any],
    active_route_segment_index: int,
) -> dict[str, Any] | None:
    """Return the Route conformance segment for a mission sequence."""

    mission = compiler_ir.get("mission")

    if not isinstance(mission, dict):
        return None

    conformance_segments = mission.get(
        "route_conformance_segments"
    )

    if not isinstance(conformance_segments, list):
        return None

    segment_index = active_route_segment_index

    if segment_index < 0:
        return None

    if segment_index >= len(conformance_segments):
        return None
 
    return {
        "flat_segment_index": segment_index,
        **conformance_segments[segment_index],
    }


def get_route_transition_for_segment(
    compiler_ir: dict[str, Any],
    segment: dict[str, Any],
) -> dict[str, Any] | None:
    """Return the Route-to-Route transition after this segment, if any."""

    route_transitions = compiler_ir["mission"]["route_transitions"]

    for transition in route_transitions:
        if transition["from_route_index"] == segment["route_index"]:
            return transition

    return None


def is_last_segment_of_route(
    compiler_ir: dict[str, Any],
    segment: dict[str, Any],
) -> bool:
    """Return whether this is the final segment of its Route."""

    next_flat_index = segment["flat_segment_index"] + 1
    segments = compiler_ir["mission"]["route_conformance_segments"]

    if next_flat_index >= len(segments):
        return True

    return (
        segments[next_flat_index]["route_index"]
        != segment["route_index"]
    )


def evaluate_route_segment_boundary_crossing(
    telemetry: TelemetryReading,
    segment: dict[str, Any],
) -> bool:
    """Return whether telemetry crossed the segment's forward boundary."""

    start_coordinate = segment["start_coordinate"]
    end_coordinate = segment["end_coordinate"]

    endpoint = (
        f"{DEFAULT_API_BASE_URL.rstrip('/')}"
        f"/api/routes/segment-boundary-crossing"
    )

    try:
        response = requests.post(
            endpoint,
            json={
                "latitude": telemetry.latitude,
                "longitude": telemetry.longitude,
                "start_latitude": start_coordinate[1],
                "start_longitude": start_coordinate[0],
                "end_latitude": end_coordinate[1],
                "end_longitude": end_coordinate[0],
            },
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=DEFAULT_API_TIMEOUT_SECONDS,
        )

        response.raise_for_status()
        result = response.json()

    except requests.RequestException as exc:
        raise RuntimeError(
            f"Could not evaluate Route segment boundary crossing: {exc}"
        ) from exc

    except requests.JSONDecodeError as exc:
        raise RuntimeError(
            "Route segment boundary API returned invalid JSON."
        ) from exc

    return bool(result.get("crossed"))


def evaluate_transition_point_containment(
    telemetry: TelemetryReading,
    transition: dict[str, Any],
) -> bool:
    """Determine whether telemetry is inside a derived transition area."""

    coordinate = transition["coordinate"]

    endpoint = (
        f"{DEFAULT_API_BASE_URL.rstrip('/')}"
        f"/api/routes/transition-point-containment"
    )

    try:
        response = requests.post(
            endpoint,
            json={
                "latitude": telemetry.latitude,
                "longitude": telemetry.longitude,
                "center_latitude": coordinate[1],
                "center_longitude": coordinate[0],
                "diameter_ft": transition["diameter_ft"],
            },
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=DEFAULT_API_TIMEOUT_SECONDS,
        )

        response.raise_for_status()
        result = response.json()

    except requests.RequestException as exc:
        raise RuntimeError(
            f"Could not evaluate transition containment: {exc}"
        ) from exc

    except requests.JSONDecodeError as exc:
        raise RuntimeError(
            "Transition containment API returned invalid JSON."
        ) from exc

    inside = result.get("inside")

    if not isinstance(inside, bool):
        raise RuntimeError(
            "Transition containment API response is missing inside."
        )

    return inside


def evaluate_route_conformance(
    telemetry: TelemetryReading,
    segment: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate one telemetry position against one Route segment."""

    start_coordinate = segment["start_coordinate"]
    end_coordinate = segment["end_coordinate"]
    route_width_ft = segment["route_width_ft"]

    endpoint = (
        f"{DEFAULT_API_BASE_URL.rstrip('/')}"
        f"/api/routes/segment-conformance"
    )

    try:
        response = requests.post(
            endpoint,
            json={
                "latitude": telemetry.latitude,
                "longitude": telemetry.longitude,
                "start_latitude": start_coordinate[1],
                "start_longitude": start_coordinate[0],
                "end_latitude": end_coordinate[1],
                "end_longitude": end_coordinate[0],
                "route_width_ft": route_width_ft,
            },
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=DEFAULT_API_TIMEOUT_SECONDS,
        )

        response.raise_for_status()
        result = response.json()

    except requests.RequestException as exc:
        raise RuntimeError(
            f"Could not evaluate Route conformance: {exc}"
        ) from exc

    except requests.JSONDecodeError as exc:
        raise RuntimeError(
            "Route conformance API returned invalid JSON."
        ) from exc

    return result


def evaluate_vertical_conformance(
    compiler_ir: dict[str, Any],
    telemetry: TelemetryReading,
) -> bool:
    """Evaluate one telemetry altitude against the Flight Band."""

    mission = compiler_ir.get("mission")

    if not isinstance(mission, dict):
        return False

    minimum_agl_ft = mission.get("minimum_agl_ft")
    maximum_agl_ft = mission.get("maximum_agl_ft")

    altitude_ft = telemetry.relative_altitude_ft

    return (
        minimum_agl_ft
        <= altitude_ft
        <= maximum_agl_ft
    )


def execute_preflight(
    context: FlightProcessContext,
) -> PreflightResult:
    """Execute all preflight assertions in compiler IR order."""

    if context.flight_execution is None:
        raise ValueError(
            "Flight process context is missing the Flight Execution Record."
        )

    if context.compiler_ir is None:
        raise ValueError(
            "Flight process context is missing the compiler IR."
        )

    assertion_results: list[AssertionResult] = []

    for assertion in get_preflight_assertions(context.compiler_ir):
        result = execute_assertion(
            context,
            assertion,
        )

        assertion_results.append(result)

        if not result.passed:
            return PreflightResult(
                flight_execution_uuid=context.flight_execution_id,
                status=constants.PreflightStatus.FAILED,
                assertion_results=tuple(assertion_results),
            )

    return PreflightResult(
        flight_execution_uuid=context.flight_execution_id,
        status=constants.PreflightStatus.PASSED,
        assertion_results=tuple(assertion_results),
    )


def execute_postflight(
    context: FlightProcessContext,
) -> PostflightResult:
    """Execute all post-flight assertions in compiler IR order."""

    if context.flight_execution is None:
        raise ValueError(
            "Flight process context is missing the Flight Execution Record."
        )

    if context.compiler_ir is None:
        raise ValueError(
            "Flight process context is missing the compiler IR."
        )

    assertion_results: list[AssertionResult] = []

    for assertion in get_postflight_assertions(
        context.compiler_ir
    ):
        result = execute_assertion(
            context,
            assertion,
        )

        assertion_results.append(result)

        if not result.passed:
            return PostflightResult(
                flight_execution_uuid=context.flight_execution_id,
                status=constants.PostflightStatus.FAILED,
                assertion_results=tuple(assertion_results),
            )

    return PostflightResult(
        flight_execution_uuid=context.flight_execution_id,
        status=constants.PostflightStatus.PASSED,
        assertion_results=tuple(assertion_results),
    )


def get_preflight_assertions(
    compiler_ir: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return executable preflight assertions in compiler sequence order."""

    compiler_assertions = compiler_ir.get("assertions")

    if not isinstance(compiler_assertions, list):
        raise ValueError(
            "Compiler IR is missing the assertions array."
        )

    supported_preflight_commands = {
        constants.NAV_ASSERT_POSITION_IN_GEOMETRY,
        constants.NAV_ASSERT_ARRIVAL_IN_GEOMETRY,
        constants.NAV_ASSERT_DEPARTURE_TIME,
        constants.NAV_ASSERT_FLIGHT_BAND,
    }

    assertions: list[dict[str, Any]] = []

    for assertion in compiler_assertions:
        if not isinstance(assertion, dict):
            raise ValueError(
                "Each compiler IR assertion must be an object."
            )

        if assertion.get("assertion_type") in supported_preflight_commands:
            assertions.append(assertion)

    return assertions


def get_postflight_assertions(
    compiler_ir: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return executable post-flight assertions in sequence order."""

    compiler_assertions = compiler_ir.get("assertions")

    if not isinstance(compiler_assertions, list):
        raise ValueError(
            "Compiler IR is missing the assertions array."
        )

    assertions: list[dict[str, Any]] = []

    for assertion in compiler_assertions:
        if not isinstance(assertion, dict):
            raise ValueError(
                "Each compiler IR assertion must be an object."
            )

        if (
            assertion.get("assertion_type")
            == constants.NAV_ASSERT_ARRIVAL_IN_GEOMETRY
        ):
            assertions.append(assertion)

    return assertions


def execute_assertion(
    context: FlightProcessContext,
    assertion: dict[str, Any],
) -> AssertionResult:
    """Dispatch one assertion to its implementation procedure."""

    command = assertion.get("assertion_type")

    if command == constants.NAV_ASSERT_POSITION_IN_GEOMETRY:
        return assert_position_in_geometry(
            context,
            assertion,
        )

    if command == constants.NAV_ASSERT_ARRIVAL_IN_GEOMETRY:
        return assert_arrival_in_geometry(
            context,
            assertion,
        )

    if command == constants.NAV_ASSERT_DEPARTURE_TIME:
        return assert_departure_time(
            context,
            assertion,
        )

    if command == constants.NAV_ASSERT_FLIGHT_BAND:
        return assert_flight_band(assertion)

    raise ValueError(
        f"Unsupported NAVProxy assertion: {command}"
    )


def get_current_position(
    context: FlightProcessContext,
) -> tuple[float, float]:
    """Return the aircraft position appropriate to the flight stage."""

    if context.lifecycle_phase == "pre_flight":
        for assertion in context.compiler_ir["assertions"]:
            if (
                assertion["assertion_type"]
                == constants.NAV_ASSERT_POSITION_IN_GEOMETRY
            ):
                coordinate = assertion["parameters"]["coordinate"]

                return (
                    coordinate[1],
                    coordinate[0],
                )

        raise RuntimeError(
            "Compiler IR is missing the departure position assertion."
        )

    if context.lifecycle_phase == "in_flight":
        raise NotImplementedError(
            "In-flight position retrieval is not implemented."
        )

    if context.lifecycle_phase == "post_flight":
        if context.compiler_ir is None:
            raise ValueError(
                "Flight process context is missing compiler IR."
            )

        for assertion in context.compiler_ir["assertions"]:
            if (
                assertion["assertion_type"]
                == constants.NAV_ASSERT_ARRIVAL_IN_GEOMETRY
            ):
                coordinate = assertion["parameters"]["coordinate"]

                return (
                    coordinate[1],
                    coordinate[0],
                )

        raise ValueError(
            "Compiler IR is missing the arrival position assertion."
        )


    raise ValueError(
        f"Unknown flight lifecycle phase: {context.lifecycle_phase}"
    )


def assert_position_in_geometry(
    context: FlightProcessContext,
    assertion: dict[str, Any],
) -> AssertionResult:
    """Confirm that the aircraft is inside its authorized departure geometry."""

    if context.flight_execution is None:
        raise ValueError(
            "Flight process context is missing the Flight Execution Record."
        )

    latitude, longitude = get_current_position(context)

    if isinstance(latitude, bool) or not isinstance(latitude, (int, float)):
        raise ValueError(
            "Flight controller returned an invalid latitude."
        )

    if isinstance(longitude, bool) or not isinstance(longitude, (int, float)):
        raise ValueError(
            "Flight controller returned an invalid longitude."
        )

    flight_execution = context.flight_execution

    departure_droneport_id = flight_execution.get(
        "departure_droneport_id"
    )

    if departure_droneport_id:
        if not isinstance(departure_droneport_id, str):
            raise ValueError(
                "departure_droneport_id must be a string or null."
            )

        endpoint = (
            f"{DEFAULT_API_BASE_URL.rstrip('/')}"
            f"/api/droneports/{departure_droneport_id}"
            f"/point-containment"
        )
    else:
        origin_site_id = flight_execution.get("origin_site_id")

        if not isinstance(origin_site_id, str) or not origin_site_id:
            raise ValueError(
                "Flight Execution Record is missing origin_site_id."
            )

        endpoint = (
            f"{DEFAULT_API_BASE_URL.rstrip('/')}"
            f"/api/sites/{origin_site_id}"
            f"/point-containment"
        )

    try:
        response = requests.post(
            endpoint,
            json={
                "latitude": latitude,
                "longitude": longitude,
            },
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=DEFAULT_API_TIMEOUT_SECONDS,
        )

        response.raise_for_status()
        containment = response.json()
    except requests.RequestException as exc:
        raise RuntimeError(
            f"Could not evaluate departure point containment: {exc}"
        ) from exc
    except requests.JSONDecodeError as exc:
        raise RuntimeError(
            "Point-containment API returned invalid JSON."
        ) from exc

    inside = containment.get("inside")

    if not isinstance(inside, bool):
        raise RuntimeError(
            "Point-containment API response is missing inside."
        )

    return AssertionResult(
        command=constants.NAV_ASSERT_POSITION_IN_GEOMETRY,
        passed=inside,
        message=(
            "Aircraft is inside the authorized departure geometry."
            if inside
            else "Aircraft is outside the authorized departure geometry."
        ),
    )


def assert_arrival_in_geometry(
    context: FlightProcessContext,
    assertion: dict[str, Any],
) -> AssertionResult:
    """Confirm that the authorized destination remains operational."""

    if context.flight_execution is None:
        raise ValueError(
            "Flight process context is missing the Flight Execution Record."
        )

    if context.lifecycle_phase == "post_flight":
        return assert_arrival_position_in_geometry(
            context,
            assertion,
        )

    flight_execution = context.flight_execution

    arrival_droneport_id = flight_execution.get(
        "arrival_droneport_id"
    )

    if arrival_droneport_id:
        if not isinstance(arrival_droneport_id, str):
            raise ValueError(
                "arrival_droneport_id must be a string or null."
            )

        destination_type = "arrival DronePort"
        endpoint = (
            f"{DEFAULT_API_BASE_URL.rstrip('/')}"
            f"/api/droneports/{arrival_droneport_id}"
        )
    else:
        destination_site_id = flight_execution.get(
            "destination_site_id"
        )

        if (
            not isinstance(destination_site_id, str)
            or not destination_site_id
        ):
            raise ValueError(
                "Flight Execution Record is missing destination_site_id."
            )

        destination_type = "destination Site"
        endpoint = (
            f"{DEFAULT_API_BASE_URL.rstrip('/')}"
            f"/api/sites/{destination_site_id}"
        )

    try:
        response = requests.get(
            endpoint,
            headers={
                "Accept": "application/json",
            },
            timeout=DEFAULT_API_TIMEOUT_SECONDS,
        )

        response.raise_for_status()
        destination = response.json()
    except requests.RequestException as exc:
        raise RuntimeError(
            f"Could not retrieve the {destination_type}: {exc}"
        ) from exc
    except requests.JSONDecodeError as exc:
        raise RuntimeError(
            f"The {destination_type} API returned invalid JSON."
        ) from exc

    operational_status = destination.get("operational_status")

    if not isinstance(operational_status, str):
        raise RuntimeError(
            f"The {destination_type} API response is missing "
            "operational_status."
        )

    is_operational = operational_status == "active"

    return AssertionResult(
        command=constants.NAV_ASSERT_ARRIVAL_IN_GEOMETRY,
        passed=is_operational,
        message=(
            f"The {destination_type} is operational and available "
            "for arrival."
            if is_operational
            else (
                f"The {destination_type} is not operational and "
                "is unavailable for arrival."
            )
        ),
    )


def assert_arrival_position_in_geometry(
    context: FlightProcessContext,
    assertion: dict[str, Any],
) -> AssertionResult:
    """Confirm that the aircraft landed inside its authorized arrival geometry."""

    if context.flight_execution is None:
        raise ValueError(
            "Flight process context is missing the Flight Execution Record."
        )

    latitude, longitude = get_current_position(context)

    if isinstance(latitude, bool) or not isinstance(latitude, (int, float)):
        raise ValueError(
            "Flight controller returned an invalid latitude."
        )

    if isinstance(longitude, bool) or not isinstance(longitude, (int, float)):
        raise ValueError(
            "Flight controller returned an invalid longitude."
        )

    flight_execution = context.flight_execution

    arrival_droneport_id = flight_execution.get(
        "arrival_droneport_id"
    )

    if arrival_droneport_id:
        endpoint = (
            f"{DEFAULT_API_BASE_URL.rstrip('/')}"
            f"/api/droneports/{arrival_droneport_id}"
            "/point-containment"
        )
    else:
        destination_site_id = flight_execution.get(
            "destination_site_id"
        )

        endpoint = (
            f"{DEFAULT_API_BASE_URL.rstrip('/')}"
            f"/api/sites/{destination_site_id}"
            "/point-containment"
        )

    response = requests.post(
        endpoint,
        json={
            "latitude": latitude,
            "longitude": longitude,
        },
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        timeout=DEFAULT_API_TIMEOUT_SECONDS,
    )

    response.raise_for_status()

    inside = response.json()["inside"]

    return AssertionResult(
        command=constants.NAV_ASSERT_ARRIVAL_IN_GEOMETRY,
        passed=inside,
        message=(
            "Aircraft landed inside the authorized arrival geometry."
            if inside
            else "Aircraft landed outside the authorized arrival geometry."
        ),
    )


def assert_departure_time(
    context: FlightProcessContext,
    assertion: dict[str, Any],
) -> AssertionResult:
    """Confirm that preflight is inside the permitted launch window."""

    if context.flight_execution is None:
        raise ValueError(
            "Flight process context is missing the Flight Execution Record."
        )

    parameters = assertion.get("parameters")

    if not isinstance(parameters, dict):
        raise ValueError(
            "Departure-time assertion is missing its parameters object."
        )

    departure_date = parameters.get("departure_date")
    departure_time = parameters.get("departure_time")

    if not isinstance(departure_date, str) or not departure_date:
        raise ValueError(
            "Departure-time assertion is missing departure_date."
        )

    if not isinstance(departure_time, str) or not departure_time:
        raise ValueError(
            "Departure-time assertion is missing departure_time."
        )

    operational_timezone = context.flight_execution.get(
        "operational_timezone"
    )

    if (
        not isinstance(operational_timezone, str)
        or not operational_timezone
    ):
        raise ValueError(
            "Flight Execution Record is missing operational_timezone."
        )

    try:
        timezone_info = ZoneInfo(operational_timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(
            "Flight Execution Record contains an invalid "
            "operational_timezone."
        ) from exc

    try:
        requested_departure = datetime.fromisoformat(
            f"{departure_date}T{departure_time}"
        ).replace(
            tzinfo=timezone_info
        )
    except ValueError as exc:
        raise ValueError(
            "Departure-time assertion contains an invalid date or time."
        ) from exc

    launch_window_opens = requested_departure - timedelta(
        minutes=LAUNCH_WINDOW_PREFLIGHT_MINUTES,
    )

    launch_window_expires = requested_departure + timedelta(
        minutes=LAUNCH_WINDOW_EXPIRES_MINUTES,
    )

    current_datetime = datetime.now(
        timezone_info
    ).replace(
        microsecond=0
    )

    passed = (
        launch_window_opens
        <= current_datetime
        <= launch_window_expires
    )

    if passed:
        message = (
            "Current time is inside the permitted launch window: "
            f"{launch_window_opens.isoformat()} through "
            f"{launch_window_expires.isoformat()}."
        )
    elif current_datetime < launch_window_opens:
        message = (
            "Preflight began before the permitted launch window. "
            "The launch window opens at "
            f"{launch_window_opens.isoformat()}."
        )
    else:
        message = (
            "The permitted launch window has expired. "
            "The launch window expired at "
            f"{launch_window_expires.isoformat()}."
        )

    return AssertionResult(
        command=constants.NAV_ASSERT_DEPARTURE_TIME,
        passed=passed,
        message=message,
    )


def assert_flight_band(
    assertion: dict[str, Any],
) -> AssertionResult:
    """
    Confirm that a currently active Flight Band permits the flight.

    Flight Band eligibility is evaluated using the current day and time
    in the Flight Execution's operational timezone.
    """

    parameters = assertion.get("parameters")

    if not isinstance(parameters, dict):
        raise ValueError(
            "Flight Band assertion is missing its parameters object."
        )

    flight_class = parameters.get("flight_class")
    operational_timezone = parameters.get(
        "operational_timezone"
    )

    if not isinstance(flight_class, str) or not flight_class:
        raise ValueError(
            "Flight Band assertion is missing flight_class."
        )

    if (
        not isinstance(operational_timezone, str)
        or not operational_timezone
    ):
        raise ValueError(
            "Flight Band assertion is missing operational_timezone."
        )

    try:
        timezone_info = ZoneInfo(operational_timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(
            "Flight Band assertion contains an invalid "
            "operational_timezone."
        ) from exc

    current_datetime = datetime.now(
        timezone_info
    )

    # Flight Band days use Sunday=0 through Saturday=6.
    current_day = (
        current_datetime.weekday() + 1
    ) % 7

    current_time = current_datetime.time().replace(
        second=0,
        microsecond=0,
        tzinfo=None,
    )

    flight_bands = load_flight_bands(
        flight_class=flight_class,
    )

    applicable_flight_band = resolve_applicable_flight_band(
        flight_bands=flight_bands,
        operational_timezone=operational_timezone,
        current_datetime=current_datetime,
    )

    if applicable_flight_band is not None:
        return AssertionResult(
            command=constants.NAV_ASSERT_FLIGHT_BAND,
            passed=True,
            message=(
                "An active Flight Band permits this flight "
                "at the current operational day and time."
            ),
        )


    return AssertionResult(
        command=constants.NAV_ASSERT_FLIGHT_BAND,
        passed=False,
        message=(
            "No active Flight Band permits this flight at the "
            "current operational day and time."
        ),
    )


def record_preflight_result(
    context: FlightProcessContext,
    preflight_result: PreflightResult,
) -> None:
    """Append the final preflight outcome to the Flight Log."""

    if preflight_result.status == constants.PreflightStatus.PASSED:
        flight_log_id = append_flight_log(
            context=context,
            lifecycle_phase="pre_flight",
            event_type="preflight_completed",
            event_status="passed",
            message="All preflight assertions passed.",
            details={
                "assertion_count": len(
                    preflight_result.assertion_results
                ),
            },
        )

        LOGGER.info(
            "Preflight completed: flight=%s log_entry=%s",
            context.flight_id,
            flight_log_id,
        )

        return

    failed_assertion = next(
        (
            assertion_result
            for assertion_result in reversed(
                preflight_result.assertion_results
            )
            if not assertion_result.passed
        ),
        None,
    )

    details: dict[str, Any] = {
        "assertion_count": len(
            preflight_result.assertion_results
        ),
    }

    message = "Preflight validation failed."

    if failed_assertion is not None:
        details["failed_command"] = failed_assertion.command
        details["failure_message"] = failed_assertion.message
        message = failed_assertion.message

    flight_log_id = append_flight_log(
        context=context,
        lifecycle_phase="pre_flight",
        event_type="preflight_failed",
        event_status="failed",
        message=message,
        details=details,
    )

    LOGGER.warning(
        "Preflight failed: flight=%s log_entry=%s",
        context.flight_id,
        flight_log_id,
    )

def record_postflight_result(
    context: FlightProcessContext,
    result: PostflightResult,
) -> str:
    """Append the final post-flight assertion result."""

    passed = (
        result.status
        == constants.PostflightStatus.PASSED
    )

    failed_result = next(
        (
            assertion_result
            for assertion_result in result.assertion_results
            if not assertion_result.passed
        ),
        None,
    )

    details = {
        "assertion_count": len(
            result.assertion_results
        ),
    }

    if failed_result is not None:
        details.update({
            "failed_command": failed_result.command,
            "failure_message": failed_result.message,
        })

    flight_log_id = append_flight_log(
        context=context,
        lifecycle_phase="post_flight",
        event_type=(
            "postflight_completed"
            if passed
            else "postflight_failed"
        ),
        event_status=(
            "completed"
            if passed
            else "failed"
        ),
        message=(
            "Post-flight assertions completed successfully."
            if passed
            else failed_result.message
        ),
        details=details,
    )

    LOGGER.info(
        "Post-flight %s: flight=%s log_entry=%s",
        "completed" if passed else "failed",
        context.flight_id,
        flight_log_id,
    )

    return flight_log_id


def release_flight_execution(
    flight_execution_id: str,
) -> None:
    """Return a preflight-failed scheduled FER to active status."""

    endpoint = (
        f"{DEFAULT_API_BASE_URL.rstrip('/')}"
        f"/api/flight-executions/{flight_execution_id}/release"
    )

    response = requests.post(
        endpoint,
        headers={
            "Accept": "application/json",
        },
        timeout=DEFAULT_API_TIMEOUT_SECONDS,
    )

    response.raise_for_status()

