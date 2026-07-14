"""
core/optimizer.py — Bộ tối ưu AI What-If (4 pha NEMA, PCE)
=============================================================
Hàm mục tiêu What-If Predictive (4 pha NEMA Leading Left Turn):

    J(u) = Σ_p  w_p × Σ_{i∈p} (d_i^residual)²  +  λ × Σ_p (Δu_p / S)²

Nâng cấp v5.0:
  - 4 biến tối ưu (u_PH1, u_PH2, u_PH3, u_PH4) thay vì 2
  - PCE cho arrival rates
  - Left-turn saturation factor
  - Min/max green riêng cho thẳng vs rẽ trái

Tham chiếu:
  - LQR cost function
  - HCM Saturation Flow Model
  - Nelder-Mead simplex method
"""

from dataclasses import dataclass

from scipy.optimize import minimize

from config import (
    ALPHA,
    LAMBDA,
    S_NORMALIZE,
    PHASE_WEIGHTS,
    PHASES,
    PHASE_IDS,
    DIRECTIONS,
    SATURATION_FLOW_RATE,
    LEFT_TURN_SATURATION_FACTOR,
    STARTUP_LOST_TIME,
    ARRIVAL_RATE_SCALE,
    BASE_DENSITY,
    YELLOW_DURATION,
    ALL_RED_DURATION,
    MIN_GREEN_TIME,
    MIN_GREEN_TIME_THROUGH,
    MAX_GREEN_TIME,
    MAX_GREEN_TIME_LEFT,
    WEIGHTED_PCE,
)
from core.utils import get_hour_multiplier, get_queue_capacity


@dataclass
class OptimizationResult:
    """Kết quả tối ưu — 4 pha."""
    green_times: dict[str, int]
    best_cost: float
    current_cost: float
    improvement: float


def compute_effective_density(
    current_densities: dict[str, float],
    forecast_values: dict[str, float],
    alpha: float = ALPHA,
) -> dict[str, float]:
    """d_eff = α × d_current + (1 − α) × V_forecast."""
    d_eff: dict[str, float] = {}
    for direction in DIRECTIONS:
        d_current = current_densities.get(direction, 0.0)
        v_forecast = forecast_values.get(direction, 0.0)
        d_eff[direction] = alpha * d_current + (1.0 - alpha) * v_forecast
    return d_eff


def _get_phase_directions(phase_id: str) -> list[str]:
    for phase in PHASES:
        if phase["id"] == phase_id:
            return phase["directions"]
    return []


def _get_phase_type(phase_id: str) -> str:
    for phase in PHASES:
        if phase["id"] == phase_id:
            return phase.get("type", "THROUGH")
    return "THROUGH"


def _get_min_green(phase_id: str) -> int:
    """Min green phụ thuộc loại pha."""
    return MIN_GREEN_TIME if _get_phase_type(phase_id) == "LEFT" else MIN_GREEN_TIME_THROUGH


def _get_max_green(phase_id: str) -> int:
    """Max green phụ thuộc loại pha."""
    return MAX_GREEN_TIME_LEFT if _get_phase_type(phase_id) == "LEFT" else MAX_GREEN_TIME


def compute_cost_j(
    effective_densities: dict[str, float],
    candidate: dict[str, int | float],
    current_plan: dict[str, int],
    hour: int,
    weights: dict[str, float] = PHASE_WEIGHTS,
    lam: float = LAMBDA,
    s: float = S_NORMALIZE,
) -> float:
    """
    Hàm mục tiêu J(u) — 4 pha NEMA, có PCE.

    CONSISTENT với generator/physical_twin.
    """
    n_phases = len(PHASE_IDS)
    transition_time = YELLOW_DURATION + ALL_RED_DURATION
    m_h = get_hour_multiplier(hour)

    total_cycle = sum(float(candidate.get(p, 30)) for p in PHASE_IDS) + n_phases * transition_time

    density_cost = 0.0
    for phase_id in PHASE_IDS:
        w_p = weights.get(phase_id, 1.0)
        u_p = float(candidate.get(phase_id, 30))
        directions = _get_phase_directions(phase_id)
        is_left = _get_phase_type(phase_id) == "LEFT"

        for direction in directions:
            d_eff = effective_densities.get(direction, 0.0)
            capacity = get_queue_capacity(direction)

            # Arrival (có PCE)
            arrival_per_sec = BASE_DENSITY.get(direction, 0.1) * m_h * ARRIVAL_RATE_SCALE * WEIGHTED_PCE
            arrival_total = arrival_per_sec * total_cycle

            # Clearance (có left-turn factor)
            s_per_sec = SATURATION_FLOW_RATE / 3600.0 / capacity
            if is_left:
                s_per_sec *= LEFT_TURN_SATURATION_FACTOR

            utilization = min(1.0, d_eff / 0.3)
            clearance_rate = s_per_sec * utilization

            effective_green = max(0.0, u_p - STARTUP_LOST_TIME * 0.5)
            clearance_total = clearance_rate * effective_green

            d_residual = max(0.0, d_eff + arrival_total - clearance_total)
            density_cost += w_p * (d_residual ** 2)

    # Switching cost
    control_cost = 0.0
    for phase_id in PHASE_IDS:
        delta_u = float(candidate.get(phase_id, 30)) - float(current_plan.get(phase_id, 30))
        control_cost += (delta_u / s) ** 2
    control_cost *= lam

    return density_cost + control_cost


def _proportional_allocation(
    effective_densities: dict[str, float],
    total_green_budget: float,
) -> list[float]:
    """Phân bổ xanh tỷ lệ thuận với demand mỗi pha."""
    phase_demands: list[float] = []
    for phase_id in PHASE_IDS:
        directions = _get_phase_directions(phase_id)
        demand = sum(effective_densities.get(d, 0.01) for d in directions)
        phase_demands.append(demand)

    total_demand = sum(phase_demands)
    if total_demand < 0.01:
        return [total_green_budget / len(PHASE_IDS)] * len(PHASE_IDS)

    alloc = []
    for i, demand in enumerate(phase_demands):
        pid = PHASE_IDS[i]
        share = demand / total_demand
        lo = float(_get_min_green(pid))
        hi = float(_get_max_green(pid))
        g = max(lo, min(hi, share * total_green_budget))
        alloc.append(g)
    return alloc


def optimize(
    current_densities: dict[str, float],
    forecast_values: dict[str, float],
    current_green_times: dict[str, int],
    hour: int = 12,
) -> OptimizationResult:
    """
    Tìm phân bổ thời gian xanh tối ưu cho 4 pha (4 biến).

    Multi-start Nelder-Mead (3 starting points).
    """
    d_eff = compute_effective_density(current_densities, forecast_values)
    j_current = compute_cost_j(d_eff, current_green_times, current_green_times, hour)

    # Bounds cho từng pha (rẽ trái vs thẳng khác nhau)
    bounds_info = [(float(_get_min_green(p)), float(_get_max_green(p))) for p in PHASE_IDS]

    def objective(u_vec):
        cand = {}
        for i, p in enumerate(PHASE_IDS):
            lo, hi = bounds_info[i]
            cand[p] = max(lo, min(hi, u_vec[i]))
        return compute_cost_j(d_eff, cand, current_green_times, hour)

    # Multi-start: 3 starting points
    total_budget = sum(current_green_times.get(p, 25) for p in PHASE_IDS)

    starting_points = [
        [float(current_green_times.get(p, 25)) for p in PHASE_IDS],
        _proportional_allocation(d_eff, total_budget),
        _proportional_allocation(d_eff, total_budget * 1.3),
    ]

    best_cost = j_current
    best_x = [float(current_green_times.get(p, 25)) for p in PHASE_IDS]

    for x0 in starting_points:
        try:
            result = minimize(
                objective,
                x0=x0,
                method="Nelder-Mead",
                options={"maxiter": 500, "xatol": 0.5, "fatol": 1e-6},
            )
            if result.fun < best_cost:
                best_cost = result.fun
                best_x = result.x
        except Exception:
            continue

    # Convert result
    best_candidate: dict[str, int] = {}
    for i, p in enumerate(PHASE_IDS):
        lo, hi = bounds_info[i]
        best_candidate[p] = int(round(max(lo, min(hi, best_x[i]))))

    if j_current > 1e-9:
        improvement = ((j_current - best_cost) / j_current) * 100.0
    else:
        improvement = 0.0

    return OptimizationResult(
        green_times=best_candidate,
        best_cost=round(best_cost, 6),
        current_cost=round(j_current, 6),
        improvement=round(max(0.0, improvement), 1),
    )
