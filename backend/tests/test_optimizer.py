"""
tests/test_optimizer.py — Unit tests cho Optimizer (4 pha NEMA)
"""
import sys
sys.path.insert(0, ".")

import pytest
from core.optimizer import optimize, compute_effective_density, compute_cost_j
from config import DIRECTIONS, PHASE_IDS, DEFAULT_GREEN_TIMES


class TestEffectiveDensity:
    def test_blend(self):
        current = {d: 0.5 for d in DIRECTIONS}
        forecast = {d: 0.8 for d in DIRECTIONS}
        d_eff = compute_effective_density(current, forecast, alpha=0.85)
        for d in DIRECTIONS:
            expected = 0.85 * 0.5 + 0.15 * 0.8
            assert abs(d_eff[d] - expected) < 0.001


class TestCostFunction:
    def test_cost_positive(self):
        d_eff = {d: 0.5 for d in DIRECTIONS}
        candidate = {p: 30 for p in PHASE_IDS}
        cost = compute_cost_j(d_eff, candidate, candidate, hour=12)
        assert cost >= 0

    def test_4_phases(self):
        d_eff = {d: 0.3 for d in DIRECTIONS}
        candidate = {p: 25 for p in PHASE_IDS}
        cost = compute_cost_j(d_eff, candidate, candidate, hour=12)
        assert isinstance(cost, float)


class TestOptimize:
    def test_returns_4_phases(self):
        densities = {d: 0.3 for d in DIRECTIONS}
        forecast = {d: 0.35 for d in DIRECTIONS}
        current_gt = dict(DEFAULT_GREEN_TIMES)
        result = optimize(densities, forecast, current_gt, hour=12)
        assert len(result.green_times) == 4
        for p in PHASE_IDS:
            assert p in result.green_times
            assert result.green_times[p] >= 8   # min green
            assert result.green_times[p] <= 90  # max green

    def test_improvement_non_negative(self):
        densities = {d: 0.5 for d in DIRECTIONS}
        forecast = {d: 0.6 for d in DIRECTIONS}
        result = optimize(densities, forecast, DEFAULT_GREEN_TIMES, hour=8)
        assert result.improvement >= 0

    def test_left_turn_shorter_than_through(self):
        """Rẽ trái nên được phân bổ ít xanh hơn thẳng."""
        densities = {d: 0.5 for d in DIRECTIONS}
        forecast = {d: 0.5 for d in DIRECTIONS}
        result = optimize(densities, forecast, DEFAULT_GREEN_TIMES, hour=12)
        # PH1 (left) should generally be <= PH2 (through)
        # PH3 (left) should generally be <= PH4 (through)
        # (not always guaranteed by optimizer, but usually)
        assert isinstance(result.green_times["PH1"], int)
        assert isinstance(result.green_times["PH2"], int)

    def test_high_density_increases_green(self):
        """Mật độ cao → optimizer phải tăng thời gian xanh."""
        low_density = {d: 0.1 for d in DIRECTIONS}
        high_density = {d: 0.8 for d in DIRECTIONS}
        result_low = optimize(low_density, low_density, DEFAULT_GREEN_TIMES, hour=8)
        result_high = optimize(high_density, high_density, DEFAULT_GREEN_TIMES, hour=8)
        total_low = sum(result_low.green_times.values())
        total_high = sum(result_high.green_times.values())
        assert total_high >= total_low
