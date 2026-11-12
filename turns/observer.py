
import math

from app.services.route_service import get_coordinate_distance


TURN_OBSERVATION_RADIUS_FT = 30.0


def evaluate_turn_observation(
    telemetry,
    turn: dict,
    segments: list[dict],
) -> dict:
    """Observe aircraft position within a turn region."""

    coordinate = turn["turn_coordinate"]

    result, error = get_coordinate_distance({
        "first_longitude": telemetry.longitude,
        "first_latitude": telemetry.latitude,
        "second_longitude": coordinate[0],
        "second_latitude": coordinate[1],
    })

    if error is not None or result is None:
        raise RuntimeError(
            error or "Could not calculate distance to turn."
        )

    distance_ft = float(result["distance_ft"])

    inside_radius = (
        distance_ft <= TURN_OBSERVATION_RADIUS_FT
    )

    lane_offsets = None

    if inside_radius:
        lane_offsets = evaluate_turn_lane_offsets(
            telemetry,
            turn,
            segments,
        )

    return {
        "route_node_id": turn.get("route_node_id"),
        "incoming_segment_index": turn["incoming_segment_index"],
        "outgoing_segment_index": turn["outgoing_segment_index"],
        "turn_angle_degrees": turn["turn_angle_degrees"],
        "distance_to_turn_ft": distance_ft,
        "inside_observation_radius": inside_radius,
        "lane_offsets": lane_offsets,
    }


def calculate_signed_lane_offset_ft(
    telemetry,
    start_coordinate,
    end_coordinate,
) -> float:
    """Signed lateral offset from an operational lane centerline."""

    latitude = math.radians(
        (start_coordinate[1] + end_coordinate[1]) / 2.0
    )

    feet_per_degree_lat = 364000.0
    feet_per_degree_lon = (
        feet_per_degree_lat * math.cos(latitude)
    )

    segment_x = (
        end_coordinate[0] - start_coordinate[0]
    ) * feet_per_degree_lon

    segment_y = (
        end_coordinate[1] - start_coordinate[1]
    ) * feet_per_degree_lat

    aircraft_x = (
        telemetry.longitude - start_coordinate[0]
    ) * feet_per_degree_lon

    aircraft_y = (
        telemetry.latitude - start_coordinate[1]
    ) * feet_per_degree_lat

    segment_length = math.hypot(segment_x, segment_y)

    if segment_length <= 0.0:
        raise ValueError("Turn observation segment has zero length.")

    return (
        segment_x * aircraft_y
        - segment_y * aircraft_x
    ) / segment_length


def classify_turn_deviation(
    signed_offset_ft: float,
    turn_direction: str,
) -> dict:
    """Classify lateral deviation relative to turn direction."""

    if turn_direction not in ("left", "right"):
        raise ValueError("Invalid turn direction.")

    inside_offset_ft = (
        signed_offset_ft
        if turn_direction == "left"
        else -signed_offset_ft
    )

    return {
        "signed_offset_ft": signed_offset_ft,
        "inside_turn_offset_ft": max(0.0, inside_offset_ft),
        "outside_turn_offset_ft": max(0.0, -inside_offset_ft),
    }


def determine_turn_direction(
    incoming_start,
    vertex,
    outgoing_end,
) -> str:
    """Determine left or right turn from operational geometry."""

    latitude = math.radians(vertex[1])
    longitude_scale = math.cos(latitude)

    incoming_x = (
        vertex[0] - incoming_start[0]
    ) * longitude_scale
    incoming_y = vertex[1] - incoming_start[1]

    outgoing_x = (
        outgoing_end[0] - vertex[0]
    ) * longitude_scale
    outgoing_y = outgoing_end[1] - vertex[1]

    cross_product = (
        incoming_x * outgoing_y
        - incoming_y * outgoing_x
    )

    if cross_product > 0.0:
        return "left"

    if cross_product < 0.0:
        return "right"

    return "straight"


def evaluate_turn_lane_offsets(
    telemetry,
    turn: dict,
    segments: list[dict],
) -> dict:
    """Measure aircraft deviation from both turn segments."""

    incoming = segments[turn["incoming_segment_index"]]
    outgoing = segments[turn["outgoing_segment_index"]]

    incoming_start = incoming["operational_start_coordinate"]
    vertex = incoming["operational_end_coordinate"]
    outgoing_end = outgoing["operational_end_coordinate"]

    direction = determine_turn_direction(
        incoming_start,
        vertex,
        outgoing_end,
    )

    if direction == "straight":
        raise ValueError("Turn has no measurable direction.")

    incoming_offset = calculate_signed_lane_offset_ft(
        telemetry,
        incoming_start,
        vertex,
    )

    outgoing_offset = calculate_signed_lane_offset_ft(
        telemetry,
        outgoing["operational_start_coordinate"],
        outgoing_end,
    )

    return {
        "turn_direction": direction,
        "incoming": classify_turn_deviation(
            incoming_offset,
            direction,
        ),
        "outgoing": classify_turn_deviation(
            outgoing_offset,
            direction,
        ),
    }


def get_active_turns(
    turns: list[dict],
    active_segment_index: int,
) -> list[dict]:
    """Find turns associated with the active Route segment."""

    return [
        turn
        for turn in turns
        if active_segment_index in (
            turn["incoming_segment_index"],
            turn["outgoing_segment_index"],
        )
    ]


def observe_active_turns(
    telemetry,
    compiler_ir: dict,
    active_segment_index: int,
) -> list[dict]:
    """Collect turn observations for the current telemetry reading."""

    mission = compiler_ir["mission"]
    turns = mission.get("route_turns", [])
    segments = mission["route_conformance_segments"]

    observations = []

    for turn in get_active_turns(
        turns,
        active_segment_index,
    ):
        observation = evaluate_turn_observation(
            telemetry,
            turn,
            segments,
        )

        if not observation["inside_observation_radius"]:
            continue

        observations.append({
            **observation,
            "observed_at": telemetry.observed_at,
            "latitude": telemetry.latitude,
            "longitude": telemetry.longitude,
            "ground_speed_ft_s": telemetry.ground_speed_ft_s,
            "roll_degrees": telemetry.roll_degrees,
            "pitch_degrees": telemetry.pitch_degrees,
            "yaw_degrees": telemetry.yaw_degrees,
        })

    return observations


