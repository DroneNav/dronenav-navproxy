from __future__ import annotations

import json
import logging
import os
import ssl
import time
from datetime import datetime, timezone
from uuid import UUID

import clickhouse_connect
import pika

from app.navproxy.telemetry.telemetry_publisher import (
  RABBITMQ_HOST,
  RABBITMQ_PORT,
  RABBITMQ_VHOST,
  get_rabbitmq_credentials,
)


LOGGER = logging.getLogger(__name__)

logging.basicConfig(
  level=logging.INFO,
  format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

TELEMETRY_QUEUE = "dronenav.telemetry.clickhouse"

CLICKHOUSE_HOST = "clickhouse.dronenav.org"
CLICKHOUSE_PORT = 8123
CLICKHOUSE_DATABASE = "dronenav"
CLICKHOUSE_TABLE = "telemetry_raw"

TELEMETRY_COLUMNS = [
  "flight_execution_id",
  "flight_id",
  "observed_at",
  "latitude",
  "longitude",
  "relative_altitude_ft",
  "absolute_altitude_ft",
  "ground_speed_ft_s",
  "armed",
  "heartbeat_active",
  "mission_sequence",
  "battery_percent",
  "energy_health",
  "navigation_health",
  "vehicle_health",
]


def get_clickhouse_credentials() -> tuple[str, str]:
  username = os.environ.get("CLICKHOUSE_USER")
  password = os.environ.get("CLICKHOUSE_PASSWORD")

  if not username or not password:
    raise RuntimeError(
      "CLICKHOUSE_USER and CLICKHOUSE_PASSWORD must be set"
    )

  return username, password


def build_telemetry_row(message: dict) -> list:
  observed_at = datetime.fromisoformat(
    message["observed_at"].replace("Z", "+00:00")
  )

  if observed_at.tzinfo is None:
    raise ValueError("Telemetry observed_at must include a timezone")

  return [
    UUID(message["flight_execution_id"]),
    UUID(message["flight_id"]),
    observed_at.astimezone(timezone.utc),
    *[
      message.get(column)
      for column in TELEMETRY_COLUMNS[3:]
    ],
  ]


def connect_clickhouse():
  username, password = get_clickhouse_credentials()

  return clickhouse_connect.get_client(
    host=CLICKHOUSE_HOST,
    port=CLICKHOUSE_PORT,
    username=username,
    password=password,
    database=CLICKHOUSE_DATABASE,
    connect_timeout=10,
    send_receive_timeout=30,
  )


def connect_rabbitmq():
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
    heartbeat=120,
    blocked_connection_timeout=60,
  )

  return pika.BlockingConnection(parameters)


def consume_telemetry() -> None:
  clickhouse = connect_clickhouse()
  rabbitmq = connect_rabbitmq()
  channel = rabbitmq.channel()

  channel.basic_qos(prefetch_count=1)

  LOGGER.info(
    "ClickHouse telemetry collector started: queue=%s",
    TELEMETRY_QUEUE,
  )

  try:
    for method, properties, body in channel.consume(
      TELEMETRY_QUEUE,
      inactivity_timeout=1.0,
      auto_ack=False,
    ):
      if body is None:
        continue

      try:
        message = json.loads(body.decode("utf-8"))
        row = build_telemetry_row(message)

        clickhouse.insert(
          CLICKHOUSE_TABLE,
          [row],
          column_names=TELEMETRY_COLUMNS,
        )

        channel.basic_ack(
          delivery_tag=method.delivery_tag,
        )

      except Exception:
        LOGGER.exception(
          "ClickHouse telemetry insertion failed"
        )

        channel.basic_nack(
          delivery_tag=method.delivery_tag,
          requeue=True,
        )

        raise

  finally:
    if rabbitmq.is_open:
      rabbitmq.close()

    clickhouse.close()


def main() -> None:
  while True:
    try:
      consume_telemetry()

    except KeyboardInterrupt:
      LOGGER.info("ClickHouse telemetry collector stopped")
      return

    except Exception:
      LOGGER.exception(
        "ClickHouse telemetry collector disconnected; retrying"
      )
      time.sleep(5)


if __name__ == "__main__":
  main()

