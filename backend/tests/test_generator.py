"""
tests/test_generator.py — Unit tests cho Generator (8 hướng, PCE)
"""
import sys
sys.path.insert(0, ".")

import pytest
from core.generator import TrafficGenerator, compute_arrival_rate, compute_clearance_rate
from config import DIRECTIONS, LEFT_TURN_DIRECTIONS


class TestArrivalRate:
    def test_positive(self):
        for d in DIRECTIONS:
            rate = compute_arrival_rate(d, 12)
            assert rate >= 0.0

    def test_peak_higher(self):
        rate_peak = compute_arrival_rate("NS", 8)
        rate_night = compute_arrival_rate("NS", 2)
        # Trung bình peak > night (có noise nên test nhiều lần)
        peak_sum = sum(compute_arrival_rate("NS", 8) for _ in range(100))
        night_sum = sum(compute_arrival_rate("NS", 2) for _ in range(100))
        assert peak_sum > night_sum


class TestClearanceRate:
    def test_positive_when_dense(self):
        for d in DIRECTIONS:
            rate = compute_clearance_rate(0.5, d)
            assert rate > 0.0

    def test_left_turn_slower(self):
        """Tổng PCU/s giải tỏa rẽ trái phải ít hơn thẳng."""
        from config import QUEUE_CAPACITY, QUEUE_CAPACITY_LEFT
        rate_through = compute_clearance_rate(0.5, "NS") * QUEUE_CAPACITY
        rate_left = compute_clearance_rate(0.5, "NS_LEFT") * QUEUE_CAPACITY_LEFT
        assert rate_left < rate_through


class TestTrafficGenerator:
    def test_initial_zero(self):
        gen = TrafficGenerator()
        for d in DIRECTIONS:
            assert gen.densities[d] == 0.0

    def test_8_directions(self):
        gen = TrafficGenerator()
        assert len(gen.densities) == 8

    def test_tick_increases_density(self):
        gen = TrafficGenerator()
        for _ in range(50):
            gen.tick(hour=8, green_directions=[])
        total = sum(gen.densities.values())
        assert total > 0

    def test_sensor_assimilation(self):
        gen = TrafficGenerator()
        readings = {d: 0.5 for d in DIRECTIONS}
        gen.update_from_sensor(readings, hour=12)
        for d in DIRECTIONS:
            assert abs(gen.densities[d] - 0.5) < 0.01

    def test_sensor_dropout_prediction(self):
        gen = TrafficGenerator()
        readings = {d: None for d in DIRECTIONS}
        gen.update_from_sensor(readings, hour=12)
        # Should still work (prediction mode)
        assert all(gen.densities[d] >= 0 for d in DIRECTIONS)
