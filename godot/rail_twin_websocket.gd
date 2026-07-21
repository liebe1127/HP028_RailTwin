extends Node3D
## 하부 레일 변형 예측 디지털 트윈 — FastAPI WebSocket 연동
##
## FBX가 하나여도 OK. 파일을 쪼개지 말고, 임포트된 씬 트리 안에서
## "움직이는 크레인 부분" / "색 바꿀 레일 메시" 경로만 Inspector에서 지정하면 됨.
##
## 권장 씬 구조 예시:
##   RailTwinRoot (Node3D)  ← 이 스크립트
##    └─ GantryModel (FBX 임포트 루트, 이름은 달라도 됨)
##         ├─ .../Trolley 또는 Bridge   ← crane_path 로 지정 (이동)
##         └─ .../Rail 또는 Track       ← rail_path 로 지정 (색상)
##
## 수신 키: distance_x, CREST, PRED_RAIL_DEFORM

@export var websocket_url := "ws://127.0.0.1:8000/ws"

## Inspector에서 FBX 안 노드를 드래그해 연결하세요.
## (비어 있으면 아래에서 이름 후보로 자동 탐색 시도)
@export var crane_path: NodePath
@export var rail_path: NodePath

## 크레인 주행 축: "x" 또는 "z"
@export var travel_axis := "x"

## 자동 탐색용 이름 힌트 (FBX 노드 이름에 포함되면 매칭)
@export var crane_name_hints: PackedStringArray = ["crane", "trolley", "gantry", "bridge", "hoist", "carriage"]
@export var rail_name_hints: PackedStringArray = ["rail", "track", "레일"]

var socket := WebSocketPeer.new()

var target_distance_x: float = 0.0
var target_crest: float = 0.0
var target_rail_deform: float = 0.0

var current_distance_x: float = 0.0
var current_crest: float = 0.0
var current_rail_deform: float = 0.0

var crane_node: Node3D
var rail_mesh: MeshInstance3D

const NORMAL_CREST_THRESHOLD := 1.5
const DANGER_CREST_THRESHOLD := 5.0
const LERP_SPEED := 10.0


func _ready() -> void:
	_resolve_nodes()
	_print_scene_tree_hint()

	var err := socket.connect_to_url(websocket_url)
	if err != OK:
		push_error("WebSocket 연결 실패: %s (코드 %s)" % [websocket_url, err])
		return
	print("[RailTwin] WebSocket 연결 시도: ", websocket_url)

	if rail_mesh and rail_mesh.get_active_material(0):
		rail_mesh.set_surface_override_material(
			0, rail_mesh.get_active_material(0).duplicate()
		)


func _process(delta: float) -> void:
	socket.poll()

	if socket.get_ready_state() == WebSocketPeer.STATE_OPEN:
		while socket.get_available_packet_count():
			var packet := socket.get_packet()
			var data = JSON.parse_string(packet.get_string_from_utf8())
			if typeof(data) == TYPE_DICTIONARY:
				_apply_payload(data)

	current_distance_x = lerp(current_distance_x, target_distance_x, delta * LERP_SPEED)
	current_crest = lerp(current_crest, target_crest, delta * LERP_SPEED)
	current_rail_deform = lerp(current_rail_deform, target_rail_deform, delta * LERP_SPEED)

	if crane_node:
		if travel_axis.to_lower() == "z":
			crane_node.position.z = current_distance_x
		else:
			crane_node.position.x = current_distance_x

	update_rail_color(current_crest)


func _resolve_nodes() -> void:
	# 1) Inspector에서 지정한 경로 우선
	if crane_path != NodePath(""):
		crane_node = get_node_or_null(crane_path) as Node3D
	if rail_path != NodePath(""):
		rail_mesh = get_node_or_null(rail_path) as MeshInstance3D

	# 2) 비어 있으면 FBX 트리에서 이름 힌트로 자동 탐색
	if crane_node == null:
		crane_node = _find_node3d_by_hints(crane_name_hints)
	if rail_mesh == null:
		rail_mesh = _find_mesh_by_hints(rail_name_hints)

	if crane_node:
		print("[RailTwin] 크레인 노드: ", crane_node.get_path())
	else:
		push_warning("[RailTwin] 크레인 노드를 못 찾음 → Inspector의 Crane Path를 지정하세요.")

	if rail_mesh:
		print("[RailTwin] 레일 메시: ", rail_mesh.get_path())
	else:
		push_warning("[RailTwin] 레일 MeshInstance3D를 못 찾음 → Inspector의 Rail Path를 지정하세요.")


func _find_node3d_by_hints(hints: PackedStringArray) -> Node3D:
	for child in _all_descendants(self):
		if not (child is Node3D):
			continue
		var n := String(child.name).to_lower()
		for h in hints:
			if String(h).to_lower() in n:
				return child as Node3D
	return null


func _find_mesh_by_hints(hints: PackedStringArray) -> MeshInstance3D:
	for child in _all_descendants(self):
		if not (child is MeshInstance3D):
			continue
		var n := String(child.name).to_lower()
		for h in hints:
			if String(h).to_lower() in n:
				return child as MeshInstance3D
	# 힌트 실패 시: MeshInstance3D가 하나뿐이면 그걸 레일로 사용
	var meshes: Array[MeshInstance3D] = []
	for child in _all_descendants(self):
		if child is MeshInstance3D:
			meshes.append(child)
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
	print("[RailTwin] === 씬 트리 (노드 이름 확인용) ===")
	_print_tree_recursive(self, 0)
	print("[RailTwin] === Inspector에서 Crane Path / Rail Path에 위 경로를 넣으세요 ===")


func _print_tree_recursive(node: Node, depth: int) -> void:
	var indent := ""
	for i in depth:
		indent += "  "
	var kind := node.get_class()
	print("%s- %s (%s)" % [indent, node.name, kind])
	for c in node.get_children():
		_print_tree_recursive(c, depth + 1)


func _apply_payload(data: Dictionary) -> void:
	if data.has("distance_x"):
		target_distance_x = float(data["distance_x"]) / 100.0
	elif data.has("DIST"):
		target_distance_x = float(data["DIST"]) / 100.0

	if data.has("CREST") and data["CREST"] != null:
		target_crest = float(data["CREST"])

	if data.has("PRED_RAIL_DEFORM") and data["PRED_RAIL_DEFORM"] != null:
		target_rail_deform = float(data["PRED_RAIL_DEFORM"])


func update_rail_color(crest_value: float) -> void:
	if rail_mesh == null:
		return

	var risk_ratio := clampf(
		(crest_value - NORMAL_CREST_THRESHOLD)
		/ (DANGER_CREST_THRESHOLD - NORMAL_CREST_THRESHOLD),
		0.0,
		1.0
	)
	var mapped_color := Color.from_hsv(lerpf(0.33, 0.0, risk_ratio), 1.0, 1.0)
	var material := rail_mesh.get_active_material(0) as StandardMaterial3D
	if material:
		material.albedo_color = mapped_color
