"""
core/forecaster.py — Kalman Filter 2D (Constant Velocity Model) — 8 hướng
==========================================================================
Nâng cấp cho 8 hướng (4 thẳng + 4 rẽ trái protected).

Kalman Filter 2D — Constant Velocity Model:
    State vector x = [density, velocity]ᵀ
    - density:  mật độ giao thông hiện tại
    - velocity: tốc độ thay đổi mật độ (dx/dt)

    State transition (F):
        density(t+1) = density(t) + velocity(t) × dt + w₁
        velocity(t+1) = velocity(t) + w₂

    Observation (H):
        z(t) = [1, 0] × x(t) + v
        → Sensor chỉ đo được density

    Forecast:
        density_future = density + velocity × horizon

Tham chiếu:
    - Kalman, R.E. (1960). "A New Approach to Linear Filtering"
    - Bar-Shalom, Y. "Estimation with Applications to Tracking"
"""
from __future__ import annotations

import logging

from config import (
    KALMAN_Q_DENSITY,
    KALMAN_Q_VELOCITY,
    KALMAN_R,
    FORECAST_HORIZON_SEC,
    DIRECTIONS,
)

logger = logging.getLogger("forecaster")


class KalmanForecaster:
    """
    Bộ dự báo mật độ giao thông — Kalman Filter 2D cho 8 hướng.
    """

    def __init__(
        self,
        q_density: float = KALMAN_Q_DENSITY,
        q_velocity: float = KALMAN_Q_VELOCITY,
        R: float = KALMAN_R,
        dt: float = 1.0,
        forecast_horizon: float = FORECAST_HORIZON_SEC,
    ) -> None:
        self.q_d = q_density
        self.q_v = q_velocity
        self.R = R
        self.dt = dt
        self.horizon = forecast_horizon

        # State vector [density, velocity] cho 8 hướng
        self.x: dict[str, list[float]] = {d: [0.0, 0.0] for d in DIRECTIONS}

        # Error covariance P (2×2 stored as [P11, P12, P21, P22])
        self._init_steady_state_P()

        # Kalman Gain K = [K1, K2]
        self.K: dict[str, list[float]] = {d: [0.5, 0.0] for d in DIRECTIONS}

        # Đếm số lần cập nhật
        self.update_count: int = 0

    def _init_steady_state_P(self) -> None:
        """Khởi tạo P ở trạng thái steady-state (DARE)."""
        self.P: dict[str, list[float]] = {}
        for d in DIRECTIONS:
            P = [0.1, 0.0, 0.0, 0.1]
            for _ in range(50):
                P = self._dare_iterate(P)
            self.P[d] = P

    def _dare_iterate(self, P: list[float]) -> list[float]:
        """Một bước DARE iteration cho Kalman 2D."""
        dt = self.dt
        P11, P12, P21, P22 = P
        Pp11 = P11 + dt * P21 + dt * (P12 + dt * P22) + self.q_d
        Pp12 = P12 + dt * P22
        Pp21 = P21 + dt * P22
        Pp22 = P22 + self.q_v

        S = Pp11 + self.R
        K1 = Pp11 / S
        K2 = Pp21 / S

        P_new11 = (1.0 - K1) * Pp11
        P_new12 = (1.0 - K1) * Pp12
        P_new21 = Pp21 - K2 * Pp11
        P_new22 = Pp22 - K2 * Pp12

        return [P_new11, P_new12, P_new21, P_new22]

    def update(self, measurements: dict[str, float]) -> dict[str, float]:
        """
        Cập nhật Kalman Filter 2D với measurement mới cho tất cả 8 hướng.
        """
        dt = self.dt

        for d in DIRECTIONS:
            z = measurements.get(d)
            if z is None:
                self._predict_only(d)
                continue

            x_d, x_v = self.x[d]
            P11, P12, P21, P22 = self.P[d]

            # Predict
            x_pred_d = x_d + dt * x_v
            x_pred_v = x_v

            Pp11 = P11 + dt * P21 + dt * (P12 + dt * P22) + self.q_d
            Pp12 = P12 + dt * P22
            Pp21 = P21 + dt * P22
            Pp22 = P22 + self.q_v

            # Update
            innovation = z - x_pred_d
            S = Pp11 + self.R
            K1 = Pp11 / S
            K2 = Pp21 / S

            self.x[d] = [
                x_pred_d + K1 * innovation,
                x_pred_v + K2 * innovation,
            ]

            self.P[d] = [
                (1.0 - K1) * Pp11,
                (1.0 - K1) * Pp12,
                Pp21 - K2 * Pp11,
                Pp22 - K2 * Pp12,
            ]

            self.K[d] = [K1, K2]

        self.update_count += 1
        return self.get_forecast()

    def _predict_only(self, direction: str) -> None:
        """Chỉ predict step khi sensor dropout."""
        dt = self.dt
        x_d, x_v = self.x[direction]
        P11, P12, P21, P22 = self.P[direction]

        self.x[direction] = [x_d + dt * x_v, x_v]

        self.P[direction] = [
            P11 + dt * P21 + dt * (P12 + dt * P22) + self.q_d,
            P12 + dt * P22,
            P21 + dt * P22,
            P22 + self.q_v,
        ]

    def get_state_estimate(self) -> dict[str, float]:
        """Ước lượng mật độ HIỆN TẠI (đã lọc nhiễu)."""
        return {d: max(0.0, min(1.0, self.x[d][0])) for d in DIRECTIONS}

    def get_velocity_estimate(self) -> dict[str, float]:
        """Ước lượng tốc độ thay đổi (dx/dt)."""
        return {d: self.x[d][1] for d in DIRECTIONS}

    def get_forecast(self, horizon: float | None = None) -> dict[str, float]:
        """DỰ BÁO mật độ TƯƠNG LAI."""
        h = horizon if horizon is not None else self.horizon
        forecast: dict[str, float] = {}
        for d in DIRECTIONS:
            density_now = self.x[d][0]
            velocity = self.x[d][1]
            predicted = density_now + velocity * h
            forecast[d] = max(0.0, min(1.0, predicted))
        return forecast

    @property
    def values(self) -> dict[str, float]:
        return self.get_forecast()

    @property
    def uncertainties(self) -> dict[str, float]:
        return {d: self.P[d][0] for d in DIRECTIONS}

    @property
    def is_converged(self) -> bool:
        return all(self.P[d][0] < 0.01 for d in DIRECTIONS)


def pretrain_forecaster(forecaster: KalmanForecaster, iterations: int = 200) -> None:
    """Light Pre-training: 200 iterations warm-up cho 8 hướng."""
    logger.info(f"Light Pre-training Kalman 2D ({iterations} iters, 8 directions)...")

    from core.utils import get_hour_multiplier
    from config import BASE_DENSITY, ARRIVAL_RATE_SCALE, WEIGHTED_PCE

    for i in range(iterations):
        hour = i % 24
        m_h = get_hour_multiplier(hour)
        fake_measurements: dict[str, float] = {}
        for d in DIRECTIONS:
            base_rate = BASE_DENSITY.get(d, 0.1) * m_h * ARRIVAL_RATE_SCALE * WEIGHTED_PCE
            eq_density = min(1.0, max(0.0, base_rate * 30.0))
            fake_measurements[d] = eq_density

        forecaster.update(fake_measurements)

    logger.info(
        f"Pre-training done! Updates: {forecaster.update_count} | "
        f"Converged: {forecaster.is_converged}"
    )
