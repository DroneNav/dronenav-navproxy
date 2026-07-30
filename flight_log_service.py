"""Shared-database operations required by NAVProxy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text

from app.config.constants import (
    EXECUTION_STATUS_COMPLETED,
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


def get_requested_departure_datetime(
    flight_execution_id: str,
) -> datetime | None:
    """Return the requested departure datetime for one Flight Execution."""

    with engine.connect() as connection:
        result = connection.execute(
            text(
                """
                SELECT requested_departure_datetime
                FROM flight_executions
                WHERE flight_execution_id = :flight_execution_id
                """
            ),
            {
                "flight_execution_id": flight_execution_id,
            },
        )

        row = result.one_or_none()

        if row is None:
            raise RuntimeError(
                f"Flight Execution {flight_execution_id} was not found."
            )

        return row.requested_departure_datetime


def begin_flight_log(context: FlightProcessContext) -> None:
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


def complete_flight_log(context: FlightProcessContext) -> None:
    """Transition the Flight Log from in_flight to completed."""

    with engine.begin() as connection:
        result = connection.execute(
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

        if result.scalar_one_or_none() is None:
            raise RuntimeError(
                "Flight Log could not transition from in_flight to completed."
            )


