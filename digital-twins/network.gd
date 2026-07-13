extends Node

# ── Cấu hình WebSocket ──
var socket = WebSocketPeer.new()
var websocket_url = "ws://127.0.0.1:8000/traffic-ws"
var _connected = false
var _reconnect_timer = 0.0
const RECONNECT_INTERVAL = 3.0  # Thử kết nối lại sau 3 giây

# Tìm trực tiếp biến lưu từ Node gốc Main
@onready var main_node = get_node("/root/Main") 

func _ready():
	# ── Kết nối WebSocket ngay khi scene sẵn sàng ──
	_connect_to_server()

func _connect_to_server():
	"""Khởi tạo kết nối WebSocket tới Backend."""
	var err = socket.connect_to_url(websocket_url)
	if err != OK:
		print("[NETWORK] ❌ Lỗi kết nối WebSocket: ", err)
	else:
		print("[NETWORK] 🔗 Đang kết nối tới: ", websocket_url)

func _process(delta):
	socket.poll()
	
	var state = socket.get_ready_state()
	
	match state:
		WebSocketPeer.STATE_OPEN:
			if not _connected:
				_connected = true
				_reconnect_timer = 0.0
				print("[NETWORK] ✅ Đã kết nối thành công tới Backend!")
			
			# Nhận tất cả gói tin từ server
			while socket.get_available_packet_count() > 0:
				var raw = socket.get_packet().get_string_from_utf8()
				var data = JSON.parse_string(raw)
				if data and data is Dictionary:
					_on_data_received(data)
		
		WebSocketPeer.STATE_CLOSING:
			pass  # Đang đóng, chờ
		
		WebSocketPeer.STATE_CLOSED:
			if _connected:
				_connected = false
				var code = socket.get_close_code()
				var reason = socket.get_close_reason()
				print("[NETWORK] ❌ Mất kết nối! Code: ", code, " Reason: ", reason)
			
			# Tự động kết nối lại
			_reconnect_timer += delta
			if _reconnect_timer >= RECONNECT_INTERVAL:
				_reconnect_timer = 0.0
				print("[NETWORK] 🔄 Đang thử kết nối lại...")
				socket = WebSocketPeer.new()
				_connect_to_server()
		
		WebSocketPeer.STATE_CONNECTING:
			pass  # Đang chờ kết nối

func _on_data_received(data: Dictionary):
	"""
	Xử lý dữ liệu nhận từ Backend WebSocket.
	Gọi hàm update_twin_state() trên Main để cập nhật toàn bộ UI.
	"""
	# Cập nhật toàn bộ trạng thái Digital Twin qua hàm chính của Main
	if main_node and main_node.has_method("update_twin_state"):
		main_node.update_twin_state(data)

func send_control_action(green_times: Dictionary):
	"""
	FEEDBACK LOOP Level 4:
	Gửi lệnh thay đổi chu kỳ đèn ngược lên Backend (4 hướng).
	
	Payload: {"action": "APPLY_LIGHTS", "green_times": {"NS": 50, "EW": 40, "SN": 35, "WE": 30}}
	"""
	if socket.get_ready_state() == WebSocketPeer.STATE_OPEN:
		var payload = {
			"action": "APPLY_LIGHTS",
			"green_times": green_times
		}
		var json_str = JSON.stringify(payload)
		socket.send_text(json_str)
		print("[NETWORK] 📤 Gửi FEEDBACK 4 hướng: ", green_times)
	else:
		print("[NETWORK] ⚠️ Chưa kết nối! Không thể gửi lệnh.")

