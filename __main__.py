"""Command-line launcher for NAVProxy."""

from __future__ import annotations

import argparse
import logging

from .execution_service import run_navproxy_process
from .reusable_execution_service import run_reusable_navproxy_process
from .settings import DEFAULT_FLIGHT_SECONDS, DEFAULT_PREFLIGHT_SECONDS


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the DroneNav NAVProxy flight process.",
    )
    parser.add_argument(
        "--flight-execution-id",
        required=True,
        help="Flight Execution UUID.",
    )
    parser.add_argument(
        "--flight-id",
        required=True,
        help="Flight UUID created during claim.",
    )
    parser.add_argument(
        "--preflight-seconds",
        type=int,
        default=DEFAULT_PREFLIGHT_SECONDS,
        help=f"Pre-flight wait in seconds. Default: {DEFAULT_PREFLIGHT_SECONDS}.",
    )
    parser.add_argument(
        "--flight-seconds",
        type=int,
        default=DEFAULT_FLIGHT_SECONDS,
        help=f"In-flight wait in seconds. Default: {DEFAULT_FLIGHT_SECONDS}.",
    )
    parser.add_argument(
        "--execution-mode",
        choices=("scheduled", "reusable"),
        default="scheduled",
        help="NAVProxy execution profile. Default: scheduled.",
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    logging.getLogger("pika").setLevel(logging.WARNING)

    arguments = _parse_arguments()

    if arguments.execution_mode == "reusable":
        run_reusable_navproxy_process(
            flight_execution_id=arguments.flight_execution_id,
            flight_id=arguments.flight_id,
            preflight_seconds=arguments.preflight_seconds,
            flight_seconds=arguments.flight_seconds,
        )
    else:
        run_navproxy_process(
            flight_execution_id=arguments.flight_execution_id,
            flight_id=arguments.flight_id,
            preflight_seconds=arguments.preflight_seconds,
            flight_seconds=arguments.flight_seconds,
        )

if __name__ == "__main__":
    main()

