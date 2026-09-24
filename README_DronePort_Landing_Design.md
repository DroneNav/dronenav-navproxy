# DronePort Landing Space Design

## Purpose

This document defines the DroneNav design rules for DronePorts and
DronePort Landing Spaces. It captures the Phase 3 architecture and
operational rules established for representing a DronePort, its fixed
network location, and the individual physical landing positions
contained within it.

The central design principle is:

> **The DronePort POINT is stable network topology. Landing Space POINTs
> represent the actual touchdown locations within that DronePort.**

A Landing Space is therefore a child resource of a DronePort. It does
not replace or relocate the DronePort itself.

------------------------------------------------------------------------

## 1. DronePort Model

A DronePort represents a network location at which an aircraft may take
off or land.

The DronePort geometry is a GeoJSON/PostGIS `Point` representing the
fixed reference point and Route Node location for the DronePort.

The physical operating area of the DronePort is represented by a
diameter around that point.

Current design defaults:

-   DronePort geometry: `POINT`
-   Default DronePort diameter: **30 feet**
-   DronePort POINT: immutable network/reference location
-   DronePort is associated one-to-one with its Route Node

The DronePort POINT must **not** be moved merely to represent a
particular touchdown location. Moving that point would alter DroneNav
network topology and potentially affect connected Routes.

Only appropriate DronePort attributes, such as its diameter, may be
changed without redefining the network location.

------------------------------------------------------------------------

## 2. Landing Space Model

A Landing Space represents an individual physical touchdown position
inside a DronePort.

Each Landing Space:

-   belongs to exactly one DronePort;
-   has its own `POINT` geometry;
-   has a heading;
-   may indicate charging capability;
-   has an operational status;
-   is physically constrained to the parent DronePort area.

The Landing Space geometry is the aircraft touchdown location. Multiple
Landing Spaces allow a single DronePort to support multiple physical
takeoff/landing positions while retaining one stable DronePort/Route
Node reference point.

------------------------------------------------------------------------

## 3. Database Structure

Landing Spaces are stored in:

`droneport_landing_spaces`

The Phase 3 structure is:

  Field                  Purpose
  ---------------------- ----------------------------------
  `landing_space_id`     UUIDv7 primary identifier
  `droneport_id`         Parent DronePort
  `geometry`             `POINT(4326)` touchdown location
  `heading_degrees`      Landing/takeoff heading
  `charging_capable`     Whether charging is available
  `operational_status`   `active` or `inactive`
  `created_by`           Creation audit identity
  `created_at`           Creation timestamp

Defaults:

-   `heading_degrees = 0`
-   `charging_capable = false`
-   `operational_status = active`
-   `created_at = now()`

------------------------------------------------------------------------

## 4. Default Landing Space

Every DronePort must have at least one Landing Space.

When a DronePort is created, the backend automatically creates its
initial/default Landing Space.

The initial Landing Space:

-   belongs to the newly created DronePort;
-   uses the **same POINT geometry as the DronePort**;
-   begins at the center/reference location of the DronePort;
-   is active by default.

The React client does **not** create this initial child record. Default
Landing Space creation is a backend responsibility so the invariant
applies regardless of which client creates a DronePort.

After creation, the initial Landing Space has no permanent special
status. It may be relocated within the DronePort or have its attributes
changed under the same rules as any other Landing Space.

The DronePort POINT itself remains unchanged.

------------------------------------------------------------------------

## 5. Landing Space Count

A DronePort may contain a maximum of:

**16 Landing Spaces total**

The count includes both:

-   active Landing Spaces; and
-   inactive Landing Spaces.

The default Landing Space counts toward the 16-space maximum.

For example:

``` text
1 default Landing Space
+ 15 additional Landing Spaces
= 16 total Landing Spaces
```

Creation of a seventeenth Landing Space must be rejected.

Inactive Landing Spaces remain records belonging to the DronePort and
therefore continue to count toward the maximum.

------------------------------------------------------------------------

## 6. Operational Status

Landing Spaces use two operational states:

-   `active`
-   `inactive`

Landing Spaces are not deleted through the Landing Space API.

There is intentionally no DELETE operation. A Landing Space that should
no longer participate in operations is made inactive.

At least **one active Landing Space must remain** for every DronePort.

An update that would leave a DronePort with zero active Landing Spaces
must therefore be rejected.

Administrative/editor views load both active and inactive Landing Spaces
so that the complete physical configuration of the DronePort remains
visible and manageable.

------------------------------------------------------------------------

## 7. Geometry Rules

### 7.1 Parent containment

Every Landing Space POINT must lie inside the physical circle
represented by its parent DronePort.

The API is authoritative for this validation.

The client may provide a spatial editor that helps the user select a
valid position, but correctness does not depend on client-side geometry
validation.

### 7.2 Duplicate locations

Two Landing Spaces within the same DronePort may not occupy the same
geometry.

The API must reject duplicate Landing Space locations within a
DronePort.

### 7.3 DronePort POINT remains fixed

Relocating a Landing Space changes only:

`droneport_landing_spaces.geometry`

It must not modify:

-   the parent DronePort geometry;
-   the associated Route Node geometry; or
-   connected Route topology.

This separation is fundamental to the design.

------------------------------------------------------------------------

## 8. Heading

Each Landing Space has a heading expressed in degrees.

The API accepts the defined heading range for the Landing Space
resource. The Phase 3 editor presents heading as an integer compass
heading:

**0 through 359 degrees**

Heading is an attribute of the Landing Space, not of the parent
DronePort.

------------------------------------------------------------------------

## 9. Charging Capability

`charging_capable` identifies whether a Landing Space provides aircraft
charging capability.

It is a Boolean attribute:

-   `true` --- charging capability is available;
-   `false` --- charging capability is not available.

The Phase 3 default is `false`.

This attribute is retained on the Landing Space so future operational
assignment can consider aircraft requirements and Landing Space
capabilities without changing the DronePort topology model.

------------------------------------------------------------------------

## 10. API Contract

The Landing Space API provides:

``` text
POST  /api/droneport-landing-spaces
GET   /api/droneport-landing-spaces
GET   /api/droneport-landing-spaces/<landing_space_id>
PATCH /api/droneport-landing-spaces/<landing_space_id>
```

There is no DELETE endpoint.

### Collection filtering

The collection GET supports filtering by:

-   `droneport_id`
-   `operational_status`

The administrative Landing Space editor requests:

``` text
GET /api/droneport-landing-spaces?droneport_id=<droneport_id>
```

It deliberately does **not** apply an active-status filter because both
active and inactive Landing Spaces must be available for editing and
because both count toward the 16-space limit.

------------------------------------------------------------------------

## 11. POST Rules

Creation requires the essential relationship, geometry, and audit
information:

``` json
{
  "droneport_id": "<uuid>",
  "geometry": {
    "type": "Point",
    "coordinates": [longitude, latitude]
  },
  "created_by": "<identity>"
}
```

The client does not need to send values already governed by backend
defaults, including:

-   heading `0`;
-   charging capability `false`;
-   operational status `active`.

Before accepting creation, the API must enforce the DronePort Landing
Space invariants, including:

-   valid parent DronePort;
-   geometry inside the DronePort;
-   no duplicate Landing Space geometry within that DronePort;
-   maximum 16 total Landing Spaces.

------------------------------------------------------------------------

## 12. PATCH Rules

Landing Space updates may modify:

-   `geometry`
-   `heading_degrees`
-   `charging_capable`
-   `operational_status`

Creation/audit identity is not rewritten through PATCH.

Geometry updates move the Landing Space only. They do not move the
parent DronePort.

Operational-status updates must preserve the invariant that the
DronePort has at least one active Landing Space.

------------------------------------------------------------------------

## 13. Administrative UI Design

Landing Spaces are managed as children of a selected DronePort.

They are **not** a separate top-level map editing mode.

The Phase 3 React editor supports:

-   loading all Landing Spaces for a selected DronePort;
-   viewing active and inactive Landing Spaces;
-   changing heading;
-   changing charging capability;
-   changing active/inactive status;
-   adding Landing Spaces;
-   relocating existing Landing Spaces.

There is no delete control.

------------------------------------------------------------------------

## 14. Spatial Placement Editor

A normal geographic map is not well suited to precisely editing multiple
Landing Spaces inside a DronePort only tens of feet across.

DroneNav therefore separates two concerns:

``` text
Main Leaflet map
    = geographic and network context

Landing Space Editor
    = precise local spatial placement within the DronePort
```

The Landing Space Editor presents an enlarged representation of the
actual DronePort circle.

The center crosshair represents the immutable DronePort POINT.

Existing Landing Spaces are plotted relative to that point using their
GPS coordinates. A selected or proposed Landing Space can then be
positioned within the enlarged circle and converted back to geographic
coordinates for API submission.

The editor does **not** enlarge the real DronePort geometry. It is
simply a local-coordinate editing representation of the same physical
area.

------------------------------------------------------------------------

## 15. Main Map Representation

Landing Spaces may also be displayed on the main Leaflet map as small
physical markers.

Because a typical DronePort is approximately 30 feet in diameter,
individual Landing Spaces become difficult to select on the geographic
map as their number increases.

The main map should therefore be considered primarily geographic/network
context.

The enlarged Landing Space Editor is the appropriate interface for
precise Landing Space placement and, as the UI evolves, individual
Landing Space selection.

------------------------------------------------------------------------

## 16. Governance Boundary

Landing Spaces are administrative children of a DronePort.

They are not independently treated as surveyed/governed network
overlays.

The governed network object remains the DronePort and its associated
Route Node. Landing Spaces describe the physical operating configuration
inside that governed DronePort.

This keeps physical touchdown configuration separate from DroneNav
network topology and overlay governance.

------------------------------------------------------------------------

## 17. Operational Assignment

An aviator or normal operational user does not manually choose a Landing
Space as part of the Phase 3 flight-planning workflow.

Landing Space assignment is intended to be transparent to the user and
performed by DroneNav operational logic.

Future assignment logic may consider information such as:

-   Landing Space operational status;
-   occupancy/availability;
-   aircraft characteristics;
-   charging requirements;
-   heading or operational constraints.

Those future policies do not change the underlying Phase 3 data model.

------------------------------------------------------------------------

## 18. Design Invariants

The following rules summarize the design and should be preserved by
future implementations:

1.  A DronePort has one stable geographic POINT associated with network
    topology.
2.  A Landing Space is a child of exactly one DronePort.
3.  Every DronePort has at least one Landing Space.
4.  The backend creates the initial Landing Space automatically.
5.  The initial Landing Space begins at the DronePort POINT.
6.  The initial Landing Space may later be moved without moving the
    DronePort.
7.  A DronePort may contain no more than 16 Landing Spaces total.
8.  Inactive Landing Spaces count toward the 16-space maximum.
9.  At least one Landing Space must remain active.
10. Landing Spaces are made inactive rather than deleted.
11. Every Landing Space POINT must remain within its parent DronePort.
12. Duplicate Landing Space geometries within a DronePort are not
    permitted.
13. Landing Space relocation never relocates the DronePort or Route
    Node.
14. Landing Spaces are administrative children, not independently
    surveyed/governed overlays.
15. Operational Landing Space assignment is a backend concern rather
    than an aviator selection requirement.

------------------------------------------------------------------------

## 19. Architectural Summary

The DronePort/Landing Space distinction allows DroneNav to represent
both network topology and real physical landing infrastructure without
conflating the two.

``` text
Route Network
     |
 Route Node
     |
 DronePort POINT          <- stable network reference
     |
     +-- Landing Space 1  <- physical touchdown POINT
     +-- Landing Space 2  <- physical touchdown POINT
     +-- Landing Space 3
     ...
     +-- Landing Space 16
```

The DronePort remains the stable endpoint through which Routes and
network topology are defined.

Landing Spaces provide the finer-grained physical positions required for
aircraft operations inside that endpoint.

This separation allows Landing Space configuration and future assignment
logic to evolve without destabilizing the DroneNav route network.
