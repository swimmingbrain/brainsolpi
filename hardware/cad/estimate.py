"""rough filament and time estimate per part, the slicer has the last word"""

DENSITY = 1.26  # g per cm3, matte PLA
LINE_W = 0.42
WALLS = 4
FLOW = 9.0  # mm3 per second averaged over walls, infill and travel on the A1 mini
LAYER_S = 2.0  # seconds per layer for z hop, wipe and the slow first layers

SETTINGS = {
    # part: layer height, infill percent, infill pattern, colour role
    "tray": (0.2, 15, "gyroid"),
    "lid": (0.2, 15, "gyroid"),
    "bedlid": (0.2, 15, "gyroid"),
    "foot": (0.2, 100, "concentric"),
    "neck_front": (0.2, 25, "gyroid"),
    "neck_back": (0.2, 25, "gyroid"),
    "head_back": (0.2, 15, "gyroid"),
    "head_bezel": (0.2, 15, "gyroid"),
    "ear_horn": (0.16, 40, "gyroid"),
    "ear_pivot": (0.16, 40, "gyroid"),
    "cap": (0.12, 100, "concentric"),
    "fit_test": (0.2, 15, "gyroid"),
    "servo_test": (0.2, 25, "gyroid"),
}


def estimate(name, mesh):
    layer, infill, pattern = SETTINGS[name]
    vol = float(mesh.volume)
    # four walls of 0.42 on the sides, five layers on top and bottom, about 1.4 mm on average
    shell = min(vol, float(mesh.area) * 1.4)
    material = shell + (vol - shell) * infill / 100.0
    grams = material / 1000.0 * DENSITY
    height = float(mesh.extents[2])
    layers = max(1, int(round(height / layer)))
    minutes = (material / FLOW + layers * LAYER_S) / 60.0
    return {"layer": layer, "infill": infill, "pattern": pattern, "grams": grams, "minutes": minutes}
