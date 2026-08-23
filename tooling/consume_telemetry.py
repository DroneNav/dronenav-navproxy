from __future__ import annotations

import json
import ssl

import pika

from app.navproxy.telemetry_publisher import (
    RABBITMQ_HOST,
    RABBITMQ_PORT,
    RABBITMQ_VHOST,
    get_rabbitmq_credentials,
)


TELEMETRY_QUEUE = "dronenav.telemetry.raw"


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
        f"Consuming telemetry from {TELEMETRY_QUEUE}. "
        "Press Ctrl+C to stop."
    )

    try:
        for method, properties, body in channel.consume(
            TELEMETRY_QUEUE,
            inactivity_timeout=1.0,
            auto_ack=True,
        ):
            if body is None:
                continue

            message = json.loads(
                body.decode("utf-8")
            )

            print(
                json.dumps(
                    message,
                    indent=2,
                    sort_keys=True,
                )
            )

    except KeyboardInterrupt:
        pass

    finally:
        channel.cancel()
        connection.close()


if __name__ == "__main__":
    main()

