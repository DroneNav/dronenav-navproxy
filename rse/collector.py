from __future__ import annotations

import json
import logging
import ssl

import pika

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
from app.models.route_occupancy_state_model import (
    update_route_occupancy_state,
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
                    requeue=True,
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

            return route, previous_route

    return None, None


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

    route, previous_route = get_route_for_mission_sequence(
        route_ranges,
        int(mission_sequence),
    )

    if route is None:
        return

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

    with engine.begin() as connection:
        if previous_route_id is not None:
            update_route_occupancy_state(
                connection,
                route_id=previous_route_id,
                flight_execution_id=flight_execution_id,
                actual_exit_time=message["observed_at"],
                state="exited",
            )

        update_route_occupancy_state(
            connection,
            route_id=route_id,
            flight_execution_id=flight_execution_id,
            actual_entry_time=message["observed_at"],
            actual_exit_time=current_route_exit_time,
            last_latitude=message["latitude"],
            last_longitude=message["longitude"],
            last_altitude_ft=message["relative_altitude_ft"],
            state=current_route_state,
        )

    return



if __name__ == "__main__":
    main()

