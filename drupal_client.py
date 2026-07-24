"""Drupal callback integration for Flight Plan lifecycle updates."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

from .settings import (
    DRUPAL_STATUS_CALLBACK_TIMEOUT_SECONDS,
    DRUPAL_STATUS_CALLBACK_TOKEN,
    DRUPAL_STATUS_CALLBACK_URL,
)

LOGGER = logging.getLogger(__name__)


def notify_flight_plan_status(flight_execution_id: str, status: str) -> None:
    """Notify Drupal of a Flight Plan lifecycle status transition."""

    if not DRUPAL_STATUS_CALLBACK_TOKEN:
        raise RuntimeError("DRUPAL_STATUS_CALLBACK_TOKEN is not configured.")

    occurred_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    response = requests.post(
        DRUPAL_STATUS_CALLBACK_URL,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-DroneNav-Callback-Token": DRUPAL_STATUS_CALLBACK_TOKEN,
        },
        json={
            "flight_execution_id": flight_execution_id,
            "status": status,
            "occurred_at": occurred_at,
        },
        timeout=DRUPAL_STATUS_CALLBACK_TIMEOUT_SECONDS,
    )

    try:
        response.raise_for_status()
    except requests.HTTPError:
        LOGGER.error(
            "Drupal Flight Plan status callback failed: "
            "execution=%s status=%s http_status=%s response=%s",
            flight_execution_id,
            status,
            response.status_code,
            response.text,
        )
        raise

    LOGGER.info(
        "Drupal Flight Plan status callback succeeded: execution=%s status=%s",
        flight_execution_id,
        status,
    )

