"""
config.py — Cấu hình các hằng số hệ thống cho Digital Twin Level 4 Pro
=======================================================================
Tất cả các tham số toán học, vật lý và AI được khai báo tập trung tại đây
để dễ dàng điều chỉnh mà không cần sửa logic.

Nâng cấp v5.0:
  - 4 pha NEMA (Leading Left Turn) thay vì 2 pha
  - 8 hướng di chuyển (4 thẳng + 4 rẽ trái protected)
  - PCE (Passenger Car Equivalent) cho xe máy Việt Nam
  - Simulation Clock tách biệt wall clock
  - SUMO integration parameters
  - Auto-apply AI (Prescriptive thật sự)

Tham chiếu lý thuyết:
  - HCM (Highway Capacity Manual) 6th Edition — Saturation Flow, Delay
  - HCM 2010 Delay Model (d1 + d2 + d3) — Adaptive Signal Delay
  - Kalman Filter 2D (Constant Velocity) — Real-time State Estimation & Forecast
  - NEMA Phase Numbering — Standard 4-phase Signal Control (Leading Left Turn)
  - Cell Transmission Model (CTM) — Physical Twin Simulation
  - PCE from Vietnam research (Hanoi/HCMC studies)
  - ISO 23247: Digital Twin Framework
  - Eclipse SUMO — Microscopic traffic simulation
"""

# ============================================================
# 1. THÔNG SỐ GIAO THÔNG VẬT LÝ — 8 hướng, 4 pha
# ============================================================

# 8 hướng di chuyển: 4 thẳng + 4 rẽ trái protected
DIRECTIONS: list[str] = [
    "NS", "NS_LEFT",      # Bắc→Nam thẳng,  Bắc rẽ trái (→ Tây)
    "EW", "EW_LEFT",      # Đông→Tây thẳng, Đông rẽ trái (→ Bắc)
    "SN", "SN_LEFT",      # Nam→Bắc thẳng,  Nam rẽ trái (→ Đông)
    "WE", "WE_LEFT",      # Tây→Đông thẳng, Tây rẽ trái (→ Nam)
]

THROUGH_DIRECTIONS: list[str] = ["NS", "EW", "SN", "WE"]
LEFT_TURN_DIRECTIONS: list[str] = ["NS_LEFT", "EW_LEFT", "SN_LEFT", "WE_LEFT"]

# ── Mô hình pha đèn NEMA 4 pha — Leading Left Turn ──
# Pha 1: Rẽ trái NS+SN (protected, không xung đột)
# Pha 2: Thẳng NS+SN (đối diện, không xung đột)
# Pha 3: Rẽ trái EW+WE (protected)
# Pha 4: Thẳng EW+WE
PHASES: list[dict] = [
    {"id": "PH1", "name": "Bắc-Nam rẽ trái",  "directions": ["NS_LEFT", "SN_LEFT"], "type": "LEFT"},
    {"id": "PH2", "name": "Bắc-Nam thẳng",     "directions": ["NS", "SN"],           "type": "THROUGH"},
    {"id": "PH3", "name": "Đông-Tây rẽ trái",  "directions": ["EW_LEFT", "WE_LEFT"], "type": "LEFT"},
    {"id": "PH4", "name": "Đông-Tây thẳng",     "directions": ["EW", "WE"],           "type": "THROUGH"},
]
PHASE_IDS: list[str] = ["PH1", "PH2", "PH3", "PH4"]

# Lưu lượng nền cơ sở cho từng hướng — hệ số tỷ lệ (0 → 1)
# Rẽ trái thường chiếm 15-25% lưu lượng thẳng
BASE_DENSITY: dict[str, float] = {
    "NS": 0.40,       "NS_LEFT": 0.12,   # Trục chính Bắc-Nam
    "EW": 0.30,       "EW_LEFT": 0.10,   # Trục phụ Đông-Tây
    "SN": 0.25,       "SN_LEFT": 0.08,   # Ngược trục chính
    "WE": 0.20,       "WE_LEFT": 0.06,   # Ngược trục phụ
}

# Biên độ nhiễu ngẫu nhiên ε ~ Uniform(-NOISE, +NOISE)
NOISE_AMPLITUDE: float = 0.06

# ── Mô hình giải tỏa theo HCM Saturation Flow ──
# Saturation flow rate: lưu lượng bão hòa (PCU/giờ/làn)
# Tiêu chuẩn HCM 6th Edition: 1800 veh/h/lane cho đường đô thị
SATURATION_FLOW_RATE: float = 1800.0

# Hệ số giảm saturation flow cho rẽ trái (HCM: 0.85-0.95)
LEFT_TURN_SATURATION_FACTOR: float = 0.85

# Sức chứa hàng chờ mỗi hướng (PCU — Passenger Car Unit)
# Hướng thẳng: đoạn đường 300m × 2 làn, ~60 PCU
# Hướng rẽ trái: đoạn 100m × 1 làn, ~20 PCU
QUEUE_CAPACITY: int = 60
QUEUE_CAPACITY_LEFT: int = 20

# Thời gian mất mát khởi động (startup lost time) — giây
# Xe đầu tiên phản ứng chậm ~2s khi đèn chuyển xanh (MUTCD/HCM)
STARTUP_LOST_TIME: float = 2.0

# Hệ số chuyển đổi mật độ nền → tốc độ xe đến mỗi giây
ARRIVAL_RATE_SCALE: float = 0.007

# Bảng hệ số nhân giờ cao điểm M(h) — 24 mốc, nội suy tuyến tính
HOUR_MULTIPLIER_ANCHORS: list[tuple[int, float]] = [
    (0,  0.25),   # Nửa đêm
    (1,  0.12),   # Khuya vắng nhất
    (2,  0.12),
    (3,  0.12),
    (4,  0.12),
    (5,  0.35),   # Bắt đầu sáng sớm
    (6,  0.75),   # Tăng dần
    (7,  1.40),   # Trước giờ cao điểm sáng
    (8,  2.00),   # *** Đỉnh cao điểm sáng ***
    (9,  1.60),
    (10, 1.20),
    (11, 1.10),
    (12, 1.30),   # Buổi trưa
    (13, 1.10),
    (14, 1.05),
    (15, 1.20),
    (16, 1.55),   # Trước giờ cao điểm chiều
    (17, 1.90),   # *** Đỉnh cao điểm chiều ***
    (18, 1.50),
    (19, 1.10),
    (20, 0.80),
    (21, 0.55),
    (22, 0.40),
    (23, 0.30),
]

# ============================================================
# 2. PCE — Passenger Car Equivalent (Giao thông Việt Nam)
# ============================================================
# Tham chiếu:
#   - Nghiên cứu PCE tại Hà Nội/HCMC (ResearchGate, EASTS)
#   - PCE xe máy ≈ 0.25-0.5 (phụ thuộc điều kiện cụ thể)
#   - Sử dụng giá trị 0.25 cho xe máy trong đô thị mật độ cao

PCE_CAR: float = 1.0          # Ô tô con = 1 PCU
PCE_MOTORCYCLE: float = 0.25  # Xe máy = 0.25 PCU
PCE_BUS: float = 2.0          # Xe buýt = 2 PCU
PCE_TRUCK: float = 2.5        # Xe tải = 2.5 PCU

# Tỷ lệ phương tiện (đặc trưng giao thông đô thị Việt Nam)
VEHICLE_MIX: dict[str, float] = {
    "car": 0.25,           # 25% ô tô
    "motorcycle": 0.65,    # 65% xe máy (trội nhất)
    "bus": 0.05,           # 5% xe buýt
    "truck": 0.05,         # 5% xe tải
}

# PCE trung bình có trọng số
# = 0.25×1.0 + 0.65×0.25 + 0.05×2.0 + 0.05×2.5 = 0.6375 PCU/veh
_PCE_MAP: dict[str, float] = {
    "car": PCE_CAR,
    "motorcycle": PCE_MOTORCYCLE,
    "bus": PCE_BUS,
    "truck": PCE_TRUCK,
}
WEIGHTED_PCE: float = sum(
    VEHICLE_MIX[v] * _PCE_MAP[v] for v in VEHICLE_MIX
)

# ============================================================
# 3. THÔNG SỐ PHYSICAL TWIN (Mô phỏng thế giới thực / SUMO)
# ============================================================

# Xe đến theo Poisson process — λ (xe/giây) cho mỗi hướng
# λ_dir = BASE_DENSITY[dir] × M(h) × ARRIVAL_RATE_SCALE × QUEUE_CAPACITY

# Độ nhiễu sensor ảo: σ_sensor
SENSOR_NOISE_STD: float = 0.03

# Xác suất sensor bị lỗi (packet loss/camera che khuất)
SENSOR_DROPOUT_RATE: float = 0.02

# ── SUMO Integration ──
SUMO_ENABLED: bool = True     # True = dùng SUMO, False = fallback mô phỏng nội bộ
SUMO_CFG_PATH: str = "sumo/intersection.sumocfg"
SUMO_GUI: bool = False        # True = mở sumo-gui, False = headless
SUMO_STEP_LENGTH: float = 1.0 # Bước SUMO (giây)

# ============================================================
# 4. THÔNG SỐ MÔ HÌNH DỰ BÁO KALMAN FILTER 2D
# ============================================================

KALMAN_Q_DENSITY: float = 0.0005
KALMAN_Q_VELOCITY: float = 0.001
KALMAN_R: float = 0.01

# Horizon dự báo (giây) — Kalman forecast look-ahead
FORECAST_HORIZON_SEC: float = 10.0

# Số giây mỗi bước mô phỏng offline (1 giây thực = 1 tick)
TICK_INTERVAL_SEC: float = 1.0

# ============================================================
# 5. THÔNG SỐ HÀM MỤC TIÊU AI (Optimizer — LQR-style)
# ============================================================

# alpha: trọng số giữa mật độ hiện tại và dự báo Kalman
ALPHA: float = 0.85

# lambda: hệ số phạt thay đổi thời gian đèn quá lớn
LAMBDA: float = 0.15

# S: hệ số chuẩn hóa cho Δu (đơn vị: giây)
S_NORMALIZE: float = 30.0

# Trọng số ưu tiên pha (trục chính > hướng phụ, rẽ trái thấp hơn thẳng)
PHASE_WEIGHTS: dict[str, float] = {
    "PH1": 0.6,   # Rẽ trái Bắc-Nam (thấp hơn thẳng)
    "PH2": 1.0,   # Thẳng Bắc-Nam — trục chính
    "PH3": 0.5,   # Rẽ trái Đông-Tây
    "PH4": 0.8,   # Thẳng Đông-Tây — trục phụ
}

# Auto-apply AI: tự động áp dụng kết quả optimizer
AUTO_APPLY_ENABLED: bool = True
AUTO_APPLY_MIN_IMPROVEMENT: float = 1.0  # Chỉ apply khi cải thiện > 1%

# ============================================================
# 6. THÔNG SỐ CHU KỲ ĐÈN MẶC ĐỊNH & THÔNG MINH
# ============================================================

# Thời gian đèn xanh mặc định cho từng PHA (giây)
DEFAULT_GREEN_TIMES: dict[str, int] = {
    "PH1": 15,   # Rẽ trái Bắc-Nam (ngắn hơn thẳng)
    "PH2": 35,   # Thẳng Bắc-Nam — trục chính
    "PH3": 12,   # Rẽ trái Đông-Tây
    "PH4": 30,   # Thẳng Đông-Tây — trục phụ
}

# Thời gian đèn vàng chuyển tiếp (giây)
YELLOW_DURATION: int = 3

# Thời gian toàn đỏ giữa các pha (giây)
ALL_RED_DURATION: int = 2

# Thời gian đèn xanh tối thiểu (MUTCD requirement: ≥ 7s)
# Rẽ trái cần ít nhất 8s, thẳng ít nhất 15s
MIN_GREEN_TIME: int = 8
MIN_GREEN_TIME_THROUGH: int = 15

# Thời gian đèn xanh tối đa
MAX_GREEN_TIME: int = 90
MAX_GREEN_TIME_LEFT: int = 30

# Ngưỡng mật độ cắt sớm pha xanh (Actuated Green Cutoff)
DENSITY_CUTOFF: float = 0.15

# ============================================================
# 7. THÔNG SỐ KPI — HCM 2010 Delay Model
# ============================================================

# Mức delay tối đa chấp nhận được (giây) — LOS F: delay > 80s
MAX_ACCEPTABLE_DELAY: float = 80.0

# Hệ số hiệu chỉnh cho actuated control (k factor)
HCM_K_FACTOR: float = 0.5

# Hệ số upstream filtering (I factor)
HCM_I_FACTOR: float = 1.0

# ============================================================
# 8. SIMULATION CLOCK — Đồng hồ mô phỏng tách biệt
# ============================================================

SIM_SPEED_MULTIPLIER: float = 1.0    # 1x = realtime, 10x = fast-forward
SIM_START_HOUR: int = 7              # Bắt đầu lúc 7:30 sáng
SIM_START_MINUTE: int = 30

# ============================================================
# 9. THÔNG SỐ SERVER
# ============================================================

HOST: str = "0.0.0.0"
PORT: int = 8000
WS_ENDPOINT: str = "/traffic-ws"

# CORS
ALLOWED_ORIGINS: list[str] = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:3000",
    "http://localhost:5173",
    "null",  # Godot Web export chạy local file://
]

# Version
VERSION: str = "5.0.0"
