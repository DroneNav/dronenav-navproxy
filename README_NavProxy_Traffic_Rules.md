# DroneNav Traffic Management Rules

## 1. Purpose

DroneNav Traffic Management governs the simultaneous use of Routes by aircraft operating within Flight Bands.

Traffic management provides two independent forms of traffic control:

1. **Route capacity control** — limits the total number of aircraft simultaneously active on a Route within a Flight Band.
2. **Traffic separation** — assigns aircraft to vertical flight layers and permits reuse of those layers when sufficient longitudinal separation has been established.

Traffic management operates on live operational state maintained in `route_occupancy_state`.

The occupancy table represents current traffic state. It is not a historical flight record.

---

## 2. Traffic Management Scope

Traffic management decisions are scoped to the combination:

```text
Route + Flight Band
```

A Flight Band is an independent governed operating envelope.

Overlapping Flight Bands do not share traffic state or vertical-layer allocation unless an explicit cross-band traffic-management policy is introduced in the future.

---

## 3. Route Occupancy Lifecycle

Each scheduled Flight Execution creates planned Route occupancy records for the Routes it is expected to traverse.

An occupancy progresses through:

```text
planned → active → exited
```

### 3.1 Planned

`planned` indicates that the Flight Execution is expected to traverse the Route but has not yet entered it.

### 3.2 Active

`active` indicates that the aircraft is currently occupying the Route.

An active occupancy MUST contain sufficient current aircraft position information to support Route conformance and traffic-management calculations.

### 3.3 Exited

`exited` indicates that the aircraft has completed traversal of the Route.

### 3.4 Occupancy Persistence

`route_occupancy_state` is ephemeral operational state.

After a Flight Execution completes, its Route occupancy records are removed.

If a Flight Execution is cancelled before flight, its planned occupancy records are removed.

Historical flight activity and telemetry MUST be retained by systems designed for historical storage rather than by the live occupancy table.

---

## 4. Route Capacity

Each Route defines:

```text
maximum_aircraft_capacity
```

This value represents the maximum total number of simultaneously active aircraft permitted on that Route within a single Flight Band.

### 4.1 Unlimited Capacity

```text
maximum_aircraft_capacity = 0
```

means that DroneNav applies no explicit Route-capacity limit.

Traffic separation rules still apply.

### 4.2 Limited Capacity

When:

```text
maximum_aircraft_capacity > 0
```

the number of active occupancies for the Route and Flight Band MUST be less than `maximum_aircraft_capacity` before another aircraft may be admitted.

Route capacity counts all active aircraft regardless of:

* assigned vertical layer;
* longitudinal position;
* clearance status.

An aircraft remains part of Route capacity while its occupancy state is `active`.

---

## 5. Flight Band Vertical Layers

Vertical traffic layers are derived from the governed Flight Band altitude range.

The current policy constants are:

```text
VERTICAL_CONFORMANCE_MARGIN_FT = 10
VERTICAL_LAYER_SEPARATION_FT   = 10
VERTICAL_LAYER_SPACING_FT      = 30
```

where:

```text
VERTICAL_LAYER_SPACING_FT =
    (2 × VERTICAL_CONFORMANCE_MARGIN_FT)
    + VERTICAL_LAYER_SEPARATION_FT
```

### 5.1 Lowest Layer

The lowest usable layer is:

```text
Flight Band minimum AGL + 10 ft
```

### 5.2 Additional Layers

Additional layers occur every 30 ft.

For example, a Flight Band beginning at 50 ft AGL produces:

```text
60 ft
90 ft
120 ft
150 ft
...
```

### 5.3 Upper Margin

A layer MUST NOT be created unless its assigned altitude preserves the required 10-ft conformance margin below the Flight Band maximum altitude.

---

## 6. Flight Altitude Assignment

DroneNav assigns one relative flight altitude to a Flight Execution.

The altitude is selected when NAVProxy requests a Route slot before beginning flight execution.

Once assigned, the same `assigned_relative_altitude_ft` applies to all planned Route occupancy records belonging to that Flight Execution.

NAVProxy does not request a new altitude merely because the aircraft transitions to another Route.

The assigned altitude is subsequently consumed by mission compilation and flight execution.

---

## 7. Initial Vertical-Layer Allocation

When an aircraft requests a Route slot, DroneNav MUST first enforce Route capacity.

If Route capacity is available, DroneNav constructs the valid vertical layers for the requested Flight Band.

DroneNav MUST prefer an unused vertical layer before considering reuse of an occupied layer.

Layers are evaluated from lowest to highest.

The first available unused layer is assigned.

Conceptually:

```text
60 ft  unused → assign 60 ft
90 ft  unused
120 ft unused
150 ft unused
```

A higher layer is not selected merely because it offers greater longitudinal clearance when a lower unused layer exists.

---

## 8. Longitudinal Separation

When all available vertical layers are occupied, DroneNav MAY permit another aircraft to use an existing layer if sufficient longitudinal separation exists.

The current minimum longitudinal separation is:

```text
MINIMUM_LONGITUDINAL_SEPARATION_FT = 500
```

Longitudinal separation is measured as progress along the governed Route geometry from the Route departure point.

Straight-line geographic distance from the departure point MUST NOT be substituted for distance along the Route.

Aircraft position is projected onto the Route geometry to determine longitudinal progress.

---

## 9. Route Minimum Length

Every Route MUST have a geodesic LineString length of at least:

```text
MINIMUM_LONGITUDINAL_SEPARATION_FT
```

Under the current policy:

```text
minimum Route length = 500 ft
```

This is a system-wide Route geometry invariant.

A Route shorter than the minimum longitudinal separation distance MUST be rejected during Route creation.

This invariant ensures that longitudinal traffic separation can be evaluated locally within each Route without reconstructing cumulative progress across multiple Routes.

---

## 10. Trailing Aircraft

Multiple aircraft MAY occupy the same vertical layer when longitudinal separation rules permit it.

When more than one active, uncleared aircraft occupies a layer, the aircraft closest to the Route departure point is the **trailing aircraft** for that layer.

The trailing aircraft controls whether the layer can be reused.

Example:

```text
60-ft layer:

Aircraft A → 700 ft from departure
Aircraft B → 1,200 ft from departure
```

The layer's effective longitudinal clearance is:

```text
700 ft
```

not 1,200 ft.

The aircraft farthest along the Route MUST NOT be used to determine layer clearance when another uncleared aircraft trails behind it.

---

## 11. Clearance State

Route occupancy includes a nullable:

```text
cleared
```

field.

Clearance is independent of the occupancy lifecycle.

`state` describes whether an aircraft is planned, active, or exited.

`cleared` describes whether that occupancy continues to constrain longitudinal reuse of its assigned vertical layer.

An aircraft may therefore be:

```text
state   = active
cleared = true
```

The aircraft is still physically occupying the Route and therefore still counts against Route capacity, but it no longer prevents another aircraft from being assigned the same vertical layer.

A cleared occupancy MUST be ignored when determining which active aircraft controls longitudinal clearance for a layer.

---

## 12. Occupied-Layer Reuse Algorithm

Occupied-layer reuse is evaluated only when no unused vertical layer is available.

DroneNav MUST perform the following procedure:

1. Group active, uncleared occupancies by assigned vertical layer.
2. For each layer, identify the trailing aircraft.
3. Determine that trailing aircraft's longitudinal distance from the Route departure point.
4. Compare the trailing-aircraft distance for all occupied layers.
5. Select the layer whose trailing aircraft is farthest from the Route departure point.
6. Determine whether that distance is at least `MINIMUM_LONGITUDINAL_SEPARATION_FT`.
7. If the minimum separation has been reached:

   * mark the controlling occupancy as cleared;
   * make that vertical layer available for reuse;
   * assign the layer to the requesting Flight Execution.
8. If no layer has sufficient longitudinal clearance, no layer is assigned.

Example:

```text
Layer    Trailing aircraft progress
-----    --------------------------
60 ft             400 ft
90 ft             700 ft
120 ft            900 ft
150 ft            650 ft
```

The preferred reusable layer is:

```text
120 ft
```

because its trailing aircraft has the greatest longitudinal clearance.

Since:

```text
900 ft >= 500 ft
```

the controlling 120-ft occupancy may be cleared and the 120-ft layer reused.

---

## 13. Repeated Layer Reuse

A vertical layer may contain multiple active aircraft over time.

After an occupancy has been cleared, it no longer participates in determining the trailing aircraft for that layer.

The next active, uncleared aircraft closest to the Route departure point becomes the controlling occupancy.

For example:

```text
60-ft layer

Aircraft A → cleared
Aircraft B → 650 ft
Aircraft C → 1,100 ft
```

Aircraft B controls the next reuse decision.

If Aircraft B is cleared and another aircraft enters the layer, the same procedure repeats.

This permits controlled longitudinal sequencing of multiple aircraft within the same vertical layer.

---

## 14. Allocation Concurrency

Route-slot allocation MUST be serialized for each:

```text
Route + Flight Band
```

The allocation decision and resulting state changes MUST occur within one database transaction protected by the Route/Flight-Band allocation lock.

The protected operation includes:

```text
lock
→ inspect Route capacity
→ inspect active occupancy
→ determine vertical-layer availability
→ determine longitudinal clearance when required
→ update clearance state when required
→ assign altitude
→ commit
```

Two simultaneous allocation requests MUST NOT be able to independently observe the same slot as available and both claim it outside the serialized allocation transaction.

---

## 15. No-Slot Behavior

Failure to obtain a traffic slot is not an API failure.

If:

* Route capacity is exhausted; or
* no unused vertical layer exists; and
* no occupied layer has sufficient longitudinal clearance,

the allocation request returns:

```json
{
  "assigned_relative_altitude_ft": null
}
```

with a successful HTTP response.

NAVProxy MUST treat this as normal traffic-management waiting behavior.

NAVProxy waits 10 seconds and retries the slot request.

A 4xx or 5xx response represents an API, request, or system failure rather than ordinary traffic congestion.

---

## 16. Downstream Route Independence

Slot allocation for the current shared Route does not depend on the aircraft having identical downstream destinations or identical complete Flight Paths.

Aircraft may share an initial Route and subsequently diverge onto different Routes.

Longitudinal clearance is evaluated against the governed geometry of the Route currently controlling admission.

The system-wide minimum Route-length invariant ensures that the required longitudinal separation can be established within that Route.

---

## 17. Traffic Management Invariants

The following invariants govern the current DroneNav traffic-management implementation:

```text
1. Traffic state is scoped by Route + Flight Band.

2. Route capacity and traffic separation are independent controls.

3. Every Route is at least the minimum longitudinal separation distance.

4. A Flight Execution receives one assigned relative altitude.

5. All planned Route occupancies for that Flight Execution receive that altitude.

6. Unused vertical layers are always preferred over occupied-layer reuse.

7. Multiple aircraft may share a vertical layer only after longitudinal clearance.

8. The trailing uncleared aircraft controls reuse of a shared layer.

9. Cleared active aircraft still count against Route capacity.

10. Cleared occupancies no longer block vertical-layer reuse.

11. Longitudinal distance is measured along Route geometry.

12. Allocation and clearance changes are serialized transactionally.

13. No available slot produces a normal wait/retry result, not an operational error.
```

---

## 18. Current Policy Constants

The current traffic-management policy is:

```text
VERTICAL_CONFORMANCE_MARGIN_FT       = 10
VERTICAL_LAYER_SEPARATION_FT         = 10
VERTICAL_LAYER_SPACING_FT            = 30
MINIMUM_LONGITUDINAL_SEPARATION_FT   = 500
NAVProxy slot retry interval          = 10 seconds
```

These constants define current DroneNav traffic policy. They SHOULD remain centralized in application configuration rather than duplicated throughout traffic-management implementation.

