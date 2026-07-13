"""
main.py — File chạy chính: Digital Twin Level 4 — Prescriptive Twin
=====================================================================
Khởi tạo FastAPI + WebSocket, tích hợp:
  1. Bộ sinh dữ liệu vật lý HCM (TrafficGenerator)
  2. Mô hình dự báo Kalman Filter (KalmanForecaster + Pre-training)
  3. Bộ tối ưu AI What-if scipy (Optimizer) — 4 hướng độc lập
  4. WebSocket broadcast mỗi giây
  5. Feedback Loop Level 4 (nhận lệnh từ Client)
  6. KPI theo HCM/Webster

Chạy server:
    python main.py
"""

import asyncio
import json
import logging
import math
import sys
from contextlib import asynccontextmanager
from datetime import datetime
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
    DENSITY_CUTOFF,
    PHASE_ORDER,
    SATURATION_FLOW_RATE,
    QUEUE_CAPACITY,
    MAX_ACCEPTABLE_DELAY,
    ARRIVAL_RATE_SCALE,
    BASE_DENSITY,
    DIRECTIONS,
    HOST,
    PORT,
)
from core.generator import TrafficGenerator, get_hour_multiplier
from core.forecaster import KalmanForecaster, pretrain_forecaster
from core.optimizer import optimize

# ── Logging ───────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-12s | %(levelname)-5s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


# ╔══════════════════════════════════════════════════════════════╗
# ║  TRẠNG THÁI TOÀN CỤC CỦA NGÃ TƯ (Singleton)              ║
# ╚══════════════════════════════════════════════════════════════╝

class IntersectionState:
    """
    Trạng thái toàn cục của ngã tư mô phỏng.

    Máy trạng thái 4 pha — mỗi pha gồm 3 bước:
      [DIR]_GREEN → YELLOW → ALL_RED → (pha tiếp theo)

    Mỗi hướng có green time riêng biệt, có thể điều chỉnh độc lập.
    """

    def __init__(self) -> None:
        # ── Thời gian đèn xanh cho từng hướng (giây) ──
        self.green_times: dict[str, int] = dict(DEFAULT_GREEN_TIMES)
        self.yellow_time: int = YELLOW_DURATION
        self.all_red_time: int = ALL_RED_DURATION

        # ── Máy trạng thái pha đèn ──
        # phase_index: vị trí trong PHASE_ORDER (0=NS, 1=EW, 2=SN, 3=WE)
        # sub_phase: "GREEN" | "YELLOW" | "ALL_RED"
        self.phase_index: int = 0
        self.sub_phase: str = "GREEN"
        self.phase_timer: float = 0.0
        self._calc_phase_duration()

        # ── Module vật lý & AI ──
        self.generator = TrafficGenerator()
        self.forecaster = KalmanForecaster()

        # ── Kết quả AI gần nhất ──
        self.last_ai_result: dict[str, int] = dict(DEFAULT_GREEN_TIMES)
        self.last_ai_improvement: float = 0.0

        # ── Bộ điều khiển cảm ứng AI (Adaptive Control State) ──
        self.starvation_counter: dict[str, int] = {d: 0 for d in DIRECTIONS}
        self.next_priority_dir: str | None = None

        # ── Tick counter ──
        self.tick_count: int = 0

    @property
    def current_phase_dir(self) -> str:
        """Hướng đang ở pha hiện tại (NS/EW/SN/WE)."""
        return PHASE_ORDER[self.phase_index]

    @property
    def phase(self) -> str:
        """Tên pha dạng chuỗi cho frontend: 'NS_GREEN', 'YELLOW', 'ALL_RED'..."""
        if self.sub_phase == "GREEN":
            return f"{self.current_phase_dir}_GREEN"
        elif self.sub_phase == "YELLOW":
            return f"{self.current_phase_dir}_YELLOW"
        else:
            return "ALL_RED"

    def _calc_phase_duration(self) -> None:
        """Tính thời gian tối đa cho sub-phase hiện tại."""
        if self.sub_phase == "GREEN":
            self.phase_max = float(self.green_times[self.current_phase_dir])
        elif self.sub_phase == "YELLOW":
            self.phase_max = float(self.yellow_time)
        else:  # ALL_RED
            self.phase_max = float(self.all_red_time)

    def _advance_phase(self) -> None:
        """Chuyển sang sub-phase/pha tiếp theo (CẢM ỨNG ĐỘNG AI - Urgency Score)."""
        if self.sub_phase == "GREEN":
            self.sub_phase = "YELLOW"
        elif self.sub_phase == "YELLOW":
            self.sub_phase = "ALL_RED"
        else:  # ALL_RED → chuyển sang pha hướng tiếp theo theo độ khẩn cấp (Urgency Score)
            current_dir = self.current_phase_dir
            # Cập nhật bộ đếm đói (starvation): hướng vừa chạy được reset = 0, các hướng khác +1
            for d in DIRECTIONS:
                if d == current_dir:
                    self.starvation_counter[d] = 0
                else:
                    self.starvation_counter[d] += 1

            # Chọn hướng tiếp theo
            if self.next_priority_dir and self.next_priority_dir in DIRECTIONS and self.next_priority_dir != current_dir:
                selected_dir = self.next_priority_dir
                logger.info(f"⚡ ĐUỔI PHA ƯU TIÊN AI: Chọn ngay {selected_dir} do lệnh Áp Dụng Khẩn Cấp!")
                self.next_priority_dir = None
            else:
                # Kiểm tra xem có hướng nào bị chờ quá lâu không (Starvation Protection >= 2 lượt)
                starved_dirs = [d for d in DIRECTIONS if d != current_dir and self.starvation_counter[d] >= 2]
                if starved_dirs:
                    # Chọn hướng bị chờ lâu nhất
                    selected_dir = max(starved_dirs, key=lambda d: self.starvation_counter[d])
                    logger.info(f"🛡️ CHỐNG CHẾT ĐÓI: Ưu tiên mở hướng {selected_dir} (đã chờ {self.starvation_counter[selected_dir]} lượt)")
                else:
                    # Tính điểm khẩn cấp Urgency Score cho các hướng đang đỏ
                    # Urgency = Mật độ * 0.6 + Dự báo EMA * 0.3 + Chờ lâu * 0.1
                    densities = self.generator.densities
                    forecast = self.forecaster.values
                    candidate_dirs = [d for d in DIRECTIONS if d != current_dir]
                    
                    best_urgency = -1.0
                    selected_dir = candidate_dirs[0]
                    for d in candidate_dirs:
                        u_score = densities.get(d, 0.0) * 0.6 + forecast.get(d, 0.0) * 0.3 + (self.starvation_counter[d] * 0.1)
                        if u_score > best_urgency:
                            best_urgency = u_score
                            selected_dir = d
                    
                    if best_urgency > 0.4:
                        logger.info(f"🧠 AI DYNAMIC PHASE: Chọn hướng {selected_dir} có Urgency Score cao nhất ({best_urgency:.2f})")

            self.phase_index = PHASE_ORDER.index(selected_dir)
            self.sub_phase = "GREEN"

        self.phase_timer = 0.0
        self._calc_phase_duration()

    def get_light_state(self, direction: str) -> str:
        """
        Trả về trạng thái đèn (XANH / VANG / DO) cho một hướng cụ thể.
        """
        current_dir = self.current_phase_dir
        if self.sub_phase == "GREEN" and direction == current_dir:
            return "XANH"
        elif self.sub_phase == "YELLOW" and direction == current_dir:
            return "VANG"
        return "DO"

    def get_green_directions(self) -> list[str]:
        """Trả về danh sách các hướng đang ở pha XANH."""
        if self.sub_phase == "GREEN":
            return [self.current_phase_dir]
        return []

    def time_remaining_for_direction(self, direction: str) -> float:
        """
        Tính time_left RIÊNG cho từng hướng dựa trên dự kiến thứ tự pha động của AI.
        """
        current_dir = self.current_phase_dir
        remaining_in_current = max(0.0, self.phase_max - self.phase_timer)

        if direction == current_dir:
            return remaining_in_current

        # Dự báo thứ tự 3 hướng tiếp theo sẽ được mở XANH dựa trên độ ưu tiên/starvation
        densities = self.generator.densities
        other_dirs = [d for d in DIRECTIONS if d != current_dir]
        
        if self.next_priority_dir and self.next_priority_dir in other_dirs:
            first_next = self.next_priority_dir
            remaining_others = [d for d in other_dirs if d != first_next]
            sorted_others = sorted(remaining_others, key=lambda d: densities.get(d, 0.0) + self.starvation_counter[d]*0.2, reverse=True)
            predicted_queue = [first_next] + sorted_others
        else:
            predicted_queue = sorted(other_dirs, key=lambda d: densities.get(d, 0.0) + self.starvation_counter[d]*0.2, reverse=True)

        if direction not in predicted_queue:
            return remaining_in_current + 45.0

        pos = predicted_queue.index(direction)
        wait = remaining_in_current
        
        # Thêm thời gian vàng và đỏ của pha hiện tại
        if self.sub_phase == "GREEN":
            wait += self.yellow_time + self.all_red_time
        elif self.sub_phase == "YELLOW":
            wait += self.all_red_time

        # Thêm thời gian của các pha xếp hàng trước hướng này
        for i in range(pos):
            inter_dir = predicted_queue[i]
            wait += self.green_times[inter_dir] + self.yellow_time + self.all_red_time

        return wait

    def apply_new_timing(self, new_green_times: dict[str, int]) -> None:
        """
        FEEDBACK LOOP Level 4:
        Nhận cấu hình đèn mới từ client và KÍCH HOẠT OVERRIDE CÓ KIỂM TRA AN TOÀN.
        Tuân thủ tiêu chuẩn MUTCD: KHÔNG CẮT PHA XANH TRƯỚC MIN_GREEN_TIME.
        """
        for direction in DIRECTIONS:
            if direction in new_green_times:
                self.green_times[direction] = max(MIN_GREEN_TIME, min(120, new_green_times[direction]))

        logger.info(
            f"🔄 FEEDBACK LOOP: Cập nhật chu kỳ đèn → "
            + " | ".join(f"{d}={self.green_times[d]}s" for d in DIRECTIONS)
        )
        
        # ── OVERRIDE CÓ KIỂM TRA AN TOÀN (MUTCD-compliant) ──
        # Tìm hướng được AI đề xuất mở xanh lâu nhất (hoặc đang kẹt xe nhất)
        target_dir = max(DIRECTIONS, key=lambda d: self.green_times[d] * 2.0 + self.generator.densities.get(d, 0.0) * 100.0)
        current_dir = self.current_phase_dir
        
        if target_dir != current_dir:
            self.next_priority_dir = target_dir
            if self.sub_phase == "GREEN":
                if self.phase_timer >= MIN_GREEN_TIME:
                    # ĐỦ AN TOÀN: đã chạy xanh >= MIN_GREEN → cắt được
                    logger.info(f"🚀 SAFE OVERRIDE: Cắt pha {current_dir}_GREEN (đã chạy {self.phase_timer:.0f}s >= {MIN_GREEN_TIME}s) → mở {target_dir}!")
                    self.sub_phase = "YELLOW"
                    self.phase_timer = 0.0
                    self._calc_phase_duration()
                else:
                    # CHƯA ĐỦ MIN_GREEN → chỉ đặt ưu tiên, chờ đủ thời gian
                    logger.info(f"⏳ QUEUED OVERRIDE: Đặt ưu tiên {target_dir}, chờ MIN_GREEN ({self.phase_timer:.0f}/{MIN_GREEN_TIME}s)")
        elif self.sub_phase == "GREEN":
            # Đang ở đúng hướng ưu tiên AI → áp dụng số giây xanh mới
            self._calc_phase_duration()
            if self.phase_timer >= self.phase_max:
                self._advance_phase()

    def tick(self) -> dict[str, Any]:
        """
        Chạy 1 bước mô phỏng (1 giây) và trả về toàn bộ payload JSON cho WebSocket broadcast.
        """
        self.tick_count += 1
        now = datetime.now()
        current_hour = now.hour

        # ── 1. Cập nhật pha đèn & Kiểm tra Cắt Sớm (Actuated Green Cutoff) ──
        if self.sub_phase == "GREEN" and self.phase_timer >= MIN_GREEN_TIME:
            current_dir = self.current_phase_dir
            # Nếu mật độ hướng hiện tại đã giải tỏa xong (< DENSITY_CUTOFF) -> tự động chuyển Vàng
            if self.generator.densities.get(current_dir, 0.0) < DENSITY_CUTOFF:
                logger.info(f"✂️ ACTUATED CUTOFF: Vắng xe hướng {current_dir} (mật độ {self.generator.densities.get(current_dir, 0.0):.2f}), cắt sớm sau {self.phase_timer:.0f}s!")
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

        # ── 2. Sinh mật độ xe ──
        densities = self.generator.tick(
            hour=current_hour,
            green_directions=green_dirs,
        )

        # ── 3. Cập nhật dự báo Kalman Filter ──
        forecast = self.forecaster.update(densities)

        # ── 4. Chạy AI tối ưu (mỗi 5 giây để giảm tải) ──
        if self.tick_count % 5 == 0:
            result = optimize(
                current_densities=densities,
                forecast_values=forecast,
                current_green_times=self.green_times,
                hour=current_hour,
            )
            self.last_ai_result = result.green_times
            self.last_ai_improvement = result.improvement

        # ── 5. Tính KPI theo HCM / Webster ──
        kpis = self._compute_kpis(densities, current_hour)

        # ── 6. Đóng gói JSON payload (KHỚP VỚI FRONTEND GODOT) ──
        payload: dict[str, Any] = {}

        # Trạng thái 4 hướng — mỗi hướng có time_left RIÊNG
        for direction in DIRECTIONS:
            payload[direction] = {
                "density":   round(densities[direction], 4),
                "light":     self.get_light_state(direction),
                "time_left": round(self.time_remaining_for_direction(direction), 1),
            }

        # Pha hiện tại (Frontend Godot kiểm tra trường "phase")
        payload["phase"] = self.phase

        # Chỉ số KPI
        payload["kpis"] = kpis

        # Dự báo Kalman Filter
        payload["forecast"] = {d: round(v, 4) for d, v in forecast.items()}

        # Quyết định AI — 4 hướng đầy đủ
        payload["ai_decision"] = {
            "green_times": self.last_ai_result,
            "improvement": self.last_ai_improvement,
        }

        return payload

    def _compute_kpis(self, densities: dict[str, float], hour: int) -> dict[str, Any]:
        """
        Tính KPI theo mô hình HCM (Highway Capacity Manual) / Webster.

        1. Throughput (xe/phút):
            c_i = s × (g_i / C)              ← capacity mỗi hướng (HCM)
            throughput = Σ c_i × (1 - d_i)   ← actual throughput (giảm khi kẹt)
            Chuyển đổi từ veh/h → veh/min

        2. Average Delay (giây) — Webster's formula (1958):
            d = C(1-λ)² / 2(1-λx)  +  x² / 2q(1-x)
            Trong đó:
              C = cycle length
              λ = g/C (green ratio)
              x = degree of saturation (v/c ratio)
              q = arrival rate (veh/s)
            Đơn giản hóa cho mô phỏng real-time.

        3. Efficiency (%):
            eff = max(0, 1 - avg_delay / MAX_ACCEPTABLE_DELAY) × 100
        """
        # Tổng chu kỳ C
        C = sum(self.green_times[d] for d in DIRECTIONS) + len(DIRECTIONS) * (YELLOW_DURATION + ALL_RED_DURATION)
        s_per_hour = SATURATION_FLOW_RATE  # 1800 veh/h/lane

        total_throughput = 0.0
        total_delay = 0.0
        m_h = get_hour_multiplier(hour)

        for direction in DIRECTIONS:
            g_i = self.green_times[direction]
            d_i = densities.get(direction, 0.0)

            # ── Green ratio λ ──
            green_ratio = g_i / C if C > 0 else 0.25

            # ── Capacity c_i (veh/h) ──
            capacity = s_per_hour * green_ratio

            # ── Arrival rate q (veh/h) — có hệ số giờ M(h) ──
            base = BASE_DENSITY.get(direction, 0.3)
            q_per_sec = base * m_h * ARRIVAL_RATE_SCALE
            q_per_hour = q_per_sec * 3600 * QUEUE_CAPACITY  # chuyển từ density/s → veh/h

            # ── Degree of saturation x = v/c ──
            x = min(0.98, q_per_hour / capacity) if capacity > 0 else 0.5

            # ── Throughput hướng i (veh/h) ──
            # Throughput thực = capacity × min(1, demand/capacity) × (1 - spillback_factor)
            actual_throughput = capacity * min(1.0, x) * max(0.1, 1.0 - d_i * 0.5)
            total_throughput += actual_throughput

            # ── Webster's delay (giây) ──
            # d = C(1-λ)² / 2(1-λ·x) + x²/(2·q·(1-x))
            numerator1 = C * ((1 - green_ratio) ** 2)
            denominator1 = 2.0 * max(0.05, 1 - green_ratio * x)
            uniform_delay = numerator1 / denominator1

            # Overflow delay (random delay component)
            q_per_sec_abs = max(0.001, q_per_sec * QUEUE_CAPACITY)
            denominator2 = 2.0 * q_per_sec_abs * max(0.02, 1 - x)
            overflow_delay = (x ** 2) / denominator2

            delay_i = uniform_delay + min(overflow_delay, 120.0)  # Cap tại 120s
            total_delay += delay_i

        # ── Tổng hợp KPI ──
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
    """Quản lý danh sách các WebSocket client đang kết nối."""

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"🔗 Client kết nối! Tổng: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(f"❌ Client ngắt kết nối. Còn lại: {len(self.active_connections)}")

    async def broadcast(self, message: str) -> None:
        """Gửi tin nhắn đến tất cả client đang kết nối."""
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

# Singleton trạng thái ngã tư
state = IntersectionState()
manager = ConnectionManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Vòng đời ứng dụng FastAPI:
    1. Startup: Pre-train Kalman Filter, khởi động vòng lặp mô phỏng
    2. Shutdown: Dọn dẹp tài nguyên
    """
    logger.info("🚀 Khởi động Digital Twin Level 4 — Prescriptive Twin")
    logger.info("=" * 60)

    # ── PRE-TRAINING: Giải quyết Cold Start ──
    logger.info("📚 Đang Pre-train Kalman Filter (30 ngày dữ liệu offline)...")
    pretrain_forecaster(state.forecaster)
    logger.info("✅ Kalman Filter đã sẵn sàng (hội tụ)!")
    logger.info("=" * 60)

    # ── Khởi động vòng lặp mô phỏng chạy nền ──
    simulation_task = asyncio.create_task(_simulation_loop())
    logger.info(f"🌐 WebSocket endpoint: ws://{HOST}:{PORT}/traffic-ws")
    logger.info("⏳ Đang chờ client kết nối...")

    yield  # ← Server đang chạy

    # ── Shutdown ──
    simulation_task.cancel()
    logger.info("🛑 Server đã dừng.")


app = FastAPI(
    title="Digital Twin Level 4 — Smart Traffic Intersection",
    description="Backend mô phỏng nút giao thông thông minh đạt cấp Prescriptive Twin",
    version="2.0.0",
    lifespan=lifespan,
)

# ── CORS cho phép mọi nguồn (dev) ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ╔══════════════════════════════════════════════════════════════╗
# ║  VÒNG LẶP MÔ PHỎNG NỀN (Simulation Loop)                  ║
# ╚══════════════════════════════════════════════════════════════╝

async def _simulation_loop() -> None:
    """
    Vòng lặp chính: mỗi giây (1 tick) thực hiện:
    1. Tính toán trạng thái ngã tư mới
    2. Broadcast JSON đến tất cả WebSocket client
    """
    logger.info("▶️  Vòng lặp mô phỏng bắt đầu (1 tick/giây)")

    while True:
        try:
            # Tính toán 1 tick
            payload = state.tick()

            # Broadcast nếu có client
            if manager.active_connections:
                message = json.dumps(payload, ensure_ascii=False)
                await manager.broadcast(message)

                # Log mỗi 10 giây
                if state.tick_count % 10 == 0:
                    avg_d = sum(
                        payload[d]["density"] for d in DIRECTIONS
                    ) / len(DIRECTIONS)
                    gt = state.green_times
                    logger.info(
                        f"📊 Tick #{state.tick_count:>6} | "
                        f"Pha: {state.phase:<12} | "
                        f"Mật độ TB: {avg_d:.3f} | "
                        f"Đèn: {' '.join(f'{d}={gt[d]}s' for d in DIRECTIONS)} | "
                        f"AI improve: +{state.last_ai_improvement:.1f}%"
                    )

            # Chờ 1 giây
            await asyncio.sleep(1.0)

        except asyncio.CancelledError:
            logger.info("⏹️  Vòng lặp mô phỏng đã dừng.")
            break
        except Exception as e:
            logger.error(f"❗ Lỗi trong vòng lặp mô phỏng: {e}")
            await asyncio.sleep(1.0)


# ╔══════════════════════════════════════════════════════════════╗
# ║  WEBSOCKET ENDPOINT                                        ║
# ╚══════════════════════════════════════════════════════════════╝

@app.websocket("/traffic-ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint chính: /traffic-ws

    - Khi client kết nối → thêm vào danh sách broadcast
    - Lắng nghe tin nhắn ngược (FEEDBACK LOOP Level 4)
    - Khi client ngắt → loại bỏ khỏi danh sách
    """
    await manager.connect(websocket)

    try:
        while True:
            # Lắng nghe tin nhắn từ client (Feedback Loop)
            raw_data = await websocket.receive_text()

            try:
                message = json.loads(raw_data)
                action = message.get("action", "")

                if action == "APPLY_LIGHTS":
                    # ── FEEDBACK LOOP Level 4 — 4 hướng độc lập ──
                    new_times: dict[str, int] = {}
                    for direction in DIRECTIONS:
                        key = f"{direction.lower()}_green"
                        if key in message:
                            new_times[direction] = int(message[key])
                        elif direction in message.get("green_times", {}):
                            new_times[direction] = int(message["green_times"][direction])

                    if new_times:
                        state.apply_new_timing(new_times)

                    # Gửi xác nhận lại cho client
                    ack = json.dumps({
                        "ack": True,
                        "action": "APPLY_LIGHTS",
                        "green_times": state.green_times,
                        "message": "Đã cập nhật chu kỳ đèn cho " + ", ".join(
                            f"{d}={state.green_times[d]}s" for d in DIRECTIONS
                        ),
                    }, ensure_ascii=False)
                    await websocket.send_text(ack)

                    logger.info(
                        f"✅ FEEDBACK: Nhận lệnh từ client → "
                        + " | ".join(f"{d}={state.green_times[d]}s" for d in DIRECTIONS)
                    )
                else:
                    logger.warning(f"⚠️  Nhận action không xác định: {action}")

            except json.JSONDecodeError:
                logger.warning(f"⚠️  Tin nhắn không phải JSON: {raw_data[:100]}")

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"❗ Lỗi WebSocket: {e}")
        manager.disconnect(websocket)


# ╔══════════════════════════════════════════════════════════════╗
# ║  HTTP ENDPOINTS (REST API phụ trợ)                          ║
# ╚══════════════════════════════════════════════════════════════╝

@app.get("/")
async def root():
    """Trang chủ — kiểm tra server đang chạy."""
    return {
        "service": "Digital Twin Level 4 — Smart Traffic Intersection",
        "version": "3.0.0 (HCM/Webster/Kalman/scipy)",
        "status": "running",
        "websocket": f"ws://{HOST}:{PORT}/traffic-ws",
        "tick_count": state.tick_count,
        "phase": state.phase,
        "kalman_converged": state.forecaster.is_converged,
    }


@app.get("/status")
async def get_status():
    """Trả về trạng thái hiện tại của ngã tư (REST API)."""
    densities = state.generator.densities
    forecast = state.forecaster.get_forecast()
    avg_d = sum(densities.values()) / len(densities)

    current_hour = datetime.now().hour
    return {
        "tick_count": state.tick_count,
        "phase": state.phase,
        "densities": densities,
        "forecast": forecast,
        "kpis": state._compute_kpis(densities, current_hour),
        "green_times": state.green_times,
        "ai_decision": {
            "green_times": state.last_ai_result,
            "improvement": state.last_ai_improvement,
        },
        "connected_clients": len(manager.active_connections),
    }


# ╔══════════════════════════════════════════════════════════════╗
# ║  ENTRY POINT                                                ║
# ╚══════════════════════════════════════════════════════════════╝

if __name__ == "__main__":
    import uvicorn

    logger.info("=" * 60)
    logger.info("  🚦 DIGITAL TWIN LEVEL 4 — PRESCRIPTIVE TWIN")
    logger.info("  📡 Smart Traffic Intersection Backend v2.0")
    logger.info("  🔄 4-Phase Independent Traffic Lights")
    logger.info("=" * 60)

    uvicorn.run(
        "main:app",
        host=HOST,
        port=PORT,
        reload=False,
        log_level="info",
    )
