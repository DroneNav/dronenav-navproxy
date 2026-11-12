from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID
import json
import time

from app.navproxy.telemetry.collector import (
  connect_clickhouse,
  connect_rabbitmq,
)
from app.navproxy.telemetry.telemetry_publisher import (
  TELEMETRY_EXCHANGE,
  TURN_OBSERVATION_ROUTING_KEY,
)


LOGGER = logging.getLogger(__name__)

TURN_OBSERVATION_QUEUE = "dronenav.turn_observations.clickhouse"
CLICKHOUSE_TABLE = "turn_observations"
TURN_OBSERVATION_COLUMNS = [
  "flight_execution_id",
  "route_node_id",
  "incoming_segment_index",
  "outgoing_segment_index",
  "observed_at",
  "latitude",
  "longitude",
  "ground_speed_ft_s",
  "roll_degrees",
  "pitch_degrees",
  "yaw_degrees",
  "turn_angle_degrees",
  "turn_direction",
  "distance_to_turn_ft",
  "incoming_signed_offset_ft",
  "incoming_inside_turn_offset_ft",
  "incoming_outside_turn_offset_ft",
  "outgoing_signed_offset_ft",
  "outgoing_inside_turn_offset_ft",
  "outgoing_outside_turn_offset_ft",
]


def build_turn_observation_row(message: dict) -> list:
  """Convert one turn observation into a ClickHouse row."""

  observed_at = datetime.fromisoformat(
    message["observed_at"].replace("Z", "+00:00")
  )

  if observed_at.tzinfo is None:
    raise ValueError(
      "Turn observation timestamp must include a timezone"
    )

  lane_offsets = message["lane_offsets"]
  incoming = lane_offsets["incoming"]
  outgoing = lane_offsets["outgoing"]

  route_node_id = message.get("route_node_id")

  return [
    UUID(message["flight_execution_id"]),
    UUID(route_node_id) if route_node_id else None,
    int(message["incoming_segment_index"]),
    int(message["outgoing_segment_index"]),
    observed_at.astimezone(timezone.utc),
    message.get("latitude"),
    message.get("longitude"),
    message.get("ground_speed_ft_s"),
    message.get("roll_degrees"),
    message.get("pitch_degrees"),
    message.get("yaw_degrees"),
    float(message["turn_angle_degrees"]),
    lane_offsets["turn_direction"],
    float(message["distance_to_turn_ft"]),
    float(incoming["signed_offset_ft"]),
    float(incoming["inside_turn_offset_ft"]),
    float(incoming["outside_turn_offset_ft"]),
    float(outgoing["signed_offset_ft"]),
    float(outgoing["inside_turn_offset_ft"]),
    float(outgoing["outside_turn_offset_ft"]),
  ]


def declare_turn_observation_queue(channel) -> None:
  """Declare and bind the durable turn observation queue."""

  channel.queue_declare(
    queue=TURN_OBSERVATION_QUEUE,
    durable=True,
  )

  channel.queue_bind(
    exchange=TELEMETRY_EXCHANGE,
    queue=TURN_OBSERVATION_QUEUE,
    routing_key=TURN_OBSERVATION_ROUTING_KEY,
  )


def consume_turn_observations() -> None:
  """Consume turn observations and persist them in ClickHouse."""

  clickhouse = connect_clickhouse()
  rabbitmq = connect_rabbitmq()
  channel = rabbitmq.channel()

  declare_turn_observation_queue(channel)
  channel.basic_qos(prefetch_count=1)

  LOGGER.info(
    "ClickHouse turn observation collector started: queue=%s",
    TURN_OBSERVATION_QUEUE,
  )

  try:
    for method, properties, body in channel.consume(
      TURN_OBSERVATION_QUEUE,
      inactivity_timeout=1.0,
      auto_ack=False,
    ):
      if body is None:
        continue

      try:
        message = json.loads(body.decode("utf-8"))
        row = build_turn_observation_row(message)

        clickhouse.insert(
          CLICKHOUSE_TABLE,
          [row],
          column_names=TURN_OBSERVATION_COLUMNS,
        )

        channel.basic_ack(
          delivery_tag=method.delivery_tag,
        )

      except Exception:
        LOGGER.exception(
          "ClickHouse turn observation insertion failed"
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
      consume_turn_observations()

    except KeyboardInterrupt:
      LOGGER.info("Turn observation collector stopped")
      return

    except Exception:
      LOGGER.exception(
        "Turn observation collector disconnected; retrying"
      )
      time.sleep(5)


if __name__ == "__main__":
  main()


