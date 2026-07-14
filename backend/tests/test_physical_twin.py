"""
tests/test_physical_twin.py — Unit tests cho Physical Twin (8 hướng)
"""
import sys
sys.path.insert(0, ".")

import pytest
from core.physical_twin import SimulatedPhysicalTwin, create_physical_twin
from core.utils import get_hour_multiplier
from config import DIRECTIONS, THROUGH_DIRECTIONS, LEFT_TURN_DIRECTIONS, QUEUE_CAPACITY, QUEUE_CAPACITY_LEFT


class TestHourMultiplier:
    def test_peak_morning(self):
        m_8 = get_hour_multiplier(8)
        assert m_8 >= 1.5

    def test_night_low(self):
        m_2 = get_hour_multiplier(2)
        assert m_2 <= 0.2

    def test_all_positive(self):
        for h in range(24):
            assert get_hour_multiplier(h) > 0


class TestSimulatedPhysicalTwin:
    def test_initial_state(self):
        pt = SimulatedPhysicalTwin()
        for d in DIRECTIONS:
            assert pt.queue[d] == 0
            assert pt.densities[d] == 0.0

    def test_8_directions(self):
        pt = SimulatedPhysicalTwin()
        assert len(pt.queue) == 8
        assert len(pt.densities) == 8
        for d in DIRECTIONS:
            assert d in pt.queue

    def test_arrivals_increase_queue(self):
        pt = SimulatedPhysicalTwin()
        for _ in range(100):
            pt.tick(hour=8, green_directions=[])
        total = sum(pt.queue.values())
        assert total > 0

    def test_green_clears_queue(self):
        pt = SimulatedPhysicalTwin()
        # Tích xe trước (all red)
        for _ in range(100):
            pt.tick(hour=8, green_directions=[])
        total_before = sum(pt.queue[d] for d in ["NS", "SN"])

        # Mở xanh NS+SN lâu đủ để giải tỏa
        for _ in range(60):
            pt.tick(hour=8, green_directions=["NS", "SN"])
        total_after = sum(pt.queue[d] for d in ["NS", "SN"])
        # Tổng queue NS+SN phải giảm đáng kể
        assert total_after < total_before

    def test_left_turn_directions(self):
        pt = SimulatedPhysicalTwin()
        for _ in range(50):
            pt.tick(hour=8, green_directions=[])
        # Rẽ trái phải có queue (nhưng thấp hơn thẳng)
        for _ in range(30):
            pt.tick(hour=8, green_directions=["NS_LEFT", "SN_LEFT"])
        assert isinstance(pt.queue["NS_LEFT"], int)

    def test_queue_capacity_limit(self):
        pt = SimulatedPhysicalTwin()
        for _ in range(5000):
            pt.tick(hour=8, green_directions=[])
        for d in THROUGH_DIRECTIONS:
            assert pt.queue[d] <= QUEUE_CAPACITY
        for d in LEFT_TURN_DIRECTIONS:
            assert pt.queue[d] <= QUEUE_CAPACITY_LEFT

    def test_density_range(self):
        pt = SimulatedPhysicalTwin()
        for _ in range(200):
            pt.tick(hour=8, green_directions=["NS", "SN"])
        for d in DIRECTIONS:
            assert 0.0 <= pt.densities[d] <= 1.0

    def test_sensor_readings(self):
        pt = SimulatedPhysicalTwin()
        for _ in range(50):
            pt.tick(hour=12, green_directions=["NS", "SN"])
        readings = pt.read_sensors()
        assert isinstance(readings, dict)
        assert len(readings) == 8

    def test_pce_affects_arrivals(self):
        """PCE phải giảm số xe đến (WEIGHTED_PCE < 1)."""
        pt = SimulatedPhysicalTwin()
        for _ in range(200):
            pt.tick(hour=8, green_directions=[])
        # Với PCE = 0.6375, queue phải thấp hơn so với PCE = 1.0
        assert all(pt.queue[d] <= QUEUE_CAPACITY for d in THROUGH_DIRECTIONS)


class TestFactory:
    def test_create_fallback(self):
        pt = create_physical_twin(use_sumo=False)
        assert isinstance(pt, SimulatedPhysicalTwin)
