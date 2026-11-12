import math
from typing import Any

from app.services.route_service import get_coordinate_distance
from app.services.geometry_service import calculate_turn_angle

from app.config.constants import (
    MINIMUM_TURN_ANGLE_DEG,
)



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

    if angle < MINIMUM_TURN_ANGLE_DEG:
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

