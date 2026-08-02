"""Blender rig for rendering pak128 isometric tiles.

Imported by the `build_*.py` scripts that run inside Blender. Nothing here
touches Pillow or the sprite sheet — Blender's bundled Python has no Pillow, so
cells are rendered as individual RGBA PNGs and `tools/assemble_sheet.py` packs
them afterwards.

The projection
--------------
Simutrans draws a 2:1 diamond: one tile edge covers 64px horizontally and 32px
vertically. In an orthographic camera that is an elevation of exactly 30°
(sin 30° = 0.5), i.e. `rotation_euler = (60°, 0°, 45°)`. Note this is *not*
Blender's "true isometric" 54.736°, which would give 2:1.1547 and drift a pixel
every few tiles.

With one tile edge as one world unit, `ortho_scale = sqrt(2)` makes a
128px-wide render cover the tile exactly. That fixes the scale chain:

    world +X  ->  screen right and down   (the E axis, `b` in the 2D renderer)
    world +Y  ->  screen right and up     (the N axis, `a`)
    world +Z  ->  screen up
    1 world unit along X or Y  ->  64px across, 32px down/up
    1 world unit along Z       ->  78.4px up

pak128's height step is 16px, hence `HEIGHT_STEP` below. The tile is taken as
16m of ground, which is what makes a real 3.1m Transrapid girder come out at
the ~14px the rail sets use for their track band.

Vertical framing
----------------
A tile centred in a 128x128 frame would land at y=32..96, but pak128 cells put
the diamond at y=64..128. The camera is therefore lifted along its own up
vector by 32px worth of world space, which pushes the content down the frame by
exactly that much. `selftest.py` asserts the result lands on the reference
diamond pixel for pixel.

Lighting
--------
Measured off pak128's own rail sheet: its ramp facing screen-lower-left renders
at mean 222, flat ground at 186, and the opposite ramp at 167. Fitting Lambert
to those three numbers puts the key light at ~45° elevation coming from world
-Y, with a fill to lift the shadow side. Same rig here, so maglev tiles sit in
the same light as every other pak128 way.
"""

from __future__ import annotations

import math

import bmesh
import bpy
from mathutils import Vector

TILE_PX = 128
TILE_M = 16.0                     # ground covered by one tile, in metres
HEIGHT_STEP = 16.0 / 78.4         # one Simutrans height level, in world units
ORTHO_SCALE = math.sqrt(2.0)

# Screen basis of the camera, useful for framing maths.
CAM_RIGHT = Vector((0.7071067812, 0.7071067812, 0.0))
CAM_UP = Vector((-0.3535533906, 0.3535533906, 0.8660254038))
CAM_FORWARD = Vector((-0.6123724357, 0.6123724357, -0.5))
PX_PER_SCREEN_UNIT = TILE_PX / ORTHO_SCALE       # 90.51

# Diamond corners in world space, named by where they land on screen.
CORNER_TOP = (-0.5, 0.5)
CORNER_RIGHT = (0.5, 0.5)
CORNER_BOTTOM = (0.5, -0.5)
CORNER_LEFT = (-0.5, -0.5)

# Ground plane per tile shape: z = c + cx*x + cy*y. The ramps raise the two
# corners on one edge by a full height step, leaving the other two where flat
# ground puts them — which is how pak128's own ImageUp tiles are built.
SHAPES = {
    "flat": (0.0, 0.0, 0.0),
    "up_n": (HEIGHT_STEP / 2, 0.0, -HEIGHT_STEP),   # y = -0.5 edge raised
    "up_s": (HEIGHT_STEP / 2, 0.0, +HEIGHT_STEP),   # y = +0.5 edge raised
    "up_w": (HEIGHT_STEP / 2, +HEIGHT_STEP, 0.0),   # x = +0.5 edge raised
    "up_e": (HEIGHT_STEP / 2, -HEIGHT_STEP, 0.0),   # x = -0.5 edge raised
}


def m(metres: float) -> float:
    """Metres -> world units."""
    return metres / TILE_M


def ground_z(shape: str, x: float, y: float) -> float:
    c, cx, cy = SHAPES[shape]
    return c + cx * x + cy * y


def ground_point(shape: str, x: float, y: float) -> Vector:
    return Vector((x, y, ground_z(shape, x, y)))


def ground_normal(shape: str) -> Vector:
    """Unit normal of the (possibly tilted) ground plane."""
    _, cx, cy = SHAPES[shape]
    return Vector((-cx, -cy, 1.0)).normalized()


# --------------------------------------------------------------------------
# Scene construction
# --------------------------------------------------------------------------

def clear_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def setup_camera(supersample: int = 4) -> bpy.types.Object:
    cam_data = bpy.data.cameras.new("iso")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = ORTHO_SCALE
    cam = bpy.data.objects.new("iso", cam_data)
    bpy.context.scene.collection.objects.link(cam)

    # Back the camera off along its view axis (orthographic, so distance only
    # affects clipping) and lift it so the diamond lands in the lower half of
    # the cell the way pak128 packs it. That is 32px, plus a half pixel: the
    # reference diamond is widest on row 96 alone, which puts its centre on a
    # pixel centre rather than on a pixel boundary. Without the half pixel the
    # widest row is 126px instead of 128 and every tile is a row too high.
    lift = (TILE_PX / 4 + 0.5) / PX_PER_SCREEN_UNIT
    cam.location = -CAM_FORWARD * 10.0 + CAM_UP * lift
    cam.rotation_euler = (math.radians(60.0), 0.0, math.radians(45.0))
    cam_data.clip_start = 0.1
    cam_data.clip_end = 100.0

    bpy.context.scene.camera = cam
    return cam


def setup_lighting(key_energy: float = 2.95, fill: float = 0.34) -> None:
    """Key sun from world -Y at 45°, plus a flat world fill."""
    sun_data = bpy.data.lights.new("key", type="SUN")
    sun_data.energy = key_energy
    sun_data.angle = math.radians(3.0)        # slightly soft shadow edges
    sun = bpy.data.objects.new("key", sun_data)
    bpy.context.scene.collection.objects.link(sun)
    # A sun points along its local -Z; rotating +45° about X aims it towards
    # +Y and downwards, i.e. the light arrives from -Y at 45° elevation.
    sun.rotation_euler = (math.radians(45.0), 0.0, 0.0)

    world = bpy.data.worlds.new("fill")
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (0.82, 0.86, 0.92, 1.0)   # cool sky bounce
    bg.inputs[1].default_value = fill
    bpy.context.scene.world = world


# pak128's ramp tiles are not physically shaded. Fitting Lambert to its three
# measured tones (flat 189, shaded ramp 167, sunlit ramp 227) has no solution:
# the shaded ramp matches a ~43 degree sun exactly, but the sunlit one is far
# brighter than that same sun can produce. They evidently lifted it by hand for
# readability. Matching the physics would leave maglev ramps visibly duller
# than rail ramps beside them, so the convention wins over the physics: these
# are the stops needed to land each ramp on pak128's own tone.
RAMP_EXPOSURE = {
    "flat": 0.0,
    "up_n": -0.093,   # 178 -> 167
    "up_w": -0.015,
    "up_e": 0.0,
    "up_s": +0.169,   # 202 -> 227
}


def setup_render(supersample: int = 4, samples: int = 96,
                 shape: str = "flat") -> None:
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    # No diffuse bounce. Light bouncing off a lit girder wall onto the apron
    # reads as a smudge at 128px, and pak128's own tiles have no such bleed;
    # the world fill stands in for indirect light instead.
    scene.cycles.diffuse_bounces = 0
    scene.cycles.max_bounces = 1
    scene.render.resolution_x = TILE_PX * supersample
    scene.render.resolution_y = TILE_PX * supersample
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"
    # Without this the AgX view transform desaturates everything and the tiles
    # no longer match pak128's palette.
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = RAMP_EXPOSURE.get(shape, 0.0)


def setup(supersample: int = 4, samples: int = 96, shape: str = "flat") -> None:
    clear_scene()
    setup_camera(supersample)
    setup_lighting()
    setup_render(supersample, samples, shape)


def render_to(path: str) -> None:
    bpy.context.scene.render.filepath = path
    bpy.ops.render.render(write_still=True)


# --------------------------------------------------------------------------
# Mesh helpers
# --------------------------------------------------------------------------

def new_mesh(name: str, verts, faces, materials=None, bevel: float = 0.0):
    """Build an object from raw geometry, with normals made consistent.

    `materials` may be a single material or a list; face material indices are
    set by the caller and index into that list.
    """
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([tuple(v) for v in verts], [], faces)
    mesh.validate()
    mesh.update()

    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)

    if materials is not None:
        for mat in (materials if isinstance(materials, (list, tuple)) else [materials]):
            obj.data.materials.append(mat)

    # from_pydata does not order faces, so half of them can end up inside out.
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()

    if bevel > 0.0:
        mod = obj.modifiers.new("bevel", "BEVEL")
        mod.width = bevel
        mod.segments = 2
        mod.limit_method = "ANGLE"
        mod.angle_limit = math.radians(35.0)
    return obj


def polygon(name: str, shape: str, points_xy, material=None, lift: float = 0.0):
    """A flat patch lying on the tile's ground plane."""
    verts = [ground_point(shape, x, y) + Vector((0, 0, lift)) for x, y in points_xy]
    return new_mesh(name, verts, [list(range(len(verts)))], material)


def extrude_profile(name: str, profile, start: Vector, end: Vector,
                    right: Vector, up: Vector, materials=None,
                    edge_materials=None, bevel: float = 0.0,
                    caps: bool = True):
    """Sweep a closed 2D cross-section along a straight run.

    `profile` is a list of `(perp, height)` pairs in world units; `right` and
    `up` are the unit perpendicular in the ground plane and the plane normal.
    Both ends are capped unless `caps` is false, which leaves an open skin —
    useful when the ends need their own geometry, such as a wall with a
    doorway cut into it.

    `edge_materials` maps a profile *edge* index (the face swept by the segment
    from point i to point i+1) to a material slot. Picking faces by profile
    index rather than by position keeps the assignment correct on ramp tiles,
    where world height is no guide to height above the apron.
    """
    n = len(profile)
    verts = []
    for base in (start, end):
        for perp, height in profile:
            verts.append(base + right * perp + up * height)

    faces = [[i, (i + 1) % n, n + (i + 1) % n, n + i] for i in range(n)]
    if caps:
        faces.append(list(range(n - 1, -1, -1)))      # start cap
        faces.append(list(range(n, 2 * n)))           # end cap

    obj = new_mesh(name, verts, faces, materials, bevel)
    for edge_index, slot in (edge_materials or {}).items():
        obj.data.polygons[edge_index].material_index = slot
    return obj


# --------------------------------------------------------------------------
# Materials
# --------------------------------------------------------------------------

def _seam_grid(node_tree, period_m: float, width_m: float):
    """A mask that is 1 on a panel joint line and 0 elsewhere.

    Object coordinates are world coordinates here (every object is built at the
    origin from world-space vertices), so the grid lines up across tiles and a
    joint continues straight through a tile boundary.
    """
    nodes, links = node_tree.nodes, node_tree.links
    period = period_m / TILE_M
    coord = nodes.new("ShaderNodeTexCoord")
    split = nodes.new("ShaderNodeSeparateXYZ")
    links.new(coord.outputs["Object"], split.inputs[0])

    per_axis = []
    for axis in (0, 1):
        scale = nodes.new("ShaderNodeMath")
        scale.operation = "MULTIPLY"
        scale.inputs[1].default_value = 1.0 / period
        links.new(split.outputs[axis], scale.inputs[0])

        frac = nodes.new("ShaderNodeMath")
        frac.operation = "FRACT"
        links.new(scale.outputs[0], frac.inputs[0])

        # Distance to the nearest grid line is min(f, 1 - f).
        flip = nodes.new("ShaderNodeMath")
        flip.operation = "SUBTRACT"
        flip.inputs[0].default_value = 1.0
        links.new(frac.outputs[0], flip.inputs[1])

        nearest = nodes.new("ShaderNodeMath")
        nearest.operation = "MINIMUM"
        links.new(frac.outputs[0], nearest.inputs[0])
        links.new(flip.outputs[0], nearest.inputs[1])

        on_line = nodes.new("ShaderNodeMath")
        on_line.operation = "LESS_THAN"
        on_line.inputs[1].default_value = width_m / period_m
        links.new(nearest.outputs[0], on_line.inputs[0])
        per_axis.append(on_line.outputs[0])

    combine = nodes.new("ShaderNodeMath")
    combine.operation = "MAXIMUM"
    links.new(per_axis[0], combine.inputs[0])
    links.new(per_axis[1], combine.inputs[1])
    return combine.outputs[0]


def make_glass(name: str, tint, face_alpha: float = 0.12,
               edge_alpha: float = 0.72, blend: float = 0.30,
               roughness: float = 0.06):
    """Translucent glazing whose opacity rises towards the silhouette.

    Uniform alpha reads as grey haze, not glass. Real glazing is almost
    invisible face-on and bright at grazing angles, so alpha is driven by a
    Layer Weight *Facing* output. That single node is the difference between
    reading as a tube and reading as a smear.

    Uses the Principled **Alpha** input rather than Transmission on purpose:
    transmission would refract whatever is behind the glass, which is noise at
    128px and wrong once the sprite is composited in 2D.
    """
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*tint, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = 0.0

    weight = nodes.new("ShaderNodeLayerWeight")
    weight.inputs["Blend"].default_value = blend

    spread = nodes.new("ShaderNodeMapRange")
    spread.inputs["From Min"].default_value = 0.0
    spread.inputs["From Max"].default_value = 1.0
    spread.inputs["To Min"].default_value = face_alpha
    spread.inputs["To Max"].default_value = edge_alpha
    links.new(weight.outputs["Facing"], spread.inputs["Value"])
    links.new(spread.outputs["Result"], bsdf.inputs["Alpha"])

    mat.blend_method = "BLEND" if hasattr(mat, "blend_method") else mat.blend_method
    return mat


# Simutrans keeps a table of 31 exact colours with special meaning — player
# colours, and lights that do not darken when the map dims at night (see
# `image_t::rgbtab`). A sprite cannot render one of those directly through
# Cycles, so an accent is rendered flat in an unmistakable flag colour and
# swapped for the exact value during packing.
FLAG_LIGHT = (1.0, 0.0, 1.0)


def make_flag_emission(name: str, colour=FLAG_LIGHT):
    """Unshaded marker material, swapped for a Simutrans light during packing."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    for node in list(nodes):
        if node.type != "OUTPUT_MATERIAL":
            nodes.remove(node)
    emission = nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = (*colour, 1.0)
    emission.inputs["Strength"].default_value = 1.0
    links.new(emission.outputs["Emission"],
              nodes["Material Output"].inputs["Surface"])
    return mat


def no_shadow(obj) -> None:
    """Stop an object casting shadows.

    A 4m glass tube casting a solid shadow band across the apron makes the
    whole thing read as opaque, whatever the material says.
    """
    for attr in ("visible_shadow", "is_shadow_catcher"):
        if hasattr(obj, attr) and attr == "visible_shadow":
            obj.visible_shadow = False


def make_material(name: str, base_color, roughness: float = 0.9,
                  metallic: float = 0.0, noise: float = 0.0,
                  seams: float = 0.0, seam_period_m: float = 4.0,
                  seam_width_m: float = 0.10):
    """Principled surface with optional concrete grain and panel joints.

    pak128's ways are panelled concrete, not flat fills. `noise` adds the
    grain, `seams` the joint lines; both feed the bump as well as the albedo,
    so the joints pick up a real occlusion line rather than being painted on.
    """
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*base_color, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic

    colour_out = None
    height_out = None

    if noise > 0.0:
        tex = nodes.new("ShaderNodeTexNoise")
        tex.inputs["Scale"].default_value = 260.0
        tex.inputs["Detail"].default_value = 3.0
        height_out = tex.outputs["Fac"]

        # The grain nudges the albedo too, so concrete is not a dead flat fill.
        mixer = nodes.new("ShaderNodeMixRGB")
        mixer.blend_type = "MIX"
        mixer.inputs["Fac"].default_value = 0.10
        mixer.inputs["Color1"].default_value = (*base_color, 1.0)
        mixer.inputs["Color2"].default_value = (
            *[min(1.0, c * 1.18) for c in base_color], 1.0)
        links.new(tex.outputs["Fac"], mixer.inputs["Fac"])
        colour_out = mixer.outputs["Color"]

    if seams > 0.0:
        mask = _seam_grid(mat.node_tree, seam_period_m, seam_width_m)
        joint = nodes.new("ShaderNodeMixRGB")
        joint.blend_type = "MIX"
        joint.inputs["Color2"].default_value = (
            *[c * (1.0 - seams) for c in base_color], 1.0)
        links.new(mask, joint.inputs["Fac"])
        if colour_out is not None:
            links.new(colour_out, joint.inputs["Color1"])
        else:
            joint.inputs["Color1"].default_value = (*base_color, 1.0)
        colour_out = joint.outputs["Color"]

        # Sink the joint slightly so it catches its own shading.
        groove = nodes.new("ShaderNodeMath")
        groove.operation = "MULTIPLY"
        groove.inputs[1].default_value = -0.55
        links.new(mask, groove.inputs[0])
        if height_out is not None:
            combined = nodes.new("ShaderNodeMath")
            combined.operation = "ADD"
            links.new(height_out, combined.inputs[0])
            links.new(groove.outputs[0], combined.inputs[1])
            height_out = combined.outputs[0]
        else:
            height_out = groove.outputs[0]

    if colour_out is not None:
        links.new(colour_out, bsdf.inputs["Base Color"])
    if height_out is not None:
        bump = nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = max(noise, 0.25)
        links.new(height_out, bump.inputs["Height"])
        links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat
