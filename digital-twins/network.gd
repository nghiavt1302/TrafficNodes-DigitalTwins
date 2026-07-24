extends Node

# ── Cấu hình WebSocket ──
var socket = WebSocketPeer.new()
var websocket_url = "ws://127.0.0.1:8000/traffic-ws"
var _connected = false
var _reconnect_timer = 0.0
const RECONNECT_INTERVAL = 3.0

@onready var main_node = get_node("/root/Main")

func _ready():
	_connect_to_server()

func _connect_to_server():
	var err = socket.connect_to_url(websocket_url)
	if err != OK:
		print("[NETWORK] ❌ Lỗi kết nối: ", err)
	else:
		print("[NETWORK] 🔗 Đang kết nối: ", websocket_url)

func _process(delta):
	socket.poll()
	var state = socket.get_ready_state()
	
	match state:
		WebSocketPeer.STATE_OPEN:
			if not _connected:
				_connected = true
				_reconnect_timer = 0.0
				print("[NETWORK] ✅ Đã kết nối Backend!")
			
			while socket.get_available_packet_count() > 0:
				var raw = socket.get_packet().get_string_from_utf8()
				var data = JSON.parse_string(raw)
				if data and data is Dictionary:
					_on_data_received(data)
		
		WebSocketPeer.STATE_CLOSING:
			pass
		
		WebSocketPeer.STATE_CLOSED:
			if _connected:
				_connected = false
				var code = socket.get_close_code()
				var reason = socket.get_close_reason()
				print("[NETWORK] ❌ Mất kết nối! Code: ", code, " Reason: ", reason)
			
			_reconnect_timer += delta
			if _reconnect_timer >= RECONNECT_INTERVAL:
				_reconnect_timer = 0.0
				print("[NETWORK] 🔄 Thử kết nối lại...")
				socket = WebSocketPeer.new()
				_connect_to_server()
		
		WebSocketPeer.STATE_CONNECTING:
			pass

func _on_data_received(data: Dictionary):
	if main_node and main_node.has_method("update_twin_state"):
		main_node.update_twin_state(data)

# ╔══════════════════════════════════════════════════════════════╗
# ║  GỬI LỆNH ĐIỀU KHIỂN                                       ║
# ╚══════════════════════════════════════════════════════════════╝

func _send(payload: Dictionary):
	if socket.get_ready_state() == WebSocketPeer.STATE_OPEN:
		var json_str = JSON.stringify(payload)
		socket.send_text(json_str)
	else:
		print("[NETWORK] ⚠️ Chưa kết nối!")

func send_control_action(green_times: Dictionary):
	"""FEEDBACK LOOP Level 4: Gửi timing xuống Backend."""
	_send({"action": "APPLY_LIGHTS", "green_times": green_times})
	print("[NETWORK] 📤 Gửi APPLY_LIGHTS: ", green_times)

func send_speed_command(speed: float):
	"""Thay đổi tốc độ simulation clock."""
	_send({"action": "SET_SPEED", "speed": speed})
	print("[NETWORK] ⏩ SET_SPEED: ", speed, "x")

func send_jump_command(hour: int):
	"""Nhảy tới giờ bất kỳ."""
	_send({"action": "JUMP_TO_HOUR", "hour": hour})
	print("[NETWORK] ⏭️ JUMP_TO_HOUR: ", hour, ":00")

func send_toggle_auto():
	"""Toggle auto-apply AI."""
	_send({"action": "TOGGLE_AUTO_APPLY"})
	print("[NETWORK] 🤖 TOGGLE_AUTO_APPLY")

func send_toggle_weather():
	"""Toggle thời tiết (tạnh ↔ mưa)."""
	_send({"action": "TOGGLE_WEATHER"})
	print("[NETWORK] 🌦️ TOGGLE_WEATHER")

func send_emergency(direction: String = "NS", kind: String = "ambulance"):
	"""Kích hoạt ưu tiên xe ưu tiên (preemption đèn xanh). kind: ambulance | police."""
	_send({"action": "EMERGENCY", "direction": direction, "kind": kind})
	print("[NETWORK] 🚨 EMERGENCY: ", direction, " ", kind)

func send_pause():
	_send({"action": "PAUSE"})

func send_resume():
	_send({"action": "RESUME"})
