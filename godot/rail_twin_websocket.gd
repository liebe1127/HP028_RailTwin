extends Node3D
## 하부 레일 변형 예측 디지털 트윈 — FastAPI WebSocket 연동 (Godot 4.7)
##
## 서버 페이로드:
##   { "left": { distance_x, CREST, PRED_RAIL_DEFORM, rail_risk[], ... },
##     "right": { ... },
##     "source": "demo" }
## 구 평면 페이로드(left/right 없음)도 호환 — 양쪽 레일에 같은 값을 적용.
##
## 권장 씬 구조:
##   RailTwinRoot (Node3D)  ← 이 스크립트
##    ├─ GantryModel (FBX)
##    │    ├─ .../Trolley          ← crane_path
##    │    ├─ .../RailLeft         ← left_rail_path (선택)
##    │    └─ .../RailRight        ← right_rail_path (선택)
##    ├─ RailRiskSegmentsLeft      ← 자동 생성 가능
##    └─ RailRiskSegmentsRight
##
## Godot 4.7 WebSocket: poll() + was_string_packet() + STATE_* 처리

## 클라우드: wss://223.130.128.198:8000/ws  |  로컬: ws://127.0.0.1:8000/ws
@export var websocket_url: String = "wss://223.130.128.198:8000/ws"
## 자체 서명(NCP) 인증서면 true — TLS 검증 생략(시연용). Let's Encrypt면 false.
@export var tls_insecure: bool = true
@export var reconnect_sec: float = 3.0

@export var crane_path: NodePath
@export var rail_path: NodePath  ## 구버전 호환 — 지정 시 왼쪽 레일로 사용
@export var left_rail_path: NodePath
@export var right_rail_path: NodePath
@export var rail_segments_root_path: NodePath  ## 구버전 호환 — 왼쪽 세그먼트 루트
@export var left_segments_root_path: NodePath
@export var right_segments_root_path: NodePath

@export var travel_axis: String = "x"
@export var rail_length_m: float = 1.0
@export var segment_count: int = 20
@export var auto_build_segments: bool = true
@export var hide_source_rail: bool = true
@export var segment_width: float = 0.08
@export var segment_height: float = 0.04
@export var segment_gap: float = 0.002
## 좌/우 레일 사이 간격(m). travel이 x면 z로, z면 x로 벌림.
@export var rail_pair_gap: float = 0.35

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
var left_rail_mesh: MeshInstance3D
var right_rail_mesh: MeshInstance3D
var left_root: Node3D
var right_root: Node3D
var left_meshes: Array[MeshInstance3D] = []
var right_meshes: Array[MeshInstance3D] = []
var left_risk: PackedFloat32Array = PackedFloat32Array()
var right_risk: PackedFloat32Array = PackedFloat32Array()

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
	var err: Error
	if websocket_url.begins_with("wss://") and tls_insecure:
		# 자체 서명 인증서: 기본 검증은 handshake -9984 등으로 실패함
		err = socket.connect_to_url(websocket_url, TLSOptions.client_unsafe())
	else:
		err = socket.connect_to_url(websocket_url)
	if err != OK:
		push_error("[RailTwin] WebSocket 연결 실패: %s (Error %s)" % [websocket_url, err])
		_reconnect_left = reconnect_sec
		return
	print("[RailTwin] Connecting to %s (tls_insecure=%s) ..." % [websocket_url, tls_insecure])


func _poll_socket(delta: float) -> void:
	if not _want_socket:
		return

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
			if not socket.was_string_packet():
				continue
			var text: String = packet.get_string_from_utf8()
			var parsed: Variant = JSON.parse_string(text)
			if parsed is Dictionary:
				_apply_payload(parsed as Dictionary)

	elif state == WebSocketPeer.STATE_CLOSING:
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
	if crane_node == null:
		crane_node = _find_node3d_by_hints(crane_name_hints)

	if left_rail_path != NodePath(""):
		left_rail_mesh = get_node_or_null(left_rail_path) as MeshInstance3D
	if left_rail_mesh == null and rail_path != NodePath(""):
		left_rail_mesh = get_node_or_null(rail_path) as MeshInstance3D
	if right_rail_path != NodePath(""):
		right_rail_mesh = get_node_or_null(right_rail_path) as MeshInstance3D
	if left_rail_mesh == null:
		left_rail_mesh = _find_mesh_by_hints(rail_name_hints)

	if left_segments_root_path != NodePath(""):
		left_root = get_node_or_null(left_segments_root_path) as Node3D
	if left_root == null and rail_segments_root_path != NodePath(""):
		left_root = get_node_or_null(rail_segments_root_path) as Node3D
	if left_root == null:
		left_root = get_node_or_null("RailRiskSegmentsLeft") as Node3D
	if left_root == null:
		left_root = get_node_or_null("RailRiskSegments") as Node3D

	if right_segments_root_path != NodePath(""):
		right_root = get_node_or_null(right_segments_root_path) as Node3D
	if right_root == null:
		right_root = get_node_or_null("RailRiskSegmentsRight") as Node3D

	if crane_node != null:
		print("[RailTwin] crane: ", crane_node.get_path())
	else:
		push_warning("[RailTwin] crane 노드 없음 → Crane Path 지정")

	for mesh in [left_rail_mesh, right_rail_mesh]:
		if mesh != null and hide_source_rail:
			mesh.visible = false


func _setup_segments() -> void:
	if left_root == null:
		left_root = Node3D.new()
		left_root.name = "RailRiskSegmentsLeft"
		add_child(left_root)
	if right_root == null:
		right_root = Node3D.new()
		right_root.name = "RailRiskSegmentsRight"
		add_child(right_root)

	left_meshes = _collect_or_build_side(left_root, left_rail_mesh, "L", -rail_pair_gap * 0.5)
	right_meshes = _collect_or_build_side(right_root, right_rail_mesh, "R", rail_pair_gap * 0.5)

	left_risk = PackedFloat32Array()
	left_risk.resize(left_meshes.size())
	left_risk.fill(0.0)
	right_risk = PackedFloat32Array()
	right_risk.resize(right_meshes.size())
	right_risk.fill(0.0)
	_apply_segment_colors(left_meshes, left_risk)
	_apply_segment_colors(right_meshes, right_risk)

	print(
		"[RailTwin] left_seg=%d right_seg=%d length=%.2fm"
		% [left_meshes.size(), right_meshes.size(), rail_length_m]
	)


func _collect_or_build_side(
	root: Node3D,
	source_mesh: MeshInstance3D,
	prefix: String,
	lateral: float
) -> Array[MeshInstance3D]:
	var meshes: Array[MeshInstance3D] = []
	for child in root.get_children():
		if child is MeshInstance3D:
			meshes.append(child as MeshInstance3D)
	if meshes.is_empty() and auto_build_segments:
		meshes = _build_segment_meshes(root, source_mesh, prefix, lateral)
	return meshes


func _build_segment_meshes(
	root: Node3D,
	source_mesh: MeshInstance3D,
	prefix: String,
	lateral: float
) -> Array[MeshInstance3D]:
	for child in root.get_children():
		child.queue_free()

	var meshes: Array[MeshInstance3D] = []
	var n: int = maxi(segment_count, 1)
	var seg_len: float = rail_length_m / float(n)
	var box_len: float = maxf(seg_len - segment_gap, 0.001)

	var origin := Vector3.ZERO
	if source_mesh != null:
		origin = source_mesh.position
	else:
		if travel_axis.to_lower() == "z":
			origin = Vector3(lateral, 0.0, 0.0)
		else:
			origin = Vector3(0.0, 0.0, lateral)

	for i in range(n):
		var mi := MeshInstance3D.new()
		mi.name = "RailSeg_%s_%02d" % [prefix, i]
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

		root.add_child(mi)
		meshes.append(mi)
	return meshes


func _side_dict(data: Dictionary, key: String) -> Dictionary:
	if data.has(key) and data[key] is Dictionary:
		return data[key] as Dictionary
	return {}


func _apply_payload(data: Dictionary) -> void:
	var left: Dictionary = _side_dict(data, "left")
	var right: Dictionary = _side_dict(data, "right")
	# 구 평면 페이로드: left/right 키가 없으면 전체를 양쪽에 적용
	if left.is_empty() and right.is_empty():
		left = data
		right = data

	var loc: Dictionary = left if not left.is_empty() else right
	_apply_shared_fields(loc)
	if not left.is_empty() and left.has("rail_risk") and left["rail_risk"] is Array:
		left_risk = _update_rail_risk_from_array(left["rail_risk"] as Array, left_meshes)
		_apply_segment_colors(left_meshes, left_risk)
	if not right.is_empty() and right.has("rail_risk") and right["rail_risk"] is Array:
		right_risk = _update_rail_risk_from_array(right["rail_risk"] as Array, right_meshes)
		_apply_segment_colors(right_meshes, right_risk)


func _apply_shared_fields(data: Dictionary) -> void:
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


func _update_rail_risk_from_array(
	arr: Array, meshes: Array[MeshInstance3D]
) -> PackedFloat32Array:
	var risk := PackedFloat32Array()
	risk.resize(meshes.size())
	risk.fill(0.0)
	var n: int = mini(arr.size(), meshes.size())
	for i in range(n):
		risk[i] = clampf(float(arr[i]), 0.0, 1.0)
	return risk


func _apply_segment_colors(meshes: Array[MeshInstance3D], risk: PackedFloat32Array) -> void:
	var n: int = mini(risk.size(), meshes.size())
	for i in range(n):
		var mi: MeshInstance3D = meshes[i]
		var mat: Material = mi.get_active_material(0)
		if mat == null:
			mat = StandardMaterial3D.new()
			mi.set_surface_override_material(0, mat)
		var std := mat as StandardMaterial3D
		if std == null:
			std = StandardMaterial3D.new()
			mi.set_surface_override_material(0, std)
		std.albedo_color = _risk_to_color(risk[i])


## 범례: 파랑(정상) → 초록(낮음) → 노랑(중간) → 빨강(높음)
func _risk_to_color(risk: float) -> Color:
	var r: float = clampf(risk, 0.0, 1.0)
	if r < 0.15:
		return Color(0.25, 0.50, 0.95)
	if r < 0.40:
		return Color(0.20, 0.85, 0.35)
	if r < 0.70:
		return Color(0.95, 0.85, 0.15)
	return Color(0.95, 0.22, 0.18)


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
	print("[RailTwin] === set Crane Path / Left·Right Rail Path in Inspector ===")


func _print_tree_recursive(node: Node, depth: int) -> void:
	var indent: String = ""
	for _i in depth:
		indent += "  "
	print("%s- %s (%s)" % [indent, node.name, node.get_class()])
	for c in node.get_children():
		_print_tree_recursive(c, depth + 1)
