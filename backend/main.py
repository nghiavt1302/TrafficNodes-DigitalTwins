"""
main.py — Digital Twin Level 4 Pro — Prescriptive Twin (v5.0)
==============================================================
Kiến trúc Digital Twin đúng chuẩn ISO 23247:

    ┌───────────────────┐     sensor data      ┌────────────────────┐
    │  PHYSICAL TWIN    │ ─────────────────►   │  DIGITAL TWIN      │
    │  (SUMO/Fallback)  │  (có nhiễu/dropout)  │  (Bản sao số)      │
    │                   │                       │                    │
    │  - SUMO microscopic│   control signal    │  - Kalman Filter 2D│
    │  - 4 pha NEMA     │ ◄─────────────────── │  - AI Optimizer    │
    │  - PCE xe máy VN  │   (AUTO-APPLY L4)    │  - State Estimator │
    └───────────────────┘                       └────────────────────┘
            │                                          │
            └──────────── WebSocket ───────────────────┘
                          ↕ Godot 3D Frontend

Nâng cấp v5.0:
  1. Simulation Clock tách biệt wall clock
  2. AUTO-APPLY AI (Prescriptive thật sự)
  3. 4 pha NEMA (Leading Left Turn)
  4. 8 hướng (4 thẳng + 4 rẽ trái)
  5. PCE xe máy Việt Nam
  6. SUMO Physical Twin (với fallback)
  7. Sửa KPI (bỏ heuristic)

Chạy server:
    python main.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import sys
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

# ── Import các module nội bộ ──────────────────────────────────
sys.path.insert(0, ".")
from config import (
    DEFAULT_GREEN_TIMES,
    YELLOW_DURATION,
    ALL_RED_DURATION,
    MIN_GREEN_TIME,
    MIN_GREEN_TIME_THROUGH,
    DENSITY_CUTOFF,
    PHASES,
    PHASE_IDS,
    SATURATION_FLOW_RATE,
    LEFT_TURN_SATURATION_FACTOR,
    MAX_ACCEPTABLE_DELAY,
    HCM_K_FACTOR,
    HCM_I_FACTOR,
    ARRIVAL_RATE_SCALE,
    BASE_DENSITY,
    DIRECTIONS,
    THROUGH_DIRECTIONS,
    LEFT_TURN_DIRECTIONS,
    WEIGHTED_PCE,
    VEHICLE_MIX,
    HOST,
    PORT,
    VERSION,
    ALLOWED_ORIGINS,
    SUMO_ENABLED,
    AUTO_APPLY_ENABLED,
    AUTO_APPLY_MIN_IMPROVEMENT,
    SIM_SPEED_MULTIPLIER,
    SIM_START_HOUR,
    SIM_START_MINUTE,
)
from core.physical_twin import create_physical_twin
from core.generator import TrafficGenerator
from core.forecaster import KalmanForecaster, pretrain_forecaster
from core.optimizer import optimize
from core.sim_clock import SimulationClock
from core.utils import get_hour_multiplier, get_queue_capacity

# ── Logging ───────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-14s | %(levelname)-5s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


# ╔══════════════════════════════════════════════════════════════╗
# ║  TRẠNG THÁI TOÀN CỤC CỦA NGÃ TƯ (Singleton)              ║
# ╚══════════════════════════════════════════════════════════════╝

def _get_phase_for_direction(direction: str) -> str:
    for phase in PHASES:
        if direction in phase["directions"]:
            return phase["id"]
    return PHASE_IDS[0]


def _get_phase_directions(phase_id: str) -> list[str]:
    for phase in PHASES:
        if phase["id"] == phase_id:
            return phase["directions"]
    return []


class IntersectionState:
    """
    Trạng thái ngã tư — Digital Twin Level 4 Pro.

    Máy trạng thái 4 pha NEMA (Leading Left Turn):
      PH1_GREEN → YELLOW → ALL_RED →
      PH2_GREEN → YELLOW → ALL_RED →
      PH3_GREEN → YELLOW → ALL_RED →
      PH4_GREEN → YELLOW → ALL_RED → (repeat)
    """

    def __init__(self) -> None:
        # ── Simulation Clock ──
        self.sim_clock = SimulationClock(
            start_hour=SIM_START_HOUR,
            start_minute=SIM_START_MINUTE,
            speed=SIM_SPEED_MULTIPLIER,
        )

        # ── Thời gian đèn xanh cho 4 PHA ──
        self.green_times: dict[str, int] = dict(DEFAULT_GREEN_TIMES)
        self.yellow_time: int = YELLOW_DURATION
        self.all_red_time: int = ALL_RED_DURATION

        # ── Máy trạng thái 4 pha NEMA ──
        self.phase_index: int = 0
        self.sub_phase: str = "GREEN"
        self.phase_timer: float = 0.0
        self._calc_phase_duration()

        # ── Physical Twin (SUMO hoặc Fallback) ──
        self.physical_twin = create_physical_twin(use_sumo=SUMO_ENABLED)

        # ── Digital Twin modules ──
        self.generator = TrafficGenerator()
        self.forecaster = KalmanForecaster()

        # ── AI ──
        self.last_ai_result: dict[str, int] = dict(DEFAULT_GREEN_TIMES)
        self.last_ai_improvement: float = 0.0
        self.auto_apply_enabled: bool = AUTO_APPLY_ENABLED

        # ── Starvation tracking ──
        self.starvation_counter: dict[str, int] = {p: 0 for p in PHASE_IDS}
        self.next_priority_phase: str | None = None

        # ── Fidelity tracking ──
        self._fidelity_errors: list[float] = []

        # ── asyncio Lock ──
        self.lock = asyncio.Lock()

        # ── Tick counter ──
        self.tick_count: int = 0

    @property
    def current_phase_id(self) -> str:
        return PHASE_IDS[self.phase_index]

    @property
    def current_green_directions(self) -> list[str]:
        return _get_phase_directions(self.current_phase_id)

    @property
    def phase(self) -> str:
        if self.sub_phase == "GREEN":
            return f"{self.current_phase_id}_GREEN"
        elif self.sub_phase == "YELLOW":
            return f"{self.current_phase_id}_YELLOW"
        else:
            return "ALL_RED"

    def _calc_phase_duration(self) -> None:
        if self.sub_phase == "GREEN":
            self.phase_max = float(self.green_times[self.current_phase_id])
        elif self.sub_phase == "YELLOW":
            self.phase_max = float(self.yellow_time)
        else:
            self.phase_max = float(self.all_red_time)

    def _get_min_green_for_current_phase(self) -> int:
        """Min green phụ thuộc loại pha (LEFT vs THROUGH)."""
        for phase in PHASES:
            if phase["id"] == self.current_phase_id:
                if phase.get("type") == "LEFT":
                    return MIN_GREEN_TIME
                return MIN_GREEN_TIME_THROUGH
        return MIN_GREEN_TIME

    def _advance_phase(self) -> None:
        """Chuyển sang sub-phase/pha tiếp theo (4 pha NEMA)."""
        if self.sub_phase == "GREEN":
            self.sub_phase = "YELLOW"
        elif self.sub_phase == "YELLOW":
            self.sub_phase = "ALL_RED"
        else:
            current_phase = self.current_phase_id
            for p in PHASE_IDS:
                if p == current_phase:
                    self.starvation_counter[p] = 0
                else:
                    self.starvation_counter[p] += 1

            if self.next_priority_phase and self.next_priority_phase != current_phase:
                selected_phase = self.next_priority_phase
                logger.info(f"⚡ OVERRIDE: Chuyển sang pha ưu tiên {selected_phase}")
                self.next_priority_phase = None
            else:
                # Round-robin 4 pha
                next_idx = (PHASE_IDS.index(current_phase) + 1) % len(PHASE_IDS)
                selected_phase = PHASE_IDS[next_idx]

            self.phase_index = PHASE_IDS.index(selected_phase)
            self.sub_phase = "GREEN"

        self.phase_timer = 0.0
        self._calc_phase_duration()

    def get_light_state(self, direction: str) -> str:
        current_dirs = self.current_green_directions
        if self.sub_phase == "GREEN" and direction in current_dirs:
            return "XANH"
        elif self.sub_phase == "YELLOW" and direction in current_dirs:
            return "VANG"
        return "DO"

    def get_green_directions(self) -> list[str]:
        if self.sub_phase == "GREEN":
            return self.current_green_directions
        return []

    def time_remaining_for_direction(self, direction: str) -> float:
        dir_phase = _get_phase_for_direction(direction)
        current_phase = self.current_phase_id
        remaining = max(0.0, self.phase_max - self.phase_timer)

        if dir_phase == current_phase:
            return remaining

        # Tính thời gian chờ qua các pha trung gian
        wait = remaining
        if self.sub_phase == "GREEN":
            wait += self.yellow_time + self.all_red_time
        elif self.sub_phase == "YELLOW":
            wait += self.all_red_time

        # Đếm số pha trung gian giữa pha hiện tại và pha đích
        current_idx = PHASE_IDS.index(current_phase)
        target_idx = PHASE_IDS.index(dir_phase)
        if target_idx <= current_idx:
            target_idx += len(PHASE_IDS)
        intermediate_count = target_idx - current_idx - 1

        for i in range(intermediate_count):
            mid_idx = (current_idx + 1 + i) % len(PHASE_IDS)
            mid_phase = PHASE_IDS[mid_idx]
            wait += self.green_times[mid_phase] + self.yellow_time + self.all_red_time

        return wait

    def apply_new_timing(self, new_green_times: dict[str, int]) -> None:
        """FEEDBACK LOOP Level 4: Nhận cấu hình đèn mới."""
        for phase_id in PHASE_IDS:
            if phase_id in new_green_times:
                for phase in PHASES:
                    if phase["id"] == phase_id:
                        if phase.get("type") == "LEFT":
                            max_g = 30
                        else:
                            max_g = 90
                        break
                else:
                    max_g = 90
                min_g = MIN_GREEN_TIME
                self.green_times[phase_id] = max(min_g, min(max_g, new_green_times[phase_id]))

        logger.info(
            "🔄 TIMING UPDATE: " +
            " | ".join(f"{p}={self.green_times[p]}s" for p in PHASE_IDS)
        )

        # Recalculate current phase duration if in GREEN
        if self.sub_phase == "GREEN":
            self._calc_phase_duration()
            if self.phase_timer >= self.phase_max:
                self._advance_phase()

    def _compute_fidelity(self, dt_densities: dict[str, float]) -> float:
        """Fidelity Score: 1 - RMSE(DT, GT)."""
        ground_truth = self.physical_twin.get_ground_truth()
        squared_errors = []
        for d in DIRECTIONS:
            dt_val = dt_densities.get(d, 0.0)
            gt_val = ground_truth.get(d, 0.0)
            squared_errors.append((dt_val - gt_val) ** 2)

        rmse = math.sqrt(sum(squared_errors) / len(squared_errors))

        self._fidelity_errors.append(rmse)
        if len(self._fidelity_errors) > 100:
            self._fidelity_errors.pop(0)

        return max(0.0, min(1.0, 1.0 - rmse))

    def tick(self) -> dict[str, Any]:
        """
        Chạy 1 bước mô phỏng (1 tick).

        Pipeline:
          0. Simulation Clock tick
          1. Pha đèn state machine
          2. Physical Twin tick
          3. Sensor reading
          4. Digital Twin assimilation
          5. Kalman Filter update
          6. AI Optimizer (mỗi 5 tick) + AUTO-APPLY
          7. KPI (HCM 2010 — fixed)
          8. Fidelity Score
        """
        self.tick_count += 1

        # ── 0. Simulation Clock ──
        self.sim_clock.tick()
        current_hour = self.sim_clock.hour

        # ── 1. Pha đèn & Actuated Green Cutoff ──
        min_green = self._get_min_green_for_current_phase()

        if self.sub_phase == "GREEN" and self.phase_timer >= min_green:
            all_clear = all(
                self.generator.densities.get(d, 0.0) < DENSITY_CUTOFF
                for d in self.current_green_directions
            )
            if all_clear:
                logger.info(
                    f"✂️ ACTUATED CUTOFF: Pha {self.current_phase_id}, "
                    f"cắt sớm sau {self.phase_timer:.0f}s"
                )
                self._advance_phase()
            else:
                self.phase_timer += 1.0
                if self.phase_timer >= self.phase_max:
                    self._advance_phase()
        else:
            self.phase_timer += 1.0
            if self.phase_timer >= self.phase_max:
                self._advance_phase()

        green_dirs = self.get_green_directions()

        # ── 2. Physical Twin tick ──
        physical_densities = self.physical_twin.tick(
            hour=current_hour,
            green_directions=green_dirs,
            phase_id=self.current_phase_id,
            sub_phase=self.sub_phase,
        )

        # ── 3. Sensor reading ──
        sensor_data = self.physical_twin.read_sensors()

        # ── 4. Digital Twin assimilation ──
        dt_densities = self.generator.update_from_sensor(
            sensor_readings=sensor_data,
            green_directions=green_dirs,
            hour=current_hour,
        )

        # ── 5. Kalman Filter update ──
        forecast = self.forecaster.update(dt_densities)
        state_estimate = self.forecaster.get_state_estimate()
        velocity_estimate = self.forecaster.get_velocity_estimate()

        # ── 6. AI Optimizer (mỗi 5 tick) + AUTO-APPLY ──
        if self.tick_count % 5 == 0:
            result = optimize(
                current_densities=state_estimate,
                forecast_values=forecast,
                current_green_times=self.green_times,
                hour=current_hour,
            )
            self.last_ai_result = result.green_times
            self.last_ai_improvement = result.improvement

            # AUTO-APPLY (Prescriptive Level 4)
            if (self.auto_apply_enabled and
                    result.improvement > AUTO_APPLY_MIN_IMPROVEMENT):
                self.apply_new_timing(result.green_times)
                logger.info(
                    f"🤖 AUTO-APPLY: "
                    + " | ".join(f"{p}={result.green_times[p]}s" for p in PHASE_IDS)
                    + f" (+{result.improvement:.1f}%)"
                )

        # ── 7. KPI (HCM 2010 — fixed) ──
        kpis = self._compute_kpis(state_estimate, current_hour)

        # ── 8. Fidelity Score ──
        fidelity = self._compute_fidelity(dt_densities)

        # ── 9. Đóng gói JSON payload ──
        payload: dict[str, Any] = {}

        for direction in DIRECTIONS:
            payload[direction] = {
                "density":   round(dt_densities.get(direction, 0.0), 4),
                "light":     self.get_light_state(direction),
                "time_left": round(self.time_remaining_for_direction(direction), 1),
            }

        payload["phase"] = self.phase
        payload["kpis"] = kpis
        payload["forecast"] = {d: round(v, 4) for d, v in forecast.items()}
        payload["velocity"] = {d: round(v, 6) for d, v in velocity_estimate.items()}

        payload["ai_decision"] = {
            "green_times": self.last_ai_result,
            "improvement": self.last_ai_improvement,
        }

        payload["ground_truth"] = {
            d: round(v, 4) for d, v in physical_densities.items()
        }

        payload["queue_counts"] = self.physical_twin.get_queue_counts()
        payload["fidelity"] = round(fidelity * 100, 1)

        # Simulation Clock info
        payload["sim_clock"] = self.sim_clock.to_dict()

        # Auto-apply status
        payload["auto_apply"] = self.auto_apply_enabled

        # Vehicle mix & PCE
        payload["vehicle_mix"] = VEHICLE_MIX
        payload["weighted_pce"] = round(WEIGHTED_PCE, 4)

        return payload

    def _compute_kpis(self, densities: dict[str, float], hour: int) -> dict[str, Any]:
        """
        KPI theo HCM 2010 Delay Model — FIXED (no heuristic).

        d = d1 (uniform) + d2 (incremental)
        throughput = min(demand, capacity) — đúng HCM
        """
        C = sum(self.green_times[p] for p in PHASE_IDS) + len(PHASE_IDS) * (YELLOW_DURATION + ALL_RED_DURATION)
        s_per_hour = SATURATION_FLOW_RATE
        m_h = get_hour_multiplier(hour)

        total_throughput = 0.0
        total_delay = 0.0

        for direction in DIRECTIONS:
            phase_id = _get_phase_for_direction(direction)
            g_i = self.green_times[phase_id]
            capacity_dir = get_queue_capacity(direction)

            green_ratio = g_i / C if C > 0 else 0.5

            # Capacity (PCU/h) — with left-turn factor
            effective_s = s_per_hour
            if direction in LEFT_TURN_DIRECTIONS:
                effective_s *= LEFT_TURN_SATURATION_FACTOR
            capacity = effective_s * green_ratio

            # Arrival rate (PCU/h) — with PCE
            base = BASE_DENSITY.get(direction, 0.1)
            q_per_sec = base * m_h * ARRIVAL_RATE_SCALE * WEIGHTED_PCE
            q_per_hour = q_per_sec * 3600 * capacity_dir

            # Degree of saturation
            x = min(0.98, q_per_hour / capacity) if capacity > 0 else 0.5

            # Throughput = min(demand, capacity) — FIXED (no heuristic)
            actual_throughput = min(q_per_hour, capacity)
            total_throughput += actual_throughput

            # HCM 2010 d1: Uniform Delay
            numerator1 = 0.5 * C * ((1 - green_ratio) ** 2)
            denominator1 = max(0.05, 1.0 - min(1.0, x) * green_ratio)
            d1 = numerator1 / denominator1

            # HCM 2010 d2: Incremental Delay
            T = C / 3600.0
            c_cap = max(1.0, capacity)
            k = HCM_K_FACTOR
            I = HCM_I_FACTOR

            term_inside = (x - 1.0) ** 2 + (8.0 * k * I * x) / (c_cap * T) if T > 0 else 0
            d2 = 900.0 * T * ((x - 1.0) + math.sqrt(max(0.0, term_inside)))
            d2 = max(0.0, min(d2, 120.0))

            delay_i = d1 + d2
            total_delay += delay_i

        avg_delay = total_delay / len(DIRECTIONS)
        throughput_per_min = total_throughput / 60.0
        efficiency = max(0.0, (1.0 - avg_delay / MAX_ACCEPTABLE_DELAY)) * 100.0

        return {
            "throughput": round(throughput_per_min, 1),
            "avgWait":    round(avg_delay, 1),
            "efficiency": round(min(100.0, efficiency), 1),
        }


# ╔══════════════════════════════════════════════════════════════╗
# ║  QUẢN LÝ KẾT NỐI WEBSOCKET                                ║
# ╚══════════════════════════════════════════════════════════════╝

class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"🔗 Client kết nối! Tổng: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(f"❌ Client ngắt. Còn: {len(self.active_connections)}")

    async def broadcast(self, message: str) -> None:
        disconnected: list[WebSocket] = []
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                disconnected.append(connection)
        for conn in disconnected:
            self.disconnect(conn)


# ╔══════════════════════════════════════════════════════════════╗
# ║  KHỞI TẠO FASTAPI + LIFESPAN                               ║
# ╚══════════════════════════════════════════════════════════════╝

state = IntersectionState()
manager = ConnectionManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Khởi động Digital Twin Level 4 Pro v5.0")
    logger.info("=" * 60)
    logger.info("  🏗️  Physical Twin ↔ Digital Twin (ISO 23247)")
    logger.info("  🔄 4 pha NEMA (Leading Left Turn)")
    logger.info("  🏍️  PCE xe máy VN: 0.25 PCU (mix: 65% moto)")
    logger.info(f"  🕐 SimClock: {SIM_START_HOUR:02d}:{SIM_START_MINUTE:02d}, speed={SIM_SPEED_MULTIPLIER}x")
    logger.info(f"  🤖 Auto-apply AI: {'ON' if AUTO_APPLY_ENABLED else 'OFF'}")
    logger.info(f"  🚗 SUMO: {'ENABLED' if SUMO_ENABLED else 'DISABLED (fallback)'}")
    logger.info("=" * 60)

    # Pre-training Kalman
    logger.info("📚 Pre-training Kalman 2D (8 hướng)...")
    pretrain_forecaster(state.forecaster)
    logger.info("✅ Kalman Filter 2D sẵn sàng!")

    # Simulation loop
    simulation_task = asyncio.create_task(_simulation_loop())
    logger.info(f"🌐 WebSocket: ws://{HOST}:{PORT}/traffic-ws")

    yield

    simulation_task.cancel()
    # Cleanup SUMO
    if hasattr(state.physical_twin, 'close'):
        state.physical_twin.close()
    logger.info("🛑 Server đã dừng.")


app = FastAPI(
    title="Digital Twin Level 4 Pro — Smart Traffic Intersection",
    description=(
        "Backend mô phỏng nút giao thông thông minh — Prescriptive Twin.\n"
        "4 pha NEMA, SUMO Physical Twin, PCE xe máy VN, Auto-apply AI."
    ),
    version=VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ╔══════════════════════════════════════════════════════════════╗
# ║  VÒNG LẶP MÔ PHỎNG NỀN                                    ║
# ╚══════════════════════════════════════════════════════════════╝

async def _simulation_loop() -> None:
    logger.info("▶️  Simulation loop bắt đầu")

    while True:
        try:
            async with state.lock:
                payload = state.tick()

            if manager.active_connections:
                message = json.dumps(payload, ensure_ascii=False)
                await manager.broadcast(message)

                if state.tick_count % 10 == 0:
                    avg_d = sum(
                        payload[d]["density"] for d in THROUGH_DIRECTIONS
                    ) / len(THROUGH_DIRECTIONS)
                    gt = state.green_times
                    logger.info(
                        f"📊 #{state.tick_count:>6} | "
                        f"⏰ {state.sim_clock.time_str} | "
                        f"Pha: {state.phase:<12} | "
                        f"TB: {avg_d:.3f} | "
                        f"Đèn: {' '.join(f'{p}={gt[p]}s' for p in PHASE_IDS)} | "
                        f"Fidelity: {payload.get('fidelity', 0):.1f}%"
                    )

            # Sleep interval based on sim speed
            sleep_time = max(0.05, 1.0 / state.sim_clock.speed)
            await asyncio.sleep(sleep_time)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"❗ Lỗi simulation: {e}")
            await asyncio.sleep(1.0)


# ╔══════════════════════════════════════════════════════════════╗
# ║  WEBSOCKET ENDPOINT                                        ║
# ╚══════════════════════════════════════════════════════════════╝

@app.websocket("/traffic-ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)

    try:
        while True:
            raw_data = await websocket.receive_text()
            try:
                message = json.loads(raw_data)
                action = message.get("action", "")

                if action == "APPLY_LIGHTS":
                    green_times_data = message.get("green_times", {})
                    new_times: dict[str, int] = {}
                    for phase_id in PHASE_IDS:
                        if phase_id in green_times_data:
                            new_times[phase_id] = int(green_times_data[phase_id])

                    if new_times:
                        async with state.lock:
                            state.apply_new_timing(new_times)

                    ack = json.dumps({
                        "ack": True,
                        "action": "APPLY_LIGHTS",
                        "green_times": state.green_times,
                    }, ensure_ascii=False)
                    await websocket.send_text(ack)

                elif action == "SET_SPEED":
                    speed = float(message.get("speed", 1.0))
                    async with state.lock:
                        state.sim_clock.set_speed(speed)
                    ack = json.dumps({
                        "ack": True, "action": "SET_SPEED",
                        "speed": state.sim_clock.speed,
                    })
                    await websocket.send_text(ack)

                elif action == "JUMP_TO_HOUR":
                    hour = int(message.get("hour", 8))
                    minute = int(message.get("minute", 0))
                    async with state.lock:
                        state.sim_clock.jump_to(hour, minute)
                    ack = json.dumps({
                        "ack": True, "action": "JUMP_TO_HOUR",
                        "sim_clock": state.sim_clock.to_dict(),
                    })
                    await websocket.send_text(ack)

                elif action == "TOGGLE_AUTO_APPLY":
                    async with state.lock:
                        state.auto_apply_enabled = not state.auto_apply_enabled
                    ack = json.dumps({
                        "ack": True, "action": "TOGGLE_AUTO_APPLY",
                        "auto_apply": state.auto_apply_enabled,
                    })
                    await websocket.send_text(ack)

                elif action == "PAUSE":
                    state.sim_clock.pause()
                elif action == "RESUME":
                    state.sim_clock.resume()

                else:
                    logger.warning(f"⚠️ Unknown action: {action}")

            except json.JSONDecodeError:
                logger.warning(f"⚠️ Invalid JSON: {raw_data[:100]}")

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"❗ WebSocket error: {e}")
        manager.disconnect(websocket)


# ╔══════════════════════════════════════════════════════════════╗
# ║  HTTP ENDPOINTS                                             ║
# ╚══════════════════════════════════════════════════════════════╝

@app.get("/")
async def root():
    return {
        "service": "Digital Twin Level 4 Pro",
        "version": VERSION,
        "architecture": "Physical Twin ↔ Digital Twin (ISO 23247)",
        "phase_model": "4-phase NEMA (Leading Left Turn)",
        "pce": {"motorcycle": 0.25, "weighted": round(WEIGHTED_PCE, 4)},
        "sim_clock": state.sim_clock.to_dict(),
        "auto_apply": state.auto_apply_enabled,
        "status": "running",
        "websocket": f"ws://{HOST}:{PORT}/traffic-ws",
        "tick_count": state.tick_count,
    }


@app.get("/status")
async def get_status():
    dt_densities = state.generator.densities
    gt_densities = state.physical_twin.get_ground_truth()
    forecast = state.forecaster.get_forecast()
    current_hour = state.sim_clock.hour

    return {
        "tick_count": state.tick_count,
        "phase": state.phase,
        "sim_clock": state.sim_clock.to_dict(),
        "digital_twin_densities": dt_densities,
        "physical_twin_densities": gt_densities,
        "queue_counts": state.physical_twin.get_queue_counts(),
        "forecast": forecast,
        "kpis": state._compute_kpis(dt_densities, current_hour),
        "green_times": state.green_times,
        "ai_decision": {
            "green_times": state.last_ai_result,
            "improvement": state.last_ai_improvement,
        },
        "auto_apply": state.auto_apply_enabled,
        "fidelity": round(state._compute_fidelity(dt_densities) * 100, 1),
        "connected_clients": len(manager.active_connections),
    }


# ╔══════════════════════════════════════════════════════════════╗
# ║  ENTRY POINT                                                ║
# ╚══════════════════════════════════════════════════════════════╝

if __name__ == "__main__":
    import uvicorn

    logger.info("=" * 60)
    logger.info("  🚦 DIGITAL TWIN LEVEL 4 PRO — PRESCRIPTIVE TWIN")
    logger.info(f"  📡 Smart Traffic Intersection Backend v{VERSION}")
    logger.info("  🏗️  SUMO + 4-Phase NEMA + PCE + Auto-Apply AI")
    logger.info("=" * 60)

    uvicorn.run(
        app,
        host=HOST,
        port=PORT,
        reload=False,
        log_level="info",
    )
