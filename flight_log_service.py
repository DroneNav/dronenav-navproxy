"""Shared-database operations required by NAVProxy."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text

from app.config.constants import (
    EXECUTION_STATUS_COMPLETED,
    EXECUTION_STATUS_DISPATCHED,
    FLIGHT_LOG_STATUS_COMPLETED,
    FLIGHT_LOG_STATUS_IN_FLIGHT,
    FLIGHT_LOG_STATUS_PRE_FLIGHT,
)
from app.config.database import engine


@dataclass(frozen=True)
class FlightProcessContext:
    """Identifiers and execution type required during one NAVProxy run."""

    flight_execution_id: str
    flight_log_id: str
    is_scheduled: bool


def load_and_validate_context(
    flight_execution_id: str,
    flight_log_id: str,
) -> FlightProcessContext:
    """Load and validate the supplied Flight Execution and Flight Log pair."""

    with engine.connect() as connection:
        result = connection.execute(
            text(
                """
                SELECT
                    fe.flight_execution_id,
                    fe.requested_departure_datetime,
                    fe.execution_status,
                    fl.flight_log_id,
                    fl.flight_log_status
                FROM flight_executions AS fe
                JOIN flight_log AS fl
                  ON fl.flight_execution_id = fe.flight_execution_id
                WHERE fe.flight_execution_id = :flight_execution_id
                  AND fl.flight_log_id = :flight_log_id
                """
            ),
            {
                "flight_execution_id": flight_execution_id,
                "flight_log_id": flight_log_id,
            },
        )
        row = result.mappings().first()

    if row is None:
        raise ValueError(
            "The Flight Execution and Flight Log combination was not found."
        )

    if row["flight_log_status"] != FLIGHT_LOG_STATUS_PRE_FLIGHT:
        raise ValueError(
            "The Flight Log must be in pre_flight status before launch."
        )

    is_scheduled = row["requested_departure_datetime"] is not None

    if is_scheduled and row["execution_status"] != EXECUTION_STATUS_DISPATCHED:
        raise ValueError(
            "A scheduled Flight Execution must be dispatched before launch."
        )

    return FlightProcessContext(
        flight_execution_id=str(row["flight_execution_id"]),
        flight_log_id=str(row["flight_log_id"]),
        is_scheduled=is_scheduled,
    )


def record_takeoff(context: FlightProcessContext) -> None:
    """Transition the Flight Log from pre_flight to in_flight."""

    with engine.begin() as connection:
        result = connection.execute(
            text(
                """
                UPDATE flight_log
                SET
                    flight_log_status = :in_flight_status,
                    updated_at = NOW()
                WHERE flight_log_id = :flight_log_id
                  AND flight_execution_id = :flight_execution_id
                  AND flight_log_status = :pre_flight_status
                RETURNING flight_log_id
                """
            ),
            {
                "flight_log_id": context.flight_log_id,
                "flight_execution_id": context.flight_execution_id,
                "pre_flight_status": FLIGHT_LOG_STATUS_PRE_FLIGHT,
                "in_flight_status": FLIGHT_LOG_STATUS_IN_FLIGHT,
            },
        )

        if result.scalar_one_or_none() is None:
            raise RuntimeError(
                "Flight Log could not transition from pre_flight to in_flight."
            )


def record_landing(context: FlightProcessContext) -> None:
    """Complete the Flight Log and, when scheduled, the Flight Execution."""

    with engine.begin() as connection:
        log_result = connection.execute(
            text(
                """
                UPDATE flight_log
                SET
                    flight_log_status = :completed_status,
                    updated_at = NOW()
                WHERE flight_log_id = :flight_log_id
                  AND flight_execution_id = :flight_execution_id
                  AND flight_log_status = :in_flight_status
                RETURNING flight_log_id
                """
            ),
            {
                "flight_log_id": context.flight_log_id,
                "flight_execution_id": context.flight_execution_id,
                "in_flight_status": FLIGHT_LOG_STATUS_IN_FLIGHT,
                "completed_status": FLIGHT_LOG_STATUS_COMPLETED,
            },
        )

        if log_result.scalar_one_or_none() is None:
            raise RuntimeError(
                "Flight Log could not transition from in_flight to completed."
            )

        if not context.is_scheduled:
            return

        execution_result = connection.execute(
            text(
                """
                UPDATE flight_executions
                SET
                    execution_status = :completed_status,
                    flight_termination_datetime = NOW(),
                    updated_at = NOW()
                WHERE flight_execution_id = :flight_execution_id
                  AND execution_status = :dispatched_status
                RETURNING flight_execution_id
                """
            ),
            {
                "flight_execution_id": context.flight_execution_id,
                "dispatched_status": EXECUTION_STATUS_DISPATCHED,
                "completed_status": EXECUTION_STATUS_COMPLETED,
            },
        )

        if execution_result.scalar_one_or_none() is None:
            raise RuntimeError(
                "Scheduled Flight Execution could not transition from "
                "dispatched to completed."
            )

