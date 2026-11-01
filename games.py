from dataclasses import dataclass
from enum import Enum


class Game(Enum):
    SLY1 = "sly1"
    SLY2 = "sly2"
    SLY3 = "sly3"
    SLY4 = "sly4"
    HACKPACK = "hackpack"
    ALTEREGO = "alterego"
    SPARKRUNNER = "sparkrunner"
    SYSTEMCRACKER = "systemcracker"


@dataclass(frozen=True)
class Preset:
    # Orthographic camera (the default)
    height: float            # how far above the map plane the camera sits, along `axis`
    view: float              # world units the frame shows top to bottom: how much a shot captures, and the scale
    # Perspective camera (ORTHO = False)
    fov: float               # degrees
    distance: float          # how far the camera is from the map plane along `axis`
    step: float = None       # world units covered by one 370 px crop. None = worked out from fov and distance
    axis: str = None         # "X", "Y", "Z" (look along +axis) or "-X", "-Y", "-Z" (look along -axis) for a
                             # side view. None = the game's up axis (top-down)
    yaw: float = None        # degrees, overrides the axis' default yaw (top-down: rotates the tiles)


# Sly 2's perspective values (fov 0.002 rad at height 500000, 510 units per crop) match the
# existing tiles. `view` keeps that scale (510 units per 370 px is about 990 per 720 px frame),
# and `height` is a tenth of the perspective distance, low enough for the game to load its
# textures properly. The other games use the same values until they're calibrated.
PRESETS = {
    Game.SLY1: Preset(height=660, view=2000, fov=1.15, distance=5000, step=500),
    Game.SLY2: Preset(height=3300, view=3000, fov=0.1146, distance=5000, step=510),
    Game.SLY3: Preset(height=1121, view=2000, fov=0.1146, distance=5000, step=510),
    Game.SLY4: Preset(height=13.7, view=30, fov=0.112, distance=5000, step=5),
    Game.HACKPACK: Preset(height=15, view=20, fov=0.1146, distance=500000, step=510),
    # Alter Ego hacks are 2D: looking along -Z (yaw -180, pitch 0), Sly 4 / Hackpack units
    Game.ALTEREGO: Preset(height=15, view=20, fov=0.1146, distance=500000, step=510, axis="-Z"),
    # Sparkrunner maps are top-down at yaw 0 (pitch -90) instead of the default -90
    Game.SPARKRUNNER: Preset(height=160, view=60, fov=1.0, distance=1, step=1, yaw=0),
    Game.SYSTEMCRACKER: Preset(height=55, view=60, fov=1.0, distance=1, step=1, yaw=-180),
}
