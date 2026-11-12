from .braking import calculate_braking_distance_ft


def calculate_deceleration_distance(
    cruise_speed_ft_s: float,
    turn_speed_ft_s: float,
    deceleration_ft_s2: float,
) -> float:
    """Calculate the distance required to slow before a turn."""

    if cruise_speed_ft_s <= 0:
        raise ValueError("Cruise speed must be positive.")

    if turn_speed_ft_s <= 0:
        raise ValueError("Turn speed must be positive.")

    if turn_speed_ft_s > cruise_speed_ft_s:
        raise ValueError("Turn speed cannot exceed cruise speed.")

    return calculate_braking_distance_ft(
        cruise_speed_ft_s,
        turn_speed_ft_s,
        deceleration_ft_s2,
    )

