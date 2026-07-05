# NAVProxy

## Overview

NAVProxy is the execution layer of the DroneNav platform.

Its responsibility is to bridge the gap between DroneNav's governance platform and supported flight control platforms. NAVProxy receives an approved flight execution package from DroneNav, validates that it can be executed by the configured flight platform, translates the execution package into platform-specific commands, and monitors the execution of the flight.

NAVProxy is intentionally designed as an adapter rather than a flight controller. It does not make governance decisions, generate flight plans, or replace the capabilities of an existing flight control platform.

---

# Project Goals

The goals of NAVProxy are to:

* Execute approved DroneNav flight operations.
* Provide a clean separation between governance and aircraft control.
* Isolate DroneNav from platform-specific flight controller implementations.
* Allow DroneNav to support multiple flight controller platforms through a common execution architecture.
* Provide a consistent interface for mission execution, telemetry, and operational status reporting.

---

# Architectural Role

The DroneNav ecosystem is composed of several distinct layers.

```text
DroneNav Governance
    │
    │  Flight Planning
    │  Flight Authorization
    │  Operational Policies
    ▼
NAVProxy
    │
    │  Translation
    │  Validation
    │  Execution
    ▼
Flight Control Platform
```

Each layer has a well-defined responsibility.

DroneNav determines **what** is authorized.

NAVProxy determines **how** an approved flight is expressed to the configured flight platform.

The flight control platform remains responsible for safely controlling the aircraft.

---

# Design Principles

## Separation of Responsibilities

Governance, authorization, execution, and aircraft control are separate concerns.

NAVProxy intentionally avoids duplicating functionality that belongs in either DroneNav or the underlying flight control platform.

---

## Platform Independence

NAVProxy is designed around a common execution model rather than any single flight controller implementation.

Platform-specific behavior should be isolated behind adapters so that support for additional flight controller platforms can be added without changing DroneNav.

---

## Configuration over Specialization

Supported flight controller capabilities are defined through platform profiles and configuration.

NAVProxy should adapt to the capabilities of the configured platform rather than requiring changes to DroneNav for each supported implementation.

---

## Minimal Translation Layer

NAVProxy should perform only the work necessary to translate DroneNav execution packages into platform-specific operations.

Business logic, workflow, approvals, and operational policy belong in DroneNav.

---

## Safety First

NAVProxy shall never bypass or weaken safety mechanisms provided by the underlying flight control platform.

Whenever possible, existing platform capabilities should be leveraged before introducing new functionality.

---

## Extensibility

The architecture should support incremental enhancement without requiring significant redesign.

New execution capabilities should be introduced through well-defined interfaces and modular platform adapters.

---

# Responsibilities

NAVProxy is responsible for:

* Receiving approved execution packages from DroneNav.
* Validating execution package compatibility with the configured platform.
* Translating execution packages into platform-specific operations.
* Uploading mission and operational data.
* Initiating approved flight execution.
* Monitoring execution progress.
* Reporting operational status and events back to DroneNav.
* Managing platform-specific configuration.

NAVProxy is **not** responsible for:

* Flight planning.
* Governance.
* Flight authorization.
* Airspace policy.
* Operational approvals.
* Pilot certification.
* Authority management.
* Spatial data management.

---

# Platform Support

NAVProxy is intended to support multiple flight control platforms through a common execution architecture.

Each supported platform should be implemented as an independent adapter that translates DroneNav execution packages into the capabilities of that platform.

Platform-specific functionality should remain isolated to preserve a consistent execution model across all supported platforms.

---

# Development Philosophy

NAVProxy follows several core engineering principles:

* Favor simple, maintainable designs.
* Prefer composition over platform-specific branching.
* Keep platform adapters isolated from business logic.
* Use existing platform capabilities whenever practical.
* Introduce new functionality only when a genuine capability gap exists.
* Design for long-term maintainability and extensibility.

---

# Repository Organization

The repository is organized around logical execution layers rather than specific flight controller implementations.

Typical components include:

* Configuration
* Platform adapters
* Execution services
* Validation services
* Telemetry services
* Status reporting
* Logging
* Common utilities

The internal organization should encourage modularity, testing, and future platform expansion.

---

# Long-Term Vision

NAVProxy provides a stable execution layer between DroneNav governance and supported flight control platforms.

As DroneNav evolves, new operational capabilities can be introduced within NAVProxy while maintaining compatibility with existing platform adapters. This allows DroneNav to continue advancing independently while preserving a clean separation between governance, execution, and aircraft control.

The long-term objective is to provide a robust, extensible execution architecture capable of supporting multiple flight control platforms through a consistent and well-defined interface.
