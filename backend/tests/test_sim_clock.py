"""
tests/test_sim_clock.py — Unit tests cho SimulationClock
"""
import sys
sys.path.insert(0, ".")

import pytest
from core.sim_clock import SimulationClock


class TestSimulationClock:
    def test_initial_state(self):
        clock = SimulationClock(start_hour=7, start_minute=30, speed=1.0)
        assert clock.hour == 7
        assert clock.minute == 30
        assert clock.speed == 1.0
        assert clock.paused is False

    def test_tick_advances_time(self):
        clock = SimulationClock(start_hour=7, start_minute=30, speed=1.0)
        clock.tick()
        assert clock.total_sim_seconds == 1.0

    def test_speed_multiplier(self):
        clock = SimulationClock(start_hour=7, start_minute=0, speed=10.0)
        clock.tick(dt_real=1.0)
        assert clock.total_sim_seconds == 10.0

    def test_fast_forward(self):
        clock = SimulationClock(start_hour=7, start_minute=0, speed=60.0)
        # 60 ticks at 60x = 3600 sim-seconds = 1 hour
        for _ in range(60):
            clock.tick(dt_real=1.0)
        assert clock.hour == 8
        assert clock.minute == 0

    def test_jump_to_future(self):
        clock = SimulationClock(start_hour=7, start_minute=0, speed=1.0)
        clock.jump_to(17, 0)
        assert clock.hour == 17
        assert clock.minute == 0

    def test_jump_to_past_wraps_day(self):
        clock = SimulationClock(start_hour=20, start_minute=0, speed=1.0)
        clock.jump_to(8, 0)
        assert clock.hour == 8
        assert clock.day == 2

    def test_pause_resume(self):
        clock = SimulationClock(start_hour=7, start_minute=0, speed=1.0)
        clock.pause()
        assert clock.paused is True
        dt = clock.tick()
        assert dt == 0.0  # No time advances when paused
        clock.resume()
        dt = clock.tick()
        assert dt == 1.0

    def test_time_str_format(self):
        clock = SimulationClock(start_hour=8, start_minute=5, speed=1.0)
        assert clock.time_str == "08:05:00"

    def test_to_dict(self):
        clock = SimulationClock(start_hour=7, start_minute=30, speed=2.0)
        d = clock.to_dict()
        assert d["hour"] == 7
        assert d["minute"] == 30
        assert d["speed"] == 2.0
        assert d["paused"] is False
        assert d["day"] == 1

    def test_wrap_midnight(self):
        clock = SimulationClock(start_hour=23, start_minute=59, speed=1.0)
        for _ in range(120):  # 2 minutes
            clock.tick()
        assert clock.hour == 0
        assert clock.day == 2
