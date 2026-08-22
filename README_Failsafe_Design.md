# DroneNav Failsafe Design

## Purpose

This document records the platform-independent failsafe design
principles for DroneNav Phase 2.

DroneNav defines the operational meaning of a failsafe and the required
recovery outcome independently of any particular flight-controller
platform. ArduPilot, PX4, and other flight-controller integrations are
implementation mappings of these principles rather than the source of
DroneNav policy.

## Failsafe Design Principles

### 1. No HOME / RTL

DroneNav has no operational concept of HOME.

Failsafe recovery shall not depend on Return-to-Launch (RTL),
Return-to-Home, SmartRTL, or equivalent HOME-based behavior.
Flight-controller-specific HOME concepts may exist internally, but they
are not part of DroneNav operational semantics.

### 2. Abort and Recover

A genuine aircraft-side failsafe aborts the mission.

Once a failsafe requiring recovery is triggered, mission completion is
no longer the priority. The aircraft shall transition to the safest
available recovery behavior as soon as practical.

A recovery team is dispatched using the aircraft's last reported or
final reported location. A failsafe recovery location is an abnormal
recovery location and is not required to be a normal DroneNav Route or
Site destination.

### 3. Emergency Egress Governance

Emergency egress shall be considered during Route governance.

A Route shall not be evaluated solely on whether normal traversal is
acceptable. Governance must also consider whether an aircraft can safely
leave the normal Route and recover if an aircraft-side failsafe occurs.

Safe recovery takes precedence over normal Route conformance after a
failsafe has activated.

### 4. Governed Failsafe Recovery Points

Every interior Route segment shall be assigned a governed failsafe
recovery point.

Departure and arrival segments are excluded from this requirement.
Multiple interior Route segments may share the same failsafe point.

For a Route containing `N` segments:

-   required segment-to-failsafe assignments: `N - 2`
-   minimum number of unique failsafe points: `1`
-   maximum number of unique failsafe points: `N - 2`

Governance determines the recovery assignment before flight. The flight
controller shall not be required to make a governance decision during an
emergency.

When an aircraft-side failsafe occurs and adequate navigation and
controlled-flight capability remain, the aircraft shall use the failsafe
recovery assigned to its current Route segment.

### 5. Communications Independence

Loss of communications between NAVProxy Standard and the flight
controller does not, by itself, abort an otherwise valid autonomous
mission.

If NAVProxy loses the FC heartbeat or communication path, NAVProxy
attempts communications recovery and records the communications event.
The aircraft continues executing its approved autonomous mission.

Likewise, loss of NAVProxy connectivity from the FC's perspective is an
observability/communications condition rather than, by itself, an
aircraft-safety condition requiring mission abort.

The communications-monitoring lifecycle is therefore independent of the
aircraft's autonomous mission lifecycle.

### 6. Flight-Controller Independence

DroneNav failsafe policy shall remain independent of any particular
flight-controller platform.

DroneNav defines platform-neutral failsafe conditions and required
recovery outcomes. Each flight-controller adapter maps native telemetry,
health states, parameters, and failsafe capabilities into those DroneNav
semantics.

Platform-specific concepts such as ArduPilot parameters shall not define
DroneNav failsafe policy.

### 7. Deterministic Energy Policy

Energy sufficiency shall be determined objectively from governed
aircraft and mission criteria and shall not be an Aviator judgment call.

During preflight, insufficient usable energy reserve causes a preflight
assertion failure and prevents launch.

During flight, battery or energy state is captured as telemetry. Battery
state does not alter the mission while sufficient energy remains to
execute safely.

If an in-flight energy condition crosses the governed abort threshold,
the mission is aborted and governed recovery is initiated.

DroneNav should initiate energy-based recovery while sufficient energy
remains to execute the recovery safely.

### 8. Proactive Navigation Integrity

DroneNav shall react to degrading navigation integrity before navigation
becomes unusable.

Navigation measurements and estimator information may be quantitative
and platform-specific, but each FC integration shall expose the
navigation-health semantics required by DroneNav.

Conceptually, DroneNav distinguishes:

-   **Healthy** --- navigation integrity supports normal governed
    operation.
-   **Degraded / Abort** --- navigation integrity has deteriorated
    beyond the governed abort threshold but remains sufficient to
    execute emergency egress.
-   **Unusable** --- reliable governed coordinate navigation can no
    longer be assumed.

When the governed abort threshold is reached while sufficient positional
capability remains, the mission is aborted and the aircraft uses the
failsafe recovery assigned to its current Route segment.

DroneNav shall not intentionally wait for complete navigation failure
before initiating recovery.

If navigation is already insufficient to execute the governed failsafe
path, stabilization and safe landing using the capabilities that remain
take precedence over reaching the assigned failsafe point.

### 9. Proactive Vehicle Health

DroneNav shall abort normal mission execution when critical vehicle
health degrades beyond a governed threshold.

Vehicle-health conditions include platform-specific failures or
degradation affecting the aircraft's ability to sustain controlled
flight, such as propulsion, motors/ESCs, actuators or control surfaces,
power distribution, severe vibration affecting controllability, or other
critical vehicle systems recognized by the flight controller.

When sufficient controlled-flight and navigation capability remain, the
aircraft shall recover using the failsafe recovery assigned to its
current Route segment.

When sufficient capability does not remain to reach that point safely,
stabilization and immediate safe landing take precedence.

Where degradation can be detected before loss of control, recovery
should begin while the aircraft still possesses the capability necessary
to recover safely.

### 10. Reusable-Flight Geofence Containment

This principle applies to **reusable Flight Executions**. Geofence
enforcement is not the governing mechanism for scheduled AUTO Flight
Executions.

During a reusable Flight Execution, an imminent breach of a governed
geofence shall cause the FC to arrest motion toward the boundary and
hold the aircraft within the authorized geometry.

The desired behavior is:

1.  detect an imminent boundary breach;
2.  brake or hold position before the breach occurs;
3.  remain within the governed geometry;
4.  require the Aviator to command a path sufficiently away from the
    boundary;
5.  resume normal maneuvering after adequate separation is restored.

The Aviator shall not be permitted to continue commanding the aircraft
farther toward or through the governed boundary while containment is
active.

If the aircraft cannot maintain containment because navigation, vehicle
health, or another critical capability has degraded, the condition
escalates to the applicable aircraft-side failsafe.

Geofence proximity is therefore initially a containment condition, not
automatically a mission-abort condition.

### 11. Reusable-Flight Vertical Integrity

This principle applies to **reusable Flight Executions**, where a
governed vertical ceiling constrains Aviator-controlled operation.

The FC shall prevent the aircraft from exceeding the governed vertical
ceiling. As the aircraft approaches the ceiling, the FC shall arrest the
climb and hold the aircraft within the authorized vertical envelope.

The Aviator must command the aircraft sufficiently away from the ceiling
before normal vertical maneuvering resumes.

If the aircraft cannot maintain the governed vertical envelope because
navigation, vehicle health, or another critical capability has degraded,
the condition escalates to the applicable aircraft-side failsafe.

For **scheduled AUTO Flight Executions**, vertical integrity is governed
by Flight Bands and the compiled scheduled mission. Principle 11 does
not replace or duplicate Flight Band governance.

## Scheduled AUTO Recovery Model

For an aircraft-side failsafe during a scheduled AUTO Flight Execution,
the normal recovery model is:

``` text
aircraft-side failsafe
        |
        v
abort approved mission
        |
        v
identify current Route segment
        |
        v
use preassigned governed failsafe point
        |
        v
execute governed emergency egress
        |
        v
land
        |
        v
recovery team
```

This recovery model assumes sufficient navigation and controlled-flight
capability remain. When the failed capability prevents safe execution of
the governed egress path, stabilization and immediate safe landing take
precedence.

## Communications-Loss Model

Communications loss alone does not invoke the scheduled AUTO recovery
model:

``` text
NAVProxy <-> FC communications lost
        |
        v
not an aircraft-side safety failsafe
        |
        +--> FC continues approved autonomous mission
        |
        +--> NAVProxy attempts communications recovery
        |
        +--> NAVProxy records communications event
```

## Reusable-Flight Containment Model

Reusable executions use containment for governed horizontal and vertical
boundaries:

``` text
imminent horizontal or vertical boundary violation
        |
        v
FC brake / hold
        |
        v
remain inside governed envelope
        |
        v
Aviator commands away from boundary
        |
        v
adequate separation restored
        |
        v
normal operation resumes
```

If containment cannot be maintained because of a genuine aircraft-side
safety condition, the applicable abort-and-recovery principle takes
precedence.

## General Safety Pattern

Where a safety-related capability degrades progressively and that
degradation can be measured reliably, DroneNav should initiate recovery
while the aircraft still possesses the capability required for safe
recovery.

The design objective is not to wait for catastrophic failure. It is to
use the remaining safe operating margin to place the aircraft into a
governed recovery state.

