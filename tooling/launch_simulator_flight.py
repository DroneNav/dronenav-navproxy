from __future__ import annotations

import argparse
import logging

from app.models.flight_execution_model import (
    select_flight_execution, 
)

from app.services.flight_execution_service import (
    launch_scheduled_flight_execution,
)


LOGGER = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Manually launch a scheduled Flight Execution "
            "using the NAVProxy simulator."
        ),
    )

    parser.add_argument(
        "--flight-execution-id",
        required=True,
        help="Scheduled Flight Execution UUID.",
    )

    args = parser.parse_args()

    flight_execution = select_flight_execution(
        args.flight_execution_id
    )

    if flight_execution is None:
        raise RuntimeError(
            "Flight Execution was not found."
        )

    response, status_code = launch_scheduled_flight_execution(
        flight_execution["flight_execution_id"],
        flight_execution["aviator_id"],
        flight_execution["aircraft_id"],
        navproxy_fc_mode="simulator",
    )

    if status_code != 200:
        raise RuntimeError(
            f"Simulator launch failed: {response}"
        )

    LOGGER.info(
        "Simulator Flight launched: execution=%s flight=%s",
        response["flight_execution_id"],
        response["flight_id"],
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    main()

