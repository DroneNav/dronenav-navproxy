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
from app.navproxy.rms.registry import registry


collector_logger = logging.getLogger(
  "app.navproxy.rms.collector"
)

RMS_QUEUE = "dronenav.rms.collector"


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
        heartbeat=60,
    )

    connection = pika.BlockingConnection(parameters)
    channel = connection.channel()

    collector_logger.info(
        "RMS collector started: queue=%s",
        RMS_QUEUE,
    )

    try:
        for method, properties, body in channel.consume(
            RMS_QUEUE,
            inactivity_timeout=1.0,
            auto_ack=False,
        ):
            if body is None:
                continue

            try:
                snapshot = json.loads(
                    body.decode("utf-8")
                )

                if not isinstance(snapshot, dict):
                    raise ValueError(
                        "Runtime snapshot must be a JSON object"
                    )

                runtime_instance_id = snapshot.get(
                    "runtime_instance_id"
                )

                if (
                    not isinstance(runtime_instance_id, str)
                    or not runtime_instance_id
                ):
                    raise ValueError(
                        "Missing runtime_instance_id"
                    )

                registry.update(snapshot)

                channel.basic_ack(
                    delivery_tag=method.delivery_tag
                )

            except Exception:
                collector_logger.exception(
                    "RMS runtime snapshot processing failed"
                )

                channel.basic_nack(
                    delivery_tag=method.delivery_tag,
                    requeue=False,
                )

    except KeyboardInterrupt:
        collector_logger.info("RMS collector stopping")

    finally:
        if channel.is_open:
            channel.cancel()

        if connection.is_open:
            connection.close()


if __name__ == "__main__":
    main()

