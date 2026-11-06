import socket
import threading


UDP_HOST = "127.0.0.1"
UDP_PORT = 14552

TCP_HOST = "127.0.0.1"
TCP_PORT = 5773


def handle_client(client, udp_socket, state, lock):
    try:
        while True:
            data = client.recv(4096)

            if not data:
                break

            with lock:
                mavproxy_address = state["mavproxy_address"]

            if mavproxy_address is None:
                print(
                    "MAVProxy sender address not yet available.",
                    flush=True,
                )
                continue

            udp_socket.sendto(data, mavproxy_address)

    except OSError as error:
        print(f"Calibration connection error: {error}", flush=True)
    finally:
        with lock:
            if state["client"] is client:
                state["client"] = None

        client.close()


def receive_udp(udp_socket, state, lock):
    while True:
        data, sender_address = udp_socket.recvfrom(4096)

        with lock:
            if state["mavproxy_address"] != sender_address:
                state["mavproxy_address"] = sender_address
                print(
                    f"MAVProxy UDP sender: {sender_address}",
                    flush=True,
                )

            client = state["client"]

        if client is not None:
            try:
                client.sendall(data)
            except OSError:
                with lock:
                    if state["client"] is client:
                        state["client"] = None

                client.close()


def main():
    udp_socket = socket.socket(
        socket.AF_INET,
        socket.SOCK_DGRAM,
    )
    udp_socket.bind((UDP_HOST, UDP_PORT))

    server = socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM,
    )
    server.setsockopt(
        socket.SOL_SOCKET,
        socket.SO_REUSEADDR,
        1,
    )
    server.bind((TCP_HOST, TCP_PORT))
    server.listen(5)

    state = {
        "client": None,
        "mavproxy_address": None,
    }
    lock = threading.Lock()

    threading.Thread(
        target=receive_udp,
        args=(udp_socket, state, lock),
        daemon=True,
    ).start()

    print(
        f"Calibration relay listening on TCP {TCP_PORT}",
        flush=True,
    )

    while True:
        client, address = server.accept()

        print(
            f"Calibration client connected: {address}",
            flush=True,
        )

        with lock:
            previous_client = state["client"]
            state["client"] = client

        if previous_client is not None:
            previous_client.close()

        threading.Thread(
            target=handle_client,
            args=(client, udp_socket, state, lock),
            daemon=True,
        ).start()


if __name__ == "__main__":
    main()


