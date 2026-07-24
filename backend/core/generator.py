"""
core/generator.py — Digital Twin Internal Estimator (8 hướng, PCE)
===================================================================
Module này giờ đóng vai Digital Twin estimator:
  - Nhận dữ liệu sensor từ Physical Twin (có nhiễu)
  - Dự phòng: tự ước lượng khi sensor dropout
  - Hỗ trợ 8 hướng (4 thẳng + 4 rẽ trái protected)
  - PCE (Passenger Car Equivalent) cho xe máy Việt Nam

Tham chiếu:
  - HCM 6th Edition, Chapter 19: Saturation Flow Rate
  - Greenshields' fundamental diagram (flow-density)
"""
from __future__ import annotations

import random

from config import (
    BASE_DENSITY,
    SATURATION_FLOW_RATE,
    LEFT_TURN_SATURATION_FACTOR,
    STARTUP_LOST_TIME,
    ARRIVAL_RATE_SCALE,
    DIRECTIONS,
    LEFT_TURN_DIRECTIONS,
    WEIGHTED_PCE,
)
from core.utils import get_hour_multiplier, clamp, get_queue_capacity


def compute_arrival_rate(direction: str, hour: int) -> float:
    """
    Tính tốc độ xe đến (density/giây) cho một hướng.

    Công thức (có PCE):
        arrival = base(dir) × M(h) × ARRIVAL_RATE_SCALE × WEIGHTED_PCE + ε
    """
    base = BASE_DENSITY.get(direction, 0.1)
    m_h = get_hour_multiplier(hour)
    epsilon = random.uniform(-0.002, 0.002)

    arrival = base * m_h * ARRIVAL_RATE_SCALE * WEIGHTED_PCE + epsilon
    return max(0.0, arrival)


def compute_clearance_rate(current_density: float, direction: str) -> float:
    """
    Tính tốc độ giải tỏa khi đèn XANH.

    Rẽ trái giảm 15% (LEFT_TURN_SATURATION_FACTOR = 0.85).
    """
    capacity = get_queue_capacity(direction)
    s_per_sec = SATURATION_FLOW_RATE / 3600.0 / capacity

    if direction in LEFT_TURN_DIRECTIONS:
        s_per_sec *= LEFT_TURN_SATURATION_FACTOR

    utilization = min(1.0, current_density / 0.3)
    return s_per_sec * utilization


class TrafficGenerator:
    """
    Digital Twin internal estimator — mô hình ước lượng mật độ.

    Hỗ trợ 8 hướng (4 thẳng + 4 rẽ trái protected).
    """

    def __init__(self) -> None:
        self.densities: dict[str, float] = {d: 0.0 for d in DIRECTIONS}
        self._green_elapsed: dict[str, float] = {d: 0.0 for d in DIRECTIONS}

    def tick(
        self,
        hour: int,
        green_directions: list[str] | None = None,
    ) -> dict[str, float]:
        """Chạy 1 bước mô phỏng (prediction mode)."""
        greens = set(green_directions or [])

        for direction in DIRECTIONS:
            arrival = compute_arrival_rate(direction, hour)
            self.densities[direction] += arrival

            if direction in greens:
                self._green_elapsed[direction] += 1.0
                clearance = compute_clearance_rate(self.densities[direction], direction)
                if self._green_elapsed[direction] <= STARTUP_LOST_TIME:
                    clearance *= 0.5
                self.densities[direction] -= clearance
            else:
                self._green_elapsed[direction] = 0.0

            self.densities[direction] = clamp(self.densities[direction])

        return dict(self.densities)

    def update_from_sensor(
        self,
        sensor_readings: dict[str, float | None],
        green_directions: list[str] | None = None,
        hour: int = 12,
    ) -> dict[str, float]:
        """
        Data Assimilation: Cập nhật mô hình từ sensor data.

        Chiến lược:
        - Sensor có dữ liệu → dùng sensor
        - Sensor dropout (None) → prediction mode
        """
        greens = set(green_directions or [])

        for direction in DIRECTIONS:
            reading = sensor_readings.get(direction)

            if reading is not None:
                # Sensor có dữ liệu → dùng trực tiếp
                self.densities[direction] = clamp(reading)
                # Cập nhật green elapsed
                if direction in greens:
                    self._green_elapsed[direction] += 1.0
                else:
                    self._green_elapsed[direction] = 0.0
            else:
                # Sensor dropout → Prediction mode
                arrival = compute_arrival_rate(direction, hour)
                self.densities[direction] += arrival

                if direction in greens:
                    self._green_elapsed[direction] += 1.0
                    clearance = compute_clearance_rate(self.densities[direction], direction)
                    if self._green_elapsed[direction] <= STARTUP_LOST_TIME:
                        clearance *= 0.5
                    self.densities[direction] -= clearance
                else:
                    self._green_elapsed[direction] = 0.0

                self.densities[direction] = clamp(self.densities[direction])

        return dict(self.densities)

    def set_densities(self, densities: dict[str, float]) -> None:
        """Gán trực tiếp mật độ (dùng cho Pre-training)."""
        for d in DIRECTIONS:
            if d in densities:
                self.densities[d] = clamp(densities[d])
