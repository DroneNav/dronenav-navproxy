from __future__ import annotations

import json
import logging
import ssl
import pika
import math

from app.config.database import engine

from app.navproxy.telemetry_publisher import (
    RABBITMQ_HOST,
    RABBITMQ_PORT,
    RABBITMQ_VHOST,
    get_rabbitmq_credentials,
)
from app.models.flight_execution_model import (
    select_flight_execution_route_ranges,
)
from app.models.intersection_state_model import (
    select_intersection_state,
)
from app.models.route_occupancy_state_model import (
    select_route_occupancy_state,
    update_route_occupancy_state,
)
from app.services.intersection_state_service import (
    clear_intersection_slot,
    occupy_intersection_slot,
    reserve_intersection_slot,
)


FER_ROUTE_RANGE_CACHE: dict[
    str,
    list[dict],
] = {}


LOGGER = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

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
                    requeue=False,
                )

    except KeyboardInterrupt:
        pass

    finally:
        channel.cancel()
        connection.close()


def get_fer_route_ranges(
    flight_execution_id: str,
) -> list[dict]:
    """Return cached Route mission ranges for a Flight Execution."""

    route_ranges = FER_ROUTE_RANGE_CACHE.get(
        flight_execution_id
    )

    if route_ranges is None:
        route_ranges = select_flight_execution_route_ranges(
            flight_execution_id
        )

        if not route_ranges:
            raise ValueError(
                "No Route ranges found for Flight Execution "
                f"{flight_execution_id}."
            )

        FER_ROUTE_RANGE_CACHE[flight_execution_id] = (
            route_ranges
        )

    return route_ranges


def get_route_for_mission_sequence(
    route_ranges: list[dict],
    mission_sequence: int,
):
    """Return the Route range containing the mission sequence."""

    for index, route in enumerate(route_ranges):
        start_sequence = route.get(
            "start_mission_sequence"
        )
        end_sequence = route.get(
            "end_mission_sequence"
        )

        if (
            start_sequence is not None
            and end_sequence is not None
            and start_sequence
            <= mission_sequence
            <= end_sequence
        ):
            previous_route = (
                route_ranges[index - 1]
                if index > 0
                else None
            )

            next_route = (
                route_ranges[index + 1]
                if index + 1 < len(route_ranges)
                else None
            )

            return route, previous_route, next_route

    return None, None, None


def get_managed_intersection_route_node(
    route: dict,
    next_route: dict | None,
):
    """Return the cached managed intersection Route Node."""

    if next_route is None:
        return None

    return route.get("intersection_route_node_id")


def distance_between_coordinates_ft(
    latitude_1: float,
    longitude_1: float,
    latitude_2: float,
    longitude_2: float,
) -> float:
    """Calculate great-circle distance between coordinates in feet."""

    earth_radius_ft = 20925524.9

    lat1 = math.radians(latitude_1)
    lat2 = math.radians(latitude_2)
    delta_lat = math.radians(latitude_2 - latitude_1)
    delta_lon = math.radians(longitude_2 - longitude_1)

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(delta_lon / 2) ** 2
    )

    return (
        2
        * earth_radius_ft
        * math.asin(min(1.0, math.sqrt(a)))
    )


def is_outside_intersection_radius(
    route: dict,
    latitude: float,
    longitude: float,
) -> bool:
    """Check whether telemetry is outside the intersection radius."""

    center_latitude = route.get("intersection_latitude")
    center_longitude = route.get("intersection_longitude")
    diameter_ft = route.get("intersection_diameter_ft")

    if (
        center_latitude is None
        or center_longitude is None
        or diameter_ft is None
    ):
        return False

    distance_ft = distance_between_coordinates_ft(
        latitude,
        longitude,
        center_latitude,
        center_longitude,
    )

    return distance_ft > diameter_ft / 2.0


def process_telemetry(message: dict) -> None:
    """
    Process a raw telemetry observation.
    """

    flight_execution_id = message.get(
        "flight_execution_id"
    )

    if not flight_execution_id:
        raise ValueError(
            "Telemetry message is missing flight_execution_id."
        )

    route_ranges = get_fer_route_ranges(
        str(flight_execution_id)
    )

    mission_sequence = message.get(
        "mission_sequence"
    )

    if mission_sequence is None:
        return

    route, previous_route, next_route = get_route_for_mission_sequence(
        route_ranges,
        int(mission_sequence),
    )

    if route is None:
        return

    incoming_intersection_route = (
        previous_route
        if (
            previous_route is not None
            and previous_route.get("intersection_route_node_id") is not None
        )
        else None
    )

    outgoing_intersection_route = (
        route
        if (
            next_route is not None
            and route.get("intersection_route_node_id") is not None
        )
        else None
    )

    is_inside_incoming_intersection = (
        incoming_intersection_route is not None
        and incoming_intersection_route.get(
            "intersection_latitude"
        ) is not None
        and incoming_intersection_route.get(
            "intersection_longitude"
        ) is not None
        and incoming_intersection_route.get(
            "intersection_diameter_ft"
        ) is not None
        and not is_outside_intersection_radius(
            incoming_intersection_route,
            message["latitude"],
            message["longitude"],
        )
    )

    is_inside_outgoing_intersection = (
        outgoing_intersection_route is not None
        and outgoing_intersection_route.get(
            "intersection_latitude"
        ) is not None
        and outgoing_intersection_route.get(
            "intersection_longitude"
        ) is not None
        and outgoing_intersection_route.get(
            "intersection_diameter_ft"
        ) is not None
        and not is_outside_intersection_radius(
            outgoing_intersection_route,
            message["latitude"],
            message["longitude"],
        )
    )

    is_inside_intersection_radius = (
        is_inside_incoming_intersection
        or is_inside_outgoing_intersection
    )

    route_id = route["route_id"]

    previous_route_id = (
        previous_route["route_id"]
        if previous_route is not None
        else None
    )

    final_route = route_ranges[-1]

    is_final_route_exit = (
        route_id == final_route["route_id"]
        and int(mission_sequence)
        == final_route["end_mission_sequence"]
    )

    current_route_state = (
        "exited"
        if is_final_route_exit
        else "active"
    )

    current_route_exit_time = (
        message["observed_at"]
        if is_final_route_exit
        else None
    )

    segment_mission_sequences = route.get(
        "segment_mission_sequences"
    )

    is_last_route_segment = (
        isinstance(segment_mission_sequences, list)
        and bool(segment_mission_sequences)
        and int(mission_sequence)
        == segment_mission_sequences[-1]
    )

    managed_route_node_id = None

    if is_last_route_segment:
        managed_route_node_id = (
            get_managed_intersection_route_node(
                route,
                next_route,
            )
        )

    is_incoming_clearance_candidate = (
        incoming_intersection_route is not None
        and not is_inside_incoming_intersection
        and incoming_intersection_route.get(
            "intersection_latitude"
        ) is not None
        and incoming_intersection_route.get(
            "intersection_longitude"
        ) is not None
        and incoming_intersection_route.get(
            "intersection_diameter_ft"
        ) is not None
    )

    if (
        not is_final_route_exit
        and not is_inside_intersection_radius
        and not is_incoming_clearance_candidate
        and isinstance(segment_mission_sequences, list)
        and segment_mission_sequences
        and int(mission_sequence)
        not in segment_mission_sequences
    ):
        return

    last_processed_segment_sequence = route.get(
        "_last_processed_segment_sequence"
    )

    if (
        last_processed_segment_sequence is not None
        and last_processed_segment_sequence
        == int(mission_sequence)
        and not is_inside_intersection_radius
        and not is_incoming_clearance_candidate
    ):
        return

    is_new_segment_sequence = (
        last_processed_segment_sequence is None
        or last_processed_segment_sequence != int(mission_sequence)
    )

    intersection_occupancy = None

    with engine.begin() as connection:

        if managed_route_node_id is not None:
            intersection_occupancy = (
                select_route_occupancy_state(
                    connection,
                    route_id=route_id,
                    flight_execution_id=flight_execution_id,
                )
            )

        incoming_route_node_id = None

        if incoming_intersection_route is not None:
            incoming_route_node_id = (
                incoming_intersection_route.get(
                    "intersection_route_node_id"
                )
            )

        intersection_from_route = None
        intersection_to_route = None

        outgoing_route_node_id = None

        if outgoing_intersection_route is not None:
            outgoing_route_node_id = (
                outgoing_intersection_route.get(
                    "intersection_route_node_id"
                )
            )

        if incoming_route_node_id is not None:
            intersection_from_route = previous_route
            intersection_to_route = route

        if (
            is_new_segment_sequence
            and managed_route_node_id is not None
            and intersection_occupancy is not None
        ):
            intersection_state_id = reserve_intersection_slot(
                connection,
                route_node_id=managed_route_node_id,
                flight_band_id=intersection_occupancy[
                    "flight_band_id"
                ],
                assigned_relative_altitude_ft=int(
                    intersection_occupancy[
                        "assigned_relative_altitude_ft"
                    ]
                ),
                flight_execution_id=flight_execution_id,
                from_route_id=route["route_id"],
                to_route_id=next_route["route_id"],
            )

            if intersection_state_id is not None:
                LOGGER.info(
                    "Managed intersection reserved: "
                    "flight_execution_id=%s "
                    "route_node_id=%s "
                    "from_route_id=%s "
                    "to_route_id=%s "
                    "intersection_state_id=%s",
                    flight_execution_id,
                    managed_route_node_id,
                    route["route_id"],
                    next_route["route_id"],
                    intersection_state_id,
                )

        outgoing_occupancy = intersection_occupancy

        if (
            outgoing_occupancy is None
            and outgoing_route_node_id is not None
            and is_inside_outgoing_intersection
        ):
            outgoing_occupancy = select_route_occupancy_state(
                connection,
                route_id=route_id,
                flight_execution_id=flight_execution_id,
            )

        outgoing_intersection_state = None

        if (
            outgoing_occupancy is not None
            and is_inside_outgoing_intersection
        ):
            outgoing_intersection_state = select_intersection_state(
                connection,
                route_node_id=outgoing_route_node_id,
                flight_band_id=outgoing_occupancy["flight_band_id"],
                assigned_relative_altitude_ft=int(
                    outgoing_occupancy[
                        "assigned_relative_altitude_ft"
                    ]
                ),
            )

        outgoing_reserved_state_id = None

        if (
            outgoing_intersection_state is not None
            and outgoing_intersection_state["state"] == "reserved"
            and str(outgoing_intersection_state["flight_execution_id"])
            == str(flight_execution_id)
            and str(outgoing_intersection_state["from_route_id"])
            == str(route["route_id"])
            and str(outgoing_intersection_state["to_route_id"])
            == str(next_route["route_id"])
        ):
            outgoing_reserved_state_id = (
                outgoing_intersection_state["intersection_state_id"]
            )

        if outgoing_reserved_state_id is not None:
            occupied_state_id = occupy_intersection_slot(
                connection,
                intersection_state_id=outgoing_reserved_state_id,
                flight_execution_id=flight_execution_id,
            )

            if occupied_state_id is not None:
                LOGGER.info(
                    "Managed outgoing intersection occupied: "
                    "flight_execution_id=%s "
                    "intersection_state_id=%s "
                    "latitude=%.8f longitude=%.8f "
                    "distance_ft=%.2f radius_ft=%.2f",
                    flight_execution_id,
                    occupied_state_id,
                    message["latitude"],
                    message["longitude"],
                    distance_between_coordinates_ft(
                        message["latitude"],
                        message["longitude"],
                        outgoing_intersection_route["intersection_latitude"],
                        outgoing_intersection_route["intersection_longitude"],
                    ),
                    outgoing_intersection_route["intersection_diameter_ft"] / 2.0,
                )

        previous_occupancy = None
        previous_intersection_state_id = None
        intersection_state = None

        if (
            incoming_route_node_id is not None
            and intersection_from_route is not None
            and intersection_to_route is not None
            and (
                is_inside_incoming_intersection
                or is_incoming_clearance_candidate
            )
        ):
            previous_occupancy = select_route_occupancy_state(
                connection,
                route_id=intersection_from_route["route_id"],
                flight_execution_id=flight_execution_id,
            )

            if previous_occupancy is not None:
                intersection_state = select_intersection_state(
                    connection,
                    route_node_id=incoming_route_node_id,
                    flight_band_id=previous_occupancy["flight_band_id"],
                    assigned_relative_altitude_ft=int(
                        previous_occupancy[
                            "assigned_relative_altitude_ft"
                        ]
                    ),
                )

                if (
                    intersection_state is not None
                    and intersection_state["state"] == "reserved"
                    and str(intersection_state["flight_execution_id"])
                    == str(flight_execution_id)
                    and str(intersection_state["from_route_id"])
                    == str(intersection_from_route["route_id"])
                    and str(intersection_state["to_route_id"])
                    == str(intersection_to_route["route_id"])
                ):
                    previous_intersection_state_id = (
                        intersection_state["intersection_state_id"]
                    )

        if (
            previous_intersection_state_id is not None
            and is_inside_incoming_intersection
        ):
            occupied_intersection_state_id = (
                occupy_intersection_slot(
                    connection,
                    intersection_state_id=(
                        previous_intersection_state_id
                    ),
                    flight_execution_id=flight_execution_id,
                )
            )

            if occupied_intersection_state_id is not None:
                intersection_state = dict(intersection_state)
                intersection_state["state"] = "occupied"

                LOGGER.info(
                    "Managed intersection occupied: "
                    "flight_execution_id=%s "
                    "intersection_state_id=%s "
                    "latitude=%.8f longitude=%.8f "
                    "distance_ft=%.2f radius_ft=%.2f",
                    flight_execution_id,
                    occupied_intersection_state_id,
                    message["latitude"],
                    message["longitude"],
                    distance_between_coordinates_ft(
                        message["latitude"],
                        message["longitude"],
                        incoming_intersection_route[
                            "intersection_latitude"
                        ],
                        incoming_intersection_route[
                            "intersection_longitude"
                        ],
                    ),
                    incoming_intersection_route[
                        "intersection_diameter_ft"
                    ] / 2.0,
                )

        occupied_intersection_state_id = None

        if (
            incoming_route_node_id is not None
            and intersection_from_route is not None
            and intersection_to_route is not None
            and previous_occupancy is not None
        ):
            if (
                intersection_state is not None
                and intersection_state["state"] == "occupied"
                and str(intersection_state["flight_execution_id"])
                == str(flight_execution_id)
                and str(intersection_state["from_route_id"])
                == str(intersection_from_route["route_id"])
                and str(intersection_state["to_route_id"])
                == str(intersection_to_route["route_id"])
            ):
                occupied_intersection_state_id = (
                    intersection_state["intersection_state_id"]
                )

        segment_mission_sequences = route.get(
            "segment_mission_sequences"
        )

        is_beyond_intersection = (
            occupied_intersection_state_id is not None
            and is_incoming_clearance_candidate
            and previous_route is not None
            and route is intersection_to_route
        )

        if is_beyond_intersection:
            cleared_intersection_state_id = (
                clear_intersection_slot(
                    connection,
                    intersection_state_id=(
                        occupied_intersection_state_id
                    ),
                    flight_execution_id=flight_execution_id,
                )
            )

            if cleared_intersection_state_id is not None:
                LOGGER.info(
                    "Managed intersection cleared: "
                    "flight_execution_id=%s "
                    "intersection_state_id=%s "
                    "latitude=%.8f longitude=%.8f "
                    "distance_ft=%.2f radius_ft=%.2f",
                    flight_execution_id,
                    cleared_intersection_state_id,
                    message["latitude"],
                    message["longitude"],
                    distance_between_coordinates_ft(
                        message["latitude"],
                        message["longitude"],
                        incoming_intersection_route[
                            "intersection_latitude"
                        ],
                        incoming_intersection_route[
                            "intersection_longitude"
                        ],
                    ),
                    incoming_intersection_route[
                        "intersection_diameter_ft"
                    ] / 2.0,
                )

        if is_new_segment_sequence and previous_route_id is not None:
            update_route_occupancy_state(
                connection,
                route_id=previous_route_id,
                flight_execution_id=flight_execution_id,
                actual_exit_time=message["observed_at"],
                last_state_change_at=message["observed_at"],
                state="exited",
            )

        if is_new_segment_sequence:
            update_route_occupancy_state(
                connection,
                route_id=route_id,
                flight_execution_id=flight_execution_id,
                actual_entry_time=message["observed_at"],
                actual_exit_time=current_route_exit_time,
                last_latitude=message["latitude"],
                last_longitude=message["longitude"],
                last_altitude_ft=message["relative_altitude_ft"],
                last_state_change_at=message["observed_at"],
                state=current_route_state,
            )


    route["_last_processed_segment_sequence"] = int(
        mission_sequence
    )

    return



if __name__ == "__main__":
    main()

