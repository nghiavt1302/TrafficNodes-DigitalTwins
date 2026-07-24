"""
core/physical_twin.py — Physical Twin: SUMO + Fallback Simulation
==================================================================
Module này đóng vai trò "Physical Twin" trong kiến trúc Digital Twin.

Hai backend:
  1. SumoPhysicalTwin — dùng Eclipse SUMO qua TraCI (preferred)
     - Microscopic simulation thực sự
     - Mô hình xe máy + ô tô + xe buýt (PCE)
     - 4 pha NEMA Leading Left Turn
  2. SimulatedPhysicalTwin — fallback khi không có SUMO
     - Hàng chờ rời rạc + Poisson arrivals
     - Dùng cho testing/development

Tham chiếu:
  - Eclipse SUMO (Simulation of Urban Mobility) — DLR
  - TraCI (Traffic Control Interface)
  - Cell Transmission Model (Daganzo, 1994)
  - HCM 6th Edition, Chapter 19: Saturation Flow Rate
  - ISO 23247: Digital Twin Framework
"""
from __future__ import annotations

import math
import random
import logging
import os
import threading
from abc import ABC, abstractmethod
from typing import Optional

from config import (
    BASE_DENSITY,
    SATURATION_FLOW_RATE,
    LEFT_TURN_SATURATION_FACTOR,
    QUEUE_CAPACITY,
    QUEUE_CAPACITY_LEFT,
    STARTUP_LOST_TIME,
    ARRIVAL_RATE_SCALE,
    SENSOR_NOISE_STD,
    SENSOR_DROPOUT_RATE,
    DIRECTIONS,
    THROUGH_DIRECTIONS,
    LEFT_TURN_DIRECTIONS,
    PHASES,
    PHASE_IDS,
    WEIGHTED_PCE,
    VEHICLE_MIX,
    SUMO_CFG_PATH,
    SUMO_GUI,
    SUMO_STEP_LENGTH,
)
from core.utils import get_hour_multiplier, get_queue_capacity

logger = logging.getLogger("physical_twin")


# ╔══════════════════════════════════════════════════════════════╗
# ║  ABSTRACT BASE CLASS                                        ║
# ╚══════════════════════════════════════════════════════════════╝

class PhysicalTwinBase(ABC):
    """Interface chung cho mọi Physical Twin backend."""

    def __init__(self) -> None:
        self.densities: dict[str, float] = {d: 0.0 for d in DIRECTIONS}
        self.queue: dict[str, int] = {d: 0 for d in DIRECTIONS}
        self.total_arrivals: dict[str, int] = {d: 0 for d in DIRECTIONS}
        self.total_departures: dict[str, int] = {d: 0 for d in DIRECTIONS}

    @abstractmethod
    def tick(
        self,
        hour: int,
        green_directions: list[str] | None = None,
        phase_id: str | None = None,
        sub_phase: str | None = None,
        sat_factor: float = 1.0,
    ) -> dict[str, float]:
        """Chạy 1 bước mô phỏng, trả về ground truth densities.

        sat_factor: hệ số nhân dòng bão hòa (mưa < 1.0 → xe qua chậm hơn).
        """
        ...

    def read_sensors(self) -> dict[str, float | None]:
        """Đọc dữ liệu sensor ảo — có nhiễu + dropout."""
        readings: dict[str, float | None] = {}
        for direction in DIRECTIONS:
            if random.random() < SENSOR_DROPOUT_RATE:
                readings[direction] = None
                continue
            ground_truth = self.densities[direction]
            noise = random.gauss(0, SENSOR_NOISE_STD)
            measured = max(0.0, min(1.0, ground_truth + noise))
            readings[direction] = round(measured, 4)
        return readings

    def get_ground_truth(self) -> dict[str, float]:
        return dict(self.densities)

    def get_queue_counts(self) -> dict[str, int]:
        return dict(self.queue)

    def get_stats(self) -> dict[str, dict[str, int]]:
        return {
            "arrivals": dict(self.total_arrivals),
            "departures": dict(self.total_departures),
        }


# ╔══════════════════════════════════════════════════════════════╗
# ║  SUMO PHYSICAL TWIN                                         ║
# ╚══════════════════════════════════════════════════════════════╝

class SumoPhysicalTwin(PhysicalTwinBase):
    """
    Physical Twin sử dụng Eclipse SUMO qua TraCI.

    Microscopic simulation thực sự:
    - Mỗi xe là entity riêng biệt (car, motorcycle, bus, truck)
    - Dynamic routing & lane changing
    - Realistic gap acceptance cho rẽ trái
    - 4 pha NEMA signal control

    SUMO chạy trong process riêng, giao tiếp qua TCP (TraCI).
    """

    # Ánh xạ hướng Digital Twin → SUMO edge ID
    _DIRECTION_TO_EDGE: dict[str, str] = {
        "NS": "north_in",      "NS_LEFT": "north_in",
        "SN": "south_in",      "SN_LEFT": "south_in",
        "EW": "east_in",       "EW_LEFT": "east_in",
        "WE": "west_in",       "WE_LEFT": "west_in",
    }

    # Ánh xạ hướng → lane index trong SUMO
    _DIRECTION_TO_LANE: dict[str, int] = {
        "NS": 1,  "NS_LEFT": 2,
        "SN": 1,  "SN_LEFT": 2,
        "EW": 1,  "EW_LEFT": 0,
        "WE": 1,  "WE_LEFT": 0,
    }

    # Ánh xạ phase_id → SUMO TLS phase index (Green phases only)
    _PHASE_TO_TLS_INDEX: dict[str, int] = {
        "PH1": 0,    # Rẽ trái NS/SN
        "PH2": 3,    # Thẳng NS/SN
        "PH3": 6,    # Rẽ trái EW/WE
        "PH4": 9,    # Thẳng EW/WE
    }

    def __init__(self, sumo_cfg: str = SUMO_CFG_PATH) -> None:
        super().__init__()
        self._sumo_cfg = sumo_cfg
        self._connected = False
        self._traci = None
        self._step_count = 0

        self._start_sumo()

    def _start_sumo(self) -> None:
        """Khởi động SUMO simulation."""
        try:
            import traci
            import sumolib

            sumo_binary = sumolib.checkBinary("sumo-gui" if SUMO_GUI else "sumo")

            # Tìm đường dẫn tuyệt đối cho config
            cfg_path = self._sumo_cfg
            if not os.path.isabs(cfg_path):
                cfg_path = os.path.join(os.path.dirname(__file__), "..", cfg_path)
            cfg_path = os.path.abspath(cfg_path)

            if not os.path.exists(cfg_path):
                raise FileNotFoundError(f"SUMO config not found: {cfg_path}")

            traci.start([
                sumo_binary,
                "-c", cfg_path,
                "--step-length", str(SUMO_STEP_LENGTH),
                "--start",
                "--quit-on-end", "false",
            ])

            self._traci = traci
            self._connected = True
            logger.info(f"🚗 SUMO started: {cfg_path}")

        except Exception as e:
            logger.warning(f"⚠️ Cannot start SUMO: {e}. Will use fallback.")
            self._connected = False

    def tick(
        self,
        hour: int,
        green_directions: list[str] | None = None,
        phase_id: str | None = None,
        sub_phase: str | None = None,
        sat_factor: float = 1.0,
    ) -> dict[str, float]:
        """Chạy 1 bước SUMO simulation và thu thập density.

        (SUMO tự mô hình hóa hành vi xe; sat_factor được bỏ qua ở backend này.)
        """
        if not self._connected or self._traci is None:
            return dict(self.densities)

        try:
            traci = self._traci

            # ── Đồng bộ đèn SUMO với Digital Twin ──
            if phase_id and sub_phase:
                self._sync_tls(phase_id, sub_phase)

            # Advance SUMO 1 step
            traci.simulationStep()
            self._step_count += 1

            # Thu thập dữ liệu từ SUMO edges
            for direction in DIRECTIONS:
                edge_id = self._DIRECTION_TO_EDGE[direction]
                lane_idx = self._DIRECTION_TO_LANE[direction]
                lane_id = f"{edge_id}_{lane_idx}"

                try:
                    # Đếm xe trên lane (đã bao gồm cả car + motorcycle)
                    veh_count = traci.lane.getLastStepVehicleNumber(lane_id)

                    # Nếu là hướng thẳng, đếm cả lane 2
                    if direction in THROUGH_DIRECTIONS:
                        lane_id_2 = f"{edge_id}_2"
                        veh_count += traci.lane.getLastStepVehicleNumber(lane_id_2)

                    # Chuyển xe thực → PCU sử dụng WEIGHTED_PCE
                    pcu_count = int(veh_count * WEIGHTED_PCE)

                    capacity = get_queue_capacity(direction)
                    self.queue[direction] = min(capacity, pcu_count)
                    self.densities[direction] = self.queue[direction] / capacity

                except Exception:
                    pass  # Lane might not exist

            # Thống kê
            try:
                arrived = traci.simulation.getArrivedNumber()
                departed = traci.simulation.getDepartedNumber()
                # Phân bổ arrivals/departures theo tỷ lệ base_density
                total_base = sum(BASE_DENSITY.values())
                for d in DIRECTIONS:
                    ratio = BASE_DENSITY.get(d, 0.1) / total_base
                    self.total_arrivals[d] += int(departed * ratio)
                    self.total_departures[d] += int(arrived * ratio)
            except Exception:
                pass

        except Exception as e:
            logger.error(f"SUMO tick error: {e}")

        return dict(self.densities)

    def _sync_tls(self, phase_id: str, sub_phase: str) -> None:
        """Đồng bộ TLS của SUMO với pha đèn của Digital Twin."""
        if not self._connected or self._traci is None:
            return
        try:
            base_idx = self._PHASE_TO_TLS_INDEX.get(phase_id)
            if base_idx is None:
                return
            if sub_phase == "GREEN":
                tls_idx = base_idx
            elif sub_phase == "YELLOW":
                tls_idx = base_idx + 1
            else:  # ALL_RED
                tls_idx = base_idx + 2
            self._traci.trafficlight.setPhase("C", tls_idx)
        except Exception as e:
            logger.warning(f"SUMO TLS sync error: {e}")

    def set_tls_phase(self, phase_id: str, duration: int) -> None:
        """Gửi lệnh thay đổi pha đèn xuống SUMO."""
        if not self._connected or self._traci is None:
            return

        try:
            traci = self._traci
            tls_index = self._PHASE_TO_TLS_INDEX.get(phase_id)
            if tls_index is not None:
                traci.trafficlight.setPhase("C", tls_index)
                traci.trafficlight.setPhaseDuration("C", float(duration))
        except Exception as e:
            logger.warning(f"SUMO TLS error: {e}")

    def close(self) -> None:
        """Đóng kết nối SUMO."""
        if self._connected and self._traci:
            try:
                self._traci.close()
            except Exception:
                pass
            self._connected = False
            logger.info("🛑 SUMO closed.")

    @property
    def is_connected(self) -> bool:
        return self._connected


# ╔══════════════════════════════════════════════════════════════╗
# ║  SIMULATED PHYSICAL TWIN (Fallback)                         ║
# ╚══════════════════════════════════════════════════════════════╝

class SimulatedPhysicalTwin(PhysicalTwinBase):
    """
    Physical Twin mô phỏng nội bộ (fallback khi không có SUMO).

    Mô hình:
    - Hàng chờ rời rạc (đếm xe nguyên - integer, đơn vị PCU)
    - Xe đến theo Poisson process (stochastic)
    - Giải tỏa theo HCM Saturation Flow (deterministic)
    - Hỗ trợ 8 hướng (4 thẳng + 4 rẽ trái)
    - PCE conversion cho xe máy Việt Nam
    """

    def __init__(self) -> None:
        super().__init__()
        self._green_elapsed: dict[str, float] = {d: 0.0 for d in DIRECTIONS}

    def _poisson_arrivals(self, direction: str, hour: int) -> int:
        """
        Sinh số xe đến mỗi giây theo Poisson process.

        Arrivals có xét PCE:
          λ = base × M(h) × ARRIVAL_RATE_SCALE × capacity × WEIGHTED_PCE
        """
        base = BASE_DENSITY.get(direction, 0.1)
        m_h = get_hour_multiplier(hour)
        capacity = get_queue_capacity(direction)
        lam = base * m_h * ARRIVAL_RATE_SCALE * capacity * WEIGHTED_PCE

        if lam <= 0:
            return 0

        # Knuth's Poisson algorithm
        L = math.exp(-lam)
        k = 0
        p = 1.0
        while True:
            k += 1
            p *= random.random()
            if p <= L:
                break
        return k - 1

    def _saturation_departures(self, direction: str, sat_factor: float = 1.0) -> int:
        """Tính số xe rời hàng chờ theo HCM Saturation Flow."""
        q = self.queue[direction]
        if q <= 0:
            return 0

        capacity = get_queue_capacity(direction)
        s_per_sec = SATURATION_FLOW_RATE / 3600.0

        # Rẽ trái chậm hơn (HCM factor 0.85)
        if direction in LEFT_TURN_DIRECTIONS:
            s_per_sec *= LEFT_TURN_SATURATION_FACTOR

        # Thời tiết (mưa → đường trơn, giải tỏa chậm hơn)
        s_per_sec *= sat_factor

        # Utilization factor
        utilization = min(1.0, q / (capacity * 0.3))
        effective_rate = s_per_sec * utilization

        # Startup lost time
        if self._green_elapsed[direction] <= STARTUP_LOST_TIME:
            effective_rate *= 0.5

        if effective_rate <= 0:
            return 0

        floor_count = int(effective_rate)
        remainder = effective_rate - floor_count
        if random.random() < remainder:
            floor_count += 1

        return min(floor_count, q)

    def tick(
        self,
        hour: int,
        green_directions: list[str] | None = None,
        phase_id: str | None = None,
        sub_phase: str | None = None,
        sat_factor: float = 1.0,
    ) -> dict[str, float]:
        """Chạy 1 bước mô phỏng vật lý (1 giây)."""
        greens = set(green_directions or [])

        for direction in DIRECTIONS:
            capacity = get_queue_capacity(direction)

            # Xe đến (Poisson) — LIÊN TỤC bất kể đèn
            arrivals = self._poisson_arrivals(direction, hour)
            self.queue[direction] = min(capacity, self.queue[direction] + arrivals)
            self.total_arrivals[direction] += arrivals

            if direction in greens:
                # Đèn XANH → Giải tỏa (mưa làm chậm qua sat_factor)
                self._green_elapsed[direction] += 1.0
                departures = self._saturation_departures(direction, sat_factor)
                self.queue[direction] = max(0, self.queue[direction] - departures)
                self.total_departures[direction] += departures
            else:
                self._green_elapsed[direction] = 0.0

            # Cập nhật density
            self.densities[direction] = self.queue[direction] / capacity

        return dict(self.densities)


# ╔══════════════════════════════════════════════════════════════╗
# ║  FACTORY FUNCTION                                           ║
# ╚══════════════════════════════════════════════════════════════╝

def create_physical_twin(use_sumo: bool = True) -> PhysicalTwinBase:
    """
    Factory function: tạo Physical Twin phù hợp.

    Parameters
    ----------
    use_sumo : bool — True để thử dùng SUMO, False để dùng fallback

    Returns
    -------
    PhysicalTwinBase — SumoPhysicalTwin nếu SUMO khả dụng, SimulatedPhysicalTwin nếu không
    """
    if use_sumo:
        try:
            twin = SumoPhysicalTwin()
            if twin.is_connected:
                logger.info("✅ Using SUMO Physical Twin (microscopic simulation)")
                return twin
            else:
                logger.info("⚠️ SUMO failed to connect, using Simulated Physical Twin")
                return SimulatedPhysicalTwin()
        except Exception as e:
            logger.warning(f"⚠️ SUMO unavailable ({e}), using Simulated Physical Twin")
            return SimulatedPhysicalTwin()
    else:
        logger.info("📦 Using Simulated Physical Twin (internal model)")
        return SimulatedPhysicalTwin()
