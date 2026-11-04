from __future__ import annotations

import json
import ssl
from typing import Any

import pika

from app.navproxy.telemetry_publisher import (
  RABBITMQ_HOST,
  RABBITMQ_PORT,
  RABBITMQ_VHOST,
  get_rabbitmq_credentials,
)


RMS_EXCHANGE = "dronenav.rms"
RMS_ROUTING_KEY = "navproxy.runtime"


class RuntimePublisher:
  """Publish NAVProxy runtime snapshots over a dedicated connection."""

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
      heartbeat=60,
    )

    self._connection = pika.BlockingConnection(parameters)
    self._channel = self._connection.channel()

  def publish(self, snapshot: dict[str, Any]) -> None:
    """Publish one complete runtime snapshot."""

    self._channel.basic_publish(
      exchange=RMS_EXCHANGE,
      routing_key=RMS_ROUTING_KEY,
      body=json.dumps(snapshot).encode("utf-8"),
      properties=pika.BasicProperties(
        content_type="application/json",
        delivery_mode=1,
      ),
    )

  def close(self) -> None:
    """Close the dedicated RabbitMQ connection."""

    if self._connection.is_open:
      self._connection.close()

