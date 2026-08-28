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

RSE_TELEMETRY_QUEUE = "dronenav.telemetry.rse"


def main() -> None:
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

    connection = pika.BlockingConnection(parameters)
    channel = connection.channel()

    print(
        f"RSE telemetry collector started: queue={RSE_TELEMETRY_QUEUE}"
    )

    LOGGER.info(
        "RSE telemetry collector started: queue=%s",
        RSE_TELEMETRY_QUEUE,
    )

    try:
        for method, properties, body in channel.consume(
            RSE_TELEMETRY_QUEUE,
            inactivity_timeout=1.0,
            auto_ack=False,
        ):
            if body is None:
                continue

            try:
                message = json.loads(
                    body.decode("utf-8")
                )

                process_telemetry(message)

                channel.basic_ack(
                    delivery_tag=method.delivery_tag
                )

            except Exception:
                LOGGER.exception(
                    "RSE telemetry processing failed"
                )

                channel.basic_nack(
                    delivery_tag=method.delivery_tag,
                    requeue=True,
                )

    except KeyboardInterrupt:
        pass

    finally:
        channel.cancel()
        connection.close()


def process_telemetry(message: dict) -> None:
    """
    Process a raw telemetry observation.

    Future:
    - correlate with Flight Execution
    - resolve Route occupancy
    - update route_occupancy_state
    """

    LOGGER.info(
        "RSE telemetry received: %s",
        message,
    )

    print(
        json.dumps(
            message,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

