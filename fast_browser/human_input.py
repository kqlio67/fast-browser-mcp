"""Human-like mouse movement and input modeling using Bezier curves and Fitts's law.

Generates realistic mouse trajectories with natural acceleration, deceleration,
curvature, micro-tremor, and approach easing to bypass anti-bot heuristics (Cloudflare,
DataDome, Akamai).
"""

import math
import random
from typing import NamedTuple


class TrajectoryPoint(NamedTuple):
    x: float
    y: float
    delay_ms: float


def _bezier_point(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    t: float,
) -> tuple[float, float]:
    """Calculate point along cubic Bezier curve at parameter t in [0, 1]."""
    u = 1.0 - t
    tt = t * t
    uu = u * u
    uuu = uu * u
    ttt = tt * t

    x = uuu * p0[0] + 3 * uu * t * p1[0] + 3 * u * tt * p2[0] + ttt * p3[0]
    y = uuu * p0[1] + 3 * uu * t * p1[1] + 3 * u * tt * p2[1] + ttt * p3[1]
    return (x, y)


def _ease_in_out(t: float) -> float:
    """Smooth S-curve easing (smoothstep)."""
    return t * t * (3.0 - 2.0 * t)


def generate_human_trajectory(
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
    steps: int = 20,
    jitter: bool = True,
) -> list[TrajectoryPoint]:
    """Generate a sequence of coordinate points with delays simulating human hand motion.

    Args:
        start_x: Current mouse X coordinate.
        start_y: Current mouse Y coordinate.
        end_x: Target mouse X coordinate.
        end_y: Target mouse Y coordinate.
        steps: Number of intermediate movement steps (default 20).
        jitter: Whether to add micro-tremor along the path.

    Returns:
        List of TrajectoryPoint(x, y, delay_ms).
    """
    dx = end_x - start_x
    dy = end_y - start_y
    dist = math.hypot(dx, dy)

    # If already at or very close to target, return single point
    if dist < 2.0:
        return [TrajectoryPoint(round(end_x, 1), round(end_y, 1), 8.0)]

    # Dynamic steps based on distance
    effective_steps = max(steps, int(dist / 25))
    effective_steps = min(effective_steps, 60)

    # Control point 1: offset in the first third of movement
    spread = min(dist * 0.35, 120.0)
    angle = math.atan2(dy, dx)
    perp_angle = angle + (math.pi / 2 if random.random() < 0.5 else -math.pi / 2)

    dev1 = random.uniform(spread * 0.2, spread)
    cp1_x = start_x + dx * 0.3 + math.cos(perp_angle) * dev1
    cp1_y = start_y + dy * 0.3 + math.sin(perp_angle) * dev1

    # Control point 2: gentle correction in the second third
    dev2 = dev1 * random.uniform(0.2, 0.6)
    cp2_x = start_x + dx * 0.75 + math.cos(perp_angle) * dev2
    cp2_y = start_y + dy * 0.75 + math.sin(perp_angle) * dev2

    p0 = (start_x, start_y)
    p1 = (cp1_x, cp1_y)
    p2 = (cp2_x, cp2_y)
    p3 = (end_x, end_y)

    points: list[TrajectoryPoint] = []
    for i in range(1, effective_steps + 1):
        raw_t = i / effective_steps
        t = _ease_in_out(raw_t)
        bx, by = _bezier_point(p0, p1, p2, p3, t)

        # Micro-tremor fades out as we get closer to target for precision landing
        if jitter and raw_t < 0.9:
            noise_scale = (1.0 - raw_t) * 1.2
            bx += random.gauss(0, noise_scale)
            by += random.gauss(0, noise_scale)

        # Variable micro-delay (faster in middle, slower near target)
        delay = random.uniform(5.0, 14.0) if raw_t < 0.8 else random.uniform(12.0, 25.0)
        points.append(TrajectoryPoint(round(bx, 1), round(by, 1), delay))

    # Ensure last point lands exactly on target
    if points:
        points[-1] = TrajectoryPoint(round(end_x, 1), round(end_y, 1), random.uniform(20.0, 40.0))

    return points
