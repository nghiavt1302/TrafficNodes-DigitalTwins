extends Node2D

# --- Định nghĩa hằng số hệ thống ---
const LANE_WIDTH = 50.0  # Độ rộng mỗi làn xe
const INSTERSECTION_COLOR = Color(0.18, 0.18, 0.18)

# --- Bảng ánh xạ tên hướng: mã ngắn → tên hướng tiếp cận bản đồ ---
const DIR_NAMES = {
	"NS": "Bắc-Nam",
	"EW": "Đông-Tây",
	"SN": "Nam-Bắc",
	"WE": "Tây-Đông"
}

# --- Lưu trữ Trạng thái Digital Twin ---
var traffic_data = {
	"NS": {"density": 0.0, "time_left": 0.0, "light": "DO"},
	"EW": {"density": 0.0, "time_left": 0.0, "light": "DO"},
	"SN": {"density": 0.0, "time_left": 0.0, "light": "DO"},
	"WE": {"density": 0.0, "time_left": 0.0, "light": "DO"},
	"kpis": {"throughput": 0.0, "avgWait": 0.0, "efficiency": 0.0},
	"ai_decision": {"green_times": {"NS": 45, "EW": 40, "SN": 40, "WE": 35}, "improvement": 0.0}
}

var labels = {}
var center_point = Vector2.ZERO
var screen_size = Vector2.ZERO
var sim_width = 0.0
var _default_font: Font   # Font hệ thống để vẽ chữ lên canvas

func _ready():
	screen_size = get_viewport_rect().size
	# Chia màn hình 50/50. Khu vực mô phỏng chiếm 50% bên trái
	sim_width = screen_size.x * 0.5
	# Tâm của ngã tư sẽ nằm ở chính giữa của nửa bên trái (25% toàn màn hình)
	center_point = Vector2(sim_width * 0.5, screen_size.y * 0.5)
	
	# Lấy font mặc định từ theme để dùng trong _draw()
	_default_font = ThemeDB.fallback_font
	
	_dunk_dashboard_panel()

func _process(_delta):
	queue_redraw()

# ╔══════════════════════════════════════════════════════════════╗
# ║  HÀM VẼ ĐỒ HỌA NGÃ TƯ (Thu gọn trong 50% màn hình)       ║
# ╚══════════════════════════════════════════════════════════════╝
func _draw():
	# 1. Vẽ nền cỏ
	draw_rect(Rect2(Vector2.ZERO, screen_size), Color(0.1, 0.14, 0.1))
	
	# 2. Vẽ nền trục đường chính
	var horizontal_road = Rect2(0, center_point.y - LANE_WIDTH * 2, sim_width, LANE_WIDTH * 4)
	var vertical_road = Rect2(center_point.x - LANE_WIDTH * 2, 0, LANE_WIDTH * 4, screen_size.y)
	draw_rect(horizontal_road, Color(0.15, 0.15, 0.15))
	draw_rect(vertical_road, Color(0.15, 0.15, 0.15))
	draw_rect(Rect2(center_point - Vector2(LANE_WIDTH*2, LANE_WIDTH*2), Vector2(LANE_WIDTH*4, LANE_WIDTH*4)), INSTERSECTION_COLOR)

	# 3. Vẽ các làn đường (tô màu theo mật độ chuẩn từng hướng)
	# Nhánh Bắc tiếp cận ngã tư (đi xuống Nam) -> hướng NS
	_draw_lane_with_density("NS", center_point.x - LANE_WIDTH * 2, 0, LANE_WIDTH * 2, center_point.y - LANE_WIDTH * 2) 
	# Nhánh Nam tiếp cận ngã tư (đi lên Bắc) -> hướng SN
	_draw_lane_with_density("SN", center_point.x, center_point.y + LANE_WIDTH * 2, LANE_WIDTH * 2, screen_size.y - (center_point.y + LANE_WIDTH * 2)) 
	# Nhánh Tây tiếp cận ngã tư (đi sang Đông) -> hướng WE
	_draw_lane_with_density("WE", 0, center_point.y, center_point.x - LANE_WIDTH * 2, LANE_WIDTH * 2) 
	# Nhánh Đông tiếp cận ngã tư (đi sang Tây) -> hướng EW
	_draw_lane_with_density("EW", center_point.x + LANE_WIDTH * 2, center_point.y - LANE_WIDTH * 2, sim_width - (center_point.x + LANE_WIDTH * 2), LANE_WIDTH * 2) 

	# 4. Vẽ vạch kẻ đường
	_draw_road_markings()

	# 5. Vẽ đèn giao thông + đếm ngược + mật độ
	_draw_traffic_lights()

	# 6. Vẽ nhãn tên hướng + mật độ + đếm ngược lên bản đồ
	_draw_direction_overlays()

func _draw_lane_with_density(direction: String, x: float, y: float, w: float, h: float):
	var density = traffic_data[direction]["density"]
	# Luôn tô màu đường thể hiện mật độ (kể cả mật độ thấp hoặc 0%) để màu sắc đồng nhất 100% với nhãn và UI
	if density >= 0.0:
		var lane_color = _get_color_by_density(density)
		draw_rect(Rect2(x, y, w, h), Color(lane_color.r, lane_color.g, lane_color.b, 0.75))

func _get_color_by_density(density: float) -> Color:
	if density <= 0.15: return Color(0.2, 0.9, 0.4)       # Xanh lá tươi (Rất thông thoáng)
	elif density <= 0.35: return Color(0.5, 0.95, 0.2)      # Xanh lá mạ (Thông thoáng)
	elif density <= 0.55: return Color(1.0, 0.85, 0.15)     # Vàng (Trung bình)
	elif density <= 0.75: return Color(1.0, 0.55, 0.1)      # Cam (Đông đúc)
	elif density <= 0.90: return Color(1.0, 0.2, 0.2)       # Đỏ tươi (Tắc nghẽn)
	else: return Color(0.85, 0.1, 0.85)                     # Tím đỏ sẫm (Tắc nghiêm trọng)

func _draw_road_markings():
	# Vạch dừng màu trắng
	draw_rect(Rect2(center_point.x - LANE_WIDTH*2, center_point.y - LANE_WIDTH*2 - 5, LANE_WIDTH*2, 5), Color.WHITE) 
	draw_rect(Rect2(center_point.x, center_point.y + LANE_WIDTH*2, LANE_WIDTH*2, 5), Color.WHITE) 
	draw_rect(Rect2(center_point.x - LANE_WIDTH*2 - 5, center_point.y, 5, LANE_WIDTH*2), Color.WHITE) 
	draw_rect(Rect2(center_point.x + LANE_WIDTH*2, center_point.y - LANE_WIDTH*2, 5, LANE_WIDTH*2), Color.WHITE) 
	
	# Tim đường nét đứt
	_draw_dashed_line(Vector2(center_point.x, 0), Vector2(center_point.x, center_point.y - LANE_WIDTH*2), Color.YELLOW)
	_draw_dashed_line(Vector2(center_point.x, center_point.y + LANE_WIDTH*2), Vector2(center_point.x, screen_size.y), Color.YELLOW)
	_draw_dashed_line(Vector2(0, center_point.y), Vector2(center_point.x - LANE_WIDTH*2, center_point.y), Color.YELLOW)
	_draw_dashed_line(Vector2(center_point.x + LANE_WIDTH*2, center_point.y), Vector2(sim_width, center_point.y), Color.YELLOW)

func _draw_dashed_line(from: Vector2, to: Vector2, color: Color):
	var length = from.distance_to(to)
	var dir = (to - from).normalized()
	var current_dist = 0.0
	while current_dist < length:
		draw_line(from + dir * current_dist, from + dir * min(current_dist + 15, length), color, 2.0)
		current_dist += 30.0

func _draw_traffic_lights():
	var offset = LANE_WIDTH * 2.5
	var positions = {
		"NS": center_point + Vector2(-LANE_WIDTH * 1.5, -LANE_WIDTH * 2.5),
		"EW": center_point + Vector2(offset, -offset + 40),
		"SN": center_point + Vector2(offset - 40, offset),
		"WE": center_point + Vector2(-offset, offset - 40)
	}
	for dir_key in positions.keys():
		var pos = positions[dir_key]
		var state = traffic_data[dir_key]["light"]
		var light_color = Color.RED if state == "DO" else (Color.YELLOW if state == "VANG" else Color.GREEN)
		# Vòng tròn đèn
		draw_circle(pos, 18.0, Color.BLACK)
		draw_circle(pos, 14.0, light_color)
		
		# ── Vẽ số đếm ngược bên cạnh đèn ──
		var time_left = traffic_data[dir_key]["time_left"]
		var timer_text = str(int(time_left)) + "s"
		var timer_pos = pos + Vector2(22, 6)  # Lệch sang phải, căn giữa dọc
		# Nền tối cho dễ đọc
		var text_width = _default_font.get_string_size(timer_text, HORIZONTAL_ALIGNMENT_LEFT, -1, 14).x
		draw_rect(Rect2(timer_pos.x - 2, timer_pos.y - 14, text_width + 4, 18), Color(0, 0, 0, 0.7))
		draw_string(_default_font, timer_pos, timer_text, HORIZONTAL_ALIGNMENT_LEFT, -1, 14, Color.WHITE)

# ╔══════════════════════════════════════════════════════════════╗
# ║  VẼ NHÃN TÊN HƯỚNG + MẬT ĐỘ LÊN BẢN ĐỒ NGÃ TƯ           ║
# ╚══════════════════════════════════════════════════════════════╝
func _draw_direction_overlays():
	"""
	Vẽ thông tin overlay cho từng hướng trên bản đồ:
	- Tên hướng bản đồ (Bắc-Nam, Đông-Tây, ...)
	- Mật độ xe (%)
	"""
	# Vị trí đặt nhãn cho từng hướng (nằm trên nhánh đường, ngoài ngã tư)
	var label_positions = {
		# Bắc-Nam: phía trên ngã tư (nhánh Bắc)
		"NS": center_point + Vector2(-LANE_WIDTH * 1.8, -LANE_WIDTH * 4.5),
		# Đông-Tây: bên phải ngã tư (nhánh Đông)
		"EW": center_point + Vector2(LANE_WIDTH * 2.8, -LANE_WIDTH * 3.5),
		# Nam-Bắc: góc dưới phải
		"SN": center_point + Vector2(LANE_WIDTH * 2.8, LANE_WIDTH * 3.0),
		# Tây-Đông: góc dưới trái
		"WE": center_point + Vector2(-LANE_WIDTH * 5.5, LANE_WIDTH * 3.0),
	}

	for dir_key in ["NS", "EW", "SN", "WE"]:
		var pos = label_positions[dir_key]
		var density = traffic_data[dir_key]["density"]
		var density_pct = snapped(density * 100, 0.1)
		var display_name = DIR_NAMES[dir_key]
		var state = traffic_data[dir_key]["light"]

		# ── Dòng 1: Tên hướng ──
		var name_text = "🚗 " + display_name
		var name_size = _default_font.get_string_size(name_text, HORIZONTAL_ALIGNMENT_LEFT, -1, 15)

		# ── Dòng 2: Mật độ ──
		var density_text = "Mật độ: " + str(density_pct) + "%"
		var density_size = _default_font.get_string_size(density_text, HORIZONTAL_ALIGNMENT_LEFT, -1, 13)

		# ── Dòng 3: Trạng thái đèn ──
		var light_label = "ĐỎ" if state == "DO" else ("VÀNG" if state == "VANG" else "XANH")
		var light_text = "Đèn: " + light_label
		var light_size = _default_font.get_string_size(light_text, HORIZONTAL_ALIGNMENT_LEFT, -1, 13)

		# Tính kích thước hộp nền
		var box_w = max(name_size.x, max(density_size.x, light_size.x)) + 16
		var box_h = 56
		
		# Vẽ hộp nền bán trong suốt
		draw_rect(Rect2(pos.x - 4, pos.y - 16, box_w, box_h), Color(0.05, 0.05, 0.12, 0.85))
		draw_rect(Rect2(pos.x - 4, pos.y - 16, box_w, box_h), Color(0.4, 0.6, 1.0, 0.3), false, 1.5)

		# Vẽ dòng 1: Tên hướng (màu sáng, cỡ 15)
		draw_string(_default_font, pos, name_text, HORIZONTAL_ALIGNMENT_LEFT, -1, 15, Color(0.7, 0.85, 1.0))
		
		# Vẽ dòng 2: Mật độ (màu theo mức độ, cỡ 13)
		var density_color = _get_color_by_density(density)
		draw_string(_default_font, pos + Vector2(0, 18), density_text, HORIZONTAL_ALIGNMENT_LEFT, -1, 13, density_color)

		# Vẽ dòng 3: Trạng thái đèn (màu đèn, cỡ 13)
		var light_draw_color = Color.RED if state == "DO" else (Color.YELLOW if state == "VANG" else Color.GREEN)
		draw_string(_default_font, pos + Vector2(0, 34), light_text, HORIZONTAL_ALIGNMENT_LEFT, -1, 13, light_draw_color)

# ╔══════════════════════════════════════════════════════════════╗
# ║  BẢNG ĐIỀU KHIỂN DASHBOARD (50% bên phải)                   ║
# ╚══════════════════════════════════════════════════════════════╝
func _dunk_dashboard_panel():
	# 1. Panel chính
	var panel = Panel.new()
	panel.size = Vector2(screen_size.x * 0.5, screen_size.y)
	panel.position = Vector2(screen_size.x * 0.5, 0)
	add_child(panel)
	
	# 2. VBoxContainer không cần Scroll
	var vbox = VBoxContainer.new()
	vbox.size = Vector2(panel.size.x - 40, panel.size.y - 40)
	vbox.position = Vector2(20, 20)
	vbox.add_theme_constant_override("separation", 10)
	panel.add_child(vbox)
	
	# Tittle
	var title = Label.new()
	title.text = "🚦 COMMAND CENTER (DIGITAL TWIN LEVEL 4)"
	title.horizontal_alignment = HorizontalAlignment.HORIZONTAL_ALIGNMENT_CENTER
	vbox.add_child(title)
	vbox.add_child(HSeparator.new())

	# ── SECTION: MẬT ĐỘ XE THEO HƯỚNG (MỚI) ──
	var sec_density = Label.new()
	sec_density.text = "🚗 MẬT ĐỘ XE THEO HƯỚNG"
	vbox.add_child(sec_density)
	
	var density_grid = GridContainer.new()
	density_grid.columns = 2
	density_grid.add_theme_constant_override("h_separation", 30)
	density_grid.add_theme_constant_override("v_separation", 6)
	vbox.add_child(density_grid)
	
	for dir_key in ["NS", "EW", "SN", "WE"]:
		var lbl = Label.new()
		lbl.text = "• " + DIR_NAMES[dir_key] + ": --% | Đèn: -- | ⏱ --s"
		density_grid.add_child(lbl)
		labels["density_" + dir_key] = lbl

	vbox.add_child(HSeparator.new())
	
	# SECTION: KPIs
	var sec_kpi = Label.new()
	sec_kpi.text = "📊 CHỈ SỐ VẬN HÀNH (REAL-TIME)"
	vbox.add_child(sec_kpi)
	
	var kpi_grid = GridContainer.new()
	kpi_grid.columns = 2
	kpi_grid.add_theme_constant_override("h_separation", 60)
	kpi_grid.add_theme_constant_override("v_separation", 8)
	vbox.add_child(kpi_grid)
	
	var kpi_names = ["throughput", "avgWait", "efficiency"]
	var display_texts = ["• Thông lượng: --", "• Chờ TB: -- s", "• Hiệu suất: -- %"]
	for i in range(kpi_names.size()):
		var lbl = Label.new()
		lbl.text = display_texts[i]
		kpi_grid.add_child(lbl)
		labels[kpi_names[i]] = lbl
		
	vbox.add_child(HSeparator.new())
	
	# SECTION: FORECAST (dùng tên hướng bản đồ)
	var sec_forecast = Label.new()
	sec_forecast.text = "🧠 MÔ HÌNH DỰ BÁO LƯU LƯỢNG (EMA)"
	vbox.add_child(sec_forecast)
	
	var fc_grid = GridContainer.new()
	fc_grid.columns = 2
	fc_grid.add_theme_constant_override("h_separation", 60)
	fc_grid.add_theme_constant_override("v_separation", 8)
	vbox.add_child(fc_grid)
	
	for dir_key in ["NS", "EW", "SN", "WE"]:
		var lbl = Label.new()
		lbl.text = "• " + DIR_NAMES[dir_key] + ": -- %"
		fc_grid.add_child(lbl)
		labels["forecast_" + dir_key] = lbl
		
	vbox.add_child(HSeparator.new())
	
	# SECTION: AI OPTIMIZATION (đề xuất cho 4 hướng)
	var sec_ai = Label.new()
	sec_ai.text = "🤖 AI OPTIMIZATION (HÀM MỤC TIÊU min J)"
	vbox.add_child(sec_ai)

	var ai_grid = GridContainer.new()
	ai_grid.columns = 2
	ai_grid.add_theme_constant_override("h_separation", 30)
	ai_grid.add_theme_constant_override("v_separation", 6)
	vbox.add_child(ai_grid)

	for dir_key in ["NS", "EW", "SN", "WE"]:
		var lbl = Label.new()
		lbl.text = "👉 " + DIR_NAMES[dir_key] + ": --s"
		ai_grid.add_child(lbl)
		labels["ai_" + dir_key] = lbl

	var lbl_improve = Label.new()
	lbl_improve.text = "📈 Hiệu quả cải thiện: -- %"
	vbox.add_child(lbl_improve)
	labels["improvement"] = lbl_improve
	
	vbox.add_child(HSeparator.new())
	
	# SECTION: CONTROL
	var sec_feedback = Label.new()
	sec_feedback.text = "🎛️ FEEDBACK LOOP (Level 4)"
	vbox.add_child(sec_feedback)
	
	var btn_apply = Button.new()
	btn_apply.text = "ÁP DỤNG ĐỀ XUẤT CHU KỲ CỦA AI"
	btn_apply.custom_minimum_size = Vector2(0, 45)
	btn_apply.pressed.connect(self._on_apply_button_pressed)
	vbox.add_child(btn_apply)

# ╔══════════════════════════════════════════════════════════════╗
# ║  CẬP NHẬT DỮ LIỆU ĐỒNG BỘ TỪ WEBSOCKET                   ║
# ╚══════════════════════════════════════════════════════════════╝
func update_twin_state(new_data: Dictionary):
	for dir_key in ["NS", "EW", "SN", "WE"]:
		if new_data.has(dir_key):
			traffic_data[dir_key]["density"] = new_data[dir_key].get("density", 0.0)
			traffic_data[dir_key]["light"] = new_data[dir_key].get("light", "DO")
			traffic_data[dir_key]["time_left"] = new_data[dir_key].get("time_left", 0.0)
			
			# ── Cập nhật label mật độ + đèn + đếm ngược trên Dashboard ──
			var d_val = traffic_data[dir_key]["density"]
			var d_pct = snapped(d_val * 100, 0.1)
			var light_state = traffic_data[dir_key]["light"]
			var light_vn = "ĐỎ" if light_state == "DO" else ("VÀNG" if light_state == "VANG" else "XANH")
			var t_left = int(traffic_data[dir_key]["time_left"])
			var dir_name = DIR_NAMES[dir_key]
			labels["density_" + dir_key].text = "• " + dir_name + ": " + str(d_pct) + "% | " + light_vn + " | ⏱ " + str(t_left) + "s"
			labels["density_" + dir_key].add_theme_color_override("font_color", _get_color_by_density(d_val))
			
	if new_data.has("kpis"):
		var kpis = new_data["kpis"]
		labels["throughput"].text = "• Thông lượng: " + str(snapped(kpis.get("throughput", 0), 0.1)) + " xe/ph"
		labels["avgWait"].text = "• Chờ TB: " + str(snapped(kpis.get("avgWait", 0), 0.1)) + " s"
		labels["efficiency"].text = "• Hiệu suất: " + str(snapped(kpis.get("efficiency", 0), 0.1)) + " %"
		
	if new_data.has("forecast"):
		var fc = new_data["forecast"]
		for dir_key in ["NS", "EW", "SN", "WE"]:
			if fc.has(dir_key):
				labels["forecast_" + dir_key].text = "• " + DIR_NAMES[dir_key] + ": " + str(snapped(fc[dir_key] * 100, 0.1)) + " %"
				
	if new_data.has("ai_decision"):
		var ai = new_data["ai_decision"]
		traffic_data["ai_decision"] = ai
		# Cập nhật đề xuất 4 hướng
		var gt = ai.get("green_times", {})
		for dir_key in ["NS", "EW", "SN", "WE"]:
			if gt.has(dir_key):
				labels["ai_" + dir_key].text = "👉 " + DIR_NAMES[dir_key] + ": " + str(gt[dir_key]) + "s"
		labels["improvement"].text = "📈 Hiệu quả cải thiện: " + str(snapped(ai.get("improvement", 0), 0.1)) + " %"

func _on_apply_button_pressed():
	var net_manager = get_node_or_null("Network")
	var ai = traffic_data["ai_decision"]
	if net_manager and ai:
		var gt = ai.get("green_times", {})
		net_manager.send_control_action(gt)
		print("[FEEDBACK] Đã gửi lệnh điều khiển xuống Backend.")
