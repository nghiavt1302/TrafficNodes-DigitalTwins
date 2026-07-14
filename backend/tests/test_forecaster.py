"""
tests/test_forecaster.py — Unit tests cho Kalman Forecaster (8 hướng)
"""
import sys
sys.path.insert(0, ".")

import pytest
from core.forecaster import KalmanForecaster, pretrain_forecaster
from config import DIRECTIONS


class TestKalmanForecaster:
    def test_initial_state(self):
        kf = KalmanForecaster()
        assert len(kf.x) == 8
        for d in DIRECTIONS:
            assert kf.x[d] == [0.0, 0.0]

    def test_update_changes_state(self):
        kf = KalmanForecaster()
        measurements = {d: 0.5 for d in DIRECTIONS}
        kf.update(measurements)
        for d in DIRECTIONS:
            assert kf.x[d][0] > 0  # density should be positive

    def test_forecast_range(self):
        kf = KalmanForecaster()
        for _ in range(10):
            kf.update({d: 0.3 for d in DIRECTIONS})
        forecast = kf.get_forecast()
        for d in DIRECTIONS:
            assert 0.0 <= forecast[d] <= 1.0

    def test_velocity_direction(self):
        kf = KalmanForecaster()
        # Feed increasing densities
        for i in range(20):
            kf.update({d: 0.01 * i for d in DIRECTIONS})
        velocity = kf.get_velocity_estimate()
        for d in DIRECTIONS:
            assert velocity[d] > 0  # Should detect upward trend

    def test_convergence(self):
        kf = KalmanForecaster()
        for _ in range(50):
            kf.update({d: 0.5 for d in DIRECTIONS})
        assert kf.is_converged

    def test_pretrain(self):
        kf = KalmanForecaster()
        pretrain_forecaster(kf, iterations=50)
        assert kf.update_count == 50
        assert kf.is_converged

    def test_dropout_increases_uncertainty(self):
        kf = KalmanForecaster()
        for _ in range(10):
            kf.update({d: 0.5 for d in DIRECTIONS})
        p_before = kf.P["NS"][0]
        kf._predict_only("NS")
        p_after = kf.P["NS"][0]
        assert p_after > p_before
