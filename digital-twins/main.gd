extends Node3D

## ╔══════════════════════════════════════════════════════════════╗
## ║  DIGITAL TWIN LEVEL 4 PRO — 3D VISUALIZATION               ║
## ║  Godot 4.7 — CSG Primitives + CanvasLayer Dashboard         ║
## ╚══════════════════════════════════════════════════════════════╝

# --- Constants ---
const ROAD_WIDTH := 15.0       # Chiều rộng đường (3 làn × 5m)
const ROAD_LENGTH := 120.0     # Chiều dài mỗi nhánh
const LANE_WIDTH := 5.0        # Chiều rộng 1 làn
const INTERSECTION_SIZE := 15.0
const ROAD_Y := 0.05           # Cao hơn mặt đất 1 chút

const DIR_NAMES := {
	"NS": "Bắc-Nam", "NS_LEFT": "B-N rẽ trái",
	"EW": "Đông-Tây", "EW_LEFT": "Đ-T rẽ trái",
	"SN": "Nam-Bắc", "SN_LEFT": "N-B rẽ trái",
	"WE": "Tây-Đông", "WE_LEFT": "T-Đ rẽ trái",
}

const PHASE_NAMES := {
	"PH1": "Rẽ trái B-N",
	"PH2": "Thẳng B-N",
	"PH3": "Rẽ trái Đ-T",
	"PH4": "Thẳng Đ-T",
}

const THROUGH_DIRS := ["NS", "EW", "SN", "WE"]
const ALL_DIRS := ["NS", "NS_LEFT", "EW", "EW_LEFT", "SN", "SN_LEFT", "WE", "WE_LEFT"]

# --- State ---
var traffic_data := {}
var _vehicle_nodes: Dictionary = {}  # {dir: [Node3D]}
var _traffic_light_meshes: Dictionary = {}  # {dir: MeshInstance3D}
var _labels: Dictionary = {}
var _road_materials: Dictionary = {}

func _ready():
	_init_traffic_data()
	_build_ground()
	_build_roads()
	_build_intersection()
	_build_traffic_lights()
	_build_dashboard()
	
	for dir_key in ALL_DIRS:
		_vehicle_nodes[dir_key] = []

func _init_traffic_data():
	for d in ALL_DIRS:
		traffic_data[d] = {"density": 0.0, "time_left": 0.0, "light": "DO"}
	traffic_data["kpis"] = {"throughput": 0.0, "avgWait": 0.0, "efficiency": 0.0}
	traffic_data["ai_decision"] = {"green_times": {"PH1": 15, "PH2": 35, "PH3": 12, "PH4": 30}, "improvement": 0.0}
	traffic_data["ground_truth"] = {}
	traffic_data["queue_counts"] = {}
	traffic_data["fidelity"] = 0.0
	traffic_data["velocity"] = {}
	traffic_data["sim_clock"] = {"time_str": "07:30:00", "speed": 1.0, "day": 1}
	traffic_data["auto_apply"] = true
	for d in ALL_DIRS:
		traffic_data["ground_truth"][d] = 0.0
		traffic_data["queue_counts"][d] = 0
		traffic_data["velocity"][d] = 0.0

func _process(_delta: float):
	_update_vehicles()
	_update_traffic_light_colors()

# ╔══════════════════════════════════════════════════════════════╗
# ║  XÂY DỰNG MÔI TRƯỜNG 3D                                    ║
# ╚══════════════════════════════════════════════════════════════╝

func _build_ground():
	var ground := CSGBox3D.new()
	ground.name = "Ground"
	ground.size = Vector3(300, 0.1, 300)
	ground.position = Vector3(0, -0.05, 0)
	var mat := StandardMaterial3D.new()
	mat.albedo_color = Color(0.08, 0.12, 0.06)
	ground.material = mat
	add_child(ground)

func _build_roads():
	var road_mat := StandardMaterial3D.new()
	road_mat.albedo_color = Color(0.18, 0.18, 0.2)
	_road_materials["road"] = road_mat
	
	var sidewalk_mat := StandardMaterial3D.new()
	sidewalk_mat.albedo_color = Color(0.35, 0.35, 0.32)
	
	var marking_mat := StandardMaterial3D.new()
	marking_mat.albedo_color = Color(0.95, 0.95, 0.95)
	marking_mat.emission_enabled = true
	marking_mat.emission = Color(0.5, 0.5, 0.5)
	marking_mat.emission_energy_multiplier = 0.3

	# Đường dọc (Bắc-Nam)
	var road_ns := CSGBox3D.new()
	road_ns.name = "RoadNS"
	road_ns.size = Vector3(ROAD_WIDTH, 0.12, ROAD_LENGTH * 2 + INTERSECTION_SIZE)
	road_ns.position = Vector3(0, ROAD_Y, 0)
	road_ns.material = road_mat
	add_child(road_ns)
	
	# Đường ngang (Đông-Tây)
	var road_ew := CSGBox3D.new()
	road_ew.name = "RoadEW"
	road_ew.size = Vector3(ROAD_LENGTH * 2 + INTERSECTION_SIZE, 0.12, ROAD_WIDTH)
	road_ew.position = Vector3(0, ROAD_Y, 0)
	road_ew.material = road_mat
	add_child(road_ew)
	
	# Vỉa hè (4 góc)
	for ix in [-1, 1]:
		for iz in [-1, 1]:
			var sw := CSGBox3D.new()
			sw.name = "Sidewalk_%d_%d" % [ix, iz]
			sw.size = Vector3(ROAD_LENGTH - 10, 0.3, ROAD_LENGTH - 10)
			sw.position = Vector3(ix * (ROAD_WIDTH/2 + (ROAD_LENGTH-10)/2 + 5), 0.15, iz * (ROAD_WIDTH/2 + (ROAD_LENGTH-10)/2 + 5))
			sw.material = sidewalk_mat
			add_child(sw)
	
	# Vạch tim đường (dọc)
	for seg in range(-10, 11):
		if abs(seg) <= 1: continue  # Skip intersection
		var mark := CSGBox3D.new()
		mark.size = Vector3(0.15, 0.14, 3.0)
		mark.position = Vector3(0, ROAD_Y + 0.01, seg * 10.0)
		mark.material = marking_mat
		add_child(mark)
	
	# Vạch tim đường (ngang)
	for seg in range(-10, 11):
		if abs(seg) <= 1: continue
		var mark := CSGBox3D.new()
		mark.size = Vector3(3.0, 0.14, 0.15)
		mark.position = Vector3(seg * 10.0, ROAD_Y + 0.01, 0)
		mark.material = marking_mat
		add_child(mark)
	
	# Vạch dừng (4 vị trí)
	var stop_mat := StandardMaterial3D.new()
	stop_mat.albedo_color = Color(1, 1, 1)
	stop_mat.emission_enabled = true
	stop_mat.emission = Color(0.8, 0.8, 0.8)
	stop_mat.emission_energy_multiplier = 0.5
	
	for data in [
		[Vector3(-(ROAD_WIDTH/4), ROAD_Y + 0.02, -(INTERSECTION_SIZE/2 + 0.5)), Vector3(ROAD_WIDTH/2, 0.13, 0.4)],
		[Vector3((ROAD_WIDTH/4), ROAD_Y + 0.02, (INTERSECTION_SIZE/2 + 0.5)), Vector3(ROAD_WIDTH/2, 0.13, 0.4)],
		[Vector3(-(INTERSECTION_SIZE/2 + 0.5), ROAD_Y + 0.02, (ROAD_WIDTH/4)), Vector3(0.4, 0.13, ROAD_WIDTH/2)],
		[Vector3((INTERSECTION_SIZE/2 + 0.5), ROAD_Y + 0.02, -(ROAD_WIDTH/4)), Vector3(0.4, 0.13, ROAD_WIDTH/2)],
	]:
		var stop := CSGBox3D.new()
		stop.position = data[0]
		stop.size = data[1]
		stop.material = stop_mat
		add_child(stop)

func _build_intersection():
	var int_mat := StandardMaterial3D.new()
	int_mat.albedo_color = Color(0.22, 0.22, 0.25)
	
	var ibox := CSGBox3D.new()
	ibox.name = "IntersectionBox"
	ibox.size = Vector3(INTERSECTION_SIZE + 2, 0.13, INTERSECTION_SIZE + 2)
	ibox.position = Vector3(0, ROAD_Y, 0)
	ibox.material = int_mat
	add_child(ibox)

func _build_traffic_lights():
	var pole_mat := StandardMaterial3D.new()
	pole_mat.albedo_color = Color(0.2, 0.2, 0.2)
	
	# Vị trí 4 cột đèn (góc ngã tư)
	var positions := {
		"NS": Vector3(-ROAD_WIDTH/2 - 2, 0, -INTERSECTION_SIZE/2 - 2),
		"SN": Vector3(ROAD_WIDTH/2 + 2, 0, INTERSECTION_SIZE/2 + 2),
		"EW": Vector3(INTERSECTION_SIZE/2 + 2, 0, -ROAD_WIDTH/2 - 2),
		"WE": Vector3(-INTERSECTION_SIZE/2 - 2, 0, ROAD_WIDTH/2 + 2),
	}
	
	for dir_key in positions:
		var pos: Vector3 = positions[dir_key]
		
		# Cột đèn
		var pole := CSGCylinder3D.new()
		pole.name = "Pole_" + dir_key
		pole.radius = 0.15
		pole.height = 8.0
		pole.position = pos + Vector3(0, 4, 0)
		pole.material = pole_mat
		add_child(pole)
		
		# Hộp đèn
		var box := CSGBox3D.new()
		box.name = "LightBox_" + dir_key
		box.size = Vector3(1.2, 3.5, 0.8)
		box.position = pos + Vector3(0, 7.0, 0)
		var box_mat := StandardMaterial3D.new()
		box_mat.albedo_color = Color(0.1, 0.1, 0.1)
		box.material = box_mat
		add_child(box)
		
		# 3 đèn (Đỏ / Vàng / Xanh)
		for li in range(3):
			var light_mesh := CSGSphere3D.new()
			light_mesh.name = "Light_%s_%d" % [dir_key, li]
			light_mesh.radius = 0.35
			light_mesh.position = pos + Vector3(0, 8.0 - li * 1.0, 0.5)
			var lmat := StandardMaterial3D.new()
			lmat.albedo_color = Color(0.1, 0.1, 0.1)
			light_mesh.material = lmat
			add_child(light_mesh)
			
			# Lưu reference cho đèn active
			if li == 0:  # Đèn đỏ
				_traffic_light_meshes[dir_key + "_R"] = light_mesh
			elif li == 1:  # Đèn vàng
				_traffic_light_meshes[dir_key + "_Y"] = light_mesh
			else:  # Đèn xanh
				_traffic_light_meshes[dir_key + "_G"] = light_mesh
		
		# OmniLight3D cho hiệu ứng phát sáng
		var omni := OmniLight3D.new()
		omni.name = "OmniLight_" + dir_key
		omni.position = pos + Vector3(0, 7.0, 1.5)
		omni.light_energy = 2.0
		omni.omni_range = 8.0
		omni.light_color = Color.RED
		add_child(omni)
		_traffic_light_meshes[dir_key + "_omni"] = omni
		
		# ── Đèn rẽ trái (nhỏ hơn, bên cạnh đèn chính) ──
		var lt_key: String = dir_key + "_LEFT"
		var lt_offsets := {
			"NS": Vector3(2.0, 0, 0),
			"SN": Vector3(-2.0, 0, 0),
			"EW": Vector3(0, 0, 2.0),
			"WE": Vector3(0, 0, -2.0),
		}
		var lt_off: Vector3 = lt_offsets[dir_key]
		
		var lt_pole := CSGCylinder3D.new()
		lt_pole.name = "LTPole_" + dir_key
		lt_pole.radius = 0.1
		lt_pole.height = 6.0
		lt_pole.position = pos + lt_off + Vector3(0, 3, 0)
		lt_pole.material = pole_mat
		add_child(lt_pole)
		
		var lt_box := CSGBox3D.new()
		lt_box.name = "LTBox_" + dir_key
		lt_box.size = Vector3(0.9, 2.8, 0.6)
		lt_box.position = pos + lt_off + Vector3(0, 5.5, 0)
		lt_box.material = box_mat
		add_child(lt_box)
		
		for li_lt in range(3):
			var lt_mesh := CSGSphere3D.new()
			lt_mesh.name = "LTLight_%s_%d" % [dir_key, li_lt]
			lt_mesh.radius = 0.28
			lt_mesh.position = pos + lt_off + Vector3(0, 6.3 - li_lt * 0.85, 0.4)
			var ltmat := StandardMaterial3D.new()
			ltmat.albedo_color = Color(0.1, 0.1, 0.1)
			lt_mesh.material = ltmat
			add_child(lt_mesh)
			
			if li_lt == 0:
				_traffic_light_meshes[lt_key + "_R"] = lt_mesh
			elif li_lt == 1:
				_traffic_light_meshes[lt_key + "_Y"] = lt_mesh
			else:
				_traffic_light_meshes[lt_key + "_G"] = lt_mesh
		
		var lt_omni := OmniLight3D.new()
		lt_omni.name = "LTOmni_" + dir_key
		lt_omni.position = pos + lt_off + Vector3(0, 5.5, 1.0)
		lt_omni.light_energy = 1.5
		lt_omni.omni_range = 6.0
		lt_omni.light_color = Color.RED
		add_child(lt_omni)
		_traffic_light_meshes[lt_key + "_omni"] = lt_omni

func _update_traffic_light_colors():
	for dir_key in THROUGH_DIRS:
		var state_str: String = traffic_data[dir_key]["light"]
		
		# Reset tất cả đèn về tối
		for suffix in ["_R", "_Y", "_G"]:
			var mesh: CSGSphere3D = _traffic_light_meshes.get(dir_key + suffix)
			if mesh:
				var mat: StandardMaterial3D = mesh.material as StandardMaterial3D
				if mat:
					mat.albedo_color = Color(0.15, 0.15, 0.15)
					mat.emission_enabled = false
		
		# Bật đèn active
		var active_suffix := "_R"
		var light_color := Color.RED
		
		if state_str == "XANH":
			active_suffix = "_G"
			light_color = Color(0.1, 0.95, 0.3)
		elif state_str == "VANG":
			active_suffix = "_Y"
			light_color = Color(1.0, 0.9, 0.1)
		else:
			active_suffix = "_R"
			light_color = Color(1.0, 0.15, 0.1)
		
		var active_mesh: CSGSphere3D = _traffic_light_meshes.get(dir_key + active_suffix)
		if active_mesh:
			var mat: StandardMaterial3D = active_mesh.material as StandardMaterial3D
			if mat:
				mat.albedo_color = light_color
				mat.emission_enabled = true
				mat.emission = light_color
				mat.emission_energy_multiplier = 3.0
		
		# Cập nhật OmniLight
		var omni: OmniLight3D = _traffic_light_meshes.get(dir_key + "_omni")
		if omni:
			omni.light_color = light_color
	
	# ── Cập nhật đèn rẽ trái ──
	for dir_key_lt in THROUGH_DIRS:
		var lt_key: String = dir_key_lt + "_LEFT"
		var lt_state: String = traffic_data[lt_key]["light"]
		
		# Reset đèn rẽ trái về tối
		for suffix in ["_R", "_Y", "_G"]:
			var lt_mesh: CSGSphere3D = _traffic_light_meshes.get(lt_key + suffix)
			if lt_mesh:
				var lt_mat: StandardMaterial3D = lt_mesh.material as StandardMaterial3D
				if lt_mat:
					lt_mat.albedo_color = Color(0.15, 0.15, 0.15)
					lt_mat.emission_enabled = false
		
		# Bật đèn rẽ trái active
		var lt_suffix := "_R"
		var lt_color := Color.RED
		
		if lt_state == "XANH":
			lt_suffix = "_G"
			lt_color = Color(0.1, 0.95, 0.3)
		elif lt_state == "VANG":
			lt_suffix = "_Y"
			lt_color = Color(1.0, 0.9, 0.1)
		else:
			lt_suffix = "_R"
			lt_color = Color(1.0, 0.15, 0.1)
		
		var lt_active: CSGSphere3D = _traffic_light_meshes.get(lt_key + lt_suffix)
		if lt_active:
			var lt_mat: StandardMaterial3D = lt_active.material as StandardMaterial3D
			if lt_mat:
				lt_mat.albedo_color = lt_color
				lt_mat.emission_enabled = true
				lt_mat.emission = lt_color
				lt_mat.emission_energy_multiplier = 3.0
		
		var lt_omni: OmniLight3D = _traffic_light_meshes.get(lt_key + "_omni")
		if lt_omni:
			lt_omni.light_color = lt_color

# ╔══════════════════════════════════════════════════════════════╗
# ║  XE 3D (CSG PRIMITIVES)                                     ║
# ╚══════════════════════════════════════════════════════════════╝

func _update_vehicles():
	for dir_key in ALL_DIRS:
		var target: int = int(traffic_data["queue_counts"].get(dir_key, 0))
		var current: Array = _vehicle_nodes[dir_key]
		var light_state: String = traffic_data[dir_key].get("light", "DO")
		
		# Spawn thêm xe (ở cuối hàng chờ) — luôn cho phép
		while current.size() < target:
			var veh := _create_vehicle(dir_key, current.size())
			current.append(veh)
			add_child(veh)
		
		# Xóa xe — CHỈ khi đèn XANH (xe được phép rời đi)
		if light_state == "XANH":
			while current.size() > target and current.size() > 0:
				var v: Node3D = current.pop_front()
				v.queue_free()
		
		# Trượt xe còn lại tiến lên vị trí mới (lerp mượt mà)
		for i in range(current.size()):
			var new_pos := _get_vehicle_pos(dir_key, i)
			var veh: Node3D = current[i]
			veh.position = veh.position.lerp(new_pos, 0.15)

func _create_vehicle(dir_key: String, index: int) -> Node3D:
	var is_moto := randf() < 0.65
	var veh := CSGBox3D.new()
	veh.name = "Veh_%s_%d" % [dir_key, index]
	
	var mat := StandardMaterial3D.new()
	mat.emission_enabled = true
	mat.emission_energy_multiplier = 0.4
	
	if is_moto:
		veh.size = Vector3(0.6, 0.5, 1.8)
		var hue := randf()
		mat.albedo_color = Color.from_hsv(hue, 0.7, 0.9)
		mat.emission = Color.from_hsv(hue, 0.5, 0.3)
	else:
		veh.size = Vector3(1.8, 0.7, 4.2)
		var colors := [
			Color(0.8, 0.2, 0.2), Color(0.2, 0.4, 0.8),
			Color(0.9, 0.9, 0.9), Color(0.15, 0.15, 0.15),
			Color(0.7, 0.7, 0.1),
		]
		mat.albedo_color = colors[randi() % colors.size()]
		mat.emission = mat.albedo_color * 0.2
	
	veh.material = mat
	veh.position = _get_vehicle_pos(dir_key, index)
	
	# Xoay xe hướng Đông-Tây cho nằm ngang theo đường
	if dir_key in ["EW", "EW_LEFT", "WE", "WE_LEFT"]:
		veh.rotation_degrees.y = 90.0
	
	return veh

func _get_vehicle_pos(dir_key: String, index: int) -> Vector3:
	var spacing := 5.5
	var offset := (index + 1) * spacing
	var lane_y := ROAD_Y + 0.5
	
	match dir_key:
		"NS":
			return Vector3(-LANE_WIDTH, lane_y, -(INTERSECTION_SIZE/2 + offset))
		"NS_LEFT":
			return Vector3(-LANE_WIDTH/2, lane_y, -(INTERSECTION_SIZE/2 + offset))
		"SN":
			return Vector3(LANE_WIDTH, lane_y, INTERSECTION_SIZE/2 + offset)
		"SN_LEFT":
			return Vector3(LANE_WIDTH/2, lane_y, INTERSECTION_SIZE/2 + offset)
		"EW":
			return Vector3(INTERSECTION_SIZE/2 + offset, lane_y, -LANE_WIDTH)
		"EW_LEFT":
			return Vector3(INTERSECTION_SIZE/2 + offset, lane_y, -LANE_WIDTH/2)
		"WE":
			return Vector3(-(INTERSECTION_SIZE/2 + offset), lane_y, LANE_WIDTH)
		"WE_LEFT":
			return Vector3(-(INTERSECTION_SIZE/2 + offset), lane_y, LANE_WIDTH/2)
	return Vector3.ZERO

# ╔══════════════════════════════════════════════════════════════╗
# ║  DASHBOARD UI (CanvasLayer overlay)                          ║
# ╚══════════════════════════════════════════════════════════════╝

func _build_dashboard():
	var canvas := CanvasLayer.new()
	canvas.name = "DashboardUI"
	add_child(canvas)
	
	var panel := Panel.new()
	panel.name = "DashPanel"
	panel.size = Vector2(420, 720)
	panel.position = Vector2(10, 10)
	var style := StyleBoxFlat.new()
	style.bg_color = Color(0.03, 0.04, 0.08, 0.88)
	style.border_color = Color(0.2, 0.35, 0.7, 0.5)
	style.set_border_width_all(1)
	style.set_corner_radius_all(8)
	panel.add_theme_stylebox_override("panel", style)
	canvas.add_child(panel)
	
	var scroll := ScrollContainer.new()
	scroll.size = Vector2(400, 700)
	scroll.position = Vector2(10, 10)
	panel.add_child(scroll)
	
	var vbox := VBoxContainer.new()
	vbox.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	vbox.add_theme_constant_override("separation", 5)
	scroll.add_child(vbox)
	
	# Title
	_add_label(vbox, "title", "🚦 DIGITAL TWIN L4 PRO — COMMAND CENTER", 16, Color(0.6, 0.8, 1.0))
	_add_label(vbox, "arch", "SUMO + 4-Phase NEMA + PCE VN + Auto-Apply AI", 10, Color(0.4, 0.55, 0.8))
	vbox.add_child(HSeparator.new())
	
	# SimClock
	_add_label(vbox, "sec_clock", "🕐 SIMULATION CLOCK", 13, Color(0.8, 0.85, 1.0))
	_add_label(vbox, "clock_time", "• Thời gian: 07:30:00 | Speed: 1.0x | Day 1", 12, Color.WHITE)
	vbox.add_child(HSeparator.new())
	
	# Fidelity
	_add_label(vbox, "sec_fidelity", "🎯 FIDELITY", 13, Color(0.8, 0.85, 1.0))
	_add_label(vbox, "fidelity", "• Độ chính xác: -- %", 12, Color.WHITE)
	vbox.add_child(HSeparator.new())
	
	# Density (8 directions in 2 groups)
	_add_label(vbox, "sec_density", "🚗 MẬT ĐỘ XE (8 hướng, 4 pha)", 13, Color(0.8, 0.85, 1.0))
	for d in ALL_DIRS:
		var name_str: String = DIR_NAMES.get(d, d)
		_add_label(vbox, "d_" + d, "  " + name_str + ": --% | -- | ⏱ --s", 11, Color(0.7, 0.7, 0.7))
	vbox.add_child(HSeparator.new())
	
	# KPIs
	_add_label(vbox, "sec_kpi", "📊 KPI — HCM 2010", 13, Color(0.8, 0.85, 1.0))
	_add_label(vbox, "throughput", "• Thông lượng: -- PCU/ph", 12, Color.WHITE)
	_add_label(vbox, "avgWait", "• Chờ TB: -- s", 12, Color.WHITE)
	_add_label(vbox, "efficiency", "• Hiệu suất: -- %", 12, Color.WHITE)
	vbox.add_child(HSeparator.new())
	
	# AI Optimizer
	_add_label(vbox, "sec_ai", "🤖 AI OPTIMIZER (4 PHA)", 13, Color(0.8, 0.85, 1.0))
	for p in ["PH1", "PH2", "PH3", "PH4"]:
		_add_label(vbox, "ai_" + p, "  " + PHASE_NAMES[p] + ": --s", 11, Color(0.7, 0.7, 0.7))
	_add_label(vbox, "improvement", "📈 Cải thiện: -- %", 12, Color.WHITE)
	_add_label(vbox, "auto_apply_status", "🤖 Auto-Apply: ON", 12, Color(0.3, 0.9, 0.4))
	vbox.add_child(HSeparator.new())
	
	# PCE Info
	_add_label(vbox, "sec_pce", "🏍️ PCE (Giao thông VN)", 13, Color(0.8, 0.85, 1.0))
	_add_label(vbox, "pce_info", "• Xe máy: 0.25 PCU | Mix: 65% moto", 11, Color(0.6, 0.7, 0.8))
	vbox.add_child(HSeparator.new())
	
	# Controls
	_add_label(vbox, "sec_ctrl", "🎛️ CONTROLS", 13, Color(0.8, 0.85, 1.0))
	
	# Speed buttons
	var speed_hbox := HBoxContainer.new()
	speed_hbox.add_theme_constant_override("separation", 5)
	vbox.add_child(speed_hbox)
	
	for spd in [1, 5, 10, 30, 60]:
		var btn := Button.new()
		btn.text = str(spd) + "x"
		btn.custom_minimum_size = Vector2(55, 32)
		btn.pressed.connect(_on_speed_button.bind(spd))
		speed_hbox.add_child(btn)
	
	# Jump buttons
	var jump_hbox := HBoxContainer.new()
	jump_hbox.add_theme_constant_override("separation", 5)
	vbox.add_child(jump_hbox)
	
	for hr in [7, 8, 12, 17, 22]:
		var btn := Button.new()
		btn.text = str(hr) + ":00"
		btn.custom_minimum_size = Vector2(55, 32)
		btn.pressed.connect(_on_jump_button.bind(hr))
		jump_hbox.add_child(btn)
	
	# Apply AI + Toggle Auto
	var ctrl_hbox := HBoxContainer.new()
	ctrl_hbox.add_theme_constant_override("separation", 5)
	vbox.add_child(ctrl_hbox)
	
	var btn_apply := Button.new()
	btn_apply.text = "ÁP DỤNG AI"
	btn_apply.custom_minimum_size = Vector2(120, 36)
	btn_apply.pressed.connect(_on_apply_pressed)
	ctrl_hbox.add_child(btn_apply)
	
	var btn_toggle := Button.new()
	btn_toggle.text = "TOGGLE AUTO"
	btn_toggle.custom_minimum_size = Vector2(120, 36)
	btn_toggle.pressed.connect(_on_toggle_auto_pressed)
	ctrl_hbox.add_child(btn_toggle)

func _add_label(parent: Control, key: String, text: String, size: int, color: Color):
	var lbl := Label.new()
	lbl.text = text
	lbl.add_theme_font_size_override("font_size", size)
	lbl.add_theme_color_override("font_color", color)
	parent.add_child(lbl)
	_labels[key] = lbl

# ╔══════════════════════════════════════════════════════════════╗
# ║  CẬP NHẬT DỮ LIỆU TỪ WEBSOCKET                            ║
# ╚══════════════════════════════════════════════════════════════╝

func update_twin_state(data: Dictionary):
	# Directions
	for d in ALL_DIRS:
		if data.has(d):
			traffic_data[d]["density"] = data[d].get("density", 0.0)
			traffic_data[d]["light"] = data[d].get("light", "DO")
			traffic_data[d]["time_left"] = data[d].get("time_left", 0.0)
			
			var val: float = traffic_data[d]["density"]
			var pct: float = snapped(val * 100, 0.1)
			var light_str: String = traffic_data[d]["light"]
			var light_vn := "ĐỎ" if light_str == "DO" else ("VÀNG" if light_str == "VANG" else "XANH")
			var t_left := int(traffic_data[d]["time_left"])
			var name_str: String = DIR_NAMES.get(d, d)
			
			if _labels.has("d_" + d):
				_labels["d_" + d].text = "  " + name_str + ": " + str(pct) + "% | " + light_vn + " | ⏱ " + str(t_left) + "s"
				_labels["d_" + d].add_theme_color_override("font_color", _density_color(val))
	
	# KPIs
	if data.has("kpis"):
		var k: Dictionary = data["kpis"]
		_labels["throughput"].text = "• Thông lượng: " + str(snapped(k.get("throughput", 0), 0.1)) + " PCU/ph"
		_labels["avgWait"].text = "• Chờ TB: " + str(snapped(k.get("avgWait", 0), 0.1)) + " s"
		_labels["efficiency"].text = "• Hiệu suất: " + str(snapped(k.get("efficiency", 0), 0.1)) + " %"
	
	# AI Decision
	if data.has("ai_decision"):
		var ai: Dictionary = data["ai_decision"]
		traffic_data["ai_decision"] = ai
		var gt: Dictionary = ai.get("green_times", {})
		for p in ["PH1", "PH2", "PH3", "PH4"]:
			if gt.has(p) and _labels.has("ai_" + p):
				_labels["ai_" + p].text = "  " + PHASE_NAMES[p] + ": " + str(gt[p]) + "s"
		if _labels.has("improvement"):
			_labels["improvement"].text = "📈 Cải thiện: " + str(snapped(ai.get("improvement", 0), 0.1)) + " %"
	
	# Queue counts
	if data.has("queue_counts"):
		traffic_data["queue_counts"] = data["queue_counts"]
	if data.has("ground_truth"):
		traffic_data["ground_truth"] = data["ground_truth"]
	if data.has("velocity"):
		traffic_data["velocity"] = data["velocity"]
	
	# Fidelity
	if data.has("fidelity"):
		traffic_data["fidelity"] = data["fidelity"]
		var fid: float = data["fidelity"]
		if _labels.has("fidelity"):
			_labels["fidelity"].text = "• Độ chính xác: " + str(snapped(fid, 0.1)) + " %"
			var c := Color.GREEN if fid > 90.0 else (Color.YELLOW if fid > 70.0 else Color.RED)
			_labels["fidelity"].add_theme_color_override("font_color", c)
	
	# SimClock
	if data.has("sim_clock"):
		traffic_data["sim_clock"] = data["sim_clock"]
		var sc: Dictionary = data["sim_clock"]
		if _labels.has("clock_time"):
			_labels["clock_time"].text = "• " + str(sc.get("time_str", "??")) + " | Speed: " + str(sc.get("speed", 1)) + "x | Day " + str(sc.get("day", 1))
	
	# Auto-apply
	if data.has("auto_apply"):
		traffic_data["auto_apply"] = data["auto_apply"]
		if _labels.has("auto_apply_status"):
			var on: bool = data["auto_apply"]
			_labels["auto_apply_status"].text = "🤖 Auto-Apply: " + ("ON" if on else "OFF")
			_labels["auto_apply_status"].add_theme_color_override("font_color", Color(0.3, 0.9, 0.4) if on else Color(0.8, 0.3, 0.3))

func _density_color(d: float) -> Color:
	if d <= 0.15: return Color(0.2, 0.9, 0.4)
	elif d <= 0.35: return Color(0.5, 0.95, 0.2)
	elif d <= 0.55: return Color(1.0, 0.85, 0.15)
	elif d <= 0.75: return Color(1.0, 0.55, 0.1)
	elif d <= 0.90: return Color(1.0, 0.2, 0.2)
	else: return Color(0.85, 0.1, 0.85)

# ╔══════════════════════════════════════════════════════════════╗
# ║  BUTTON CALLBACKS                                           ║
# ╚══════════════════════════════════════════════════════════════╝

func _on_speed_button(speed: int):
	var net := get_node_or_null("Network")
	if net: net.send_speed_command(float(speed))

func _on_jump_button(hour: int):
	var net := get_node_or_null("Network")
	if net: net.send_jump_command(hour)

func _on_apply_pressed():
	var net := get_node_or_null("Network")
	var ai: Dictionary = traffic_data["ai_decision"]
	if net and ai:
		var gt: Dictionary = ai.get("green_times", {})
		net.send_control_action(gt)

func _on_toggle_auto_pressed():
	var net := get_node_or_null("Network")
	if net: net.send_toggle_auto()
