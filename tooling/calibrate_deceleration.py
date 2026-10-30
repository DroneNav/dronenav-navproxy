"""Measure X-500 deceleration using ArduPilot SITL telemetry."""

import argparse
import math
import time

import json
import ssl

import pika

from pymavlink import mavutil

from app.navproxy.tooling.fer_compiler import (
    load_aircraft,
    load_flight_execution,
    resolve_mission_altitude_band,
    build_launch_position_assertion,
    build_operational_route_assertions,
    build_route_assertions,
    build_route_conformance_segments,
)

from app.navproxy.tooling.mavlink_connection import (
    connect_to_ardupilot,
)

from app.navproxy.mavlink_telemetry import (
    request_ground_speed,
    request_message_interval,
)

from app.navproxy.telemetry_publisher import (
    RABBITMQ_HOST,
    RABBITMQ_PORT,
    RABBITMQ_VHOST,
    get_rabbitmq_credentials,
)


def calculate_ground_speed_ft_s(message) -> float:
    """Calculate horizontal ground speed from MAVLink telemetry."""

    velocity_m_s = math.hypot(
        message.vx,
        message.vy,
    ) / 100.0

    return velocity_m_s / 0.3048


def collect_ground_speed_samples(
    connection: mavutil.mavfile,
    duration_seconds: float,
) -> list[tuple[float, float]]:
    """Collect timestamped ground-speed samples from SITL."""

    samples = []
    start_time = time.monotonic()

    while time.monotonic() - start_time < duration_seconds:
        message = connection.recv_match(
            type="GLOBAL_POSITION_INT",
            blocking=True,
            timeout=0.5,
        )

        if message is None:
            continue

        elapsed_seconds = time.monotonic() - start_time
        speed_ft_s = calculate_ground_speed_ft_s(message)

        samples.append((elapsed_seconds, speed_ft_s))

    return samples


def calculate_average_deceleration(
    initial_speed_ft_s: float,
    final_speed_ft_s: float,
    elapsed_seconds: float,
) -> float:
    """Calculate average deceleration in ft/s²."""

    if elapsed_seconds <= 0:
        raise ValueError("Elapsed time must be positive.")

    if final_speed_ft_s > initial_speed_ft_s:
        raise ValueError("Final speed exceeds initial speed.")

    return (
        initial_speed_ft_s - final_speed_ft_s
    ) / elapsed_seconds


def command_target_ground_speed(
    connection: mavutil.mavfile,
    target_speed_ft_s: float,
) -> None:
    """Request a target ground speed from ArduPilot."""

    if target_speed_ft_s <= 0:
        raise ValueError("Target ground speed must be positive.")

    request_ground_speed(
        connection,
        speed_m_s=target_speed_ft_s * 0.3048,
    )


def measure_deceleration(
    connection: mavutil.mavfile,
    duration_seconds: float = 10.0,
) -> list[tuple[float, float]]:
    """Collect ground-speed samples during a calibration maneuver."""

    return collect_ground_speed_samples(
        connection,
        duration_seconds,
    )


def wait_for_cruise_speed(
    connection: mavutil.mavfile,
    cruise_speed_ft_s: float,
    tolerance_ft_s: float = 1.0,
    timeout_seconds: float = 60.0,
) -> bool:
    """Wait until ground speed reaches the cruise-speed range."""

    start_time = time.monotonic()
    consecutive_samples = 0

    while time.monotonic() - start_time < timeout_seconds:
        message = connection.recv_match(
            type="GLOBAL_POSITION_INT",
            blocking=True,
            timeout=0.5,
        )

        if message is None:
            continue

        speed_ft_s = calculate_ground_speed_ft_s(message)

        if abs(speed_ft_s - cruise_speed_ft_s) <= tolerance_ft_s:
            consecutive_samples += 1

            if consecutive_samples >= 15:
                return True
        else:
            consecutive_samples = 0

    return False


def calculate_segment_progress(
    latitude: float,
    longitude: float,
    start_latitude: float,
    start_longitude: float,
    end_latitude: float,
    end_longitude: float,
) -> float:
    """Calculate projected progress along a straight Route segment."""

    latitude_scale = math.cos(
        math.radians((start_latitude + end_latitude) / 2.0)
    )

    dx = (end_longitude - start_longitude) * latitude_scale
    dy = end_latitude - start_latitude

    px = (longitude - start_longitude) * latitude_scale
    py = latitude - start_latitude

    segment_length_squared = dx * dx + dy * dy

    if segment_length_squared == 0:
        raise ValueError("Segment endpoints must differ.")

    return (px * dx + py * dy) / segment_length_squared


def get_segment_coordinates(
    segment: dict,
) -> tuple[float, float, float, float]:
    """Return operational segment endpoints in latitude/longitude order."""

    start_longitude, start_latitude = segment[
        "operational_start_coordinate"
    ]

    end_longitude, end_latitude = segment[
        "operational_end_coordinate"
    ]

    return (
        start_latitude,
        start_longitude,
        end_latitude,
        end_longitude,
    )


def calculate_segment_length_ft(
    segment: dict,
) -> float:
    """Calculate the length of an operational Route segment in feet."""

    (
        start_latitude,
        start_longitude,
        end_latitude,
        end_longitude,
    ) = get_segment_coordinates(segment)

    feet_per_degree_lat, feet_per_degree_lon = (
        get_feet_per_degree(
            (start_latitude + end_latitude) / 2.0
        )
    )

    east_ft = (
        end_longitude - start_longitude
    ) * feet_per_degree_lon

    north_ft = (
        end_latitude - start_latitude
    ) * feet_per_degree_lat

    return math.hypot(
        east_ft,
        north_ft,
    )


def select_calibration_segment(
    route_segments: list[dict],
) -> dict:
    if not route_segments:
        raise ValueError(
            "No Route segments available for deceleration calibration."
        )

    return max(
        route_segments,
        key=calculate_segment_length_ft,
    )


def get_calibration_segment_progress(
    message,
    segment: dict,
) -> float:
    """Calculate aircraft progress along an operational Route segment."""

    (
        start_latitude,
        start_longitude,
        end_latitude,
        end_longitude,
    ) = get_segment_coordinates(segment)

    return calculate_segment_progress(
        latitude=message.lat / 1e7,
        longitude=message.lon / 1e7,
        start_latitude=start_latitude,
        start_longitude=start_longitude,
        end_latitude=end_latitude,
        end_longitude=end_longitude,
    )

def wait_for_calibration_segment(
    connection: mavutil.mavfile,
    segment: dict,
    timeout_seconds: float = 180.0,
) -> bool:
    """Wait for the aircraft to enter the calibration window."""

    start_time = time.monotonic()

    (
        start_latitude,
        start_longitude,
        end_latitude,
        end_longitude,
    ) = get_segment_coordinates(segment)

    while time.monotonic() - start_time < timeout_seconds:
        message = connection.recv_match(
            type="GLOBAL_POSITION_INT",
            blocking=True,
            timeout=0.5,
        )

        if message is None:
            continue

        progress = get_calibration_segment_progress(
            message,
            segment,
        )

        cross_track_ft = calculate_segment_cross_track_ft(
            latitude=message.lat / 1e7,
            longitude=message.lon / 1e7,
            start_latitude=start_latitude,
            start_longitude=start_longitude,
            end_latitude=end_latitude,
            end_longitude=end_longitude,
        )

        if (
            0.05 <= progress <= 0.20
            and cross_track_ft <= 30.0
        ):
            print(
                f"Calibration segment progress: {progress:.1%}"
            )
            return True

    return False


def verify_calibration_position(
    connection: mavutil.mavfile,
) -> bool:
    """Verify sufficient straight-line distance remains."""

    (
        start_latitude,
        start_longitude,
        end_latitude,
        end_longitude,
    ) = get_segment_coordinates(segment)

    message = connection.recv_match(
        type="GLOBAL_POSITION_INT",
        blocking=True,
        timeout=1.0,
    )

    if message is None:
        return False

    progress = get_calibration_segment_progress(
        message,
        segment,
    )

    cross_track_ft = calculate_segment_cross_track_ft(
        latitude=message.lat / 1e7,
        longitude=message.lon / 1e7,
        start_latitude=start_latitude,
        start_longitude=start_longitude,
        end_latitude=end_latitude,
        end_longitude=end_longitude,
    )

    feet_per_degree_lat, feet_per_degree_lon = (
        get_feet_per_degree(
            (start_latitude + end_latitude) / 2.0
        )
    )

    east_ft = (
        end_longitude - start_longitude
    ) * feet_per_degree_lon

    north_ft = (
        end_latitude - start_latitude
    ) * feet_per_degree_lat

    segment_length_ft = math.hypot(
        east_ft,
        north_ft,
    )

    if segment_length_ft <= 0.0:
        return False

    remaining_ft = (1.0 - progress) * segment_length_ft

    print(f"Segment progress: {progress:.1%}")
    print(f"Remaining distance: {remaining_ft:.1f} ft")

    east_unit = east_ft / segment_length_ft
    north_unit = north_ft / segment_length_ft

    forward_speed_ft_s = (
        message.vx * north_unit
        + message.vy * east_unit
    ) / 100.0 / 0.3048

    print(f"Forward speed: {forward_speed_ft_s:.2f} ft/s")

    return (
        0.05 <= progress <= 0.50
        and cross_track_ft <= 30.0
        and remaining_ft >= 500.0
        and forward_speed_ft_s > 0.0
    )


def get_feet_per_degree(
    latitude: float,
) -> tuple[float, float]:
    """Return WGS-84 feet per degree of latitude and longitude."""

    latitude_radians = math.radians(latitude)

    feet_per_degree_lat = (
        111132.92
        - 559.82 * math.cos(2.0 * latitude_radians)
        + 1.175 * math.cos(4.0 * latitude_radians)
        - 0.0023 * math.cos(6.0 * latitude_radians)
    ) / 0.3048

    feet_per_degree_lon = (
        111412.84 * math.cos(latitude_radians)
        - 93.5 * math.cos(3.0 * latitude_radians)
        + 0.118 * math.cos(5.0 * latitude_radians)
    ) / 0.3048

    return feet_per_degree_lat, feet_per_degree_lon


def calculate_segment_cross_track_ft(
    latitude: float,
    longitude: float,
    start_latitude: float,
    start_longitude: float,
    end_latitude: float,
    end_longitude: float,
) -> float:
    """Calculate perpendicular distance from a segment in feet."""

    feet_per_degree_lat, feet_per_degree_lon = (
        get_feet_per_degree(
            (start_latitude + end_latitude) / 2.0
        )
    )

    dx = (
        end_longitude - start_longitude
    ) * feet_per_degree_lon

    dy = (
        end_latitude - start_latitude
    ) * feet_per_degree_lat

    px = (
        longitude - start_longitude
    ) * feet_per_degree_lon

    py = (
        latitude - start_latitude
    ) * feet_per_degree_lat

    segment_length = math.hypot(dx, dy)

    if segment_length == 0:
        raise ValueError("Segment endpoints must differ.")

    return abs(dx * py - dy * px) / segment_length


def publish_calibration_request(
    flight_execution_id: str,
    segment: dict,
    target_speed_ft_s: float,
) -> None:
    """Request a calibration maneuver from NAVProxy."""

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

    try:
        channel = connection.channel()

        message = {
            "message_type": "calibration.request",
            "flight_execution_id": str(flight_execution_id),
            "payload": {
                "route_id": str(segment["route_id"]),
                "route_segment_index": segment["route_segment_index"],
                "target_speed_ft_s": target_speed_ft_s,
            },
        }

        channel.basic_publish(
            exchange="dronenav.control",
            routing_key=f"navproxy.{flight_execution_id}",
            body=json.dumps(message),
            properties=pika.BasicProperties(
                content_type="application/json",
                delivery_mode=2,
            ),
        )

    finally:
        connection.close()


def parse_arguments() -> argparse.Namespace:
    """Parse calibration command-line arguments."""

    parser = argparse.ArgumentParser(
        description="Measure aircraft deceleration using ArduPilot SITL."
    )

    parser.add_argument(
        "--connection",
        required=True,
        help="pymavlink connection string.",
    )

    parser.add_argument(
        "--flight-execution-id",
        required=True,
        help="Flight Execution ID used to retrieve calibration data.",
    )

    parser.add_argument(
        "--source-system",
        type=int,
        default=255,
    )

    parser.add_argument(
        "--source-component",
        type=int,
        default=190,
    )

    parser.add_argument(
        "--heartbeat-timeout",
        type=float,
        default=15.0,
    )

    parser.add_argument(
        "--target-speed-ft-s",
        type=float,
        default=10.0,
        help="Target ground speed in ft/s. Default: 10.",
    )

    return parser.parse_args()


def confirm_deceleration() -> bool:
    """Require operator confirmation before calibration."""

    response = input(
        "Enter YES to enable deceleration calibration: "
    )

    return response.strip() == "YES"


if __name__ == "__main__":
    args = parse_arguments()

    flight_execution = load_flight_execution(
        args.flight_execution_id,
    )

    print(
        "Loaded Flight Execution:",
        args.flight_execution_id,
    )

    aircraft = load_aircraft(
        flight_execution["aircraft_id"],
    )

    print(
        "Loaded Aircraft:",
        flight_execution["aircraft_id"],
    )

    (
        flight_band_id,
        minimum_agl_ft,
        maximum_agl_ft,
        commanded_cruise_speed_ft_s,
    ) = resolve_mission_altitude_band(
        flight_execution,
    )

    print(
        "Flight Band cruise speed:",
        commanded_cruise_speed_ft_s,
        "ft/s",
    )

    launch_assertion = build_launch_position_assertion(
        flight_execution,
    )

    departure_route_node_id = launch_assertion["parameters"].get(
        "route_node_id"
    )

    route_assertions = build_route_assertions(
        flight_execution,
    )

    if route_assertions and not departure_route_node_id:
        raise ValueError(
            "A Route Flight Execution requires a departure Route Node."
        )

    route_assertions = build_operational_route_assertions(
        route_assertions=route_assertions,
        departure_route_node_id=departure_route_node_id,
    )

    route_segments = build_route_conformance_segments(
        route_assertions=route_assertions,
        side="right",
    )

    print("Compiled Route segments:", len(route_segments))

    calibration_segment = select_calibration_segment(route_segments)

    print(
        "Selected calibration segment:",
        calibration_segment["route_id"],
        "segment",
        calibration_segment["route_segment_index"],
        "length:",
        round(calculate_segment_length_ft(calibration_segment), 1),
        "ft",
    )

    connection = connect_to_ardupilot(
        args.connection,
        source_system=args.source_system,
        source_component=args.source_component,
        heartbeat_timeout=args.heartbeat_timeout,
    )

    try:
        request_message_interval(
            connection,
            message_id=mavutil.mavlink.MAVLINK_MSG_ID_GLOBAL_POSITION_INT,
            frequency_hz=5.0,
        )

        if not confirm_deceleration():
            print("Calibration cancelled.")
            raise SystemExit(0)

        print("Waiting to enter selected calibration segment...")

        if not wait_for_calibration_segment(
            connection,
            calibration_segment,
        ):
            print("Calibration aborted: selected segment not detected.")
            raise SystemExit(1)

        print("Calibration segment detected.")
        print(
            "Waiting for stable cruise speed at",
            commanded_cruise_speed_ft_s,
            "ft/s...",
        )

        if not wait_for_cruise_speed(
            connection,
            cruise_speed_ft_s=commanded_cruise_speed_ft_s,
        ):
            print("Calibration aborted: stable cruise speed not detected.")
            raise SystemExit(1)

        if not verify_calibration_position(
            connection,
            calibration_segment,
        ):
            print(
                "Calibration aborted: insufficient "
                "straight-line distance remaining."
            )
            raise SystemExit(1)

        samples = measure_deceleration(
            connection,
        )

        for elapsed_seconds, speed_ft_s in samples:
            print(
                f"{elapsed_seconds:.2f}s  "
                f"{speed_ft_s:.2f} ft/s"
            )

        print(f"Collected {len(samples)} samples.")

    finally:
        connection.close()


