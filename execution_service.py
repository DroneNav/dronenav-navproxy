"""Coordinate one NAVProxy-controlled flight execution."""

from __future__ import annotations

import logging
from typing import Any

from .drupal_client import notify_flight_plan_status
from .flight_repository import (
    FlightProcessContext,
    load_and_validate_context,
    record_landing,
    record_takeoff,
)
from .settings import (
    DEFAULT_FLIGHT_SECONDS,
    DEFAULT_PREFLIGHT_SECONDS,
    FLIGHT_PLAN_STATUS_ACTIVE,
    FLIGHT_PLAN_STATUS_COMPLETED,
    FLIGHT_PLAN_STATUS_SUBMITTED,
)
from .simulator import FlightSimulator

LOGGER = logging.getLogger(__name__)


def run_navproxy_process(
    flight_execution_id: str,
    flight_log_id: str,
    preflight_seconds: int = DEFAULT_PREFLIGHT_SECONDS,
    flight_seconds: int = DEFAULT_FLIGHT_SECONDS,
) -> None:
    """Run one simulated NAVProxy-controlled aircraft flight."""

    simulator = FlightSimulator(
        preflight_seconds=_validate_wait_seconds(
            "preflight_seconds", preflight_seconds
        ),
        flight_seconds=_validate_wait_seconds("flight_seconds", flight_seconds),
    )

    context = load_and_validate_context(
        flight_execution_id=flight_execution_id,
        flight_log_id=flight_log_id,
    )

    LOGGER.info(
        "NAVProxy simulation started: execution=%s log=%s scheduled=%s",
        context.flight_execution_id,
        context.flight_log_id,
        context.is_scheduled,
    )

    simulator.run_preflight()
    _start_flight(context)

    simulator.run_flight()
    _complete_flight(context)

    LOGGER.info(
        "NAVProxy simulation completed: execution=%s log=%s",
        context.flight_execution_id,
        context.flight_log_id,
    )


def _start_flight(context: FlightProcessContext) -> None:
    record_takeoff(context)

    LOGGER.info(
        "Takeoff recorded: Flight Log %s is now in_flight.",
        context.flight_log_id,
    )

    notify_flight_plan_status(
        flight_execution_id=context.flight_execution_id,
        status=FLIGHT_PLAN_STATUS_ACTIVE,
    )


def _complete_flight(context: FlightProcessContext) -> None:
    record_landing(context)

    LOGGER.info(
        "Landing recorded: Flight Log %s is now completed.",
        context.flight_log_id,
    )

    if context.is_scheduled:
        LOGGER.info(
            "Scheduled Flight Execution %s is now completed.",
            context.flight_execution_id,
        )
        callback_status = FLIGHT_PLAN_STATUS_COMPLETED
    else:
        callback_status = FLIGHT_PLAN_STATUS_SUBMITTED

    notify_flight_plan_status(
        flight_execution_id=context.flight_execution_id,
        status=callback_status,
    )


def _validate_wait_seconds(name: str, value: Any) -> int:
    try:
        normalized_value = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer.") from exc

    if normalized_value < 0:
        raise ValueError(f"{name} must not be negative.")

    return normalized_value

