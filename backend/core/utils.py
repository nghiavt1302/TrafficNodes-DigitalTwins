"""
core/utils.py — Shared utilities cho Digital Twin Level 4 Pro
=============================================================
Chứa các hàm dùng chung giữa các module, tránh duplicate code.

- Hour multiplier table M(h) — built once, used everywhere
- Clamping utility
- Queue capacity helper (through vs left-turn)
"""

import logging
from config import HOUR_MULTIPLIER_ANCHORS, QUEUE_CAPACITY, QUEUE_CAPACITY_LEFT, LEFT_TURN_DIRECTIONS

logger = logging.getLogger("utils")


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


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Kẹp giá trị vào khoảng [lo, hi]."""
    return max(lo, min(hi, value))


def get_queue_capacity(direction: str) -> int:
    """Trả về queue capacity phù hợp cho hướng (thẳng vs rẽ trái)."""
    if direction in LEFT_TURN_DIRECTIONS:
        return QUEUE_CAPACITY_LEFT
    return QUEUE_CAPACITY
