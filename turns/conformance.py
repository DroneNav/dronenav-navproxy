from dataclasses import dataclass


AIRCRAFT_QUALIFICATION_MAX_VIOLATIONS = 10
TURN_CONFORMANCE_HYSTERESIS_FT = 1.0


@dataclass
class TurnConformanceCounter:
  violation_count: int = 0
  violation_active: bool = False
  route_violation_detected: bool = False
  max_offset_ft: float = 0.0

  def evaluate(
    self,
    route_conformance: dict,
    lane_conformance: dict,
  ) -> None:
    """Evaluate one horizontal conformance observation."""

    route_offset = float(route_conformance["distance_ft"])
    lane_offset = float(lane_conformance["distance_ft"])
    lane_limit = float(lane_conformance["half_width_ft"])

    self.max_offset_ft = max(
      self.max_offset_ft,
      route_offset,
      lane_offset,
    )

    route_violation = not route_conformance["inside"]
    lane_violation = not lane_conformance["inside"]

    if route_violation:
      self.route_violation_detected = True

    if route_violation or lane_violation:
      if not self.violation_active:
        self.violation_count += 1
        self.violation_active = True

    elif self.violation_active:
      if lane_offset < (
        lane_limit - TURN_CONFORMANCE_HYSTERESIS_FT
      ):
        self.violation_active = False

  @property
  def qualification_failed(self) -> bool:
    return (
      self.route_violation_detected
      or self.violation_count
      > AIRCRAFT_QUALIFICATION_MAX_VIOLATIONS
    )


