import math
from typing import Any

from app.services.route_service import get_coordinate_distance


TURN_MINIMUM_ANGLE_DEGREES = 5.0


def calculate_segment_length_ft(
    start_coordinate: list[float],
    end_coordinate: list[float],
) -> float:
    """Calculate operational lane segment length in feet."""

    result, error = get_coordinate_distance({
        "first_longitude": start_coordinate[0],
        "first_latitude": start_coordinate[1],
        "second_longitude": end_coordinate[0],
        "second_latitude": end_coordinate[1],
    })

    if error is not None or result is None:
        raise ValueError(
            error or "Could not calculate segment length."
        )

    return float(result["distance_ft"])


def calculate_turn_angle(
  incoming_start: list[float],
  vertex: list[float],
  outgoing_end: list[float],
) -> float:
  """Calculate the direction change between two lane segments."""

  latitude_radians = math.radians(vertex[1])

  longitude_scale = math.cos(latitude_radians)

  incoming_x = (
    vertex[0] - incoming_start[0]
  ) * longitude_scale
  incoming_y = vertex[1] - incoming_start[1]

  outgoing_x = (
    outgoing_end[0] - vertex[0]
  ) * longitude_scale
  outgoing_y = outgoing_end[1] - vertex[1]

  incoming_length = math.hypot(incoming_x, incoming_y)
  outgoing_length = math.hypot(outgoing_x, outgoing_y)

  if incoming_length == 0 or outgoing_length == 0:
    raise ValueError("Turn contains a zero-length segment.")

  cross = (
    incoming_x * outgoing_y
    - incoming_y * outgoing_x
  )

  dot = (
    incoming_x * outgoing_x
    + incoming_y * outgoing_y
  )

  return math.degrees(math.atan2(abs(cross), dot))


def identify_route_turns(
  segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
  """Identify direction changes within operational Routes."""

  turns = []

  for index in range(len(segments) - 1):
    incoming = segments[index]
    outgoing = segments[index + 1]

    angle = calculate_turn_angle(
      incoming["operational_start_coordinate"],
      incoming["operational_end_coordinate"],
      outgoing["operational_end_coordinate"],
    )

    if angle < TURN_MINIMUM_ANGLE_DEGREES:
      continue

    turns.append({
      "incoming_segment_index": index,
      "outgoing_segment_index": index + 1,
      "route_id": incoming["route_id"],
      "turn_coordinate": incoming["end_coordinate"],
      "operational_turn_coordinate": incoming["operational_end_coordinate"],
      "route_node_id": incoming["end_route_node_id"],
      "turn_angle_degrees": angle,
      "route_transition": (
        incoming["route_index"] != outgoing["route_index"]
      ),
    })

  return turns

