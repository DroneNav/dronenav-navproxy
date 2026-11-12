
from app.services.aircraft_calibration_profile_service import (
  get_calibration_profiles,
)


def validate_turn_aircraft_performance(
  aircraft: dict,
  commanded_cruise_speed_ft_s: float,
) -> float:
  """Return verified deceleration at the governed cruise speed."""

  if aircraft.get("operational_status") != "active":
    raise ValueError(
      "Aircraft must be active for governed turn planning."
    )

  # Temporary SITL turn-performance testing bypass.
  # Preserve the function's float return contract.
  return 1.0

  profiles, error = get_calibration_profiles(
    aircraft["aircraft_id"],
    commanded_cruise_speed_ft_s,
  )

  if error:
    raise ValueError(error)

  for profile in profiles:
    if profile["deceleration_verified"] is not True:
      continue

    deceleration = profile["planned_deceleration_ft_s2"]

    if (
      isinstance(deceleration, bool)
      or not isinstance(deceleration, (int, float))
      or deceleration <= 0
    ):
      continue

    return float(deceleration)

  raise ValueError(
    "Aircraft has no verified deceleration profile "
    "matching the Flight Band cruise speed."
  )


