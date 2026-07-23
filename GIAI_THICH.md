# Giải thích dự án — TrafficNodes Digital Twins

> Digital Twin (Bản sao số) cho **1 nút giao thông thông minh** (ngã tư 4 hướng).
> Mô phỏng đèn giao thông + AI tự tối ưu thời gian đèn xanh, hiển thị 3D thời gian thực.

---

## 1. Dự án làm cái gì?

Mô phỏng **1 ngã tư** theo chuẩn **Digital Twin ISO 23247**. Có 2 "thế giới" chạy song song:

```
   THẾ GIỚI THẬT                          BẢN SAO SỐ
   (Physical Twin)      ── sensor ──►     (Digital Twin)
   - Xe chạy thật                          - Đoán trạng thái từ sensor
   - Đèn đỏ/xanh/vàng   ◄── điều khiển ──  - AI tính đèn tối ưu
```

- **Physical Twin** = giả lập "đường thật" (xe đến, xếp hàng, qua đèn). Có SUMO hoặc bản giả lập nội bộ.
- **Digital Twin** = bản sao trong máy tính. Chỉ "nhìn" qua sensor (có nhiễu, có mất tín hiệu) → phải đoán trạng thái thật → dùng AI tính lại thời gian đèn tốt hơn → gửi ngược xuống điều khiển đèn.
- **Godot 3D** = màn hình hiển thị ngã tư, xe, đèn, số liệu.

Đây là mô hình **Level 4 "Prescriptive"**: AI không chỉ báo cáo, mà **tự động áp dụng** thời gian đèn mới (`AUTO_APPLY`).

---

## 2. Kiến trúc — 2 phần

### A. Backend (`backend/`) — Python / FastAPI
"Bộ não". Chạy mô phỏng, tính toán, phát dữ liệu qua **WebSocket** cổng `8000`.

### B. Frontend (`digital-twins/`) — Godot 4.7
"Màn hình". Kết nối WebSocket, vẽ ngã tư 3D + xe + đèn + dashboard số liệu. Có nút bấm điều khiển (đổi tốc độ, nhảy giờ, bật/tắt AI).

```
Backend (Python, port 8000)  ──WebSocket ws://127.0.0.1:8000/traffic-ws──►  Godot 3D
                             ◄──lệnh điều khiển (APPLY_LIGHTS, SET_SPEED...)──
```

---

## 3. Các khái niệm chính (dễ nhầm)

### 8 hướng đi
Không phải 4, mà **8**: mỗi trục có "đi thẳng" + "rẽ trái riêng":

| Hướng | Nghĩa |
|-------|-------|
| `NS`, `SN` | Bắc↔Nam đi thẳng |
| `EW`, `WE` | Đông↔Tây đi thẳng |
| `NS_LEFT`, `SN_LEFT` | Bắc/Nam rẽ trái |
| `EW_LEFT`, `WE_LEFT` | Đông/Tây rẽ trái |

### 4 pha đèn NEMA (Leading Left Turn)
Đèn xoay vòng qua 4 pha, **rẽ trái đi trước** (an toàn, không xung đột):

| Pha | Cho ai xanh | Loại |
|-----|-------------|------|
| PH1 | NS + SN rẽ trái | LEFT |
| PH2 | NS + SN thẳng | THROUGH |
| PH3 | EW + WE rẽ trái | LEFT |
| PH4 | EW + WE thẳng | THROUGH |

Mỗi pha: `GREEN` (xanh) → `YELLOW` (vàng 3s) → `ALL_RED` (đỏ hết 2s) → pha kế tiếp.

### PCE — quy đổi xe máy
Giao thông VN đông xe máy (65%). 1 xe máy chỉ chiếm chỗ = **0.25 ô tô** (PCU). Dùng để tính lưu lượng cho đúng thực tế VN.

---

## 4. Từng file backend làm gì

| File | Vai trò |
|------|---------|
| `main.py` | **Trái tim**. Vòng lặp mô phỏng (mỗi tick = 1 giây sim), máy trạng thái đèn, gom dữ liệu → WebSocket. Chứa `IntersectionState` (toàn bộ trạng thái ngã tư). |
| `config.py` | **Bảng chỉnh số**. Mọi hằng số: thời gian đèn, PCE, tỷ lệ xe, giờ cao điểm... Chỉnh ở đây, không sửa logic. |
| `core/sim_clock.py` | **Đồng hồ mô phỏng** tách khỏi giờ thật. Cho tua nhanh (10x), nhảy giờ (test cao điểm 17h), pause. |
| `core/physical_twin.py` | **"Đường thật"**. 2 bản: SUMO (vi mô, từng xe) hoặc `SimulatedPhysicalTwin` (hàng chờ + xe đến ngẫu nhiên Poisson). Tự fallback nếu không có SUMO. |
| `core/generator.py` | **Đồng hóa dữ liệu**. Nhận sensor (có nhiễu) → ước lượng mật độ Digital Twin. |
| `core/forecaster.py` | **Kalman Filter 2D**. Lọc nhiễu + **dự báo** mật độ 10 giây tới (density + velocity). |
| `core/optimizer.py` | **AI tối ưu**. Giải bài toán: chia thời gian xanh cho 4 pha sao cho tổng "xe kẹt còn lại" nhỏ nhất. Dùng `scipy` Nelder-Mead, multi-start 3 điểm. |
| `core/utils.py` | Hàm phụ: hệ số giờ cao điểm, sức chứa hàng chờ. |

---

## 5. Một "tick" (1 bước mô phỏng) chạy gì?

Trong `main.py` → `IntersectionState.tick()`:

```
0. Đồng hồ +1 giây
1. Cập nhật pha đèn (xanh/vàng/đỏ). Có "cắt sớm" nếu đường trống (Actuated Cutoff)
2. Physical Twin chạy → mật độ thật (ground truth)
3. Đọc sensor (thêm nhiễu + đôi khi mất tín hiệu)
4. Digital Twin đoán lại mật độ từ sensor
5. Kalman lọc + dự báo 10s tới
6. Mỗi 5 tick: AI tối ưu → nếu cải thiện >1% thì TỰ ĐỘNG áp dụng đèn mới
7. Tính KPI (theo mô hình delay HCM 2010)
8. Tính Fidelity Score = độ khớp giữa bản số và đường thật
9. Đóng gói JSON → gửi Godot
```

Vòng lặp nền `_simulation_loop()` lặp việc này, ngủ `1/speed` giây mỗi vòng.

---

## 6. Các chỉ số (KPI) hiển thị

| Chỉ số | Nghĩa |
|--------|-------|
| **throughput** | Số xe qua ngã tư mỗi phút (quy đổi PCU) |
| **avgWait** | Thời gian chờ trung bình (giây) — theo HCM 2010 |
| **efficiency** | Hiệu suất % (chờ càng ít → càng cao) |
| **fidelity** | Bản sao số khớp đường thật bao nhiêu % (1 − sai số RMSE) |

---

## 7. Điều khiển từ Godot (gửi xuống backend)

Nút bấm trong Godot → gửi lệnh WebSocket (xem `network.gd`):

| Lệnh | Tác dụng |
|------|----------|
| `APPLY_LIGHTS` | Áp thời gian đèn xanh thủ công |
| `SET_SPEED` | Đổi tốc độ tua (1x, 10x...) |
| `JUMP_TO_HOUR` | Nhảy tới giờ bất kỳ (test cao điểm) |
| `TOGGLE_AUTO_APPLY` | Bật/tắt AI tự động |
| `PAUSE` / `RESUME` | Dừng / chạy tiếp |

---

## 8. Cách chạy (trên máy này)

**Backend:**
```powershell
cd E:\TrafficNodes-DigitalTwins\backend
.\venv\Scripts\python.exe main.py
```
→ mở `http://127.0.0.1:8000` xem trạng thái.

**Frontend (Godot):**
```powershell
& "C:\Users\admin\AppData\Local\Microsoft\WinGet\Packages\GodotEngine.GodotEngine_Microsoft.Winget.Source_8wekyb3d8bbwe\Godot_v4.7.1-stable_win64.exe" --path E:\TrafficNodes-DigitalTwins\digital-twins
```

**Lưu ý:**
- Máy chỉ có **Python 3.9** → đã thêm `from __future__ import annotations` vào các file để chạy được cú pháp `X | None`.
- **SUMO chưa cài** → tự dùng bản giả lập nội bộ (`SimulatedPhysicalTwin`). Muốn xe vi mô thật thì cài `eclipse-sumo` rồi để `SUMO_ENABLED=True`.
- Kiểm tra Godot đã kết nối: `GET http://127.0.0.1:8000/status` → `connected_clients` ≥ 1.
