"""Coordinate one NAVProxy-controlled flight execution."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from . import constants
from .drupal_update_status import notify_flight_plan_status
from .flight_log_service import (
    FlightProcessContext,
    begin_flight_log,
    complete_flight_log,
    get_requested_departure_datetime,
)
from .settings import (
    DEFAULT_FLIGHT_SECONDS,
    DEFAULT_PREFLIGHT_SECONDS,
    FLIGHT_PLAN_STATUS_ACTIVE,
    FLIGHT_PLAN_STATUS_COMPLETED,
    FLIGHT_PLAN_STATUS_SUBMITTED,
)
from .simulator import FlightSimulator

DEFAULT_API_BASE_URL = "https://api.dronenav.org"

from .tooling.fer_compiler import load_flight_execution

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


def run_navproxy_process(
    flight_execution_id: str,
    flight_log_id: str,
    preflight_seconds: int = DEFAULT_PREFLIGHT_SECONDS,
    flight_seconds: int = DEFAULT_FLIGHT_SECONDS,
) -> None:
    """Run one simulated NAVProxy-controlled aircraft flight."""

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

    context = FlightProcessContext(
        flight_execution_id=flight_execution_id,
        flight_log_id=flight_log_id,
    )

    requested_departure_datetime = get_requested_departure_datetime(
        context.flight_execution_id,
    )

    LOGGER.info(
        "NAVProxy simulation started: execution=%s log=%s",
        context.flight_execution_id,
        context.flight_log_id,
    )

    simulator.run_preflight()

    _start_flight(context)

    simulator.run_flight()

    complete_flight_log(context)

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
        "NAVProxy simulation completed: execution=%s log=%s",
        context.flight_execution_id,
        context.flight_log_id,
    )


def _start_flight(context: FlightProcessContext) -> None:
    """Record takeoff and notify Drupal that the flight is active."""

    begin_flight_log(context)

    LOGGER.info(
        "Takeoff recorded: Flight Log %s is now in_flight.",
        context.flight_log_id,
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


def execute_flight_execution(
    flight_execution_id: str,
    flight_log_id: str,
) -> PreflightResult:
    """
    Begin execution of a Flight Execution Record.

    The initial implementation ends after preflight validation.
    """

    context = FlightProcessContext(
        flight_execution_id=flight_execution_id,
        flight_log_id=flight_log_id,
    )

    flight_execution = load_flight_execution(
        DEFAULT_API_BASE_URL,
        context.flight_execution_id,
    )

    compiler_ir = build_fer_ir(
        flight_execution,
    )

    preflight_result = execute_preflight(
        context.flight_execution_id,
        compiler_ir,
    )

    record_preflight_result(
        context,
        preflight_result,
    )

    return preflight_result


def build_fer_ir(
    flight_execution: dict[str, Any],
) -> dict[str, Any]:
    """Build the compiler intermediate representation for the FER."""

    raise NotImplementedError


def execute_preflight(
    flight_execution_uuid: str,
    compiler_ir: dict[str, Any],
) -> PreflightResult:
    """Execute all preflight assertions in compiler IR order."""

    assertion_results: list[AssertionResult] = []

    for assertion in get_preflight_assertions(compiler_ir):
        result = execute_assertion(assertion)
        assertion_results.append(result)

        if not result.passed:
            return PreflightResult(
                flight_execution_uuid=flight_execution_uuid,
                status=constants.PreflightStatus.FAILED,
                assertion_results=tuple(assertion_results),
            )

    return PreflightResult(
        flight_execution_uuid=flight_execution_uuid,
        status=constants.PreflightStatus.PASSED,
        assertion_results=tuple(assertion_results),
    )


def get_preflight_assertions(
    compiler_ir: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return assertions that execute during the preflight lifecycle."""

    assertions = compiler_ir.get("assertions", [])

    return [
        assertion
        for assertion in assertions
        if assertion.get("phase") == constants.LIFECYCLE_PHASE_PREFLIGHT
    ]


def execute_assertion(
    assertion: dict[str, Any],
) -> AssertionResult:
    """Dispatch one assertion to its implementation procedure."""

    command = assertion.get("command")

    if command == constants.NAV_ASSERT_POSITION_IN_GEOMETRY:
        return assert_position_in_geometry(assertion)

    if command == constants.NAV_ASSERT_ARRIVAL_IN_GEOMETRY:
        return assert_arrival_in_geometry(assertion)

    if command == constants.NAV_ASSERT_DEPARTURE_TIME:
        return assert_departure_time(assertion)

    if command == constants.NAV_ASSERT_FLIGHT_BAND:
        return assert_flight_band(assertion)

    raise ValueError(
        f"Unsupported NAVProxy assertion: {command}",
    )


def assert_position_in_geometry(
    assertion: dict[str, Any],
) -> AssertionResult:
    """Confirm that the aircraft is inside the departure geometry."""

    raise NotImplementedError


def assert_arrival_in_geometry(
    assertion: dict[str, Any],
) -> AssertionResult:
    """During preflight, confirm that the arrival geometry is operational."""

    raise NotImplementedError


def assert_departure_time(
    assertion: dict[str, Any],
) -> AssertionResult:
    """Confirm that departure timing requirements are satisfied."""

    raise NotImplementedError


def assert_flight_band(
    assertion: dict[str, Any],
) -> AssertionResult:
    """Confirm that the local day and time satisfy the Flight Band."""

    raise NotImplementedError


def record_preflight_result(
    context: FlightProcessContext,
    preflight_result: PreflightResult,
) -> None:
    """Record the preflight result in the Flight Log."""

    raise NotImplementedError


