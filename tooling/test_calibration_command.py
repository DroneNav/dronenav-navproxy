
from pymavlink import mavutil


def main():
    connection = mavutil.mavlink_connection(
        "tcp:127.0.0.1:15763",
        source_system=255,
        source_component=191,
    )

    try:
        heartbeat = connection.wait_heartbeat(timeout=10)

        if heartbeat is None:
            raise RuntimeError("No ArduPilot heartbeat received")

        print("Heartbeat received.")

        connection.mav.command_long_send(
            connection.target_system,
            connection.target_component,
            mavutil.mavlink.MAV_CMD_REQUEST_MESSAGE,
            0,
            mavutil.mavlink.MAVLINK_MSG_ID_AUTOPILOT_VERSION,
            0, 0, 0, 0, 0, 0,
        )

        print("Waiting for COMMAND_ACK...")

        response = connection.recv_match(
            type="COMMAND_ACK",
            blocking=True,
            timeout=5,
        )

        print("COMMAND_ACK:", response)

    finally:
        connection.close()


if __name__ == "__main__":
    main()

