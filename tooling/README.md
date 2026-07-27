# NAVProxy Tooling Commands

## Overview

The `tooling` package contains the command-line utilities used to transform a DroneNav Flight Execution Record (FER) into an executable mission for NAVProxy and supported flight controllers.

Each tool performs a single responsibility and can be executed independently for development, debugging, or regression testing.

The production pipeline is:

```text
Flight Execution Record (FER)
            │
            ▼
build_fer_compiler_input.py
            │
            ▼
fer_compiler.py
            │
            ▼
mavlink_compiler.py
            │
            ▼
mavlink_emitter.py
            │
            ▼
MISSION_ITEM_INT Mission Stream
```

The lowest-level emitter may also be executed independently:

```text
emit_mission_item_int.py
```

which converts a single compiled command into a native MAVLink `MISSION_ITEM_INT` message.

---

# Regression Test Files

The canonical regression test files are:

```text
tooling/examples/fer_<uuid>.json
```

These files represent complete Flight Execution Records and should be used for all end-to-end regression testing of the compilation pipeline.

Older example files remain only for testing individual low-level tools.

---

# Tool Reference

## build_fer_compiler_input.py

### Purpose

Retrieves a Flight Execution Record from the Flight Execution API and creates the compiler input document consumed by the FER compiler.

### Usage

```bash
python -m tooling.build_fer_compiler_input \
    <flight_execution_uuid>
```

Optional API endpoint:

```bash
python -m tooling.build_fer_compiler_input \
    --api-base-url https://api.dronenav.org/api \
    <flight_execution_uuid>
```

### Output

Creates:

```text
tooling/examples/fer_<uuid>.json
```

If the output file already exists, the tool exits successfully without overwriting the existing file.

---

## fer_compiler.py

### Purpose

The FER compiler transforms a Flight Execution Record into an executable command stream.

A Flight Execution Record is a declarative operational contract that describes **what** the aircraft is intended to do. The FER compiler translates that operational intent into an ordered sequence of executable commands.

The resulting command stream may contain multiple command families, including:

* MAVLink commands
* NAVProxy commands

Each command remains declarative. The compiler determines **what** operations must occur and the order in which they must occur, but it does not emit native protocol messages or execute the mission.

### Usage

```bash
python -m tooling.fer_compiler \
    tooling/examples/fer_<uuid>.json
```

### Output

An ordered declarative execution command stream representing the operational execution of the Flight Execution Record.

Subsequent tooling processes only the command families it understands. For example, the MAVLink compiler processes only MAVLink commands, while NAVProxy processes its own command set.

---

## mavlink_compiler.py

### Purpose

Compiles the declarative MAVLink commands into a MAVLink-specific intermediate representation.

Responsibilities include:

* metadata lookup
* command validation
* parameter encoding
* assignment of contiguous command sequence numbers
* preparation for message emission

### Usage

```bash
python -m tooling.mavlink_compiler \
    tooling/examples/fer_<uuid>.json
```

### Output

Compiled MAVLink command stream.

---

## mavlink_emitter.py

### Purpose

Converts the compiled MAVLink command stream into a complete MAVLink mission.

Responsibilities include:

* emitting `MISSION_ITEM_INT`
* assigning contiguous mission sequence numbers
* producing the final mission stream

### Usage

```bash
python -m tooling.mavlink_emitter \
    tooling/examples/fer_<uuid>.json
```

### Output

A complete MAVLink mission stream.

---

## emit_mission_item_int.py

### Purpose

Lowest-level emitter.

Converts a single compiled command into one native MAVLink `MISSION_ITEM_INT` message.

This tool is primarily intended for development, debugging, and unit testing.

### Usage

```bash
python -m tooling.emit_mission_item_int \
    tooling/examples/<command_name>.json
```

Optional arguments:

```text
--target-system
--target-component
--sequence
```

### Output

A single `MISSION_ITEM_INT` JSON message.

---

# Typical Development Workflow

Generate a compiler-input document:

```bash
python -m tooling.build_fer_compiler_input \
    <flight_execution_uuid>
```

Compile the Flight Execution Record:

```bash
python -m tooling.fer_compiler \
    tooling/examples/fer_<uuid>.json
```

Compile the MAVLink commands:

```bash
python -m tooling.mavlink_compiler \
    tooling/examples/fer_<uuid>.json
```

Emit the complete MAVLink mission:

```bash
python -m tooling.mavlink_emitter \
    tooling/examples/fer_<uuid>.json
```

---

# Regression Testing

The recommended regression strategy is to preserve every Flight Execution Record that exposes a bug or validates a new capability.

Each preserved FER becomes a permanent regression test.

Example:

```text
tooling/examples/
    fer_019f6bc9-b635-7a7f-95d9-e1f15fdadfb6.json
    fer_019f72c0-4e7d-73f5-a22e-0d5b9a3d2d91.json
    ...
```

As the tooling evolves, every FER example should continue to compile successfully without modification.

---

# Design Philosophy

Each executable performs one well-defined responsibility.

```text
Flight Execution Record
        │
        ▼
FER Compiler
        │
        ▼
MAVLink Compiler
        │
        ▼
MAVLink Emitter
        │
        ▼
MISSION_ITEM_INT Mission
```

Maintaining this separation of concerns allows each stage of the pipeline to be tested independently while preserving a complete end-to-end workflow using the same Flight Execution Record examples.

