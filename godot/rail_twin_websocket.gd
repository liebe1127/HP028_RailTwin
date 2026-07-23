extends Node3D
## 하부 레일 변형 예측 디지털 트윈 — FastAPI WebSocket 연동 (Godot 4.7)
##
## 서버가 보내는 rail_risk[] 로 레일 구간별 위험색을 칠한다.
## (전체 레일 단일 색이 아님)
##
## 권장 씬 구조:
##   RailTwinRoot (Node3D)  ← 이 스크립트
##    ├─ GantryModel (FBX)
##    │    ├─ .../Trolley   ← crane_path
##    │    └─ .../Rail      ← rail_path (원본, 선택적으로 숨김)
##    └─ RailRiskSegments   ← 자동 생성되거나 Inspector로 지정
##
## Godot 4.7 WebSocket: poll() + was_string_packet() + STATE_* 처리
## Docs: https://docs.godotengine.org/en/4.7/tutorials/networking/websocket.html

@export var websocket_url: String = "ws://127.0.0.1:8000/ws"
@export var reconnect_sec: float = 3.0

@export var crane_path: NodePath
@export var rail_path: NodePath
## 비어 있으면 자식 "RailRiskSegments"를 쓰거나 자동 생성
@export var rail_segments_root_path: NodePath

@export var travel_axis: String = "x"
@export var rail_length_m: float = 1.0
@export var segment_count: int = 20
@export var auto_build_segments: bool = true
@export var hide_source_rail: bool = true
@export var segment_width: float = 0.08
@export var segment_height: float = 0.04
@export var segment_gap: float = 0.002

@export var crane_name_hints: PackedStringArray = [
	"crane", "trolley", "gantry", "bridge", "hoist", "carriage"
]
@export var rail_name_hints: PackedStringArray = ["rail", "track", "레일"]

var socket: WebSocketPeer = WebSocketPeer.new()
var _reconnect_left: float = -1.0
var _logged_close: bool = false
var _want_socket: bool = true

var target_distance_m: float = 0.0
var current_distance_m: float = 0.0
var target_crest: float = 0.0
var target_rail_deform: float = 0.0

var crane_node: Node3D
var rail_mesh: MeshInstance3D
var segments_root: Node3D
var segment_meshes: Array[MeshInstance3D] = []
var rail_risk: PackedFloat32Array = PackedFloat32Array()

const LERP_SPEED: float = 10.0


func _ready() -> void:
	_resolve_nodes()
	_setup_segments()
	_print_scene_tree_hint()
	_connect_socket()


func _process(delta: float) -> void:
	_poll_socket(delta)

	current_distance_m = lerpf(current_distance_m, target_distance_m, delta * LERP_SPEED)

	if crane_node != null:
		if travel_axis.to_lower() == "z":
			crane_node.position.z = current_distance_m
		else:
			crane_node.position.x = current_distance_m


func _connect_socket() -> void:
	_logged_close = false
	_reconnect_left = -1.0
	socket = WebSocketPeer.new()
	var err: Error = socket.connect_to_url(websocket_url)
	if err != OK:
		push_error("[RailTwin] WebSocket 연결 실패: %s (Error %s)" % [websocket_url, err])
		_reconnect_left = reconnect_sec
		return
	print("[RailTwin] Connecting to %s ..." % websocket_url)


func _poll_socket(delta: float) -> void:
	if not _want_socket:
		return

	# 재연결 대기 중이면 타이머만 감소 (닫힌 peer는 poll 불필요)
	if _reconnect_left >= 0.0:
		_reconnect_left -= delta
		if _reconnect_left <= 0.0:
			_connect_socket()
		return

	socket.poll()
	var state: int = socket.get_ready_state()

	if state == WebSocketPeer.STATE_OPEN:
		while socket.get_available_packet_count() > 0:
			var packet: PackedByteArray = socket.get_packet()
			# Godot 4.7: 텍스트 프레임만 JSON으로 처리
			if not socket.was_string_packet():
				continue
			var text: String = packet.get_string_from_utf8()
			var parsed: Variant = JSON.parse_string(text)
			if parsed is Dictionary:
				_apply_payload(parsed as Dictionary)

	elif state == WebSocketPeer.STATE_CLOSING:
		# clean close를 위해 계속 poll
		pass

	elif state == WebSocketPeer.STATE_CLOSED:
		if not _logged_close:
			_logged_close = true
			var code: int = socket.get_close_code()
			print(
				"[RailTwin] WebSocket closed code=%d clean=%s — %.1fs 후 재연결"
				% [code, str(code != -1), reconnect_sec]
			)
		_reconnect_left = reconnect_sec


func _resolve_nodes() -> void:
	if crane_path != NodePath(""):
		crane_node = get_node_or_null(crane_path) as Node3D
	if rail_path != NodePath(""):
		rail_mesh = get_node_or_null(rail_path) as MeshInstance3D

	if crane_node == null:
		crane_node = _find_node3d_by_hints(crane_name_hints)
	if rail_mesh == null:
		rail_mesh = _find_mesh_by_hints(rail_name_hints)

	if rail_segments_root_path != NodePath(""):
		segments_root = get_node_or_null(rail_segments_root_path) as Node3D

	if segments_root == null:
		segments_root = get_node_or_null("RailRiskSegments") as Node3D

	if crane_node != null:
		print("[RailTwin] crane: ", crane_node.get_path())
	else:
		push_warning("[RailTwin] crane 노드 없음 → Crane Path 지정")

	if rail_mesh != null:
		print("[RailTwin] rail mesh: ", rail_mesh.get_path())
		if hide_source_rail:
			rail_mesh.visible = false
	else:
		push_warning("[RailTwin] rail mesh 없음 — 세그먼트를 원점 기준으로 생성")


func _setup_segments() -> void:
	segment_meshes.clear()

	if segments_root == null:
		segments_root = Node3D.new()
		segments_root.name = "RailRiskSegments"
		add_child(segments_root)

	# 기존 자식 MeshInstance3D가 있으면 그대로 사용
	for child in segments_root.get_children():
		if child is MeshInstance3D:
			segment_meshes.append(child as MeshInstance3D)

	if segment_meshes.is_empty() and auto_build_segments:
		_build_segment_meshes()

	rail_risk = PackedFloat32Array()
	rail_risk.resize(segment_meshes.size())
	rail_risk.fill(0.0)
	_apply_segment_colors()

	print("[RailTwin] segments=%d length=%.2fm" % [segment_meshes.size(), rail_length_m])


func _build_segment_meshes() -> void:
	for child in segments_root.get_children():
		child.queue_free()
	segment_meshes.clear()

	var n: int = maxi(segment_count, 1)
	var seg_len: float = rail_length_m / float(n)
	var box_len: float = maxf(seg_len - segment_gap, 0.001)

	var origin := Vector3.ZERO
	if rail_mesh != null:
		origin = rail_mesh.position

	for i in range(n):
		var mi := MeshInstance3D.new()
		mi.name = "RailSeg_%02d" % i
		var box := BoxMesh.new()
		if travel_axis.to_lower() == "z":
			box.size = Vector3(segment_width, segment_height, box_len)
		else:
			box.size = Vector3(box_len, segment_height, segment_width)
		mi.mesh = box

		var mat := StandardMaterial3D.new()
		mat.shading_mode = BaseMaterial3D.SHADING_MODE_PER_PIXEL
		mat.albedo_color = _risk_to_color(0.0)
		mi.set_surface_override_material(0, mat)

		var center: float = (float(i) + 0.5) * seg_len
		if travel_axis.to_lower() == "z":
			mi.position = origin + Vector3(0.0, segment_height * 0.5, center)
		else:
			mi.position = origin + Vector3(center, segment_height * 0.5, 0.0)

		segments_root.add_child(mi)
		segment_meshes.append(mi)


func _apply_payload(data: Dictionary) -> void:
	if data.has("distance_x") and data["distance_x"] != null:
		target_distance_m = float(data["distance_x"]) / 100.0
	elif data.has("DIST") and data["DIST"] != null:
		target_distance_m = float(data["DIST"]) / 100.0

	if data.has("CREST") and data["CREST"] != null:
		target_crest = float(data["CREST"])

	if data.has("PRED_RAIL_DEFORM") and data["PRED_RAIL_DEFORM"] != null:
		target_rail_deform = float(data["PRED_RAIL_DEFORM"])

	if data.has("rail_length_cm") and data["rail_length_cm"] != null:
		var new_len: float = float(data["rail_length_cm"]) / 100.0
		if not is_equal_approx(new_len, rail_length_m) and new_len > 0.0:
			rail_length_m = new_len

	if data.has("segment_count") and data["segment_count"] != null:
		var sc: int = int(data["segment_count"])
		if sc > 0 and sc != segment_count and auto_build_segments:
			segment_count = sc
			_setup_segments()

	if data.has("rail_risk") and data["rail_risk"] is Array:
		_update_rail_risk_from_array(data["rail_risk"] as Array)


func _update_rail_risk_from_array(arr: Array) -> void:
	var n: int = mini(arr.size(), segment_meshes.size())
	if n <= 0:
		return
	if rail_risk.size() != segment_meshes.size():
		rail_risk.resize(segment_meshes.size())
		rail_risk.fill(0.0)

	for i in range(n):
		rail_risk[i] = clampf(float(arr[i]), 0.0, 1.0)
	_apply_segment_colors()


func _apply_segment_colors() -> void:
	var n: int = mini(rail_risk.size(), segment_meshes.size())
	for i in range(n):
		var mi: MeshInstance3D = segment_meshes[i]
		var mat: Material = mi.get_active_material(0)
		if mat == null:
			mat = StandardMaterial3D.new()
			mi.set_surface_override_material(0, mat)
		var std := mat as StandardMaterial3D
		if std == null:
			std = StandardMaterial3D.new()
			mi.set_surface_override_material(0, std)
		std.albedo_color = _risk_to_color(rail_risk[i])


## 범례: 파랑(정상) → 초록(낮음) → 노랑(중간) → 빨강(높음)
func _risk_to_color(risk: float) -> Color:
	var r: float = clampf(risk, 0.0, 1.0)
	if r < 0.15:
		return Color(0.25, 0.50, 0.95)  # 정상 파랑
	if r < 0.40:
		return Color(0.20, 0.85, 0.35)  # 낮음 초록
	if r < 0.70:
		return Color(0.95, 0.85, 0.15)  # 중간 노랑
	return Color(0.95, 0.22, 0.18)  # 높음 빨강


func _find_node3d_by_hints(hints: PackedStringArray) -> Node3D:
	for child in _all_descendants(self):
		if not (child is Node3D):
			continue
		if child is MeshInstance3D:
			continue
		var n: String = String(child.name).to_lower()
		for h in hints:
			if String(h).to_lower() in n:
				return child as Node3D
	return null


func _find_mesh_by_hints(hints: PackedStringArray) -> MeshInstance3D:
	for child in _all_descendants(self):
		if not (child is MeshInstance3D):
			continue
		var n: String = String(child.name).to_lower()
		for h in hints:
			if String(h).to_lower() in n:
				return child as MeshInstance3D
	var meshes: Array[MeshInstance3D] = []
	for child in _all_descendants(self):
		if child is MeshInstance3D:
			meshes.append(child as MeshInstance3D)
	if meshes.size() == 1:
		return meshes[0]
	return null


func _all_descendants(root: Node) -> Array[Node]:
	var result: Array[Node] = []
	for c in root.get_children():
		result.append(c)
		result.append_array(_all_descendants(c))
	return result


func _print_scene_tree_hint() -> void:
	print("[RailTwin] === scene tree ===")
	_print_tree_recursive(self, 0)
	print("[RailTwin] === set Crane Path / Rail Path in Inspector ===")


func _print_tree_recursive(node: Node, depth: int) -> void:
	var indent: String = ""
	for _i in depth:
		indent += "  "
	print("%s- %s (%s)" % [indent, node.name, node.get_class()])
	for c in node.get_children():
		_print_tree_recursive(c, depth + 1)
