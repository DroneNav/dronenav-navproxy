from __future__ import annotations

import json
import os
import ssl
from datetime import datetime, timezone
from typing import Any

import pika

from app.navproxy.simulator import TelemetryReading


RABBITMQ_HOST = "rabbitmq.dronenav.org"
RABBITMQ_PORT = 5671
RABBITMQ_VHOST = "prototype"

TELEMETRY_EXCHANGE = "dronenav.telemetry"
TELEMETRY_ROUTING_KEY = "telemetry.raw"


def get_rabbitmq_credentials() -> tuple[str, str]:
    username = os.environ.get("TELEMETRY_USER")
    password = os.environ.get("TELEMETRY_PASSWORD")

    if not username:
        raise RuntimeError("TELEMETRY_USER environment variable is not set")

    if not password:
        raise RuntimeError("TELEMETRY_PASSWORD environment variable is not set")

    return username, password


def build_telemetry_message(
    *,
    flight_execution_id: str,
    flight_id: str,
    telemetry: TelemetryReading,
) -> dict[str, Any]:
    """Build one scheduled-flight telemetry message."""

    return {
        "flight_execution_id": flight_execution_id,
        "flight_id": flight_id,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "telemetry": {
            "latitude": telemetry.latitude,
            "longitude": telemetry.longitude,
            "relative_altitude_ft": telemetry.relative_altitude_ft,
            "armed": telemetry.armed,
            "heartbeat_active": telemetry.heartbeat_active,
            "mission_sequence": telemetry.mission_sequence,
        },
    }


class TelemetryPublisher:
    """Publish scheduled-flight telemetry over one RabbitMQ connection."""

    def __init__(self) -> None:
        username, password = get_rabbitmq_credentials()

        credentials = pika.PlainCredentials(
            username,
            password,
        )

        ssl_context = ssl.create_default_context()

        parameters = pika.ConnectionParameters(
            host=RABBITMQ_HOST,
            port=RABBITMQ_PORT,
            virtual_host=RABBITMQ_VHOST,
            credentials=credentials,
            ssl_options=pika.SSLOptions(
                ssl_context,
                RABBITMQ_HOST,
            ),
        )

        self._connection = pika.BlockingConnection(parameters)
        self._channel = self._connection.channel()

    def publish(
        self,
        *,
        flight_execution_id: str,
        flight_id: str,
        telemetry: TelemetryReading,
    ) -> None:
        """Publish one telemetry reading."""

        message = build_telemetry_message(
            flight_execution_id=flight_execution_id,
            flight_id=flight_id,
            telemetry=telemetry,
        )

        self._channel.basic_publish(
            exchange=TELEMETRY_EXCHANGE,
            routing_key=TELEMETRY_ROUTING_KEY,
            body=json.dumps(message).encode("utf-8"),
            properties=pika.BasicProperties(
                content_type="application/json",
                delivery_mode=2,
            ),
        )

    def close(self) -> None:
        """Close the RabbitMQ connection."""

        if self._connection.is_open:
            self._connection.close()


