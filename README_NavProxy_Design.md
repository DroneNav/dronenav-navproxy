# DroneNav NAVProxy Design Specification

**Version:** 1.0  
**Status:** Initial Architecture  
**Component:** NAVProxy  
**Project:** DroneNav

---

# 1. Introduction

## Purpose

NAVProxy is the operational runtime responsible for executing a compiled DroneNav Flight Execution Record. It bridges the gap between a declarative operational contract produced by the DroneNav platform and the real-time execution of a flight through a MAVLink-compatible flight controller.

NAVProxy is intentionally designed to be a lightweight, single-purpose execution engine. It does not perform flight planning, governance, route generation, scheduling, or operational decision making. Those responsibilities belong to other DroneNav components.

Instead, NAVProxy executes an already approved operational program exactly as prescribed while continuously verifying that the aircraft remains within the operational constraints established during flight approval.

---

## Architectural Position

DroneNav is composed of several independent components, each with a clearly defined responsibility.

### Flight Plan (Drupal)

The Flight Plan represents the aviator's intent.

It is human-readable, editable while in Draft status, and owned entirely by the Drupal governance application. Once submitted and accepted, it becomes immutable.

The Flight Plan is never consumed directly by NAVProxy.

---

### Flight Execution API

The Flight Execution API accepts validated Flight Plans and produces immutable Flight Execution Records.

A Flight Execution Record represents the operational contract approved for execution.

The Flight Execution API owns:

- Flight Execution Records
- Flight Band definitions
- Operational reference data
- Execution scheduling
- Operational history

NAVProxy never modifies a Flight Execution Record.

---

### fer_compiler

The Flight Execution Record is intentionally declarative.

Before execution it is translated by **fer_compiler** into a compiled operational program optimized for runtime execution.

The compiler performs all preprocessing required to eliminate runtime interpretation whenever practical.

Examples include:

- geometry compilation
- Route compilation
- Flight Band compilation
- assertion generation
- MAVLink command generation
- execution metadata preparation

The output of the compiler is a compiled operational program consumed directly by NAVProxy.

NAVProxy never performs compilation.

---

### NAVProxy

NAVProxy is the runtime execution engine.

Its responsibilities are limited to:

- loading the compiled operational program
- communicating with the flight controller through MAVLink
- executing compiled MAVLink commands
- evaluating compiled assertions
- recording operational events
- managing failsafe operation
- terminating when execution is complete

NAVProxy never changes the operational contract.

It executes the compiled program exactly as produced by the compiler.

---

## Design Philosophy

Several principles guided the design of NAVProxy.

### Separation of Responsibilities

Every DroneNav component owns a specific responsibility.

Flight planning, governance, scheduling, compilation, and runtime execution remain independent.

This separation greatly simplifies implementation, testing, maintenance, and long-term evolution of the platform.

---

### Immutable Operational Contract

The Flight Execution Record is immutable.

No DroneNav runtime component may modify an approved operational contract.

This guarantees that the operational program executed by NAVProxy exactly matches the approved flight.

---

### Compile Once — Execute Many

Complex interpretation is performed during compilation rather than during flight.

Runtime execution should consist primarily of:

- executing MAVLink commands
- requesting flight controller data
- evaluating assertions
- recording operational events

This minimizes runtime complexity while improving predictability and reliability.

---

### Flight Controller Authority

The flight controller remains the authoritative source for aircraft state.

NAVProxy never estimates or infers information that the flight controller can provide directly.

Examples include:

- GPS position
- altitude
- vehicle status
- landing completion

Whenever operational data is required, NAVProxy obtains the information from the flight controller before evaluating the corresponding assertion.

---

### Ephemeral Runtime

NAVProxy is not a continuously running service.

A NAVProxy instance exists only for the duration of a single Flight Execution.

The runtime lifecycle is:

1. Start
2. Load compiled operational program
3. Establish MAVLink communication
4. Execute preflight assertions
5. Execute flight
6. Record operational logs
7. Complete mission
8. Shutdown

No persistent operational state remains inside NAVProxy after termination.

---

# 2. Architecture

## Architectural Overview

NAVProxy is the runtime execution component of the DroneNav operational pipeline. It is intentionally isolated from governance, scheduling, compilation, and operational planning. By the time NAVProxy begins execution, every operational decision has already been made.

NAVProxy therefore functions as a deterministic execution engine. It accepts a compiled operational program, executes that program through the flight controller, continuously verifies operational compliance, records operational events, and safely terminates when execution is complete.

The runtime never modifies operational intent, creates new flight behavior, or performs dynamic mission planning.

---

## Component Responsibilities

The DroneNav operational pipeline consists of four primary components.

```
+---------------------+
|   Flight Plan       |
|      (Drupal)       |
+----------+----------+
           |
           v
+---------------------+
| Flight Execution API|
+----------+----------+
           |
           v
+---------------------+
|    fer_compiler     |
+----------+----------+
           |
           v
+---------------------+
|      NAVProxy       |
+---------------------+
           |
           v
+---------------------+
| Flight Controller   |
|      MAVLink        |
+---------------------+
```

Each component owns a single responsibility.

---

## Flight Plan

The Flight Plan is the aviator's declaration of intent.

It is designed for human interaction and therefore contains user-oriented information such as:

- aircraft
- aviator
- departure location
- destination
- requested departure time
- flight class
- optional flight path

The Flight Plan exists only within the Drupal governance system.

NAVProxy never loads or interprets a Flight Plan.

---

## Flight Execution API

The Flight Execution API transforms an approved Flight Plan into an immutable Flight Execution Record.

The Flight Execution Record is no longer a planning document.

It is an approved operational contract.

The API is responsible for:

- validation
- operational scheduling
- operational reference data
- Flight Band lookup
- persistent storage
- execution history

The Flight Execution API owns every Flight Execution Record for its entire lifecycle.

NAVProxy has read-only access.

---

## fer_compiler

The compiler exists to eliminate runtime interpretation.

Rather than requiring NAVProxy to repeatedly interpret declarative operational data during flight, the compiler converts that information into an optimized operational program.

The compiler may perform operations such as:

- geometry compilation
- Route compilation
- Flight Band compilation
- assertion generation
- MAVLink command generation
- operational metadata generation

The compiler is executed before flight begins.

No compilation occurs during flight.

---

## NAVProxy

NAVProxy loads the compiled operational program and executes it exactly as produced by the compiler.

Its responsibilities include:

- establishing MAVLink communications
- requesting aircraft state from the flight controller
- executing compiled MAVLink commands
- evaluating compiled assertions
- tracking Route progression
- recording Flight Log events
- recording Telemetry Log events
- initiating failsafe operation when required
- terminating after mission completion

NAVProxy never changes the compiled operational program.

---

## Flight Controller

The flight controller remains solely responsible for aircraft control.

NAVProxy never directly manipulates aircraft hardware.

Instead, NAVProxy communicates with the flight controller exclusively through MAVLink.

The flight controller remains the authoritative source for:

- aircraft position
- aircraft altitude
- vehicle status
- mission execution status
- landing completion

Whenever NAVProxy requires operational data for an assertion, it requests that information from the flight controller rather than attempting to estimate or infer it.

---

## Runtime Philosophy

NAVProxy is intentionally designed to be deterministic.

Given the same compiled operational program and the same aircraft state, NAVProxy should always perform the same sequence of operations.

This philosophy minimizes runtime complexity while maximizing operational predictability, reliability, and testability.

Operational decisions belong to the compiler.

Operational execution belongs to NAVProxy.

This separation of responsibilities is one of the fundamental architectural principles of the DroneNav platform.

---

# 3. Runtime Model

## Overview

NAVProxy is an ephemeral runtime process responsible for executing a single compiled operational program. It is not intended to be a persistent service, nor does it maintain long-term operational state. Each invocation of NAVProxy corresponds to exactly one Flight Execution Record.

The runtime begins when NAVProxy loads a compiled operational program and establishes communication with the flight controller. It terminates after the flight completes, fails, or enters a failsafe condition.

Throughout execution, NAVProxy remains focused on four primary responsibilities:

- Execute compiled MAVLink commands.
- Evaluate compiled operational assertions.
- Record operational events.
- Maintain safe aircraft operation.

---

## Runtime Lifecycle

The runtime follows a predictable lifecycle.

```
Load Compiled Program
          │
          ▼
 Establish MAVLink Connection
          │
          ▼
 Execute Preflight Assertions
          │
          ▼
 Await Launch Authorization
          │
          ▼
 Execute Flight
          │
          ▼
 Evaluate Runtime Assertions
          │
          ▼
 Execute Landing
          │
          ▼
 Evaluate Arrival Assertions
          │
          ▼
 Write Final Logs
          │
          ▼
 Shutdown
```

Each stage executes in a deterministic order.

---

## Flight Controller Responsibilities

The flight controller is the authoritative source for aircraft state.

NAVProxy never estimates information that the flight controller can provide directly.

The flight controller provides:

- Current GPS position
- Current altitude
- Aircraft status
- Mission execution status
- Landing-complete notification
- MAVLink command acknowledgements

Whenever NAVProxy requires operational information, it requests that information from the flight controller before evaluating the corresponding assertion.

---

## NAVProxy Responsibilities

NAVProxy is responsible for runtime execution of the compiled operational program.

Primary responsibilities include:

- Loading the compiled operational program.
- Establishing MAVLink communications.
- Executing compiled MAVLink commands.
- Requesting operational state from the flight controller.
- Evaluating compiled assertions.
- Tracking Route progression.
- Recording Flight Log events.
- Recording Telemetry Log events.
- Detecting operational failures.
- Entering failsafe mode when required.
- Initiating emergency landing when necessary.
- Terminating after mission completion.

NAVProxy does not create or modify operational data.

---

## Runtime State

NAVProxy maintains only the temporary state required to execute the current flight.

Typical runtime state includes:

- Current execution phase
- Current Route
- Current Route segment
- Current assertion state
- Flight Log buffer
- Telemetry Log buffer
- MAVLink communication state

All runtime state is discarded when NAVProxy terminates.

No persistent operational information is stored locally.

---

## Runtime Data Sources

NAVProxy receives information from two sources.

### Compiled Operational Program

The compiled operational program provides:

- Compiled assertions
- Compiled MAVLink commands
- Compiled geometry
- Route definitions
- Operational metadata

This information remains static throughout execution.

---

### Flight Controller

The flight controller provides dynamic operational information including:

- GPS position
- Altitude
- Vehicle status
- Landing completion
- Command acknowledgements

This information changes continuously during flight and is requested as needed by NAVProxy.

---

## Logging

NAVProxy produces two independent operational logs.

### Flight Log

The Flight Log records significant operational events throughout the lifecycle of the mission.

Examples include:

- Startup
- Preflight failures
- Flight initiation
- Assertion failures
- Arrival violations
- Mission completion
- Failsafe activation
- Emergency landing

The Flight Log represents the official operational history of the mission.

---

### Telemetry Log

The Telemetry Log records events that occur while the aircraft is airborne.

Examples include:

- MAVLink command execution
- MAVLink command acknowledgements
- In-flight assertion violations
- Position updates
- Altitude updates
- Operational telemetry
- Command failures

Telemetry entries provide a chronological record of aircraft operation during flight.

---

## Runtime Design Principles

Several principles govern NAVProxy runtime behavior.

- Runtime execution must remain deterministic.
- Operational decisions shall never be created during flight.
- The flight controller remains the authoritative source of aircraft state.
- The compiled operational program is immutable.
- Assertions verify operational compliance.
- Runtime failures shall always be recorded before termination.
- Safety takes precedence over mission completion.

These principles ensure that NAVProxy remains predictable, testable, and suitable for safety-critical operational environments.

---

# 4. Assertion Framework

## Overview

Assertions are the primary operational safety mechanism within NAVProxy.

Unlike MAVLink commands, which direct the aircraft to perform an action, assertions verify that the aircraft remains compliant with the operational contract established by the Flight Execution Record.

Assertions never change aircraft behavior directly. Instead, they determine whether the aircraft is operating within the approved constraints. When an assertion cannot be satisfied, NAVProxy records the event and responds according to the severity of the violation.

All assertions are generated by **fer_compiler** during compilation. NAVProxy never creates or modifies assertions during flight.

---

## Assertion Philosophy

The Flight Execution Record is an operational contract.

Every assertion represents one contractual requirement that must be satisfied before, during, or after flight.

Examples include:

- The aircraft must depart from the approved departure location.
- The aircraft must launch within the approved departure window.
- The aircraft must operate within the approved Flight Band.
- The aircraft must comply with Route operational constraints.
- The aircraft must land within the approved arrival geometry.

NAVProxy evaluates these requirements exactly as compiled.

---

## Assertion Lifecycle

Assertions are evaluated at specific points during the operational lifecycle.

Some assertions execute only once.

Others execute multiple times as the mission progresses.

The evaluation phase is determined by the compiler.

Typical execution phases include:

- Preflight
- Launch
- In-flight
- Arrival

Each assertion defines when it executes and what runtime information it requires.

---

## Runtime Data

Many assertions require information from the flight controller.

Typical runtime information includes:

- Current GPS position
- Current altitude
- Current vehicle state
- Landing-complete notification

When required, NAVProxy requests the information from the flight controller immediately before evaluating the assertion.

NAVProxy does not estimate or infer aircraft state.

---

## Assertion Categories

The initial NAVProxy implementation contains five assertion types.

| Assertion | Purpose |
|-----------|---------|
| NAV_ASSERT_POSITION_IN_GEOMETRY | Validate departure geometry |
| NAV_ASSERT_DEPARTURE_TIME | Validate launch window |
| NAV_ASSERT_FLIGHT_BAND | Validate operational Flight Band |
| NAV_ASSERT_ROUTE | Validate Route compliance |
| NAV_ASSERT_ARRIVAL_IN_GEOMETRY | Validate arrival geometry |

Each assertion has its own execution timing and operational semantics.

---

## Assertion Outcomes

Every assertion produces one of two outcomes.

### Pass

The operational requirement has been satisfied.

Execution continues.

---

### Fail

The operational requirement has not been satisfied.

NAVProxy records the failure and performs the appropriate operational response.

The response depends on when the assertion executes.

---

## Preflight Assertion Failure

A preflight assertion failure prevents flight from beginning.

Examples include:

- Invalid departure location.
- Outside the permitted launch window.
- Flight Band day restriction.
- Flight Band time restriction.

When a preflight assertion fails:

- The mission is aborted.
- No takeoff occurs.
- A Flight Log entry is created.
- No Telemetry Log entry is created.

---

## In-Flight Assertion Violation

An in-flight assertion violation occurs after launch.

Examples include:

- Route assertion failure.
- Operational altitude violation.
- Position-related operational violation.

When an in-flight assertion fails:

- A Flight Log entry is created.
- A Telemetry Log entry is created.
- NAVProxy performs the operational response defined for that assertion.

The response is assertion-specific.

---

## Arrival Violation

Arrival assertions execute only after the flight controller reports that landing has completed.

The initial implementation contains one arrival assertion:

- NAV_ASSERT_ARRIVAL_IN_GEOMETRY

An arrival violation indicates that the aircraft successfully completed the mission but did not land within the approved arrival geometry.

Arrival violations:

- are recorded in the Flight Log.
- do not generate Telemetry Log entries.
- do not constitute a failed flight.

The aircraft has already landed safely.

---

## Assertion Independence

Assertions operate independently.

Each assertion evaluates one operational requirement.

Failure of one assertion does not imply failure of another.

This independence simplifies implementation, testing, maintenance, and future expansion of the assertion framework.

---

## Compiler Responsibilities

The compiler determines:

- which assertions are required
- where they execute
- what operational data they require
- what parameters they use

NAVProxy simply evaluates the compiled assertions.

This separation allows new assertion types to be introduced without redesigning the runtime architecture.

---

# 5. Assertion Specifications

## Overview

This section defines the operational behavior of each assertion implemented by the initial NAVProxy runtime.

Each assertion is generated by **fer_compiler** and executed by NAVProxy exactly as compiled.

Assertions define operational compliance.

They do not control the aircraft directly.

---

# NAV_ASSERT_POSITION_IN_GEOMETRY

## Purpose

Verifies that the aircraft is located inside the approved departure geometry before launch.

The departure geometry may represent:

- a Site
- a DronePort
- another compiled departure geometry

The geometry itself is determined during compilation.

NAVProxy simply evaluates the compiled geometry.

---

## Execution Phase

Preflight

Executed before takeoff.

---

## Runtime Data Required

The assertion requests:

- Current GPS Position

from the flight controller.

---

## Successful Evaluation

The aircraft is located inside the compiled departure geometry.

Flight initialization continues.

---

## Failed Evaluation

The aircraft is not located inside the approved departure geometry.

The flight does not begin.

A Flight Log entry is created.

No Telemetry Log entry is produced.

---

# NAV_ASSERT_DEPARTURE_TIME

## Purpose

Verifies that flight begins during the approved launch window.

---

## Execution Phase

Preflight

Executed immediately before launch authorization.

---

## Runtime Data Required

The assertion requests the current operational time.

Operational timezone conversion has already been completed before NAVProxy executes the assertion.

---

## Launch Window

The launch window is determined using:

```
LAUNCH_WINDOW_PREFLIGHT_MINUTES

LAUNCH_WINDOW_EXPIRES_MINUTES
```

Flight may begin only within the configured operational window.

---

## Successful Evaluation

Current operational time falls inside the launch window.

Flight initialization continues.

---

## Failed Evaluation

Current operational time falls outside the permitted launch window.

The mission is aborted.

A Flight Log entry is created.

No Telemetry Log entry is produced.

---

# NAV_ASSERT_FLIGHT_BAND

## Purpose

Verifies compliance with the compiled Flight Band.

The Flight Band contains two independent operational responsibilities.

- Day and time authorization
- Cruise altitude authorization

---

## Preflight Evaluation

Before launch NAVProxy verifies:

- Day of week
- Time of day

Both values must satisfy the compiled Flight Band.

---

## Runtime Evaluation

The Flight Band also defines:

- Minimum cruise altitude
- Maximum cruise altitude

These values apply only during Route cruise operations.

The Flight Band altitude limits override any altitude values defined by the Route itself.

---

## Flight Band Altitude Applicability

Flight Band altitude limits apply only during intermediate Route traversal.

They do **not** apply:

- During departure (Route Segment 0)
- During final arrival
- During Site-only flights
- When no Flight Band exists

---

## Successful Evaluation

The operational Flight Band requirements are satisfied.

Mission execution continues.

---

## Failed Evaluation

### Preflight

If the day or time requirements are not satisfied:

- Flight does not begin.
- Flight Log entry is created.
- No Telemetry Log entry is created.

Runtime altitude violations are handled by the Route assertion.

---

# NAV_ASSERT_ROUTE

## Purpose

Verifies Route operational compliance during flight.

The initial implementation validates operational altitude while traversing Route segments.

Additional Route assertions may be introduced in future implementations without changing the overall assertion architecture.

---

## Execution Phase

In Flight

---

## Route Progression

NAVProxy tracks Route progression internally.

As the aircraft enters each Route segment, the corresponding Route assertions are evaluated.

---

## Segment Zero

Route Segment 0 represents departure.

No altitude assertion is performed.

The aircraft is allowed to climb toward cruise altitude.

---

## Intermediate Route Segments

Beginning with Route Segment 1, NAVProxy evaluates the compiled cruise altitude requirement.

The assertion executes **once** when the aircraft enters the segment.

Continuous altitude monitoring is not performed.

---

## Final Approach

Altitude assertions stop before the final arrival segment.

This allows the aircraft to descend normally for landing.

---

## Runtime Data Required

The assertion requests:

- Current altitude

from the flight controller.

---

## Successful Evaluation

The aircraft satisfies the compiled altitude requirement.

Mission execution continues.

---

## Failed Evaluation

An operational Route violation has occurred.

NAVProxy records:

- Flight Log entry
- Telemetry Log entry

The operational response is determined by NAVProxy runtime policy.

---

# NAV_ASSERT_ARRIVAL_IN_GEOMETRY

## Purpose

Verifies that the aircraft lands inside the approved arrival geometry.

The arrival geometry may represent:

- DronePort
- Site
- other compiled arrival geometry

---

## Execution Phase

Post Flight

The assertion executes only after the flight controller reports that landing has completed.

NAVProxy never infers landing.

Landing completion is reported authoritatively by the flight controller.

---

## Runtime Data Required

After receiving the landing notification, NAVProxy requests:

- Final GPS position

from the flight controller.

---

## Successful Evaluation

The aircraft landed inside the compiled arrival geometry.

Mission execution completes successfully.

---

## Failed Evaluation

The aircraft landed outside the approved arrival geometry.

This is recorded as an **Arrival Violation**.

The aircraft has already completed its mission and landed safely.

NAVProxy records:

- Flight Log entry

No Telemetry Log entry is created.

Arrival violations do **not** constitute a failed flight.

---

# 6. MAVLink Command Execution

## Overview

The compiled operational program contains a sequence of MAVLink commands generated by **fer_compiler**.

These commands represent the operational actions required to execute the approved Flight Execution Record.

NAVProxy executes the compiled command sequence exactly as produced by the compiler.

NAVProxy never generates, modifies, optimizes, or reorders compiled commands during flight.

---

## Command Philosophy

Assertions and MAVLink commands serve different purposes.

**MAVLink commands** instruct the flight controller to perform an operational action.

Examples include:

- Arm aircraft
- Initiate takeoff
- Navigate to waypoint
- Change flight mode
- Land aircraft

**Assertions** verify that the operational contract continues to be satisfied.

Assertions never replace commands, and commands never replace assertions.

The compiled operational program contains both.

---

## Command Execution

NAVProxy executes each compiled MAVLink command in the order specified by the compiled operational program.

For each command NAVProxy:

1. Retrieves the next compiled command.
2. Transmits the command to the flight controller.
3. Waits for the required acknowledgement or completion.
4. Records the operational result.
5. Advances to the next command.

Execution continues until:

- the mission completes,
- an operational failure occurs,
- or failsafe operation is initiated.

---

## MAVLink Communication

NAVProxy communicates with the flight controller exclusively through the MAVLink protocol.

NAVProxy does not communicate directly with flight controller hardware.

All operational interaction occurs through MAVLink messages.

Typical runtime communication includes:

- command transmission
- command acknowledgement
- vehicle status
- GPS position requests
- altitude requests
- landing notification

---

## Command Acknowledgement

Many MAVLink commands require confirmation from the flight controller before execution may continue.

NAVProxy waits for the required acknowledgement or completion before advancing to the next compiled command.

The acknowledgement mechanism ensures that the runtime remains synchronized with actual aircraft execution.

---

## Command Logging

Execution of compiled MAVLink commands is recorded in the Telemetry Log.

Typical entries include:

- command issued
- acknowledgement received
- completion received
- execution timing
- command failure

The Telemetry Log provides a chronological record of operational execution while the aircraft is airborne.

---

## Command Failure

Failure to execute or confirm a required MAVLink command is treated as a potentially catastrophic operational failure.

Examples include:

- command rejection
- acknowledgement timeout
- communication failure
- command execution failure

Because NAVProxy can no longer guarantee safe execution of the approved operational program, normal mission execution immediately terminates.

---

## Failsafe Operation

Upon detection of a catastrophic command failure, NAVProxy immediately transitions into failsafe operation.

Failsafe operation is intended to place the aircraft into the safest achievable condition while minimizing operational risk.

The specific emergency procedures are determined by the compiled operational program and the capabilities of the flight controller.

---

## Emergency Landing

When required, NAVProxy initiates an emergency landing through the flight controller.

Emergency landing takes precedence over mission completion.

The objective is no longer successful mission execution.

The objective becomes safe recovery of the aircraft.

---

## Logging Requirements

A catastrophic command failure shall always produce:

### Flight Log

Records:

- command failure
- transition to failsafe
- emergency landing initiation
- mission termination

---

### Telemetry Log

Records:

- failed command
- acknowledgement status
- communication status
- failsafe activation
- emergency landing activity

These records provide the operational history necessary for post-flight analysis.

---

## Design Principles

The MAVLink execution subsystem is governed by several principles.

- Commands execute exactly as compiled.
- Command ordering is deterministic.
- Commands are never modified during runtime.
- The flight controller remains responsible for aircraft control.
- Catastrophic command failures immediately terminate normal mission execution.
- Safety always takes precedence over mission completion.

---

# Appendix A — Initial Assertion Summary

The following table summarizes the assertions implemented by the initial NAVProxy runtime.

| Assertion | Execution Phase | Runtime Data Required | Success | Failure Logging |
|-----------|-----------------|----------------------|---------|-----------------|
| `NAV_ASSERT_POSITION_IN_GEOMETRY` | Preflight | Current GPS Position | Aircraft inside departure geometry | Flight Log |
| `NAV_ASSERT_DEPARTURE_TIME` | Preflight | Current Operational Time | Launch window satisfied | Flight Log |
| `NAV_ASSERT_FLIGHT_BAND` | Preflight | Day / Time | Flight Band authorized | Flight Log |
| `NAV_ASSERT_ROUTE` | In Flight | Current Altitude | Cruise altitude satisfied upon entering intermediate Route segments | Flight Log + Telemetry Log |
| `NAV_ASSERT_ARRIVAL_IN_GEOMETRY` | Post Flight | Final GPS Position | Aircraft landed inside arrival geometry | Flight Log |

---

# Appendix B — Failure Summary

NAVProxy recognizes three categories of operational failures.

## Preflight Assertion Failure

The aircraft has not launched.

Characteristics:

- Mission does not begin.
- No aircraft movement occurs.
- Flight Log entry is created.
- No Telemetry Log entry is created.

Typical causes include:

- Invalid departure location.
- Outside launch window.
- Flight Band day restriction.
- Flight Band time restriction.

---

## In-Flight Assertion Violation

The aircraft is airborne.

Characteristics:

- Flight Log entry.
- Telemetry Log entry.
- Assertion-specific operational response.

Typical causes include:

- Route operational violation.
- Cruise altitude violation.

---

## MAVLink Command Failure

A required MAVLink command cannot be executed or confirmed.

Characteristics:

- Considered a potentially catastrophic operational failure.
- Flight Log entry.
- Telemetry Log entry.
- Immediate transition to failsafe operation.
- Emergency landing initiated.

---

## Arrival Violation

The aircraft has already landed.

Characteristics:

- Landing completed.
- Arrival geometry not satisfied.
- Flight Log entry.
- No Telemetry Log entry.
- Does not constitute a failed flight.

---

# Appendix C — Runtime Responsibilities Summary

## Flight Controller

Authoritative source for:

- GPS position
- Altitude
- Vehicle status
- Mission status
- Landing-complete notification
- MAVLink acknowledgements

---

## NAVProxy

Responsible for:

- Loading the compiled operational program.
- Executing compiled MAVLink commands.
- Requesting aircraft state from the flight controller.
- Evaluating compiled assertions.
- Tracking Route progression.
- Recording Flight Log events.
- Recording Telemetry Log events.
- Detecting operational failures.
- Managing failsafe operation.
- Initiating emergency landing when required.
- Shutting down after mission completion.

---

# Conclusion

NAVProxy is intentionally designed as a deterministic execution engine.

Operational planning, governance, scheduling, and compilation are completed before runtime execution begins. During flight, NAVProxy executes the compiled operational program, verifies compliance with the approved operational contract through compiled assertions, communicates with the flight controller exclusively through MAVLink, records operational history, and prioritizes safety above mission completion.

By maintaining a strict separation between compilation and execution, DroneNav achieves a runtime architecture that is predictable, testable, maintainable, and suitable for safety-critical autonomous flight operations.

---





