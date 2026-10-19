extends Node3D
## Greybox test level. Pass `-- --screenshot=<path>` to save a frame and quit
## (used for PR screenshots, needs a real display, not --headless).

@onready var heroine: Heroine = $Heroine


func _ready() -> void:
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--screenshot="):
			_capture(arg.trim_prefix("--screenshot="))


func _capture(path: String) -> void:
	heroine.model.rotation.y = 0.55
	for i in 90:
		await get_tree().process_frame
	get_viewport().get_texture().get_image().save_png(path)
	get_tree().quit()
