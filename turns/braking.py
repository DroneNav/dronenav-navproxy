def calculate_braking_distance_ft(
    initial_speed_ft_s: float,
    target_speed_ft_s: float,
    deceleration_ft_s2: float,
) -> float:
    """Calculate ideal braking distance for a speed reduction."""

    if deceleration_ft_s2 <= 0:
        raise ValueError("Deceleration must be positive.")

    if target_speed_ft_s < 0:
        raise ValueError("Target speed cannot be negative.")

    if initial_speed_ft_s < 0:
        raise ValueError("Initial speed cannot be negative.")

    if target_speed_ft_s >= initial_speed_ft_s:
        return 0.0

    return (
        initial_speed_ft_s ** 2 - target_speed_ft_s ** 2
    ) / (2.0 * deceleration_ft_s2)
