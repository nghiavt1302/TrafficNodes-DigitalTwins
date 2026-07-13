"""
core/optimizer.py — Bộ tối ưu AI What-If với scipy.optimize
=============================================================
Hàm mục tiêu What-If Predictive (4 hướng):

    J(u) = Σ_i  w_i × (d_i^residual)²  +  λ × Σ_i (Δu_i / S)²

Trong đó d_i^residual mô phỏng vật lý đúng:
    - Xe đến LIÊN TỤC trong toàn bộ chu kỳ T (cả xanh lẫn đỏ)
    - Xe giải tỏa chỉ trong thời gian xanh u_i (Saturation Flow)
    - arrival_rate CÓ hệ số giờ M(h) — phân biệt cao điểm/thấp điểm

Bộ tối ưu sử dụng scipy.optimize.minimize (method=Powell):
    - Tìm nghiệm LIÊN TỤC tối ưu thực sự
    - Không bị giới hạn bởi kịch bản cố định
    - Ràng buộc: MIN_GREEN ≤ u_i ≤ MAX_GREEN

Tham chiếu:
    - LQR (Linear-Quadratic Regulator) cost function
    - HCM Saturation Flow Model
    - Powell's conjugate direction method (gradient-free)
"""

from dataclasses import dataclass

from scipy.optimize import minimize

from config import (
    ALPHA,
    LAMBDA,
    S_NORMALIZE,
    DIRECTION_WEIGHTS,
    DIRECTIONS,
    SATURATION_FLOW_RATE,
    QUEUE_CAPACITY,
    ARRIVAL_RATE_SCALE,
    BASE_DENSITY,
    YELLOW_DURATION,
    ALL_RED_DURATION,
    MIN_GREEN_TIME,
    MAX_GREEN_TIME,
)
from core.generator import get_hour_multiplier


@dataclass
class OptimizationResult:
    """Kết quả tối ưu — chứa kịch bản tốt nhất cho 4 hướng."""
    green_times: dict[str, int]   # Thời gian đèn xanh tối ưu cho 4 hướng
    best_cost: float              # Giá trị J(u) nhỏ nhất
    current_cost: float           # Giá trị J(u) của chu kỳ hiện tại
    improvement: float            # % cải thiện so với hiện tại


def compute_effective_density(
    current_densities: dict[str, float],
    forecast_values: dict[str, float],
    alpha: float = ALPHA,
) -> dict[str, float]:
    """
    Tính mật độ hiệu dụng d_i^eff cho từng hướng.

    Công thức:
        d_i^eff = α × d_i^current + (1 − α) × V_i^forecast

    Kết hợp mật độ thực đo (nặng α=85%) với dự báo Kalman (15%)
    để giảm ảnh hưởng nhiễu đo lường.
    """
    d_eff: dict[str, float] = {}
    for direction in DIRECTIONS:
        d_current = current_densities.get(direction, 0.0)
        v_forecast = forecast_values.get(direction, 0.0)
        d_eff[direction] = alpha * d_current + (1.0 - alpha) * v_forecast
    return d_eff


def compute_cost_j(
    effective_densities: dict[str, float],
    candidate: dict[str, int | float],
    current_plan: dict[str, int],
    hour: int,
    weights: dict[str, float] = DIRECTION_WEIGHTS,
    lam: float = LAMBDA,
    s: float = S_NORMALIZE,
) -> float:
    """
    Hàm mục tiêu J(u) theo mô hình WHAT-IF PREDICTIVE đúng vật lý.

    Mô phỏng mật độ tồn đọng dự kiến sau khi chạy kịch bản ứng viên:

        T_cycle = Σ u_i + N_phases × (yellow + all_red)
        red_time_i = T_cycle - u_i - yellow - all_red

        arrival_total_i = arrival_rate(i, h) × T_cycle     ← XE ĐẾN CẢ CHU KỲ
        clearance_total_i = s_per_sec × min(1, d_eff/0.3) × u_i  ← CHỈ KHI XANH

        d_residual_i = max(0, d_eff_i + arrival_total_i - clearance_total_i)

        J(u) = Σ w_i × d_residual_i² + λ × Σ (Δu_i / S)²
    """
    n_phases = len(DIRECTIONS)
    transition_time = YELLOW_DURATION + ALL_RED_DURATION

    # Hệ số giờ M(h)
    m_h = get_hour_multiplier(hour)

    # Saturation flow per second (đơn vị mật độ)
    s_per_sec = SATURATION_FLOW_RATE / 3600.0 / QUEUE_CAPACITY

    # ── Phần 1: Σ w_i × (d_residual_i)² ──
    density_cost = 0.0
    for direction in DIRECTIONS:
        w_i = weights.get(direction, 1.0)
        d_eff = effective_densities.get(direction, 0.0)
        u_i = float(candidate.get(direction, 40))

        # Tốc độ xe đến mỗi giây (có hệ số giờ M(h))
        arrival_per_sec = BASE_DENSITY.get(direction, 0.3) * m_h * ARRIVAL_RATE_SCALE

        # ═══ KEY INSIGHT: Thời gian đỏ của hướng i = thời gian XANH CỦA CÁC HƯỚNG KHÁC ═══
        # Khi hướng i đang đỏ, lý do là vì hướng khác đang xanh/vàng/toàn đỏ
        # → red_time_i = Σ_{j≠i} u_j + (N-1) × (yellow + all_red)
        # Đây là liên kết đúng: tăng xanh hướng khác = tăng đỏ hướng i
        other_green = sum(
            float(candidate.get(d, 40)) for d in DIRECTIONS if d != direction
        )
        red_time_i = other_green + (n_phases - 1) * transition_time

        # Trong thời gian XANH u_i: giải tỏa hàng chờ ở saturation flow
        queue_cleared = s_per_sec * u_i

        # Trong thời gian ĐỎ: xe tích tụ liên tục
        queue_growth = arrival_per_sec * red_time_i

        # Mật độ tồn đọng sau chu kỳ
        d_residual = max(0.0, d_eff - queue_cleared + queue_growth)

        density_cost += w_i * (d_residual ** 2)

    # ── Phần 2: λ × Σ (Δu_i / S)² — Phạt thay đổi đèn ──
    control_cost = 0.0
    for direction in DIRECTIONS:
        delta_u = float(candidate.get(direction, 40)) - float(current_plan.get(direction, 40))
        control_cost += (delta_u / s) ** 2
    control_cost *= lam

    return density_cost + control_cost


def _proportional_allocation(
    effective_densities: dict[str, float],
    total_green_budget: float,
) -> list[float]:
    """
    Tính phân bổ xanh tỷ lệ thuận với mật độ hiệu dụng.
    Hướng kẹt hơn → được phân nhiều xanh hơn.
    """
    total_d = sum(effective_densities.get(d, 0.01) for d in DIRECTIONS)
    if total_d < 0.01:
        # Nếu tất cả mật độ ~ 0, phân đều
        return [total_green_budget / len(DIRECTIONS)] * len(DIRECTIONS)

    alloc = []
    for d in DIRECTIONS:
        share = effective_densities.get(d, 0.01) / total_d
        g = max(float(MIN_GREEN_TIME), min(float(MAX_GREEN_TIME), share * total_green_budget))
        alloc.append(g)
    return alloc


def optimize(
    current_densities: dict[str, float],
    forecast_values: dict[str, float],
    current_green_times: dict[str, int],
    hour: int = 12,
) -> OptimizationResult:
    """
    Tìm phân bổ thời gian đèn xanh tối ưu bằng scipy.optimize.minimize.

    Chiến lược multi-start:
      1. x0_current: xuất phát từ chu kỳ hiện tại
      2. x0_proportional: phân bổ tỷ lệ thuận với mật độ
      3. x0_aggressive: ưu tiên hướng kẹt nhất

    Chọn nghiệm tốt nhất từ 3 starting points → tránh local minima.

    Method: Nelder-Mead (simplex) — robust, không cần gradient,
    hoạt động tốt với hàm có max() và bounds.
    """
    # Bước 1: Tính mật độ hiệu dụng
    d_eff = compute_effective_density(current_densities, forecast_values)

    # Bước 2: Tính J(u) cho chu kỳ hiện tại (baseline)
    j_current = compute_cost_j(d_eff, current_green_times, current_green_times, hour)

    # Hàm objective
    bounds_lo = float(MIN_GREEN_TIME)
    bounds_hi = float(MAX_GREEN_TIME)

    def objective(u_vec):
        cand = {}
        for i, d in enumerate(DIRECTIONS):
            cand[d] = max(bounds_lo, min(bounds_hi, u_vec[i]))
        return compute_cost_j(d_eff, cand, current_green_times, hour)

    # ── Multi-start: 3 điểm khởi đầu ──
    total_budget = sum(current_green_times[d] for d in DIRECTIONS)

    starting_points = [
        # 1. Chu kỳ hiện tại
        [float(current_green_times[d]) for d in DIRECTIONS],
        # 2. Phân bổ tỷ lệ thuận với mật độ
        _proportional_allocation(d_eff, total_budget),
        # 3. Ưu tiên hướng kẹt nhất (double green budget)
        _proportional_allocation(d_eff, total_budget * 1.3),
    ]

    best_result = None
    best_cost = j_current
    best_x = [float(current_green_times[d]) for d in DIRECTIONS]

    for x0 in starting_points:
        try:
            result = minimize(
                objective,
                x0=x0,
                method="Nelder-Mead",
                options={"maxiter": 300, "xatol": 0.5, "fatol": 1e-6},
            )
            if result.fun < best_cost:
                best_cost = result.fun
                best_x = result.x
        except Exception:
            continue

    # Chuyển kết quả về dict[str, int] (làm tròn + clamp)
    best_candidate: dict[str, int] = {}
    for i, d in enumerate(DIRECTIONS):
        best_candidate[d] = int(round(max(MIN_GREEN_TIME, min(MAX_GREEN_TIME, best_x[i]))))

    # Bước 4: Tính % cải thiện
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

