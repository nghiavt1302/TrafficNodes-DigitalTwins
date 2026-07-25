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
const EXIT_DIST := 58.0        # Xe chạy ra xa (gần mép đường ±60) rồi mới ẩn
const CROSS_DURATION := 2.8    # Giây để xe băng qua giao lộ + chạy ra xa
const RELEASE_INTERVAL := 0.8  # Nhịp thả xe khi đèn xanh (mọi hướng xanh thả đồng thời)
const VEH_Y := ROAD_Y + 0.06   # Độ cao đặt xe (đáy xe sát mặt đường)

# --- Model xe 3D (Kenney Car Kit, CC0) ---
const MODEL_DIR := "res://assets/car-kit/Models/GLB format/"
const MODEL_YAW_OFFSET := 0.0    # Kenney xe mũi +Z sẵn. Nếu ngược đầu → đổi 180.
const CAR_MODELS := ["sedan", "suv", "taxi", "hatchback-sports", "sedan-sports", "van", "police"]
const TRUCK_MODELS := ["truck", "delivery", "garbage-truck", "firetruck", "delivery-flat", "ambulance"]
const CAR_SCALE := 2.0
const TRUCK_SCALE := 1.8

# --- Xe máy (Poly by Google, CC-BY) — auto-scale theo chiều dài mục tiêu ---
const BIKE_DIR := "res://assets/bikes/"
const BIKE_MODELS := ["motorcycle", "motorcycle2", "motorcycle3"]
const BIKE_LEN := 3.0            # chiều dài mục tiêu của xe máy (đơn vị world)
const BIKE_YAW_OFFSET := 0.0     # tinh chỉnh thêm nếu cần (offset chính suy tự động từ trục dài model)

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
var _crossing: Array = []  # xe đang băng qua giao lộ: [{node,p0,p1,p2,t,dur}]
var _release_timer: float = 0.0  # đồng hồ nhịp thả xe (đồng bộ mọi hướng xanh)

# --- Môi trường: ngày/đêm + thời tiết ---
var _sun: DirectionalLight3D          # đèn mặt trời (đổi độ sáng theo giờ)
var _dt_env: Environment              # ambient + màu nền bầu trời
var _rain: CPUParticles3D             # hạt mưa (bật/tắt)
var _weather: String = "clear"        # "clear" | "rain"
var _btn_weather: Button              # nút bật/tắt mưa
var _btn_apply: Button                # nút ÁP DỤNG AI
var _btn_toggle: Button               # nút AUTO
var _btn_emergency: Button            # nút xe cấp cứu
var _btn_police: Button               # nút đoàn công an
var _emergency_active: bool = false   # đang ưu tiên
var _emergency_prev: bool = false     # trạng thái trước (bắt sườn lên)
var _emergency_dir: String = "NS"     # hướng ưu tiên
var _convoy_remaining: int = 0        # số xe còn phải sinh trong đợt
var _convoy_kind: String = "ambulance"
var _convoy_timer: float = 0.0        # nhịp sinh xe trong đoàn
var _emergency_movers: Array = []     # xe ưu tiên đang chạy dọc làn (có né vật cản)
const EMG_SPEED := 30.0               # tốc độ xe ưu tiên (đơn vị/giây)
const EMG_START := 58.0               # điểm xuất phát (cuối làn)
const EMG_END := -58.0                # điểm ra khỏi khung
const EMG_DODGE := 3.5                # độ lệch trái của xe ưu tiên (trong lòng đường)
const EMG_YIELD := 2.5                # độ dạt phải của xe thường nhường đường
var _ambulance_lights: Array = []     # [{light, mesh}] để nhấp nháy
var _blink_t: float = 0.0             # đồng hồ nhấp nháy
# --- Còi hụ (tổng hợp real-time, không cần file audio) ---
var _siren_player: AudioStreamPlayer
var _siren_pb: AudioStreamGeneratorPlayback
var _siren_phase: float = 0.0
var _siren_t: float = 0.0
var _siren_on: bool = false
const SIREN_RATE := 22050.0
var _speed_buttons: Dictionary = {}   # {speed:int -> Button}
var _hour_buttons: Dictionary = {}    # {hour:int -> Button}
var _active_speed: int = 1            # speed đang chọn (để tô sáng)
var _active_hour: int = -1            # giờ vừa nhảy tới (để tô sáng)

# --- So sánh baseline + biểu đồ 24h ---
var _chart_lines: Dictionary = {}     # {"fixed"/"actuated"/"ai" -> Line2D}
var _chart_data: Dictionary = {"fixed": {}, "actuated": {}, "ai": {}}  # series -> {hour:val}
const CHART_MAXQ := 90.0              # trần trục Y (xe chờ)
const CHART_X0 := 40.0
const CHART_Y_TOP := 54.0
const CHART_W := 410.0
const CHART_H := 104.0
const CMP_COLORS := {"fixed": Color(0.95, 0.35, 0.35), "actuated": Color(0.98, 0.72, 0.25), "ai": Color(0.35, 0.95, 0.55)}

func _ready():
	_init_traffic_data()
	_build_siren()
	_build_lighting()
	_build_rain()
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

func _process(delta: float):
	_update_vehicles()
	_release_green_vehicles(delta)
	_update_crossing(delta)
	_update_traffic_light_colors()
	# Sinh xe ưu tiên: cả đoàn (số hữu hạn), nối đuôi cách nhau
	if _convoy_remaining > 0:
		_convoy_timer += delta
		if _convoy_timer >= 0.55:
			_convoy_timer = 0.0
			_spawn_emergency_vehicle(_emergency_dir, _convoy_kind)
			_convoy_remaining -= 1
	_update_emergency_movers(delta)
	_update_beacons(delta)
	_update_siren(delta)

# ╔══════════════════════════════════════════════════════════════╗
# ║  XÂY DỰNG MÔI TRƯỜNG 3D                                    ║
# ╚══════════════════════════════════════════════════════════════╝

func _build_lighting():
	# Đèn mặt trời (định hướng) — độ sáng/màu đổi theo giờ mô phỏng
	var sun := DirectionalLight3D.new()
	sun.name = "Sun"
	sun.rotation_degrees = Vector3(-55, -40, 0)
	sun.light_energy = 1.3
	add_child(sun)
	_sun = sun

	# Ánh sáng môi trường (ambient) + màu nền bầu trời
	var we := WorldEnvironment.new()
	we.name = "WorldEnv"
	var env := Environment.new()
	env.background_mode = Environment.BG_COLOR
	env.background_color = Color(0.10, 0.12, 0.16)
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color(0.65, 0.70, 0.80)
	env.ambient_light_energy = 1.0
	we.environment = env
	add_child(we)
	_dt_env = env

# ── Mưa: hạt rơi từ trên xuống, phủ khu ngã tư (mặc định TẮT) ──
func _build_rain():
	var rain := CPUParticles3D.new()
	rain.name = "Rain"
	rain.position = Vector3(0, 45, 0)         # nguồn phát cao phía trên
	rain.amount = 900
	rain.lifetime = 1.4
	rain.emitting = false                      # bật khi trời mưa
	rain.local_coords = false
	# Phát trong 1 hộp rộng phủ toàn ngã tư
	rain.emission_shape = CPUParticles3D.EMISSION_SHAPE_BOX
	rain.emission_box_extents = Vector3(120, 1, 120)
	# Rơi thẳng xuống, nhanh
	rain.direction = Vector3(0, -1, 0)
	rain.spread = 2.0
	rain.gravity = Vector3(0, -35, 0)
	rain.initial_velocity_min = 45.0
	rain.initial_velocity_max = 60.0
	# Hạt mưa = vệt nhỏ dài, hơi xanh trong
	var mesh := BoxMesh.new()
	mesh.size = Vector3(0.06, 0.9, 0.06)
	rain.mesh = mesh
	var mat := StandardMaterial3D.new()
	mat.albedo_color = Color(0.6, 0.72, 0.9, 0.55)
	mat.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	rain.material_override = mat
	add_child(rain)
	_rain = rain

# ── Áp ánh sáng theo giờ (0–24) + thời tiết ──
func _apply_environment(hour_f: float, weather: String):
	# Hệ số ban ngày: 0 = đêm tối, 1 = trưa sáng. Chuyển mượt quanh bình minh/hoàng hôn.
	# Sáng dần 5→8h, tối dần 17→20h.
	var day := clampf((hour_f - 5.0) / 3.0, 0.0, 1.0) * clampf((20.0 - hour_f) / 3.0, 0.0, 1.0)
	day = clampf(day, 0.0, 1.0)

	var is_rain := weather == "rain"
	# Mưa → tối hơn (u ám), giảm thêm độ sáng
	var overcast := 0.55 if is_rain else 1.0

	if _sun:
		_sun.light_energy = lerpf(0.08, 1.35, day) * overcast
		# Bình minh/hoàng hôn ngả vàng cam; trưa trắng; đêm xanh lạnh
		var warm := Color(1.0, 0.72, 0.45)   # cam lúc chạng vạng
		var noon := Color(1.0, 0.98, 0.92)   # trắng ban ngày
		var golden := clampf(1.0 - absf(day - 0.5) * 2.0, 0.0, 1.0)  # cao khi day~0.5
		var sun_col := noon.lerp(warm, golden * 0.6)
		if is_rain:
			sun_col = sun_col.lerp(Color(0.7, 0.75, 0.82), 0.5)  # xám khi mưa
		_sun.light_color = sun_col

	if _dt_env:
		# Ambient: ngày sáng xanh-trắng, đêm xanh đậm tối
		var amb_day := Color(0.70, 0.75, 0.85)
		var amb_night := Color(0.12, 0.15, 0.26)
		if is_rain:
			amb_day = Color(0.45, 0.50, 0.58)   # xám ẩm
		_dt_env.ambient_light_color = amb_night.lerp(amb_day, day)
		_dt_env.ambient_light_energy = lerpf(0.28, 1.0, day) * (0.8 if is_rain else 1.0)
		# Màu nền bầu trời
		var sky_day := Color(0.45, 0.62, 0.85)
		var sky_night := Color(0.04, 0.05, 0.09)
		if is_rain:
			sky_day = Color(0.32, 0.36, 0.42)   # trời mưa xám
		_dt_env.background_color = sky_night.lerp(sky_day, day)

	# Bật/tắt hạt mưa
	if _rain and _rain.emitting != is_rain:
		_rain.emitting = is_rain

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

		# Xe rời hàng do nhịp thả (_release_green_vehicles), không xử lý ở đây.
		# Trượt xe còn lại tiến lên vị trí mới (lerp mượt mà)
		# Nếu có xe ưu tiên trên cùng trục → tất cả xe cùng đường dạt phải và dừng
		var yv := Vector3.ZERO
		if _emergency_active and _same_road(dir_key, _emergency_dir):
			yv = _yield_vec_for_dir(dir_key)
		for i in range(current.size()):
			var new_pos := _get_vehicle_pos(dir_key, i) + yv
			var veh: Node3D = current[i]
			veh.position = veh.position.lerp(new_pos, 0.15)

func _release_green_vehicles(delta: float) -> void:
	"""Nhịp thả xe đồng bộ: mỗi RELEASE_INTERVAL, MỌI hướng đang XANH cùng
	thả 1 xe đầu hàng băng qua giao lộ → 2 hướng cùng pha chạy đồng thời."""
	_release_timer += delta
	if _release_timer < RELEASE_INTERVAL:
		return
	_release_timer = 0.0
	for dir_key in ALL_DIRS:
		if traffic_data[dir_key].get("light", "DO") != "XANH":
			continue
		# Xe cùng đường với đoàn ưu tiên phải tấp lề, không được băng qua
		if _emergency_active and _same_road(dir_key, _emergency_dir):
			continue
		var current: Array = _vehicle_nodes[dir_key]
		if current.size() > 0:
			var v: Node3D = current.pop_front()
			_start_crossing(dir_key, v)

func _create_vehicle(dir_key: String, index: int) -> Node3D:
	# Pivot = gốc xe (đáy sát đất, mũi hướng +Z). Model/CSG gắn vào trong.
	var pivot := Node3D.new()
	pivot.name = "Veh_%s_%d" % [dir_key, index]

	# Phân loại theo tỷ lệ giao thông VN: 65% moto, 25% ôtô con, 10% xe lớn
	var r := randf()
	if r < 0.65:
		_attach_bike(pivot)
	elif r < 0.90:
		_attach_model(pivot, CAR_MODELS[randi() % CAR_MODELS.size()], CAR_SCALE)
	else:
		_attach_model(pivot, TRUCK_MODELS[randi() % TRUCK_MODELS.size()], TRUCK_SCALE)

	pivot.position = _get_vehicle_pos(dir_key, index)
	pivot.rotation_degrees.y = _dir_heading(dir_key)
	return pivot

func _attach_model(pivot: Node3D, model_name: String, model_scale: float) -> void:
	"""Gắn model GLB (Kenney) vào pivot; fallback moto nếu load lỗi."""
	var scene: Resource = load(MODEL_DIR + model_name + ".glb")
	if scene == null:
		_build_moto_csg(pivot)
		return
	var m: Node3D = scene.instantiate()
	m.scale = Vector3(model_scale, model_scale, model_scale)
	m.rotation_degrees.y = MODEL_YAW_OFFSET
	pivot.add_child(m)

func _attach_bike(pivot: Node3D) -> void:
	"""Gắn model xe máy GLB thật, auto-scale về BIKE_LEN. Fallback CSG nếu lỗi."""
	var model_name: String = BIKE_MODELS[randi() % BIKE_MODELS.size()]
	var scene: Resource = load(BIKE_DIR + model_name + ".glb")
	if scene == null:
		_build_moto_csg(pivot)
		return
	var m: Node3D = scene.instantiate()
	var aabb := _node_aabb(m)
	var longest: float = max(aabb.size.x, aabb.size.z)
	var s := 1.0
	if longest > 0.001:
		s = BIKE_LEN / longest
	m.scale = Vector3(s, s, s)
	# Chuẩn hóa mũi xe về +Z: model dài theo X → xoay -90; dài theo Z → giữ nguyên
	var yaw := BIKE_YAW_OFFSET
	if aabb.size.x > aabb.size.z:
		yaw += -90.0
	m.rotation_degrees.y = yaw
	m.position.y = -aabb.position.y * s   # đáy xe lên mặt đường
	_relight_meshes(m)   # giữ màu gốc, khử metallic gây đen
	pivot.add_child(m)

func _relight_meshes(root: Node3D) -> void:
	"""Giữ màu/texture gốc nhưng đặt metallic=0, roughness cao → hết đen."""
	var stack: Array = [root]
	while not stack.is_empty():
		var n = stack.pop_back()
		for c in n.get_children():
			stack.append(c)
		if n is MeshInstance3D:
			var mi := n as MeshInstance3D
			if mi.mesh == null:
				continue
			for i in range(mi.mesh.get_surface_count()):
				var base := mi.get_active_material(i)
				var mat: StandardMaterial3D
				if base is StandardMaterial3D:
					mat = (base as StandardMaterial3D).duplicate()
				else:
					mat = StandardMaterial3D.new()
				mat.metallic = 0.0
				mat.roughness = 0.9
				mi.set_surface_override_material(i, mat)

func _node_aabb(root: Node3D) -> AABB:
	"""Gộp AABB mọi mesh trong cây (tọa độ local của root)."""
	var acc := AABB()
	var first := true
	var stack: Array = [root]
	while not stack.is_empty():
		var n = stack.pop_back()
		for c in n.get_children():
			stack.append(c)
		if n is VisualInstance3D:
			var a: AABB = n.get_aabb()
			# nhân dồn transform từ n lên tới root
			var t := Transform3D.IDENTITY
			var cur: Node = n
			while cur != root and cur != null:
				t = (cur as Node3D).transform * t
				cur = cur.get_parent()
			a = t * a
			if first:
				acc = a
				first = false
			else:
				acc = acc.merge(a)
	if first:
		return AABB(Vector3.ZERO, Vector3.ONE)
	return acc

func _build_moto_csg(pivot: Node3D) -> void:
	"""Fallback: xe máy low-poly bằng CSG (khi model lỗi)."""
	var hue := randf()
	var body := CSGBox3D.new()
	body.size = Vector3(0.5, 0.45, 1.7)
	body.position = Vector3(0, 0.45, 0)
	var bmat := StandardMaterial3D.new()
	bmat.albedo_color = Color.from_hsv(hue, 0.75, 0.95)
	body.material = bmat
	pivot.add_child(body)

func _dir_heading(dir_key: String) -> float:
	"""Góc quay Y (độ) theo hướng đi của làn: 0=+Z, 180=-Z, 90=+X, -90=-X."""
	match dir_key:
		"NS", "NS_LEFT": return 0.0
		"SN", "SN_LEFT": return 180.0
		"WE", "WE_LEFT": return 90.0
		"EW", "EW_LEFT": return -90.0
	return 0.0

func _get_vehicle_pos(dir_key: String, index: int) -> Vector3:
	var spacing := 8.0
	var offset := (index + 1) * spacing
	var lane_y := VEH_Y
	
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
# ║  XE BĂNG QUA GIAO LỘ (thẳng qua + rẽ trái cong)             ║
# ╚══════════════════════════════════════════════════════════════╝

func _build_siren() -> void:
	"""Tạo còi hụ tổng hợp real-time (không cần file audio)."""
	_siren_player = AudioStreamPlayer.new()
	var gen := AudioStreamGenerator.new()
	gen.mix_rate = SIREN_RATE
	gen.buffer_length = 0.15
	_siren_player.stream = gen
	_siren_player.volume_db = -6.0
	add_child(_siren_player)

func _update_siren(delta: float) -> void:
	# Bật/tắt còi theo trạng thái ưu tiên
	if _emergency_active and not _siren_on:
		_siren_player.play()
		_siren_pb = _siren_player.get_stream_playback()
		_siren_on = true
	elif not _emergency_active and _siren_on:
		_siren_player.stop()
		_siren_pb = null
		_siren_on = false
	if not _siren_on or _siren_pb == null:
		return
	# Đổ mẫu: còi 2 tông (700Hz ↔ 950Hz, đổi mỗi 0.5s)
	var frames := _siren_pb.get_frames_available()
	for i in range(frames):
		_siren_t += 1.0 / SIREN_RATE
		if _siren_t > 100.0:
			_siren_t = 0.0
		var freq := 700.0 if fmod(_siren_t, 1.0) < 0.5 else 950.0
		_siren_phase += TAU * freq / SIREN_RATE
		if _siren_phase > TAU:
			_siren_phase -= TAU
		var s := sin(_siren_phase) * 0.3
		_siren_pb.push_frame(Vector2(s, s))

func _spawn_emergency_vehicle(dir_key: String, kind: String = "ambulance") -> void:
	"""Sinh 1 xe ưu tiên nổi bật băng qua giao lộ theo hướng ưu tiên."""
	var pivot := Node3D.new()
	if kind == "police":
		pivot.name = "Police"
		_attach_model(pivot, "police", CAR_SCALE * 1.15)
	else:
		pivot.name = "Ambulance"
		_attach_model(pivot, "ambulance", TRUCK_SCALE * 1.4)
	# Đèn hiệu trên nóc (quả cầu phát sáng to + đèn point mạnh) — nhấp nháy đỏ/xanh
	var beacon := CSGSphere3D.new()
	beacon.radius = 1.0
	beacon.position = Vector3(0, 4.0, 0)
	var bm := StandardMaterial3D.new()
	bm.albedo_color = Color(1.0, 0.12, 0.12)
	bm.emission_enabled = true
	bm.emission = Color(1.0, 0.12, 0.12)
	bm.emission_energy_multiplier = 16.0
	bm.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	beacon.material = bm
	pivot.add_child(beacon)
	var ol := OmniLight3D.new()
	ol.light_color = Color(1.0, 0.15, 0.15)
	ol.light_energy = 16.0
	ol.omni_range = 30.0
	ol.position = Vector3(0, 4.2, 0)
	pivot.add_child(ol)
	pivot.rotation_degrees.y = _dir_heading(dir_key)
	add_child(pivot)
	_ambulance_lights.append({"light": ol, "mesh": beacon, "kind": kind})
	# Chạy dọc làn có né vật cản (thay vì bay theo đường cong)
	_emergency_movers.append({"node": pivot, "dir": dir_key, "d": 0.0, "offset": 0.0})

# ── Xe ưu tiên chạy dọc làn, né xe cản rồi về làn ──
func _update_emergency_movers(delta: float) -> void:
	var total := EMG_START - EMG_END   # tổng quãng đường
	var still: Array = []
	for m in _emergency_movers:
		var node = m["node"]
		if not is_instance_valid(node):
			continue
		m["d"] += EMG_SPEED * delta
		if m["d"] >= total:
			node.queue_free()
			continue
		var frac: float = m["d"] / total
		var along := lerpf(EMG_START, EMG_END, frac)
		var dir: String = m["dir"]
		# Xe ưu tiên đi LỆCH TRÁI trong lòng đường (xe thường dạt phải nhường)
		m["offset"] = lerpf(m["offset"], -EMG_DODGE, clampf(delta * 4.0, 0.0, 1.0))
		node.position = _emg_pos(dir, along, m["offset"])
	_emergency_movers = _emergency_movers.filter(func(x): return is_instance_valid(x["node"]))

func _same_side(dir_key: String, emg_dir: String) -> bool:
	"""dir_key có cùng trục+chiều với hướng ưu tiên (gồm cả làn rẽ trái)?"""
	return dir_key == emg_dir or dir_key == emg_dir + "_LEFT"

func _same_road(dir_key: String, emg_dir: String) -> bool:
	"""Cùng trục đường (cả 2 chiều): NS↔SN hoặc EW↔WE, kể cả làn rẽ trái."""
	var AXIS := {"NS": "NS_SN", "SN": "NS_SN", "NS_LEFT": "NS_SN", "SN_LEFT": "NS_SN",
				 "EW": "EW_WE", "WE": "EW_WE", "EW_LEFT": "EW_WE", "WE_LEFT": "EW_WE"}
	return AXIS.get(dir_key, "A") == AXIS.get(emg_dir, "B")

func _yield_vec(emg_dir: String) -> Vector3:
	"""Vector dạt phải để xe thường nhường xe ưu tiên."""
	match emg_dir:
		"WE": return Vector3(0, 0, EMG_YIELD)
		"EW": return Vector3(0, 0, -EMG_YIELD)
		"SN": return Vector3(EMG_YIELD, 0, 0)
		"NS": return Vector3(-EMG_YIELD, 0, 0)
	return Vector3.ZERO

func _yield_vec_for_dir(dir_key: String) -> Vector3:
	"""Dạt phải theo hướng đi của chính xe đó (không phụ thuộc hướng xe ưu tiên)."""
	var base := dir_key.replace("_LEFT", "")
	return _yield_vec(base)

func _emg_pos(dir_key: String, along: float, offset: float) -> Vector3:
	var y := VEH_Y
	match dir_key:
		"SN": return Vector3(LANE_WIDTH + offset, y, along)
		"NS": return Vector3(-LANE_WIDTH - offset, y, -along)
		"WE": return Vector3(-along, y, LANE_WIDTH + offset)
		"EW": return Vector3(along, y, -LANE_WIDTH - offset)
	return Vector3(LANE_WIDTH + offset, y, along)

func _emg_blocked(dir_key: String, node: Node3D) -> bool:
	var cars: Array = _vehicle_nodes.get(dir_key, [])
	var ap := node.position
	for c in cars:
		if not is_instance_valid(c):
			continue
		var cp: Vector3 = c.position
		var ahead := false
		var lat_close := false
		match dir_key:
			"SN": ahead = (ap.z - cp.z) > 1.0 and (ap.z - cp.z) < 16.0; lat_close = abs(ap.x - cp.x) < 3.5
			"NS": ahead = (cp.z - ap.z) > 1.0 and (cp.z - ap.z) < 16.0; lat_close = abs(ap.x - cp.x) < 3.5
			"WE": ahead = (cp.x - ap.x) > 1.0 and (cp.x - ap.x) < 16.0; lat_close = abs(ap.z - cp.z) < 3.5
			"EW": ahead = (ap.x - cp.x) > 1.0 and (ap.x - cp.x) < 16.0; lat_close = abs(ap.z - cp.z) < 3.5
		if ahead and lat_close:
			return true
	return false

# Nhấp nháy đèn hiệu đỏ ↔ xanh (như đèn xe cấp cứu thật)
func _update_beacons(delta: float) -> void:
	_blink_t += delta
	var phase_a := fmod(_blink_t, 0.4) < 0.2
	var still: Array = []
	for b in _ambulance_lights:
		var light = b.get("light")
		var mesh = b.get("mesh")
		if not is_instance_valid(light) or not is_instance_valid(mesh):
			continue
		var kind := str(b.get("kind", "ambulance"))
		var col: Color
		if kind == "police":
			col = Color(0.15, 0.4, 1.0) if phase_a else Color(0.95, 0.97, 1.0)   # xanh dương / trắng
		else:
			col = Color(1.0, 0.1, 0.1) if phase_a else Color(0.15, 0.35, 1.0)     # đỏ / xanh
		light.light_color = col
		light.light_energy = 18.0
		var mat := mesh.material as StandardMaterial3D
		if mat:
			mat.albedo_color = col
			mat.emission = col
		still.append(b)
	_ambulance_lights = still

func _start_crossing(dir_key: String, node: Node3D) -> void:
	var path := _get_cross_path(dir_key)
	node.position = path[0]
	_crossing.append({
		"node": node, "p0": path[0], "p1": path[1], "p2": path[2],
		"t": 0.0, "dur": CROSS_DURATION,
	})

func _update_crossing(delta: float) -> void:
	var still: Array = []
	for c in _crossing:
		if not is_instance_valid(c.node):
			continue
		c.t += delta / c.dur
		if c.t >= 1.0:
			c.node.queue_free()
			continue
		var pos := _bezier(c.p0, c.p1, c.p2, c.t)
		c.node.position = pos
		var tang := _bezier_tangent(c.p0, c.p1, c.p2, c.t)
		if tang.length() > 0.001:
			c.node.rotation_degrees.y = rad_to_deg(atan2(tang.x, tang.z))
		still.append(c)
	_crossing = still

func _bezier(p0: Vector3, p1: Vector3, p2: Vector3, t: float) -> Vector3:
	var u := 1.0 - t
	return u * u * p0 + 2.0 * u * t * p1 + t * t * p2

func _bezier_tangent(p0: Vector3, p1: Vector3, p2: Vector3, t: float) -> Vector3:
	return 2.0 * (1.0 - t) * (p1 - p0) + 2.0 * t * (p2 - p1)

func _get_cross_path(dir_key: String) -> Array:
	"""Trả [p0, p1, p2] cho quadratic bezier. Thẳng: p1 = trung điểm."""
	var y := VEH_Y
	var h := INTERSECTION_SIZE / 2.0   # biên giao lộ = 7.5
	var lw := LANE_WIDTH               # 5.0
	var hw := LANE_WIDTH / 2.0         # 2.5 (làn rẽ trái)
	var e := EXIT_DIST

	var p0: Vector3
	var p2: Vector3

	match dir_key:
		# ── Thẳng: đi qua ra nhánh đối diện (p1 = trung điểm → đường thẳng) ──
		"NS":  p0 = Vector3(-lw, y, -h);  p2 = Vector3(-lw, y, e)
		"SN":  p0 = Vector3(lw, y, h);    p2 = Vector3(lw, y, -e)
		"EW":  p0 = Vector3(h, y, -lw);   p2 = Vector3(-e, y, -lw)
		"WE":  p0 = Vector3(-h, y, lw);   p2 = Vector3(e, y, lw)
		# ── Rẽ trái: cong 90° sang nhánh bên trái (p1 = góc quẹo) ──
		"NS_LEFT": return [Vector3(-hw, y, -h), Vector3(-hw, y, hw), Vector3(e, y, hw)]
		"SN_LEFT": return [Vector3(hw, y, h), Vector3(hw, y, -hw), Vector3(-e, y, -hw)]
		"EW_LEFT": return [Vector3(h, y, -hw), Vector3(-hw, y, -hw), Vector3(-hw, y, e)]
		"WE_LEFT": return [Vector3(-h, y, hw), Vector3(hw, y, hw), Vector3(hw, y, -e)]
		_:         p0 = Vector3.ZERO; p2 = Vector3.ZERO

	return [p0, (p0 + p2) * 0.5, p2]

# ╔══════════════════════════════════════════════════════════════╗
# ║  DASHBOARD UI (CanvasLayer overlay)                          ║
# ╚══════════════════════════════════════════════════════════════╝

const PANEL_W := 360
const PANEL_MARGIN := 12
const PANEL_TOP_ANCHOR := 0.4  # panel bắt đầu từ 40% chiều cao → chỉ chiếm nửa dưới

func _build_dashboard():
	var canvas := CanvasLayer.new()
	canvas.name = "Dashboard"
	canvas.layer = 10
	add_child(canvas)
	
	# ── Helper: tạo panel với style ──
	var _make_panel := func(parent: Node, pos: Vector2, sz: Vector2) -> Panel:
		var p := Panel.new()
		p.size = sz
		p.position = pos
		var s := StyleBoxFlat.new()
		s.bg_color = Color(0.03, 0.04, 0.08, 0.88)
		s.border_color = Color(0.2, 0.35, 0.7, 0.5)
		s.set_border_width_all(1)
		s.set_corner_radius_all(8)
		p.add_theme_stylebox_override("panel", s)
		parent.add_child(p)
		return p
	
	# ── Helper: tạo VBox trong panel ──
	var _make_vbox := func(panel: Panel, margin: float) -> VBoxContainer:
		var vb := VBoxContainer.new()
		vb.position = Vector2(margin, margin)
		vb.size = panel.size - Vector2(margin * 2, margin * 2)
		vb.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		vb.add_theme_constant_override("separation", 4)
		panel.add_child(vb)
		return vb
	
	# ╔══════════════════════════════════════════════════════════════╗
	# ║  TOP-LEFT: Clock + Fidelity + Phase                        ║
	# ╚══════════════════════════════════════════════════════════════╝
	var tl_panel: Panel = _make_panel.call(canvas, Vector2(10, 10), Vector2(340, 150))
	var tl_vbox: VBoxContainer = _make_vbox.call(tl_panel, 10.0)

	_add_label(tl_vbox, "title", "🚦 DIGITAL TWIN L4 PRO", 14, Color(0.6, 0.8, 1.0))
	_add_label(tl_vbox, "clock_time", "🕐 07:30:00 | Speed: 1.0x | Day 1", 12, Color.WHITE)
	_add_label(tl_vbox, "fidelity", "🎯 Fidelity: -- %", 12, Color.WHITE)
	_add_label(tl_vbox, "phase_info", "💡 Pha: -- | Còn: --s", 12, Color(0.8, 0.9, 1.0))
	_add_label(tl_vbox, "weather_info", "☀️ Tạnh | 🌤️ Ngày", 12, Color(0.75, 0.85, 1.0))
	_add_label(tl_vbox, "emergency_info", "", 12, Color(1.0, 0.3, 0.3))
	
	# ╔══════════════════════════════════════════════════════════════╗
	# ║  TOP-RIGHT: Density 8 directions                           ║
	# ╚══════════════════════════════════════════════════════════════╝
	var tr_panel: Panel = _make_panel.call(canvas, Vector2(1920 - 380 - 10, 10), Vector2(380, 205))
	# Anchor top-right
	tr_panel.set_anchors_preset(Control.PRESET_TOP_RIGHT)
	tr_panel.set_anchor(SIDE_LEFT, 1.0)
	tr_panel.set_anchor(SIDE_RIGHT, 1.0)
	tr_panel.offset_left = -390
	tr_panel.offset_right = -10
	tr_panel.offset_top = 10
	tr_panel.offset_bottom = 215
	var tr_vbox: VBoxContainer = _make_vbox.call(tr_panel, 10.0)
	
	_add_label(tr_vbox, "sec_density", "🚗 MẬT ĐỘ XE (8 hướng)", 13, Color(0.8, 0.85, 1.0))
	for d in ALL_DIRS:
		var name_str: String = DIR_NAMES.get(d, d)
		_add_label(tr_vbox, "d_" + d, "  " + name_str + ": --% | -- | ⏱ --s", 11, Color(0.7, 0.7, 0.7))
	
	# ╔══════════════════════════════════════════════════════════════╗
	# ║  BOTTOM-LEFT: KPIs + PCE                                   ║
	# ╚══════════════════════════════════════════════════════════════╝
	var bl_panel: Panel = _make_panel.call(canvas, Vector2(10, 1080 - 128 - 10), Vector2(320, 128))
	# Anchor bottom-left
	bl_panel.set_anchors_preset(Control.PRESET_BOTTOM_LEFT)
	bl_panel.set_anchor(SIDE_TOP, 1.0)
	bl_panel.set_anchor(SIDE_BOTTOM, 1.0)
	bl_panel.offset_left = 10
	bl_panel.offset_right = 330
	bl_panel.offset_top = -138
	bl_panel.offset_bottom = -10
	var bl_vbox: VBoxContainer = _make_vbox.call(bl_panel, 10.0)
	
	_add_label(bl_vbox, "sec_kpi", "📊 KPI — HCM 2010", 13, Color(0.8, 0.85, 1.0))
	_add_label(bl_vbox, "throughput", "• Thông lượng: -- PCU/ph", 11, Color.WHITE)
	_add_label(bl_vbox, "avgWait", "• Chờ TB: -- s", 11, Color.WHITE)
	_add_label(bl_vbox, "efficiency", "• Hiệu suất: -- %", 11, Color.WHITE)
	bl_vbox.add_child(HSeparator.new())
	_add_label(bl_vbox, "pce_info", "🏍️ PCE: Xe máy 0.25 PCU | Mix 65%", 10, Color(0.5, 0.6, 0.7))
	
	# ╔══════════════════════════════════════════════════════════════╗
	# ║  BOTTOM-RIGHT: AI Optimizer + Controls                     ║
	# ╚══════════════════════════════════════════════════════════════╝
	var br_panel: Panel = _make_panel.call(canvas, Vector2(1920 - 380 - 10, 1080 - 320 - 10), Vector2(380, 320))
	# Anchor bottom-right
	br_panel.set_anchors_preset(Control.PRESET_BOTTOM_RIGHT)
	br_panel.set_anchor(SIDE_LEFT, 1.0)
	br_panel.set_anchor(SIDE_RIGHT, 1.0)
	br_panel.set_anchor(SIDE_TOP, 1.0)
	br_panel.set_anchor(SIDE_BOTTOM, 1.0)
	br_panel.offset_left = -390
	br_panel.offset_right = -10
	br_panel.offset_top = -330
	br_panel.offset_bottom = -10
	var br_vbox: VBoxContainer = _make_vbox.call(br_panel, 10.0)
	
	_add_label(br_vbox, "sec_ai", "🤖 AI OPTIMIZER (4 PHA)", 13, Color(0.8, 0.85, 1.0))
	for p in ["PH1", "PH2", "PH3", "PH4"]:
		_add_label(br_vbox, "ai_" + p, "  " + PHASE_NAMES[p] + ": --s", 11, Color(0.7, 0.7, 0.7))
	_add_label(br_vbox, "improvement", "📈 Cải thiện: -- %", 11, Color.WHITE)
	_add_label(br_vbox, "auto_apply_status", "🤖 Auto-Apply: ON", 11, Color(0.3, 0.9, 0.4))
	br_vbox.add_child(HSeparator.new())
	
	# Speed buttons
	var speed_hbox := HBoxContainer.new()
	speed_hbox.add_theme_constant_override("separation", 5)
	br_vbox.add_child(speed_hbox)

	for spd in [1, 5, 10, 30, 60]:
		var btn := _make_ctrl_button(str(spd) + "x", Vector2(55, 32))
		btn.pressed.connect(_on_speed_button.bind(spd))
		speed_hbox.add_child(btn)
		_speed_buttons[spd] = btn

	# Jump buttons
	var jump_hbox := HBoxContainer.new()
	jump_hbox.add_theme_constant_override("separation", 5)
	br_vbox.add_child(jump_hbox)

	for hr in [7, 8, 12, 17, 22]:
		var btn := _make_ctrl_button(str(hr) + ":00", Vector2(55, 32))
		btn.pressed.connect(_on_jump_button.bind(hr))
		jump_hbox.add_child(btn)
		_hour_buttons[hr] = btn

	# Apply AI + Toggle Auto
	var ctrl_hbox := HBoxContainer.new()
	ctrl_hbox.add_theme_constant_override("separation", 5)
	br_vbox.add_child(ctrl_hbox)

	_btn_apply = _make_ctrl_button("ÁP DỤNG AI", Vector2(112, 36))
	_btn_apply.pressed.connect(_on_apply_pressed)
	ctrl_hbox.add_child(_btn_apply)

	_btn_toggle = _make_ctrl_button("AUTO", Vector2(90, 36))
	_btn_toggle.pressed.connect(_on_toggle_auto_pressed)
	ctrl_hbox.add_child(_btn_toggle)

	_btn_weather = _make_ctrl_button("MƯA", Vector2(90, 36))
	_btn_weather.pressed.connect(_on_weather_pressed)
	ctrl_hbox.add_child(_btn_weather)

	# Hàng nút xe cấp cứu
	var emg_hbox := HBoxContainer.new()
	emg_hbox.add_theme_constant_override("separation", 5)
	br_vbox.add_child(emg_hbox)
	_btn_emergency = _make_ctrl_button("🚑 CẤP CỨU", Vector2(140, 34))
	_btn_emergency.pressed.connect(_on_emergency_pressed)
	emg_hbox.add_child(_btn_emergency)

	_btn_police = _make_ctrl_button("🚓 ĐOÀN CÔNG AN", Vector2(190, 34))
	_btn_police.pressed.connect(_on_police_pressed)
	emg_hbox.add_child(_btn_police)

	# Tô sáng speed mặc định (1x)
	_set_active_speed(1)

	# Panel so sánh
	_build_compare_panel(canvas)

# ── Panel SO SÁNH 3 chế độ (neo giữa trên) ──
func _build_compare_panel(canvas: CanvasLayer):
	var p := Panel.new()
	p.name = "ComparePanel"
	var s := StyleBoxFlat.new()
	s.bg_color = Color(0.03, 0.04, 0.08, 0.9)
	s.border_color = Color(0.3, 0.5, 0.8, 0.6)
	s.set_border_width_all(1)
	s.set_corner_radius_all(8)
	p.add_theme_stylebox_override("panel", s)
	# Góc TRÁI TRÊN, ngay dưới panel đồng hồ — không đè lên đường
	p.offset_left = 10; p.offset_right = 470
	p.offset_top = 170; p.offset_bottom = 292
	canvas.add_child(p)

	var vb := VBoxContainer.new()
	vb.position = Vector2(12, 8)
	vb.custom_minimum_size = Vector2(436, 0)
	vb.add_theme_constant_override("separation", 3)
	p.add_child(vb)

	_add_label(vb, "cmp_title", "⚖️ SO SÁNH ĐIỀU KHIỂN — xe chờ TB (PCU) · thông lượng (PCU/ph)", 12, Color(0.75, 0.85, 1.0))

	var grid := GridContainer.new()
	grid.columns = 3
	grid.add_theme_constant_override("h_separation", 40)
	grid.add_theme_constant_override("v_separation", 2)
	vb.add_child(grid)

	# Header
	_grid_cell(grid, "hdr_mode", "Chế độ", 11, Color(0.6, 0.6, 0.7))
	_grid_cell(grid, "hdr_q", "Xe chờ", 11, Color(0.6, 0.6, 0.7))
	_grid_cell(grid, "hdr_t", "Thông lượng", 11, Color(0.6, 0.6, 0.7))
	# Rows
	var rows := [["fixed", "Đèn cố định"], ["actuated", "Actuated (cảm biến)"], ["ai", "AI (của mình)"]]
	for r in rows:
		var key: String = r[0]
		_grid_cell(grid, "cmp_" + key + "_name", r[1], 12, CMP_COLORS[key])
		_grid_cell(grid, "cmp_" + key + "_q", "--", 12, Color.WHITE)
		_grid_cell(grid, "cmp_" + key + "_t", "--", 12, Color.WHITE)

	_add_label(vb, "cmp_verdict", "AI vs đèn cố định: --", 12, Color(0.4, 0.95, 0.5))

func _grid_cell(grid: GridContainer, key: String, text: String, size: int, color: Color):
	var lbl := Label.new()
	lbl.text = text
	lbl.add_theme_font_size_override("font_size", size)
	lbl.add_theme_color_override("font_color", color)
	grid.add_child(lbl)
	_labels[key] = lbl

# ── Panel BIỂU ĐỒ 24h (neo giữa dưới) ──
func _build_chart_panel(canvas: CanvasLayer):
	var p := Panel.new()
	p.name = "ChartPanel"
	var s := StyleBoxFlat.new()
	s.bg_color = Color(0.03, 0.04, 0.08, 0.9)
	s.border_color = Color(0.3, 0.5, 0.8, 0.6)
	s.set_border_width_all(1)
	s.set_corner_radius_all(8)
	p.add_theme_stylebox_override("panel", s)
	# Góc TRÁI DƯỚI, phía trên panel KPI — không đè lên đường
	p.anchor_top = 1.0; p.anchor_bottom = 1.0
	p.offset_left = 10; p.offset_right = 470
	p.offset_top = -346; p.offset_bottom = -148
	canvas.add_child(p)

	_add_label_at(p, "chart_title", "📈 Xe chờ TB theo giờ (thấp = tốt)", 12, Color(0.75, 0.85, 1.0), Vector2(12, 8))

	# Legend (hàng 2)
	var lx := 40.0
	for item in [["fixed", "Cố định"], ["actuated", "Actuated"], ["ai", "AI"]]:
		var k: String = item[0]
		var dot := ColorRect.new()
		dot.color = CMP_COLORS[k]
		dot.size = Vector2(11, 11)
		dot.position = Vector2(lx, 31)
		p.add_child(dot)
		_add_label_at(p, "leg_" + k, item[1], 10, CMP_COLORS[k], Vector2(lx + 15, 28))
		lx += 135.0

	# Gridline ngang (mờ) tại 30/60/90 + nhãn Y
	for gv in [0, 30, 60, 90]:
		var gy := CHART_Y_TOP + CHART_H - float(gv) / CHART_MAXQ * CHART_H
		var grid := Line2D.new()
		grid.width = 1.0
		grid.default_color = Color(0.25, 0.28, 0.35) if gv > 0 else Color(0.45, 0.5, 0.6)
		grid.points = PackedVector2Array([Vector2(CHART_X0, gy), Vector2(CHART_X0 + CHART_W, gy)])
		p.add_child(grid)
		_add_label_at(p, "cy_" + str(gv), str(gv), 9, Color(0.6, 0.6, 0.7), Vector2(16, gy - 7))

	# Trục Y dọc
	var axis := Line2D.new()
	axis.width = 1.0
	axis.default_color = Color(0.45, 0.5, 0.6)
	axis.points = PackedVector2Array([Vector2(CHART_X0, CHART_Y_TOP), Vector2(CHART_X0, CHART_Y_TOP + CHART_H)])
	p.add_child(axis)

	# Nhãn trục X (0h,6,12,18,24)
	for hx in [0, 6, 12, 18, 24]:
		var px := CHART_X0 + float(hx) / 24.0 * CHART_W
		_add_label_at(p, "cx_" + str(hx), str(hx) + "h", 9, Color(0.6, 0.6, 0.7), Vector2(px - 6, CHART_Y_TOP + CHART_H + 3))

	# 3 đường dữ liệu
	for k in ["fixed", "actuated", "ai"]:
		var ln := Line2D.new()
		ln.width = 2.0
		ln.default_color = CMP_COLORS[k]
		ln.joint_mode = Line2D.LINE_JOINT_ROUND
		p.add_child(ln)
		_chart_lines[k] = ln

func _add_label_at(parent: Control, key: String, text: String, size: int, color: Color, pos: Vector2):
	var lbl := Label.new()
	lbl.text = text
	lbl.position = pos
	lbl.add_theme_font_size_override("font_size", size)
	lbl.add_theme_color_override("font_color", color)
	parent.add_child(lbl)
	_labels[key] = lbl

func _chart_point(hour: float, val: float) -> Vector2:
	var x := CHART_X0 + clampf(hour / 24.0, 0.0, 1.0) * CHART_W
	var y := CHART_Y_TOP + CHART_H - clampf(val / CHART_MAXQ, 0.0, 1.0) * CHART_H
	return Vector2(x, y)

func _redraw_chart():
	for k in ["fixed", "actuated", "ai"]:
		var data: Dictionary = _chart_data[k]
		var hours := data.keys()
		hours.sort()
		var pts := PackedVector2Array()
		for h in hours:
			pts.append(_chart_point(float(h), data[h]))
		_chart_lines[k].points = pts

# ── Tạo nút có style rõ (normal / hover / pressed / focus) ──
func _make_ctrl_button(text: String, size: Vector2) -> Button:
	var btn := Button.new()
	btn.text = text
	btn.custom_minimum_size = size
	btn.add_theme_stylebox_override("normal", _btn_sbox(Color(0.12, 0.15, 0.22), Color(0.30, 0.38, 0.55)))
	btn.add_theme_stylebox_override("hover", _btn_sbox(Color(0.20, 0.26, 0.38), Color(0.45, 0.55, 0.75)))
	btn.add_theme_stylebox_override("pressed", _btn_sbox(Color(0.16, 0.42, 0.26), Color(0.30, 0.85, 0.45)))
	btn.add_theme_stylebox_override("focus", _btn_sbox(Color(0, 0, 0, 0), Color(0.35, 0.75, 1.0)))
	return btn

func _btn_sbox(bg: Color, border: Color) -> StyleBoxFlat:
	var s := StyleBoxFlat.new()
	s.bg_color = bg
	s.border_color = border
	s.set_border_width_all(1)
	s.set_corner_radius_all(6)
	s.content_margin_left = 4
	s.content_margin_right = 4
	return s

# Đổi style "normal" của nút giữa thường / đang-chọn (xanh nổi bật)
func _set_button_active(btn: Button, active: bool) -> void:
	if not btn:
		return
	if active:
		btn.add_theme_stylebox_override("normal", _btn_sbox(Color(0.14, 0.45, 0.28), Color(0.35, 0.95, 0.5)))
		btn.add_theme_color_override("font_color", Color(0.75, 1.0, 0.8))
	else:
		btn.add_theme_stylebox_override("normal", _btn_sbox(Color(0.12, 0.15, 0.22), Color(0.30, 0.38, 0.55)))
		btn.remove_theme_color_override("font_color")

func _set_active_speed(spd: int) -> void:
	_active_speed = spd
	for k in _speed_buttons:
		_set_button_active(_speed_buttons[k], k == spd)

func _set_active_hour(hr: int) -> void:
	_active_hour = hr
	for k in _hour_buttons:
		_set_button_active(_hour_buttons[k], k == hr)

# Nhấp nháy phản hồi khi bấm nút (xác nhận đã gửi lệnh)
func _flash_button(btn: Button, txt: String) -> void:
	if not btn:
		return
	var old := btn.text
	btn.text = txt
	btn.modulate = Color(0.5, 1.0, 0.6)
	await get_tree().create_timer(1.0).timeout
	btn.text = old
	btn.modulate = Color.WHITE

func _make_dash_panel(canvas: CanvasLayer, node_name: String, anchor_right: bool) -> VBoxContainer:
	"""Tạo 1 panel neo trái hoặc phải, tự bám mép khi resize. Trả VBox chứa nội dung."""
	var panel := Panel.new()
	panel.name = node_name
	var style := StyleBoxFlat.new()
	style.bg_color = Color(0.03, 0.04, 0.08, 0.88)
	style.border_color = Color(0.2, 0.35, 0.7, 0.5)
	style.set_border_width_all(1)
	style.set_corner_radius_all(8)
	panel.add_theme_stylebox_override("panel", style)

	# Neo nửa dưới màn hình (chừa đường ngang Đông-Tây phía trên), bám mép trái/phải
	panel.anchor_top = PANEL_TOP_ANCHOR
	panel.anchor_bottom = 1.0
	panel.offset_top = 0
	panel.offset_bottom = -PANEL_MARGIN
	if anchor_right:
		panel.anchor_left = 1.0
		panel.anchor_right = 1.0
		panel.offset_left = -(PANEL_W + PANEL_MARGIN)
		panel.offset_right = -PANEL_MARGIN
	else:
		panel.anchor_left = 0.0
		panel.anchor_right = 0.0
		panel.offset_left = PANEL_MARGIN
		panel.offset_right = PANEL_MARGIN + PANEL_W
	canvas.add_child(panel)

	var scroll := ScrollContainer.new()
	scroll.set_anchors_preset(Control.PRESET_FULL_RECT)
	scroll.offset_left = 10
	scroll.offset_top = 10
	scroll.offset_right = -10
	scroll.offset_bottom = -10
	panel.add_child(scroll)

	var vbox := VBoxContainer.new()
	vbox.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	vbox.add_theme_constant_override("separation", 5)
	scroll.add_child(vbox)
	return vbox

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
	
	# AI Decision — hiện giây ĐANG CHẠY + (AI đề xuất)
	if data.has("ai_decision"):
		var ai: Dictionary = data["ai_decision"]
		traffic_data["ai_decision"] = ai
		var gt: Dictionary = ai.get("green_times", {})          # AI đề xuất
		var cur: Dictionary = data.get("current_green_times", gt)  # đang chạy thật
		for p in ["PH1", "PH2", "PH3", "PH4"]:
			if gt.has(p) and _labels.has("ai_" + p):
				var running: int = int(cur.get(p, gt[p]))
				var suggest: int = int(gt[p])
				var lbl: Label = _labels["ai_" + p]
				lbl.text = "  " + PHASE_NAMES[p] + ": " + str(running) + "s  (AI " + str(suggest) + "s)"
				# Khác nhau → tô vàng (AI muốn đổi mà chưa áp); giống → xám bình thường
				lbl.add_theme_color_override("font_color", Color(1.0, 0.8, 0.2) if running != suggest else Color(0.7, 0.7, 0.7))
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
			_labels["fidelity"].text = "🎯 Fidelity: " + str(snapped(fid, 0.1)) + " %"
			var c := Color.GREEN if fid > 90.0 else (Color.YELLOW if fid > 70.0 else Color.RED)
			_labels["fidelity"].add_theme_color_override("font_color", c)
	
	# SimClock
	if data.has("sim_clock"):
		traffic_data["sim_clock"] = data["sim_clock"]
		var sc: Dictionary = data["sim_clock"]
		if _labels.has("clock_time"):
			_labels["clock_time"].text = "🕐 " + str(sc.get("time_str", "??")) + " | Speed: " + str(sc.get("speed", 1)) + "x | Day " + str(sc.get("day", 1))
		# Đồng bộ tô sáng nút speed theo backend
		var spd_i := int(round(float(sc.get("speed", 1))))
		if spd_i != _active_speed and _speed_buttons.has(spd_i):
			_set_active_speed(spd_i)
	
	# Phase info
	if data.has("phase") and _labels.has("phase_info"):
		var phase_name: String = PHASE_NAMES.get(str(data["phase"]), str(data["phase"]))
		var time_left_str := "--"
		# Get time_left from any green direction
		for d in ALL_DIRS:
			if traffic_data[d]["light"] == "XANH":
				time_left_str = str(int(traffic_data[d]["time_left"]))
				break
		_labels["phase_info"].text = "💡 Pha: " + phase_name + " | Còn: " + time_left_str + "s"
	
	# Auto-apply
	if data.has("auto_apply"):
		traffic_data["auto_apply"] = data["auto_apply"]
		if _labels.has("auto_apply_status"):
			var on: bool = data["auto_apply"]
			_labels["auto_apply_status"].text = "🤖 Auto-Apply: " + ("ON" if on else "OFF")
			_labels["auto_apply_status"].add_theme_color_override("font_color", Color(0.3, 0.9, 0.4) if on else Color(0.8, 0.3, 0.3))
		_set_button_active(_btn_toggle, bool(data["auto_apply"]))

	# Thời tiết
	if data.has("weather"):
		_weather = str(data["weather"])
		if _btn_weather:
			_btn_weather.text = "TẠNH" if _weather == "rain" else "MƯA"
		_set_button_active(_btn_weather, _weather == "rain")

	# Ngày/đêm + thời tiết → cập nhật ánh sáng, hạt mưa
	var sc2: Dictionary = traffic_data.get("sim_clock", {})
	var hour_f: float = float(sc2.get("hour", 12)) + float(sc2.get("minute", 0)) / 60.0
	_apply_environment(hour_f, _weather)
	if _labels.has("weather_info"):
		var is_night := hour_f < 6.0 or hour_f >= 18.0
		var wx := "🌧️ Mưa" if _weather == "rain" else "☀️ Tạnh"
		var dn := "🌙 Đêm" if is_night else "🌤️ Ngày"
		_labels["weather_info"].text = wx + " | " + dn

	# Xe ưu tiên (cấp cứu)
	if data.has("emergency") and _labels.has("emergency_info"):
		var em: Dictionary = data["emergency"]
		_emergency_active = em.get("active", false)
		_emergency_dir = str(em.get("direction", "NS"))
		var kind := str(em.get("kind", "ambulance"))
		# Sườn lên: bắt đầu đợt mới → đặt số xe cần sinh (cấp cứu 1, công an cả đoàn)
		if _emergency_active and not _emergency_prev:
			_convoy_kind = kind
			_convoy_remaining = 1 if kind == "ambulance" else 5
			_convoy_timer = 0.8  # sinh xe đầu ngay
		_emergency_prev = _emergency_active
		if _emergency_active:
			var dir_nm: String = DIR_NAMES.get(_emergency_dir, _emergency_dir)
			var tag := "🚑 CẤP CỨU" if kind == "ambulance" else "🚓 ĐOÀN CÔNG AN"
			_labels["emergency_info"].text = tag + " ưu tiên: " + dir_nm + " (" + str(em.get("seconds_left", 0)) + "s)"
			_set_button_active(_btn_emergency, kind == "ambulance")
			_set_button_active(_btn_police, kind == "police")
		else:
			_labels["emergency_info"].text = ""
			_set_button_active(_btn_emergency, false)
			_set_button_active(_btn_police, false)

	# So sánh baseline
	if data.has("baselines"):
		var bl: Dictionary = data["baselines"]
		for k in ["fixed", "actuated", "ai"]:
			if bl.has(k):
				var q: float = bl[k].get("avgQueue", 0.0)
				var t: float = bl[k].get("throughput", 0.0)
				if _labels.has("cmp_" + k + "_q"): _labels["cmp_" + k + "_q"].text = str(snapped(q, 0.1))
				if _labels.has("cmp_" + k + "_t"): _labels["cmp_" + k + "_t"].text = str(snapped(t, 0.1))
		var qf: float = bl.get("fixed", {}).get("avgQueue", 0.0)
		var qai: float = bl.get("ai", {}).get("avgQueue", 0.0)
		if _labels.has("cmp_verdict") and qf > 0.0:
			var pct: float = (qf - qai) / qf * 100.0
			var better := pct >= 0.0
			_labels["cmp_verdict"].text = "AI vs đèn cố định: " + ("↓ giảm " if better else "↑ tăng ") + str(snapped(abs(pct), 0.1)) + "% xe chờ"
			_labels["cmp_verdict"].add_theme_color_override("font_color", Color(0.4, 0.95, 0.5) if better else Color(0.95, 0.55, 0.35))

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
	_set_active_speed(speed)
	var net := get_node_or_null("Network")
	if net: net.send_speed_command(float(speed))

func _on_jump_button(hour: int):
	_set_active_hour(hour)
	var net := get_node_or_null("Network")
	if net: net.send_jump_command(hour)

func _on_apply_pressed():
	var net := get_node_or_null("Network")
	var ai: Dictionary = traffic_data["ai_decision"]
	if net and ai:
		var gt: Dictionary = ai.get("green_times", {})
		net.send_control_action(gt)
		_flash_button(_btn_apply, "✓ ĐÃ ÁP DỤNG")

func _on_toggle_auto_pressed():
	var net := get_node_or_null("Network")
	if net: net.send_toggle_auto()

func _on_weather_pressed():
	var net := get_node_or_null("Network")
	if net: net.send_toggle_weather()

func _on_emergency_pressed():
	var net := get_node_or_null("Network")
	if net:
		net.send_emergency("SN", "ambulance")
		_flash_button(_btn_emergency, "🚑 ƯU TIÊN...")

func _on_police_pressed():
	var net := get_node_or_null("Network")
	if net:
		net.send_emergency("WE", "police")   # đoàn công an đi ngang trái → phải
		_flash_button(_btn_police, "🚓 ĐANG QUA...")
