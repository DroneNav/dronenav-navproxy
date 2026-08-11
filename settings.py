"""NAVProxy runtime configuration."""

from __future__ import annotations

import os

DEFAULT_PREFLIGHT_SECONDS = 30
DEFAULT_FLIGHT_SECONDS = 15

DRUPAL_STATUS_CALLBACK_URL = os.getenv(
    "DRUPAL_STATUS_CALLBACK_URL",
    "https://dronenav.org/api/flight-plans/status-callback",
)
DRUPAL_STATUS_CALLBACK_TOKEN = os.getenv("DRUPAL_STATUS_CALLBACK_TOKEN")
DRUPAL_STATUS_CALLBACK_TIMEOUT_SECONDS = int(
    os.getenv("DRUPAL_STATUS_CALLBACK_TIMEOUT_SECONDS", "10")
)

FLIGHT_PLAN_STATUS_ACTIVE = "active"
FLIGHT_PLAN_STATUS_COMPLETED = "completed"
FLIGHT_PLAN_STATUS_SUBMITTED = "submitted"

