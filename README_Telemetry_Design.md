# DroneNav Phase 3 - Foundational Telemetry Design Principles

These principles define the high-level architecture for DroneNav Phase 3 (Telemetry) and should be considered foundational design requirements for the implementation of NAVProxy and the telemetry subsystem.

---

# Principle 1 - Heartbeat Lifecycle Management

NAVProxy shall maintain a heartbeat with the aircraft for the duration of an active flight.

Loss of heartbeat **shall not immediately terminate** flight monitoring.

Upon loss of heartbeat, NAVProxy shall:

1. Detect the loss of communication.
2. Enter a configurable recovery/listening period.
3. Continue listening for heartbeat messages.
4. Attempt to reestablish communication during the recovery window.

If communication is successfully restored, normal telemetry collection resumes.

If communication cannot be restored before the recovery window expires, NAVProxy shall:

- Terminate active monitoring.
- Finalize the Flight Log.
- Record the flight as a failed execution due to communication loss.
- Preserve the last known operational state of the aircraft.
- Record the reason for termination.

This design prevents temporary communication interruptions from prematurely ending flight monitoring while still ensuring every execution reaches a deterministic conclusion.

---

# Principle 2 - Telemetry Collection Policy

Telemetry production and collection are operational policies established before flight execution.

## Reusable Flight Executions

Telemetry collection defaults to **OFF**.

Telemetry may be enabled by:

- the Aviator, or
- authorized Governance personnel

when creating the Flight Plan.

This minimizes storage and operational overhead for frequently reused flights while still allowing telemetry when desired.

## Scheduled Flight Executions

Telemetry production and collection are **always ON**.

Scheduled flights represent individual operational events and therefore always produce telemetry suitable for operational analysis, auditing, and historical review.

Telemetry policy is determined during Flight Execution Record creation and is consumed by NAVProxy during execution.

---

# Principle 3 - Communication Authority by Flight Phase

NAVProxy communication authority is determined by the current phase of flight.

## Pre-flight

Before arming, NAVProxy has bidirectional communication with the aircraft.

Typical responsibilities include:

- Establish aircraft communications
- Validate aircraft readiness
- Upload compiled mission
- Upload geofence configuration
- Upload operational constraints
- Verify mission acceptance
- Configure telemetry
- Complete pre-flight validation

---

## In-flight

Once the aircraft is airborne, NAVProxy transitions to **receive-only** operation.

During flight NAVProxy may:

- Receive heartbeat messages
- Receive telemetry
- Monitor mission progress
- Observe aircraft health
- Record operational events
- Detect communication failures
- Produce Flight Log entries

NAVProxy **shall not**:

- Modify the mission
- Upload new waypoints
- Change aircraft configuration
- Change flight modes
- Alter geofences
- Redirect the aircraft
- Modify the Flight Execution Record

All operational decisions affecting aircraft behavior must have been established before takeoff.

---

## Post-flight

After landing and disarming, NAVProxy regains bidirectional communication.

Responsibilities include:

- Retrieve final aircraft status
- Complete telemetry collection
- Finalize Flight Log
- Release operational resources
- Close the flight execution lifecycle

---

## Principle 4 – Transport Independence

DroneNav Phase 3 shall maintain complete independence from any specific communications transport technology. The Flight Execution architecture, NAVProxy runtime, telemetry pipeline, and Flight Log lifecycle shall operate consistently regardless of the underlying communications medium.

NAVProxy Standard requires only sufficient communications to safely prepare an aircraft for flight and to complete post-flight processing. Continuous connectivity during flight is an optional capability that enhances operational awareness but is not a prerequisite for autonomous mission execution. As a result, DroneNav Standard supports a broad spectrum of aircraft ranging from economical autonomous platforms utilizing Bluetooth or Wi-Fi for preflight and post-flight operations to professional and enterprise aircraft utilizing telemetry radios, Ethernet, Wi-Fi, LTE/5G, or future communications technologies.

The underlying transport mechanism shall be treated as an implementation detail of the communications layer. Higher-level DroneNav services—including Flight Execution, policy enforcement, heartbeat monitoring, telemetry processing, Flight Logging, and governance—shall remain transport agnostic.

This architectural separation enables DroneNav to support both low-cost autonomous aircraft and advanced enterprise platforms without altering the operational model. Future communications technologies may be introduced by extending the transport layer without requiring changes to the Flight Execution architecture or higher-level DroneNav services.

By separating operational execution from communications technology, DroneNav ensures that governance, Flight Execution Records, and autonomous mission execution remain consistent across all supported aircraft regardless of cost, manufacturer, or communications capability.

---

# Architectural Statement

NAVProxy is **not** an in-flight command authority.

NAVProxy is:

- a pre-flight execution authority,
- a mission deployment service, and
- an in-flight operational observer.

The Flight Controller remains solely responsible for aircraft control once the mission begins.

DroneNav's responsibility is to:

1. Validate the Flight Execution Record.
2. Compile the approved mission.
3. Deploy the mission before takeoff.
4. Observe and record the execution.
5. Produce a complete operational history of the flight.

This separation of responsibilities preserves deterministic aircraft behavior while providing comprehensive operational telemetry and governance.

---
