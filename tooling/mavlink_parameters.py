"""Read and write ArduPilot parameters using MAVLink."""

from __future__ import annotations

from typing import Any

from pymavlink import mavutil

import time


class MAVLinkParameterError(RuntimeError):
    """Raised when a MAVLink parameter operation fails."""


def wait_for_parameter(
    connection: mavutil.mavfile,
    parameter_name: str,
    *,
    timeout_seconds: float,
) -> Any:
    """Wait for the requested PARAM_VALUE response."""

    deadline = time.monotonic() + timeout_seconds

    while True:
        remaining_seconds = deadline - time.monotonic()

        if remaining_seconds <= 0:
            raise MAVLinkParameterError(
                f"Timed out waiting for parameter '{parameter_name}'."
            )

        response = connection.recv_match(
            type="PARAM_VALUE",
            blocking=True,
            timeout=remaining_seconds,
        )

        if response is None:
            raise MAVLinkParameterError(
                f"Timed out waiting for parameter '{parameter_name}'."
            )

        response_name = response.param_id

        if isinstance(response_name, bytes):
            response_name = response_name.decode("ascii")

        response_name = response_name.rstrip("\x00")

        if response_name != parameter_name:
            continue

        return response


def read_parameter(
    connection: mavutil.mavfile,
    parameter_name: str,
    *,
    timeout_seconds: float = 5.0,
) -> Any:
    """Read one parameter from the connected flight controller."""

    parameter_id = parameter_name.encode("ascii")

    connection.mav.param_request_read_send(
        connection.target_system,
        connection.target_component,
        parameter_id,
        -1,
    )

    response = wait_for_parameter(
        connection,
        parameter_name,
        timeout_seconds=timeout_seconds,
    )

    return response.param_value


def set_parameter(
    connection: mavutil.mavfile,
    parameter_name: str,
    value: float,
    *,
    timeout_seconds: float = 5.0,
) -> float:
    """Set one parameter on the connected flight controller."""

    parameter_id = parameter_name.encode("ascii")

    connection.mav.param_set_send(
        connection.target_system,
        connection.target_component,
        parameter_id,
        float(value),
        mavutil.mavlink.MAV_PARAM_TYPE_REAL32,
    )

    response = wait_for_parameter(
        connection,
        parameter_name,
        timeout_seconds=timeout_seconds,
    )

    return response.param_value



def main() -> int:
    """Read one ArduPilot parameter from SITL."""

    connection = mavutil.mavlink_connection(
        "tcp:127.0.0.1:15762",
        autoreconnect=True,
    )

    heartbeat = connection.wait_heartbeat(
        timeout=10.0,
    )

    if heartbeat is None:
        raise MAVLinkParameterError(
            "Timed out waiting for an ArduPilot heartbeat."
        )

    set_value = set_parameter(
        connection,
        "FENCE_ENABLE",
        1.0,
        timeout_seconds=5.0,
    )

    print(
        f"FENCE_ENABLE set confirmation={set_value}"
    )

    read_value = read_parameter(
        connection,
        "FENCE_ENABLE",
        timeout_seconds=5.0,
    )

    print(
        f"FENCE_ENABLE readback={read_value}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

