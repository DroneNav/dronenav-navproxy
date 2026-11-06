# DroneNav NAVProxy Calibration Environment Setup

## Purpose

This guide describes the **verified local ArduPilot SITL / MAVProxy calibration relay environment** used to communicate with the DroneNav server. It covers starting the relay, forwarding its connection through SSH, configuring MAVProxy, and validating bidirectional MAVLink communication.

## Architecture

```text
Local development environment (WSL)                DroneNav server

ArduPilot SITL
    |
    v
MAVProxy
    |  UDP output to 127.0.0.1:14552
    v
mavlink_calibration_relay.py
    |  TCP listener 127.0.0.1:5773
    |================ SSH reverse tunnel ================|
                                                         |
                                             127.0.0.1:15763 (TCP)
                                                         |
                                             Calibration MAVLink client
```

The relay is **bidirectional**: it forwards MAVProxy UDP datagrams to its connected TCP client and forwards TCP data back to the most recently observed MAVProxy UDP sender. It supports one active TCP client; a new client replaces the previous connection.

### Verified ports

| Purpose | Address / port | Notes |
|---|---|---|
| Original MAVLink tunnel, remote | `127.0.0.1:15762` | Forwards to local TCP `127.0.0.1:5762` |
| Calibration MAVProxy output | `127.0.0.1:14552` (UDP) | Sends MAVLink datagrams to the relay |
| Calibration relay listener | `127.0.0.1:5773` (TCP) | Defined in `mavlink_calibration_relay.py` |
| Calibration tunnel, remote | `127.0.0.1:15763` (TCP) | Forwards to local TCP `127.0.0.1:5773` |
| Calibration test client | `tcp:127.0.0.1:15763` | Used by `test_calibration_command.py` on server |

MAVProxy's UDP source port may be dynamically assigned (for example, `42729`). It does not need to equal `14552`.

## Prerequisites

- Local ArduPilot SITL and MAVProxy installation, already configured for the aircraft under test.
- Local Python 3 and the relay script at `~/projects/dronenav/mavlink_calibration_relay.py`.
- SSH access to `dronenavcp@api.dronenav.org`, with reverse port forwarding permitted.
- Server Python environment containing `pymavlink`, and the test script `app/navproxy/tooling/test_calibration_command.py`.
- Separate terminals for SITL/MAVProxy, the relay, the SSH tunnel, and the server test.

> The exact SITL launch command, aircraft frame, and any flight-specific calibration parameters are **not established by this guide**. Use the appropriate existing aircraft/SITL setup for those steps.

## Startup procedure

### 1. Start ArduPilot SITL and MAVProxy locally

Start the appropriate SITL vehicle and MAVProxy using your existing local startup procedure. Verify that MAVProxy is connected to the simulator before proceeding.

### 2. Start the local calibration relay

In a separate local WSL terminal:

```bash
python3 ~/projects/dronenav/mavlink_calibration_relay.py
```

Expected initial output:

```text
Calibration relay listening on TCP 5773
```

Keep this process running throughout calibration. The script binds UDP `127.0.0.1:14552` and TCP `127.0.0.1:5773`.

### 3. Configure MAVProxy's calibration output

At the **MAVProxy prompt**, inspect existing outputs:

```text
output
```

If `127.0.0.1:14552` is not already listed, add it:

```text
output add 127.0.0.1:14552
```

A verified output listing is:

```text
0: 172.22.48.1:14550
1: 127.0.0.1:14552
```

Once MAVProxy sends datagrams, the relay should print a message similar to:

```text
MAVProxy UDP sender: ('127.0.0.1', 42729)
```

The source port shown may differ.

### 4. Establish the SSH reverse tunnels

In another **local** terminal, run:

```bash
ssh -N \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -R 127.0.0.1:15762:127.0.0.1:5762 \
  -R 127.0.0.1:15763:127.0.0.1:5773 \
  dronenavcp@api.dronenav.org
```

The first mapping preserves the original MAVLink connection. The second exposes the local calibration relay to clients on the DroneNav server. Keep this SSH session running.

If the original `15762 → 5762` tunnel is **already established by another SSH session**, do not create a competing remote forward. Start only the missing calibration forward instead:

```bash
ssh -N \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -R 127.0.0.1:15763:127.0.0.1:5773 \
  dronenavcp@api.dronenav.org
```

### 5. Check the server-side TCP ports (optional)

The server environment may not have `ss` or `netstat`. Use Python 3:

```bash
python3 - <<'PY'
import socket

for port in (15762, 15763):
    with socket.socket() as sock:
        sock.settimeout(2)
        result = sock.connect_ex(("127.0.0.1", port))
        print(f"TCP {port}: {'reachable' if result == 0 else 'not reachable'}")
PY
```

Expected when both tunnels are listening:

```text
TCP 15762: reachable
TCP 15763: reachable
```

**Note:** A successful TCP connection confirms a listener is reachable; it does not by itself prove the end-to-end MAVLink path. Use the next test for that.

### 6. Verify bidirectional calibration communication

On the **DroneNav server**, from the application root with the appropriate Python environment active:

```bash
python3 app/navproxy/tooling/test_calibration_command.py
```

The test script:

1. Connects to `tcp:127.0.0.1:15763`.
2. Waits up to 10 seconds for an ArduPilot heartbeat.
3. Sends `MAV_CMD_REQUEST_MESSAGE` for `AUTOPILOT_VERSION`.
4. Waits up to 5 seconds for a `COMMAND_ACK`.
5. Closes its TCP connection.

Successful test output includes:

```text
Heartbeat received.
Waiting for COMMAND_ACK...
COMMAND_ACK: COMMAND_ACK {command : 512, result : 0, progress : 0, result_param2 : 0, target_system : 255, target_component : 191}
```

`command: 512` is `MAV_CMD_REQUEST_MESSAGE`; `result: 0` means `MAV_RESULT_ACCEPTED`. This verifies that the request and acknowledgment traveled through the relay path. The test does **not** arm the aircraft or initiate flight.

The local relay should also report:

```text
Calibration client connected: (...)
```

The test client disconnects when finished; that is expected.

## Troubleshooting

| Symptom | Check |
|---|---|
| Relay cannot bind UDP `14552` or TCP `5773` | Another local process may already own that port. Stop the duplicate process or identify the conflicting listener. |
| Relay prints no `MAVProxy UDP sender` | At MAVProxy's prompt, run `output`; confirm `127.0.0.1:14552` is present and SITL is sending MAVLink. |
| Remote TCP `15763` not reachable | Confirm the SSH reverse tunnel is still running and forwards `15763` to local `5773`. |
| SSH reports remote port forwarding failure | Check whether another tunnel already owns `15763`; avoid duplicate forwards. |
| Test connects but heartbeat times out | Check that SITL and MAVProxy are running, the `14552` output is configured, and the relay has detected a MAVProxy sender. |
| Test receives heartbeat but no `COMMAND_ACK` | Inspect the relay's client connection and MAVProxy/SITL messages; check that the request reaches the autopilot and the response returns. |
| README mentions `15772` | That is the separate multi-aircraft configuration, not this calibration relay. |

## Shutdown

After the test or calibration session, close the remote test client (the test script closes automatically), stop the SSH tunnel and local relay, and then stop MAVProxy/SITL as appropriate. Avoid interrupting a running flight or active calibration procedure.

## Scope and future documentation

This guide verifies **transport setup and connectivity**, not the full in-flight deceleration calibration workflow. Calibration flight creation, segment selection, commanded speed, operational readiness, convergence, and profile updates should be documented separately or added once their exact current procedure is verified.

### Verification record — November 6, 2026

- Relay source: UDP port `14552`, TCP port `5773`.
- MAVProxy outputs included `127.0.0.1:14552`.
- Remote ports `15762` and `15763` were reachable; `15772` was not.
- `test_calibration_command.py` used `tcp:127.0.0.1:15763`.
- The test received an accepted `COMMAND_ACK` for command `512`.

