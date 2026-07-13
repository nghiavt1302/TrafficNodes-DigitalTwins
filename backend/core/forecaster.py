"""
core/forecaster.py — Mô hình Dự báo Kalman Filter 1D
======================================================
Thay thế EMA bằng Kalman Filter 1D cho mỗi hướng giao thông.

Kalman Filter 1D:
    State model:  x(t) = x(t-1) + w,   w ~ N(0, Q)
    Observation:  z(t) = x(t) + v,      v ~ N(0, R)

    Predict:
        x̂⁻ = x̂(t-1)
        P⁻  = P(t-1) + Q

    Update:
        K   = P⁻ / (P⁻ + R)           ← Kalman Gain
        x̂   = x̂⁻ + K × (z - x̂⁻)      ← State estimate
        P   = (1 - K) × P⁻             ← Error covariance

Ưu điểm so với EMA:
    - Ước lượng uncertainty (P) → biết mức độ tin cậy dự báo
    - Tự điều chỉnh Kalman Gain (K) theo tỷ lệ Q/R
    - Phản ứng nhanh hơn với thay đổi đột ngột nhưng vẫn lọc nhiễu
    - Có cơ sở toán học chặt chẽ (Bayesian optimal estimator)

Giải quyết Cold Start bằng Pre-training:
    Chạy offline 30 ngày dữ liệu mô phỏng với chu kỳ đèn 4 pha
    để Kalman Filter hội tụ P → steady-state TRƯỚC KHI client kết nối.
"""

import logging
from typing import Optional

from config import (
    KALMAN_PROCESS_NOISE,
    KALMAN_MEASUREMENT_NOISE,
    PRETRAIN_DAYS,
    DIRECTIONS,
    PHASE_ORDER,
)
from core.generator import TrafficGenerator

logger = logging.getLogger("forecaster")


class KalmanForecaster:
    """
    Bộ dự báo mật độ giao thông dựa trên Kalman Filter 1D.

    Mỗi hướng có bộ lọc Kalman riêng biệt với:
        x: state estimate (mật độ dự báo)
        P: error covariance (độ không chắc chắn)
        K: Kalman gain (tự động điều chỉnh)
    """

    def __init__(
        self,
        Q: float = KALMAN_PROCESS_NOISE,
        R: float = KALMAN_MEASUREMENT_NOISE,
    ) -> None:
        self.Q = Q  # Process noise variance
        self.R = R  # Measurement noise variance

        # State estimate x̂ cho từng hướng
        self.x: dict[str, float] = {d: 0.0 for d in DIRECTIONS}
        # Error covariance P cho từng hướng
        self.P: dict[str, float] = {d: 1.0 for d in DIRECTIONS}
        # Kalman Gain K (lưu lại để gửi cho frontend nếu cần)
        self.K: dict[str, float] = {d: 0.5 for d in DIRECTIONS}

        # Đếm số lần cập nhật
        self.update_count: int = 0

    def update(self, measurements: dict[str, float]) -> dict[str, float]:
        """
        Cập nhật Kalman Filter với measurement mới (mật độ thực đo).

        Kalman Filter 1D — mỗi hướng:
            Predict:  x̂⁻ = x̂,  P⁻ = P + Q
            Update:   K = P⁻/(P⁻+R),  x̂ = x̂⁻ + K(z−x̂⁻),  P = (1−K)P⁻

        Parameters
        ----------
        measurements : dict — mật độ đo được {"NS": 0.7, "EW": 0.3, ...}

        Returns
        -------
        dict[str, float] — state estimate (dự báo) cho từng hướng
        """
        for d in DIRECTIONS:
            z = measurements.get(d, 0.0)

            # ── Predict step ──
            x_pred = self.x[d]                    # State prediction
            P_pred = self.P[d] + self.Q           # Covariance prediction

            # ── Update step ──
            self.K[d] = P_pred / (P_pred + self.R)   # Kalman Gain
            self.x[d] = x_pred + self.K[d] * (z - x_pred)   # State update
            self.P[d] = (1.0 - self.K[d]) * P_pred           # Covariance update

        self.update_count += 1
        return self.get_forecast()

    def get_forecast(self) -> dict[str, float]:
        """Trả về bản sao state estimate hiện tại (dự báo)."""
        return dict(self.x)

    @property
    def values(self) -> dict[str, float]:
        """Alias tương thích — trả về state estimate."""
        return dict(self.x)

    @property
    def uncertainties(self) -> dict[str, float]:
        """Trả về error covariance P (mức độ không chắc chắn)."""
        return dict(self.P)

    @property
    def is_converged(self) -> bool:
        """
        Kiểm tra xem Kalman Filter đã hội tụ chưa.
        Tiêu chí: P < 0.01 cho tất cả hướng (uncertainty đủ nhỏ).
        """
        return all(self.P[d] < 0.01 for d in DIRECTIONS)


def pretrain_forecaster(forecaster: KalmanForecaster, days: int = PRETRAIN_DAYS) -> None:
    """
    PRE-TRAINING: Giải quyết bài toán Cold Start cho Kalman Filter.

    Chạy offline sinh dữ liệu mô phỏng trong `days` ngày,
    nạp toàn bộ vào Kalman Filter. Chu kỳ đèn xoay vòng đầy đủ
    qua 4 pha (NS → EW → SN → WE) để mô hình không bị thiên lệch.

    Sau pre-training, P sẽ hội tụ về steady-state và Kalman Gain
    đạt giá trị ổn định — sẵn sàng cho dữ liệu thực.
    """
    logger.info(f"🧠 Bắt đầu Pre-training Kalman Filter ({days} ngày)...")

    offline_gen = TrafficGenerator()
    TICKS_PER_PHASE = 15

    for day in range(days):
        for hour in range(24):
            for phase_dir in PHASE_ORDER:
                for tick in range(TICKS_PER_PHASE):
                    densities = offline_gen.tick(
                        hour=hour,
                        green_direction=phase_dir,
                    )
                    forecaster.update(densities)

    logger.info(
        f"✅ Pre-training hoàn tất! "
        f"Tổng cập nhật: {forecaster.update_count:,} | "
        f"State: { {d: round(v, 4) for d, v in forecaster.x.items()} } | "
        f"P: { {d: round(v, 6) for d, v in forecaster.P.items()} } | "
        f"K: { {d: round(v, 4) for d, v in forecaster.K.items()} }"
    )
