from dataclasses import dataclass
from enum import Enum


class Game(Enum):
    SLY1 = "sly1"
    SLY2 = "sly2"
    SLY3 = "sly3"
    SLY4 = "sly4"
    HACKPACK = "hackpack"


@dataclass(frozen=True)
class Preset:
    # Orthographic camera (the default)
    height: float            # how far above the map plane the camera sits, along `axis`
    view: float              # world units the frame shows top to bottom: how much a shot captures, and the scale
    # Perspective camera (ORTHO = False)
    fov: float               # degrees
    distance: float          # how far the camera is from the map plane along `axis`
    step: float = None       # world units covered by one 370 px crop. None = worked out from fov and distance
    axis: str = None         # "X", "Y" or "Z": the axis the camera sits back along. None = the game's up axis (top-down)


# Sly 2's perspective values (fov 0.002 rad at height 500000, 510 units per crop) match the
# existing tiles. `view` keeps that scale (510 units per 370 px is about 990 per 720 px frame),
# and `height` is a tenth of the perspective distance, low enough for the game to load its
# textures properly. The other games use the same values until they're calibrated.
PRESETS = {
    Game.SLY1: Preset(height=5000, view=970, fov=1.15, distance=50000, step=500),
    Game.SLY2: Preset(height=50000, view=990, fov=0.1146, distance=500000, step=510),
    Game.SLY3: Preset(height=50000, view=990, fov=0.1146, distance=500000, step=510),
    Game.SLY4: Preset(height=500, view=9.7, fov=0.112, distance=5000, step=5),
    Game.HACKPACK: Preset(height=50000, view=990, fov=0.1146, distance=500000, step=510),
}
