"""
core/generator.py — Module sinh mật độ xe vật lý theo mô hình HCM
===================================================================
Mô hình vật lý sát thực tế:

  1. Xe đến (arrival) LIÊN TỤC bất kể đèn xanh hay đỏ:
       arrival = base(dir) × M(h) × ARRIVAL_RATE_SCALE + ε
       d += arrival  (mỗi giây)

  2. Khi đèn XANH → giải tỏa (clearance) theo Saturation Flow Model:
       clearance = (s / 3600 / Q) × min(1, d / 0.3)
       d -= clearance  (mỗi giây)

  3. Net effect mỗi giây:
       - Đèn ĐỎ:  d_new = d + arrival         (chỉ tăng)
       - Đèn XANH: d_new = d + arrival - clearance
                    → giảm nếu clearance > arrival (bình thường)
                    → tăng nếu arrival > clearance (quá tải)

Tham chiếu:
  - HCM 6th Edition, Chapter 19: Saturation Flow Rate
  - Greenshields' fundamental diagram (flow-density relationship)
"""

import random
from typing import Optional

from config import (
    BASE_DENSITY,
    NOISE_AMPLITUDE,
    SATURATION_FLOW_RATE,
    QUEUE_CAPACITY,
    STARTUP_LOST_TIME,
    ARRIVAL_RATE_SCALE,
    HOUR_MULTIPLIER_ANCHORS,
    DIRECTIONS,
)


def _build_hour_multiplier_table() -> list[float]:
    """
    Xây dựng bảng M(h) cho 24 giờ bằng nội suy tuyến tính
    từ các mốc neo trong HOUR_MULTIPLIER_ANCHORS.

    Trả về list[float] có 24 phần tử — M[0]..M[23].
    """
    anchors = sorted(HOUR_MULTIPLIER_ANCHORS, key=lambda x: x[0])
    table: list[float] = [0.0] * 24

    for h in range(24):
        left = anchors[0]
        right = anchors[-1]
        for idx in range(len(anchors) - 1):
            if anchors[idx][0] <= h <= anchors[idx + 1][0]:
                left = anchors[idx]
                right = anchors[idx + 1]
                break

        if right[0] == left[0]:
            table[h] = left[1]
        else:
            ratio = (h - left[0]) / (right[0] - left[0])
            table[h] = left[1] + ratio * (right[1] - left[1])

    return table


# Bảng hệ số M(h) được tính 1 lần khi import module
_M_TABLE: list[float] = _build_hour_multiplier_table()


def get_hour_multiplier(hour: int) -> float:
    """Trả về hệ số nhân M(h) cho giờ h ∈ [0, 23]."""
    return _M_TABLE[hour % 24]


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Kẹp giá trị vào khoảng [lo, hi]."""
    return max(lo, min(hi, value))


def compute_arrival_rate(direction: str, hour: int) -> float:
    """
    Tính tốc độ xe đến (mỗi giây) cho một hướng.

    Xe đến LIÊN TỤC bất kể đèn xanh hay đỏ.

    Công thức:
        arrival = base(dir) × M(h) × ARRIVAL_RATE_SCALE + ε
        arrival = max(0, arrival)

    Nhiễu ε ~ Uniform(-0.003, +0.003) — biến thiên tự nhiên nhẹ.
    """
    base = BASE_DENSITY.get(direction, 0.3)
    m_h = get_hour_multiplier(hour)
    epsilon = random.uniform(-0.003, 0.003)

    arrival = base * m_h * ARRIVAL_RATE_SCALE + epsilon
    return max(0.0, arrival)


def compute_clearance_rate(current_density: float) -> float:
    """
    Tính tốc độ giải tỏa khi đèn XANH theo mô hình HCM Saturation Flow.

    Mô hình:
      - Saturation flow rate s = 1800 veh/h/lane (HCM 6th Ed.)
      - Chuyển đổi sang đơn vị mật độ/giây:
            s_per_sec = s / 3600 / QUEUE_CAPACITY
      - Khi mật độ < 0.3: xe thưa, giải tỏa tỷ lệ thuận với density
        (không đủ xe để đạt saturation flow)
      - Khi mật độ >= 0.3: đạt ngưỡng bão hòa, giải tỏa ở tốc độ tối đa

    Công thức:
        clearance = s_per_sec × min(1.0, density / 0.3)

    Returns
    -------
    float — lượng mật độ giảm mỗi giây đèn XANH
    """
    s_per_sec = SATURATION_FLOW_RATE / 3600.0 / QUEUE_CAPACITY
    # Hệ số sử dụng: khi xe thưa, không đạt được saturation flow
    utilization = min(1.0, current_density / 0.3)
    return s_per_sec * utilization


class TrafficGenerator:
    """
    Bộ sinh mật độ xe vật lý cho toàn bộ ngã tư.

    Mô hình vật lý sát thực tế:
    - Xe đến LIÊN TỤC mọi lúc (cả khi đèn xanh)
    - Đèn XANH: giải tỏa theo Saturation Flow (phụ thuộc mật độ)
    - Đèn ĐỎ/VÀNG: chỉ có xe đến, không giải tỏa
    - Net density = arrival - clearance (có thể âm hoặc dương)
    """

    def __init__(self) -> None:
        self.densities: dict[str, float] = {d: 0.0 for d in DIRECTIONS}
        # Bộ đếm thời gian xanh liên tục (để tính startup lost time)
        self._green_elapsed: dict[str, float] = {d: 0.0 for d in DIRECTIONS}

    def tick(
        self,
        hour: int,
        green_direction: Optional[str] = None,
        green_directions: Optional[list[str]] = None,
    ) -> dict[str, float]:
        """
        Chạy 1 bước mô phỏng (1 giây).

        Mô hình vật lý mỗi tick:
          1. Xe đến LIÊN TỤC cho TẤT CẢ hướng: d += arrival
          2. Hướng đèn XANH: d -= clearance (Saturation Flow Model)
             - 2 giây đầu: startup lost time → clearance giảm 50%
          3. Clamp d ∈ [0, 1]

        Parameters
        ----------
        hour              : int   — giờ hiện tại (0‑23)
        green_direction   : str   — hướng đang XANH (pha đơn)
        green_directions  : list  — danh sách hướng đang XANH (pha phức tạp)
        """
        greens: set[str] = set()
        if green_directions:
            greens = set(green_directions)
        elif green_direction:
            greens = {green_direction}

        for direction in DIRECTIONS:
            # ═══ BƯỚC 1: Xe đến LIÊN TỤC (bất kể đèn gì) ═══
            arrival = compute_arrival_rate(direction, hour)
            self.densities[direction] += arrival

            if direction in greens:
                # ═══ BƯỚC 2: Đèn XANH → Giải tỏa (Saturation Flow) ═══
                self._green_elapsed[direction] += 1.0

                clearance = compute_clearance_rate(self.densities[direction])

                # Startup lost time: 2 giây đầu giải tỏa chậm 50%
                if self._green_elapsed[direction] <= STARTUP_LOST_TIME:
                    clearance *= 0.5

                self.densities[direction] -= clearance
            else:
                # Đèn ĐỎ/VÀNG: reset bộ đếm xanh (cho lần xanh kế tiếp)
                self._green_elapsed[direction] = 0.0

            # ═══ BƯỚC 3: Clamp [0, 1] ═══
            self.densities[direction] = _clamp(self.densities[direction])

        return dict(self.densities)

    def set_densities(self, densities: dict[str, float]) -> None:
        """Gán trực tiếp mật độ (dùng cho Pre-training offline)."""
        for d in DIRECTIONS:
            if d in densities:
                self.densities[d] = _clamp(densities[d])
