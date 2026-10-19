class_name Heroine
extends CharacterBody3D
## Third-person controller for the heroine. WASD or arrows move, Shift runs,
## Space jumps, J or left mouse slashes. Mouse wheel or Q/E zooms the camera.

@export var walk_speed := 2.0
@export var run_speed := 5.0
@export var jump_velocity := 5.0
@export var turn_speed := 10.0
@export var zoom_min := 1.5
@export var zoom_max := 8.0
@export var zoom_step := 0.5
@export var zoom_key_speed := 4.0

@onready var model: Node3D = $Model
@onready var anim: AnimationPlayer = $Model.find_child("AnimationPlayer", true, false)
@onready var camera_pivot: Node3D = $CameraPivot
@onready var camera: Camera3D = $CameraPivot/Camera3D

var _gravity: float = ProjectSettings.get_setting("physics/3d/default_gravity")
var _slashing := false
var _camera_dir: Vector3
var _zoom_target: float
var _zoom: float


func _ready() -> void:
	anim.animation_finished.connect(_on_animation_finished)
	_play("idle")
	_zoom = camera.position.length()
	_zoom_target = _zoom
	_camera_dir = camera.position / _zoom


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseButton and event.pressed:
		if event.button_index == MOUSE_BUTTON_WHEEL_UP:
			_set_zoom(_zoom_target - zoom_step)
		elif event.button_index == MOUSE_BUTTON_WHEEL_DOWN:
			_set_zoom(_zoom_target + zoom_step)


func _process(delta: float) -> void:
	var target := global_position + Vector3(0.0, 1.2, 0.0)
	camera_pivot.global_position = camera_pivot.global_position.lerp(target, clampf(8.0 * delta, 0.0, 1.0))
	_set_zoom(_zoom_target + (_axis(KEY_E, KEY_Q)) * zoom_key_speed * delta)
	_zoom = lerpf(_zoom, _zoom_target, clampf(10.0 * delta, 0.0, 1.0))
	camera.position = _camera_dir * _zoom


func _set_zoom(distance: float) -> void:
	_zoom_target = clampf(distance, zoom_min, zoom_max)


func _physics_process(delta: float) -> void:
	if not is_on_floor():
		velocity.y -= _gravity * delta

	var move := Vector2(
		_axis(KEY_A, KEY_D) + _axis(KEY_LEFT, KEY_RIGHT),
		_axis(KEY_W, KEY_S) + _axis(KEY_UP, KEY_DOWN)
	).limit_length()
	var running := Input.is_physical_key_pressed(KEY_SHIFT)
	var speed := run_speed if running else walk_speed
	if _slashing:
		speed *= 0.2

	velocity.x = move.x * speed
	velocity.z = move.y * speed
	if move.length() > 0.1:
		var target := atan2(move.x, move.y)
		model.rotation.y = lerp_angle(model.rotation.y, target, clampf(turn_speed * delta, 0.0, 1.0))

	if is_on_floor() and Input.is_physical_key_pressed(KEY_SPACE):
		velocity.y = jump_velocity
		_slashing = false
		_play("jump")
	elif is_on_floor() and not _slashing and _wants_slash():
		perform_slash()

	move_and_slide()
	_update_animation(move.length() > 0.1, running)


func perform_slash() -> void:
	_slashing = true
	anim.play("slash", 0.1)


func _wants_slash() -> bool:
	return Input.is_physical_key_pressed(KEY_J) or Input.is_mouse_button_pressed(MOUSE_BUTTON_LEFT)


func _update_animation(moving: bool, running: bool) -> void:
	if _slashing:
		return
	if not is_on_floor():
		if anim.current_animation != "jump":
			_play("jump")
	elif moving:
		_play("run" if running else "walk")
	else:
		_play("idle")


func _play(animation: StringName) -> void:
	if anim.current_animation != animation:
		anim.play(animation, 0.15)


func _on_animation_finished(animation: StringName) -> void:
	if animation == &"slash":
		_slashing = false


func _axis(negative: Key, positive: Key) -> float:
	return float(Input.is_physical_key_pressed(positive)) - float(Input.is_physical_key_pressed(negative))
