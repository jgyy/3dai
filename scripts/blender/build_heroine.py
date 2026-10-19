"""Finish the Tripo-rigged heroine in Blender: fix scale/orientation, author animations, export a GLB.

Run headless (put the system Python first on PATH if Blender picks up a uv/pyenv Python):

    PATH=/usr/bin:$PATH blender -b --factory-startup --python scripts/blender/build_heroine.py -- \
        art/tripo-out/heroine/<rig-task>/model.glb game/assets/characters/heroine/heroine.glb

Why this exists: Tripo's `anim retarget` preset animations were failing (error 1004) for every model,
so the idle, walk, run, jump, and slash clips are authored here on Tripo's skeleton instead.

Conventions: Blender Z up, the heroine faces -Y after the fix below (glTF +Z), X is her left-right axis.
Every pose is a world-space rotation delta per bone; unlisted bones inherit their parent's delta.
"""

import math
import sys

import bpy
from mathutils import Euler, Quaternion, Vector

HEIGHT = 1.65  # metres
FPS = 30

# Tripo's generic bone names, grouped by role. "left" is the heroine's own left.
B = {
    "spine0": "tripo::0_Left_Limb_0",
    "spine1": "tripo::0_Left_Limb_1",
    "neck": "tripo::Head_0",
    "head": "tripo::Head_1",
    "l_clav": "tripo::0_Left_Limb_2",
    "l_arm": "tripo::0_Left_Limb_3",
    "l_fore": "tripo::0_Left_Limb_4",
    "r_clav": "tripo::Spine_0",
    "r_arm": "tripo::Spine_1",
    "r_fore": "bone_27",
    "l_thigh": "tripo::0_Right_Limb_0",
    "l_shin": "tripo::0_Right_Limb_1",
    "l_foot": "tripo::0_Right_Limb_2",
    "r_thigh": "tripo::1_Left_Limb_0",
    "r_shin": "tripo::1_Left_Limb_1",
    "r_foot": "tripo::1_Left_Limb_2",
}


def rx(deg):
    return Quaternion((1, 0, 0), math.radians(deg))


def ry(deg):
    return Quaternion((0, 1, 0), math.radians(deg))


def rz(deg):
    return Quaternion((0, 0, 1), math.radians(deg))


def lerp(keys, frame):
    """Piecewise-smooth interpolation of [(frame, value), ...]."""
    if frame <= keys[0][0]:
        return keys[0][1]
    for (f0, v0), (f1, v1) in zip(keys, keys[1:]):
        if frame <= f1:
            t = (frame - f0) / (f1 - f0)
            t = t * t * (3 - 2 * t)
            return v0 + (v1 - v0) * t
    return keys[-1][1]


def load(path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=path)
    arm = next(o for o in bpy.context.scene.objects if o.type == "ARMATURE")
    mesh = next(o for o in bpy.context.scene.objects if o.type == "MESH" and o.vertex_groups)
    for o in list(bpy.context.scene.objects):
        if o not in (arm, mesh):
            bpy.data.objects.remove(o, do_unlink=True)  # Blender's bone-shape helper
    return arm, mesh


def skinned_bounds(mesh):
    """World-space (min, max) of the deformed mesh. bound_box ignores the armature."""
    deps = bpy.context.evaluated_depsgraph_get()
    evaluated = mesh.evaluated_get(deps)
    verts = [mesh.matrix_world @ v.co for v in evaluated.to_mesh().vertices]
    return (
        Vector([min(v[i] for v in verts) for i in range(3)]),
        Vector([max(v[i] for v in verts) for i in range(3)]),
    )


def normalise(arm, mesh):
    """Scale to 1.65 m, face glTF +Z, put the origin on the floor between the feet."""
    lo, hi = skinned_bounds(mesh)
    arm.rotation_mode = "XYZ"  # the glTF importer leaves armatures in quaternion mode
    arm.rotation_euler = Euler((0, 0, math.radians(-90)))
    arm.scale = (HEIGHT / (hi.z - lo.z),) * 3
    bpy.context.view_layer.update()
    lo, hi = skinned_bounds(mesh)
    arm.location += Vector((-(lo.x + hi.x) / 2, -(lo.y + hi.y) / 2, -lo.z))
    bpy.context.view_layer.update()
    bpy.ops.object.select_all(action="DESELECT")
    arm.select_set(True)
    mesh.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)


def rest_data(arm):
    rest = {b.name: b.matrix_local.to_quaternion() for b in arm.data.bones}
    head = {b.name: b.matrix_local.translation.copy() for b in arm.data.bones}
    return rest, head


def apply_pose(arm, rest, deltas, root_offset=Vector(), spine_offset=Vector()):
    """deltas: bone -> world rotation delta. Children inherit it unless listed."""
    ident = Quaternion()

    def visit(bone, parent_delta):
        delta = deltas.get(bone.name, parent_delta)
        pb = arm.pose.bones[bone.name]
        r = rest[bone.name]
        pb.rotation_mode = "QUATERNION"
        pb.rotation_quaternion = r.inverted() @ (parent_delta.inverted() @ delta) @ r
        pb.location = Vector()
        offset = Vector()
        if bone.parent is None:
            offset = root_offset
        elif bone.name == B["spine0"]:
            offset = spine_offset
        if offset.length:
            pb.location = r.inverted() @ (parent_delta.inverted() @ offset)
        for child in bone.children:
            visit(child, delta)

    for bone in arm.data.bones:
        if bone.parent is None:
            visit(bone, ident)


def keyframe(arm, frame):
    for pb in arm.pose.bones:
        pb.keyframe_insert("rotation_quaternion", frame=frame)
        pb.keyframe_insert("location", frame=frame)


# ---------------------------------------------------------------- poses
def pose_walk_run(phase, amp, knee, arm_amp, elbow, lean, bob, adduct):
    s, c = math.sin(phase), math.cos(phase)
    d = {}
    d[B["spine0"]] = rx(-lean * 0.5)
    d[B["spine1"]] = rz(5 * s) @ rx(-lean)
    d[B["head"]] = rx(lean * 0.9)
    for side, sign in (("l", 1), ("r", -1)):
        thigh = -sign * amp * s  # forward (negative about X) when the arm swings back
        flex = knee * max(0.0, sign * c) + 4
        d[B[f"{side}_thigh"]] = rx(thigh)
        d[B[f"{side}_shin"]] = rx(flex) @ rx(thigh)
        d[B[f"{side}_foot"]] = Quaternion()
        swing = sign * arm_amp * s
        upper = rx(swing) @ ry(sign * adduct)
        d[B[f"{side}_arm"]] = upper
        d[B[f"{side}_fore"]] = rx(-(elbow + 6 * (1 - sign * s) * 0.5)) @ upper
    return d, Vector((0, 0, 0)), Vector((0, 0, bob * math.cos(2 * phase)))


def pose_idle(phase):
    s = math.sin(phase)
    d = {B["spine1"]: rx(-1.2 * s), B["head"]: rx(1.0 * s) @ rz(2 * math.sin(phase * 0.5))}
    for side, sign in (("l", 1), ("r", -1)):
        upper = ry(sign * (19 + 1.2 * s)) @ rx(sign * 1.5 * s)
        d[B[f"{side}_arm"]] = upper
        d[B[f"{side}_fore"]] = rx(-9) @ upper
    return d, Vector(), Vector((0, 0, 0.004 * s))


def leg_length(arm, head):
    def dist(a, b):
        return (head[B[a]] - head[B[b]]).length

    return dist("l_thigh", "l_shin") + dist("l_shin", "l_foot")


def pose_crouch(crouch, up, leg_len, arm_swing, lean, forearm=-15):
    d = {B["spine0"]: rx(-lean * 0.5), B["spine1"]: rx(-lean), B["head"]: rx(lean * 0.8)}
    for side, sign in (("l", 1), ("r", -1)):
        d[B[f"{side}_thigh"]] = rx(-crouch)
        d[B[f"{side}_shin"]] = rx(crouch)  # = thigh (-crouch) plus flex (2 * crouch)
        d[B[f"{side}_foot"]] = Quaternion()
        upper = rx(arm_swing) @ ry(sign * 17)
        d[B[f"{side}_arm"]] = upper
        d[B[f"{side}_fore"]] = rx(forearm) @ upper
    drop = leg_len * (1 - math.cos(math.radians(crouch)))
    return d, Vector((0, 0, up - drop)), Vector()


def pose_slash(f):
    arm_swing = lerp([(0, 0), (5, -165), (9, -35), (13, 10), (21, 0)], f)
    elbow = lerp([(0, -9), (5, -35), (9, -5), (13, -15), (21, -9)], f)
    twist = lerp([(0, 0), (5, -22), (9, 28), (13, 20), (21, 0)], f)
    lean = lerp([(0, 0), (5, 4), (9, 14), (13, 10), (21, 0)], f)
    lunge = lerp([(0, 0), (5, 0.4), (9, 1), (13, 1), (21, 0)], f)
    d = {B["spine1"]: rz(twist) @ rx(-lean), B["head"]: rz(-twist * 0.7)}
    d[B["r_arm"]] = rx(arm_swing) @ ry(-lerp([(0, 19), (5, 25), (9, 12), (21, 19)], f))
    d[B["r_fore"]] = rx(elbow) @ d[B["r_arm"]]
    d[B["l_arm"]] = rx(-18 * lunge) @ ry(30)
    d[B["l_fore"]] = rx(-25) @ d[B["l_arm"]]
    d[B["l_thigh"]] = rx(-28 * lunge)
    d[B["l_shin"]] = rx(14 * lunge) @ rx(-28 * lunge)
    d[B["l_foot"]] = Quaternion()
    d[B["r_thigh"]] = rx(16 * lunge)
    d[B["r_shin"]] = rx(10 * lunge) @ rx(16 * lunge)
    d[B["r_foot"]] = Quaternion()
    return d, Vector((0, 0, -0.05 * lunge)), Vector()


def build_actions(arm, rest, head):
    leg_len = leg_length(arm, head)
    clips = []

    def clip(name, frames, pose_fn):
        act = bpy.data.actions.new(name)
        arm.animation_data_create()
        arm.animation_data.action = act
        for f in range(frames):
            deltas, root_off, spine_off = pose_fn(f)
            apply_pose(arm, rest, deltas, root_off, spine_off)
            keyframe(arm, f)
        arm.animation_data.action = None
        clips.append((name, act, frames))

    clip("idle-loop", 90, lambda f: pose_idle(2 * math.pi * f / 90))
    clip(
        "walk-loop",
        30,
        lambda f: pose_walk_run(2 * math.pi * f / 30, 22, 38, 20, 14, 2, 0.012, 17),
    )
    clip(
        "run-loop",
        20,
        lambda f: pose_walk_run(2 * math.pi * f / 20, 42, 70, 48, 75, 12, 0.03, 12),
    )

    def jump(f):
        crouch = lerp([(0, 0), (5, 38), (9, 4), (13, 24), (17, 10), (21, 40), (23, 0)], f)
        up = lerp([(0, 0), (9, 0), (13, 0.32), (17, 0.1), (20, 0)], f)
        swing = lerp([(0, 0), (5, 35), (9, -120), (13, -150), (17, -80), (21, 5), (23, 0)], f)
        lean = lerp([(0, 0), (5, 12), (9, -3), (13, 0), (21, 10), (23, 0)], f)
        return pose_crouch(crouch, up, leg_len, swing, lean)

    clip("jump", 24, jump)
    clip("slash", 22, pose_slash)
    return clips


def push_to_nla(arm, clips):
    arm.animation_data.action = None
    for name, act, frames in clips:
        track = arm.animation_data.nla_tracks.new()
        track.name = name
        strip = track.strips.new(name, 0, act)
        strip.action_frame_start = 0
        strip.action_frame_end = frames - 1
        strip.frame_end = frames - 1


def export(path):
    bpy.ops.export_scene.gltf(
        filepath=path,
        export_format="GLB",
        export_animations=True,
        export_animation_mode="NLA_TRACKS",
        export_force_sampling=True,
        export_frame_range=False,
        export_skins=True,
        export_yup=True,
        export_apply=False,
    )


def main():
    src, dst = sys.argv[sys.argv.index("--") + 1 :][:2]
    arm, mesh = load(src)
    normalise(arm, mesh)
    bpy.context.scene.render.fps = FPS
    rest, head = rest_data(arm)
    missing = [n for n in B.values() if n not in arm.data.bones]
    assert not missing, f"unexpected bone names: {missing}"
    clips = build_actions(arm, rest, head)
    apply_pose(arm, rest, {})
    push_to_nla(arm, clips)
    export(dst)
    print("EXPORTED", dst, [c[0] for c in clips])


if __name__ == "__main__":
    main()
