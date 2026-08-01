"""Shared-database operations required by NAVProxy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text

from app.config.database import engine

import json


@dataclass(frozen=True)
class FlightProcessContext:
    """Runtime state required during one NAVProxy-controlled flight."""

    flight_execution_id: str
    flight_id: str
    flight_execution: dict[str, Any] | None = None
    compiler_ir: dict[str, Any] | None = None


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


def append_flight_log(
    context: FlightProcessContext,
    lifecycle_phase: str,
    event_type: str,
    event_status: str | None,
    message: str,
    details: dict[str, Any] | None = None,
) -> str:
    """Append one significant operational event to the Flight Log."""

    with engine.begin() as connection:
        result = connection.execute(
            text(
                """
                INSERT INTO flight_log (
                    flight_id,
                    flight_execution_id,
                    lifecycle_phase,
                    event_type,
                    event_status,
                    message,
                    details
                )
                VALUES (
                    :flight_id,
                    :flight_execution_id,
                    :lifecycle_phase,
                    :event_type,
                    :event_status,
                    :message,
                    CAST(:details AS jsonb)
                )
                RETURNING flight_log_id
                """
            ),
            {
                "flight_id": context.flight_id,
                "flight_execution_id": context.flight_execution_id,
                "lifecycle_phase": lifecycle_phase,
                "event_type": event_type,
                "event_status": event_status,
                "message": message,
                "details": json.dumps(details) if details is not None else None,
            },
        )

        flight_log_id = result.scalar_one_or_none()

        if flight_log_id is None:
            raise RuntimeError(
                "Flight Log entry could not be created."
            )

        return str(flight_log_id)

