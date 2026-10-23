# README_ArduPilot_SITL.md

# DroneNav ArduPilot SITL Test Environment

## Overview

This document describes the complete DroneNav development and testing environment used to validate NAVProxy against an ArduPilot Software-In-The-Loop (SITL) simulator.

The environment intentionally separates the DroneNav platform from the simulated aircraft. The DroneNav API and NAVProxy execute on the remote development server, while ArduPilot SITL executes locally on a Windows workstation running Ubuntu under WSL. An SSH reverse tunnel exposes the local simulated vehicle to the DroneNav server, allowing NAVProxy to communicate with the simulator exactly as it will communicate with a real flight controller.

This configuration provides a repeatable development environment for validating MAVLink mission generation, mission upload/download, compiler output, and future NAVProxy runtime behavior.

---

# Architecture

```text
                    Local Development Workstation
                  Windows + WSL Ubuntu Environment

    +-------------------------------------------------------+
    |                                                       |
    |                ArduPilot SITL                         |
    |                     TCP 5762                          |
    |                         │                             |
    |                         ▼                             |
    |                    MAVProxy                           |
    |                         │                             |
    |                         ▼                             |
    |                SSH Reverse Tunnel                     |
    |                         │                             |
    +-------------------------┼-----------------------------+
                              │
                              │
                         Internet (SSH)
                              │
                              ▼
    +-------------------------------------------------------+
    |                 api.dronenav.org                      |
    |                                                       |
    |          tcp://127.0.0.1:15762                        |
    |                                                       |
    |                  DroneNav API                         |
    |                  NAVProxy                             |
    |                                                       |
    |             upload_test_mission                       |
    |             download_test_mission                     |
    |             upload_mission                            |
    +-------------------------------------------------------+
```

---

# Connection Flow

1. ArduPilot SITL starts on the local workstation.
2. MAVProxy connects to the simulated vehicle.
3. An SSH reverse tunnel exposes the local MAVLink TCP endpoint.
4. The DroneNav server connects to the tunnel endpoint.
5. DroneNav tooling uploads and downloads missions through the tunnel.
6. NAVProxy can communicate with the simulated vehicle exactly as it will during production execution.

---

# System Requirements

## Local Development Workstation

* Windows
* Windows Subsystem for Linux (WSL)
* Ubuntu
* ArduPilot SITL
* MAVProxy
* Python virtual environment

## DroneNav Development Server

* Linux
* DroneNav API project
* Python environment
* SSH access

---

# Startup Procedure

## Step 1 – Start ArduPilot SITL

Activate the ArduPilot virtual environment.

```bash
source ~/venv-ardupilot/bin/activate
```

Start the simulator.

```bash
1. sim_vehicle.py -v ArduCopter --console --map -I 0 -l 34.077756274,-84.301123283,334.61,0
2. sim_vehicle.py -v ArduCopter --console --map -I 0 -l 34.077574102,-84.300110728,334.61,0
```

Wait until SITL has completely initialized before proceeding.

---

## Step 2 – Verify MAVProxy

At the MAVProxy prompt:

```text
status
```

Verify that the simulated vehicle is running normally.

---

## Step 3 – Establish the SSH Reverse Tunnel

Open a second WSL terminal.

Start the reverse tunnel.

```bash
ssh -N \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -R 127.0.0.1:15762:127.0.0.1:5762 \
    dronenavcp@api.dronenav.org
```

Leave this terminal running for the duration of testing.

This exposes the local SITL TCP endpoint on the DroneNav server as:

```text
tcp://127.0.0.1:15762
```

---

## Step 4 – Verify the Tunnel (Optional)

On the DroneNav server:

```bash
ss -ltn | grep 15762
```

or

```bash
nc -vz 127.0.0.1 15762
```

A successful connection confirms that the reverse tunnel is active.

---

# Upload a Test Mission

Execute:

```bash
python -m tooling.upload_test_mission \
    tooling/metadata/mavlink_commands.yaml \
    tooling/examples/waypoint.json \
    --connection tcp:127.0.0.1:15762 \
    --confirm-upload
```

Expected output:

```text
Heartbeat received
MISSION_COUNT
MISSION_REQUEST 0
MISSION_ITEM_INT 0
MISSION_ACK ACCEPTED
Stored mission count verified
SUCCESS
```

Successful completion confirms that DroneNav can upload MAVLink missions to the simulated vehicle.

---

# Download Mission Verification

Execute:

```bash
python -m tooling.download_test_mission \
    tooling/metadata/mavlink_commands.yaml \
    tooling/examples/waypoint.json \
    --connection tcp:127.0.0.1:15762
```

Verify that the downloaded mission exactly matches the uploaded mission.

---

# Upload a Generated Mission Stream

Execute:

```bash
python -m tooling.upload_mission \
    tooling/metadata/mavlink_commands.yaml \
    tooling/examples/takeoff_waypoint_stream.json \
    --connection tcp:127.0.0.1:15762 \
    --confirm-upload
```

This validates the complete DroneNav mission generation pipeline by uploading a mission stream generated from DroneNav tooling.

---

# Shutdown

Terminate the SSH tunnel:

```text
Ctrl-C
```

Stop ArduPilot SITL:

```text
Ctrl-C
```

---

# Diagnostics

## Verify the Reverse Tunnel

On the DroneNav server:

```bash
nc -vz 127.0.0.1 15762
```

---

## Verify Local MAVLink Heartbeat

For local testing only (not used during the standard DroneNav workflow):

```bash
python3 -c "from pymavlink import mavutil; m=mavutil.mavlink_connection('udpin:0.0.0.0:14550'); print('Waiting for heartbeat...'); h=m.wait_heartbeat(timeout=15); print('No heartbeat received' if h is None else f'Connected: system={m.target_system}, component={m.target_component}')"
```

---

# Multi-Aircraft SITL Testing

## Overview

DroneNav supports concurrent flight execution using multiple independent ArduPilot SITL instances and NAVProxy processes.

This configuration enables testing of shared Route occupancy, intersection reservations, traffic deconfliction, and operational HOLD behavior.

Each NAVProxy process maintains its own MAVLink connection while the Route State Engine (RSE) coordinates shared operational state.

## Multi-Aircraft Configuration

The current development environment supports two simulated aircraft.

| | Aircraft 1 | Aircraft 2 |
|---|---|---|
| SITL instance | `-I 0` | `-I 1` |
| Local TCP port | 5762 | 5772 |
| Server TCP port | 15762 | 15772 |
| NAVProxy connection | `tcp:127.0.0.1:15762` | `tcp:127.0.0.1:15772` |

Both connections are established using the SSH reverse-tunnel procedure described earlier in this document.

### Passenger Configuration

Configure the following environment variable:

```text
DRONENAV_SITL_ENDPOINTS=tcp:127.0.0.1:15762,tcp:127.0.0.1:15772
```

The flight execution service assigns connections sequentially when launching NAVProxy subprocesses.

The allocator uses a locked sequence file to coordinate assignments across launches. Assignment wraps around when the endpoint list is exhausted; it does not track aircraft occupancy.

Restart Passenger after changing environment variables.

## Concurrent Flight Execution

Create and submit two Flight Plans using the DroneNav governance application.

The scheduler launches a separate NAVProxy process for each Flight Execution Record (FER).

Both processes execute independently, including mission compilation, preflight, MAVLink mission execution, telemetry reporting, and postflight processing.

The RSE maintains authoritative shared Route and intersection state.

Concurrent execution of two aircraft has been successfully validated in SITL.

## Managed Intersection Contention Test

The objective is to verify that two aircraft approaching the same managed intersection cannot simultaneously acquire the same intersection slot.

The test uses two positions:

- **Position 0:** A temporary SITL-only pause coordinate at the intersection DronePort perimeter, used by the first aircraft.
- **Position 1:** The existing operational HOLD coordinate, using `ROUTE_INTERSECTION_HOLDING_SETBACK_FT`, used by the second aircraft when its reservation is denied.

Both coordinates preserve the Route's assigned lateral lane offset.

### Enable the Test Pause

Configure Passenger:

```text
DRONENAV_SITL_TEST_PAUSE=1
```

Restart Passenger.

The test pause applies exclusively to the NAVProxy process connected to `tcp:127.0.0.1:15762`.

After acquiring its intersection reservation, aircraft 1 switches to `GUIDED` and moves to position 0. It retains the reservation while waiting for manual release.

Aircraft 2 continues normal execution. When the RSE denies its intersection reservation, NAVProxy invokes the existing operational HOLD behavior at position 1.

### Manual Release

After confirming that aircraft 2 has entered operational HOLD, execute the following command on the DroneNav server:

```bash
touch /tmp/dronenav_sitl_release
```

Aircraft 1 requests `AUTO` mode, resumes its mission, and proceeds through the intersection.

The test pause is marked complete after ArduPilot confirms `AUTO`, and NAVProxy restores the Flight Band's commanded cruise speed.

NAVProxy removes any stale release file when the test pause begins.

### Expected Test Sequence

1. Aircraft 1 acquires the intersection reservation.
2. Aircraft 1 enters `GUIDED` and moves to position 0.
3. Aircraft 2 requests the same intersection slot.
4. The RSE denies aircraft 2's request.
5. Aircraft 2 enters operational HOLD at position 1.
6. The operator manually releases aircraft 1.
7. Aircraft 1 resumes `AUTO` and clears the intersection.
8. The RSE grants the intersection to aircraft 2.
9. Aircraft 2 resumes `AUTO` and continues its mission.

The test pause is implemented entirely within NAVProxy. No changes to the RSE collector or intersection reservation algorithm are required.

## Diagnostics

The NAVProxy logs identify the test pause and release using these messages:

```text
SITL test: requesting GUIDED pause at intersection
SITL test: GUIDED pause target sent
SITL test: manual release, requesting AUTO
SITL test: AUTO confirmed, pause completed
```

Operational HOLD messages include:

```text
Requesting GUIDED HOLD
GUIDED HOLD target sent
Intersection cleared: requesting AUTO resume
```

The RSE logs provide the corresponding reservation, denial, occupancy, and clearance events.

## Disable Test Pause

Set the Passenger environment variable to:

```text
DRONENAV_SITL_TEST_PAUSE=0
```

Restart Passenger to return to normal concurrent execution.

## Validation Status

**Completed:** Two concurrent SITL aircraft, independent NAVProxy processes, mission execution, telemetry processing, and managed intersection reservation and clearance.

**Pending:** Forced intersection contention, operational HOLD validation, manual release, and subsequent FOLLOW behavior.

---

# Purpose

This environment serves as the primary research and validation platform for DroneNav NAVProxy development.

It enables developers to:

* Validate MAVLink mission upload and download.
* Verify generated mission streams.
* Exercise the DroneNav mission generation pipeline.
* Validate compiler output before flight controller integration.
* Test NAVProxy behavior against a real ArduPilot implementation without requiring physical aircraft.
* Reproduce experiments using a documented and repeatable development environment.

This test environment is intended exclusively for development and research. It provides a stable foundation for validating DroneNav mission generation, NAVProxy behavior, and future flight controller integration prior to testing on physical aircraft.

