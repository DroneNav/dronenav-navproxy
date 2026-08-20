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
sim_vehicle.py -v ArduCopter --console --map -l 34.077756274,-84.301123283,334.61,0
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

