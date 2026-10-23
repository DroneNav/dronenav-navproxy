from __future__ import annotations

import json
import logging
import ssl

import pika

from app.navproxy.telemetry_publisher import (
    RABBITMQ_HOST,
    RABBITMQ_PORT,
    RABBITMQ_VHOST,
    get_rabbitmq_credentials,
)


LOGGER = logging.getLogger(__name__)

CONTROL_EXCHANGE = "dronenav.control"

class ControlConsumer:
    """Receive RSE control messages for one Flight Execution."""

    def __init__(self, flight_execution_id: str) -> None:
        self.flight_execution_id = str(flight_execution_id)

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

        self.routing_key = (
            f"navproxy.{self.flight_execution_id}"
        )

        self.queue_name = (
            f"dronenav.control.{self.flight_execution_id}"
        )

        self._channel.queue_declare(
            queue=self.queue_name,
            durable=True,
            arguments={
                "x-expires": 86400000,
            },
        )

        self._channel.queue_bind(
            exchange=CONTROL_EXCHANGE,
            queue=self.queue_name,
            routing_key=self.routing_key,
        )


    def receive(self) -> list[dict]:
        """Return currently queued control messages without blocking."""

        messages = []

        while True:
            method, properties, body = self._channel.basic_get(
                queue=self.queue_name,
                auto_ack=False,
            )

            if method is None:
                break

            message = json.loads(body.decode("utf-8"))

            if str(message.get("flight_execution_id")) != self.flight_execution_id:
                raise ValueError(
                    "Control message Flight Execution ID mismatch."
                )

            messages.append({
                "delivery_tag": method.delivery_tag,
                "message": message,
            })

        return messages


    def acknowledge(self, delivery_tag: int) -> None:
        """Acknowledge a successfully processed control message."""

        self._channel.basic_ack(
            delivery_tag=delivery_tag,
        )


    def close(self) -> None:
        """Close the RabbitMQ control connection."""

        if self._connection.is_open:
            self._connection.close()


