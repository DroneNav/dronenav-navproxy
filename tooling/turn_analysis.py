from app.navproxy.tooling.chsql import client
from app.services.route_service import (
    evaluate_route_segment_conformance,
    get_route_by_id,
)
from app.services.geometry_service import build_offset_polyline


def load_operational_lane(route_ids):
    combined_coordinates = []
    combined_widths = []

    for route_id in route_ids:
        route = get_route_by_id(route_id)

        if route is None:
            raise ValueError(f"Route not found: {route_id}")

        coordinates = route["geometry"]["coordinates"]
        attributes = route["segment_attributes"]

        if not combined_coordinates:
            combined_coordinates.extend(coordinates)
        elif combined_coordinates[-1] == coordinates[0]:
            combined_coordinates.extend(coordinates[1:])
        elif combined_coordinates[-1] == coordinates[-1]:
            coordinates = list(reversed(coordinates))
            attributes = list(reversed(attributes))
            combined_coordinates.extend(coordinates[1:])
        else:
            raise ValueError(
                f"Route {route_id} does not connect to previous Route"
            )

        combined_widths.extend(
            item["route_width_ft"]
            for item in attributes
        )

    return build_offset_polyline(
        coordinates=combined_coordinates,
        segment_widths_ft=combined_widths,
        side="right",
    )

def load_turn_observations(flight_execution_id):
    result = client.query(
        """
        SELECT
            incoming_segment_index,
            outgoing_segment_index,
            latitude,
            longitude,
            ground_speed_ft_s,
            turn_angle_degrees
        FROM turn_observations
        WHERE flight_execution_id = {flight_id:UUID}
        ORDER BY observed_at
        """,
        parameters={
            "flight_id": flight_execution_id,
        },
    )

    return [
        dict(zip(result.column_names, row))
        for row in result.result_rows
    ]


def signed_lateral_offset_ft(
    latitude,
    longitude,
    start,
    end,
):
    from math import cos, radians, hypot

    reference_latitude = radians(
        (start[1] + end[1]) / 2.0
    )

    feet_per_degree_lat = 364000.0
    feet_per_degree_lon = (
        feet_per_degree_lat * cos(reference_latitude)
    )

    dx = (
        end[0] - start[0]
    ) * feet_per_degree_lon

    dy = (
        end[1] - start[1]
    ) * feet_per_degree_lat

    px = (
        longitude - start[0]
    ) * feet_per_degree_lon

    py = (
        latitude - start[1]
    ) * feet_per_degree_lat

    length = hypot(dx, dy)

    if length == 0:
        raise ValueError("Zero-length operational segment")

    return (dx * py - dy * px) / length


def evaluate_turn_observation(observation, lane_coordinates):
    incoming_index = observation["incoming_segment_index"]
    outgoing_index = observation["outgoing_segment_index"]

    distances = []

    for segment_index in (incoming_index, outgoing_index):
        if not 0 <= segment_index < len(lane_coordinates) - 1:
            raise ValueError(
                f"Invalid operational segment index: {segment_index}"
            )

        start = lane_coordinates[segment_index]
        end = lane_coordinates[segment_index + 1]

        result, error = evaluate_route_segment_conformance({
            "latitude": observation["latitude"],
            "longitude": observation["longitude"],
            "start_latitude": start[1],
            "start_longitude": start[0],
            "end_latitude": end[1],
            "end_longitude": end[0],
            "route_width_ft": 10.0,
        })

        if error:
            raise RuntimeError(error)

        distances.append((
            result["distance_ft"],
            segment_index,
        ))

    offset_ft, nearest_segment_index = min(distances)

    start = lane_coordinates[nearest_segment_index]
    end = lane_coordinates[nearest_segment_index + 1]

    signed_offset_ft = signed_lateral_offset_ft(
        latitude=observation["latitude"],
        longitude=observation["longitude"],
        start=start,
        end=end,
    )

    return {
        "offset_ft": offset_ft,
        "signed_offset_ft": signed_offset_ft,
        "nearest_segment_index": nearest_segment_index,
        "allowed_offset_ft": 5.0,
        "inside": offset_ft <= 5.0,
    }


def analyze_flight(flight_execution_id, lane_coordinates):
    observations = load_turn_observations(flight_execution_id)
    turns = {}

    for observation in observations:
        key = (
            observation["incoming_segment_index"],
            observation["outgoing_segment_index"],
        )

        result = evaluate_turn_observation(
            observation,
            lane_coordinates,
        )

        if key not in turns:
            turns[key] = {
                "angle": observation["turn_angle_degrees"],
                "samples": 0,
                "maximum_offset_ft": 0.0,
                "violations": 0,
            }

        summary = turns[key]
        summary["samples"] += 1
        summary["maximum_offset_ft"] = max(
            summary["maximum_offset_ft"],
            result["offset_ft"],
        )

        if not result["inside"]:
            summary["violations"] += 1

    print(f"\nFlight: {flight_execution_id}")
    print(
        "Turn    Angle    Samples    "
        "Max offset    Violations"
    )

    for key, summary in sorted(turns.items()):
        print(
            f"{key[0]}->{key[1]}    "
            f"{summary['angle']:.1f}°    "
            f"{summary['samples']}    "
            f"{summary['maximum_offset_ft']:.3f} ft    "
            f"{summary['violations']}"
        )


def main():
    route_ids = [
        "01a0830a-4f1b-7f6e-84ef-c4836692f8ec",
        "01a08306-7a12-7b25-bc35-3995f3a21b63",
    ]

    flights = {
        "25 mph": "01a1ca22-2cc5-7aa6-acab-ecb3193ed953",
        "10 mph": "01a1ca31-e8cc-7cf5-969b-7a1dbc8f96ca",
    }

    lane_coordinates = load_operational_lane(route_ids)

    for speed, flight_execution_id in flights.items():
        print(f"\nGoverned cruise speed: {speed}")
        analyze_flight(
            flight_execution_id,
            lane_coordinates,
        )


if __name__ == "__main__":
    main()


