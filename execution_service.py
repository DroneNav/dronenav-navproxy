"""Coordinate one NAVProxy-controlled flight execution."""

from __future__ import annotations

import logging

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import requests

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
from .simulator import FlightSimulator
from .tooling.fer_compiler import (
    load_and_compile_flight_execution,
    load_flight_bands,
)


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

    flight_execution, compiler_ir = load_and_compile_flight_execution(
        flight_execution_id=flight_execution_id,
    )

    context = FlightProcessContext(
        flight_execution_id=flight_execution_id,
        flight_id=flight_id,
        flight_execution=flight_execution,
        compiler_ir=compiler_ir,
    )

    requested_departure_datetime = get_requested_departure_datetime(
        context.flight_execution_id,
    )

    LOGGER.info(
        "NAVProxy execution started: execution=%s flight=%s commands=%d",
        context.flight_execution_id,
        context.flight_id,
        len(compiler_ir.get("commands", [])),
    )

    preflight_result = execute_preflight(context)

    record_preflight_result(
        context,
        preflight_result,
    )

    if preflight_result.status != constants.PreflightStatus.PASSED:
        LOGGER.warning(
            "NAVProxy execution stopped during preflight: "
            "execution=%s flight=%s",
            context.flight_execution_id,
            context.flight_id,
        )
        return

    simulator.run_preflight()

    _start_flight(context)

    simulator.run_flight()

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


def get_preflight_assertions(
    compiler_ir: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return executable preflight assertions in compiler sequence order."""

    commands = compiler_ir.get("commands")

    if not isinstance(commands, list):
        raise ValueError(
            "Compiler IR is missing the commands array."
        )

    supported_preflight_commands = {
        constants.NAV_ASSERT_POSITION_IN_GEOMETRY,
        constants.NAV_ASSERT_ARRIVAL_IN_GEOMETRY,
        constants.NAV_ASSERT_DEPARTURE_TIME,
        constants.NAV_ASSERT_FLIGHT_BAND,
    }

    assertions: list[dict[str, Any]] = []

    for command in commands:
        if not isinstance(command, dict):
            raise ValueError(
                "Each compiler IR command must be an object."
            )

        if command.get("command") in supported_preflight_commands:
            assertions.append(command)

    return assertions


def execute_assertion(
    context: FlightProcessContext,
    assertion: dict[str, Any],
) -> AssertionResult:
    """Dispatch one assertion to its implementation procedure."""

    command = assertion.get("command")

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


def get_current_position() -> tuple[float, float]:
    """
    Temporary flight-controller stub.

    Returns the current aircraft position. During early NAVProxy
    development this is hardcoded for integration testing.
    """

    return (
        34.076687671,
        -84.300904604,
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

    latitude, longitude = get_current_position()

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

