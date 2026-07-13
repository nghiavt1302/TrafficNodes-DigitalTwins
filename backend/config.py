"""
config.py — Cấu hình các hằng số hệ thống cho Digital Twin Level 4
=================================================================
Tất cả các tham số toán học, vật lý và AI được khai báo tập trung tại đây
để dễ dàng điều chỉnh mà không cần sửa logic.

Tham chiếu lý thuyết:
  - HCM (Highway Capacity Manual) 6th Edition — Saturation Flow, Delay
  - Webster's Delay Formula (1958) — Average Intersection Delay
  - Kalman Filter 1D — Real-time State Estimation
"""

# ============================================================
# 1. THÔNG SỐ SINH MẬT ĐỘ XE (Physical Generator)
# ============================================================

# Lưu lượng nền cơ sở cho từng hướng — hệ số tỷ lệ (0 → 1)
# đại diện cho "sức hút giao thông" tương đối của mỗi hướng.
BASE_DENSITY: dict[str, float] = {
    "NS": 0.40,   # Bắc → Nam — trục chính, lưu lượng cao nhất
    "EW": 0.30,   # Đông → Tây
    "SN": 0.25,   # Nam → Bắc
    "WE": 0.20,   # Tây → Đông — lưu lượng thấp nhất
}

# Biên độ nhiễu ngẫu nhiên ε ~ Uniform(-NOISE, +NOISE)
NOISE_AMPLITUDE: float = 0.06

# ── Mô hình giải tỏa theo HCM Saturation Flow ──
# Saturation flow rate: lưu lượng bão hòa (xe/giờ/làn)
# Tiêu chuẩn HCM 6th Edition: 1800 veh/h/lane cho đường đô thị
SATURATION_FLOW_RATE: float = 1800.0

# Sức chứa hàng chờ mỗi hướng (xe)
# Ước lượng: đoạn đường 300m × 1 làn, mỗi xe chiếm 5m = 60 xe
QUEUE_CAPACITY: int = 60

# Thời gian mất mát khởi động (startup lost time) — giây
# Xe đầu tiên phản ứng chậm ~2s khi đèn chuyển xanh (MUTCD/HCM)
STARTUP_LOST_TIME: float = 2.0

# Hệ số chuyển đổi mật độ nền → tốc độ xe đến mỗi giây
# Đã hiệu chuẩn sao cho:
#   - M(h)=1.0 (bình thường): hệ thống CÂN BẰNG (clearance ≈ arrival)
#   - M(h)=2.0 (cao điểm): hệ thống QUÁ TẢI (cần tối ưu phân bổ xanh)
#   Ví dụ: NS (base=0.4), M(h)=1.0:
#     arrival = 0.4 × 1.0 × 0.007 = 0.0028/s ≈ clearance 0.0083/s × 45/135
ARRIVAL_RATE_SCALE: float = 0.007

# Bảng hệ số nhân giờ cao điểm M(h) — 24 mốc, nội suy tuyến tính
# Quy tắc: 8h & 17h đạt đỉnh (1.9‑2.0), 1h‑4h đêm thấp nhất (~0.12)
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
# 2. THÔNG SỐ MÔ HÌNH DỰ BÁO KALMAN FILTER
# ============================================================

# Kalman Filter 1D cho mỗi hướng:
#   State:       x(t) = x(t-1) + w,  w ~ N(0, Q)
#   Observation: z(t) = x(t) + v,    v ~ N(0, R)
#
# Q nhỏ → mô hình tin rằng state thay đổi chậm (mượt hơn)
# R nhỏ → mô hình tin measurement chính xác (phản ứng nhanh hơn)
KALMAN_PROCESS_NOISE: float = 0.001
KALMAN_MEASUREMENT_NOISE: float = 0.01

# Số ngày dữ liệu quá khứ để Pre-training (giải quyết Cold Start)
PRETRAIN_DAYS: int = 30

# Số giây mỗi bước mô phỏng offline (1 giây thực = 1 tick)
TICK_INTERVAL_SEC: float = 1.0

# ============================================================
# 3. THÔNG SỐ HÀM MỤC TIÊU AI (Optimizer — LQR-style)
# ============================================================

# alpha: trọng số giữa mật độ hiện tại và dự báo Kalman
# d_eff = alpha * d_current + (1 - alpha) * V_forecast
ALPHA: float = 0.85

# lambda: hệ số phạt thay đổi thời gian đèn quá lớn
# Ngăn AI "nhảy" kịch bản liên tục (switching chaos)
LAMBDA: float = 0.15

# S: hệ số chuẩn hóa cho Δu (đơn vị: giây)
S_NORMALIZE: float = 30.0

# Trọng số ưu tiên hướng (trục chính > hướng ngược)
DIRECTION_WEIGHTS: dict[str, float] = {
    "NS": 1.0,
    "EW": 1.0,
    "SN": 0.6,
    "WE": 0.6,
}

# Danh sách các hướng giao thông
DIRECTIONS: list[str] = ["NS", "EW", "SN", "WE"]

# Thứ tự pha đèn xanh trong 1 chu kỳ (mỗi hướng có pha xanh riêng)
PHASE_ORDER: list[str] = ["NS", "EW", "SN", "WE"]

# ============================================================
# 4. THÔNG SỐ CHU KỲ ĐÈN MẶC ĐỊNH & THÔNG MINH (Adaptive Control)
# ============================================================

# Thời gian đèn xanh mặc định cho từng pha (giây)
DEFAULT_GREEN_TIMES: dict[str, int] = {
    "NS": 45,   # Bắc→Nam — trục chính, lưu lượng cao nhất
    "EW": 40,   # Đông→Tây — trục chính
    "SN": 40,   # Nam→Bắc — hướng ngược, lưu lượng thấp hơn
    "WE": 35,   # Tây→Đông — hướng ngược, lưu lượng thấp nhất
}

# Thời gian đèn vàng chuyển tiếp (giây)
YELLOW_DURATION: int = 3

# Thời gian toàn đỏ giữa các pha (giây) — để xe trong ngã tư thoát ra
ALL_RED_DURATION: int = 2

# Thời gian đèn xanh tối thiểu (MUTCD requirement: ≥ 7s, thường 10-15s)
MIN_GREEN_TIME: int = 15

# Thời gian đèn xanh tối đa — ràng buộc cho optimizer
MAX_GREEN_TIME: int = 90

# Ngưỡng mật độ xe dưới mức này sẽ tự động cắt sớm pha xanh (Actuated Green Cutoff)
DENSITY_CUTOFF: float = 0.15

# ============================================================
# 5. THÔNG SỐ KPI (HCM / Webster)
# ============================================================

# Saturation flow cho tính KPI — dùng chung với generator
# (đã khai báo SATURATION_FLOW_RATE ở trên)

# Mức delay tối đa chấp nhận được (giây) — dùng để tính % hiệu suất
# LOS F theo HCM: delay > 80s
MAX_ACCEPTABLE_DELAY: float = 80.0

# ============================================================
# 6. THÔNG SỐ SERVER
# ============================================================

HOST: str = "0.0.0.0"
PORT: int = 8000
WS_ENDPOINT: str = "/traffic-ws"
