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
    fov: float               # degrees
    distance: float          # how far the camera is from the map plane along `axis`
    step: float = None       # world units covered by one 370 px crop. None = worked out from fov and distance
    axis: str = None         # "X", "Y" or "Z": the axis the camera sits back along. None = the game's up axis (top-down)


# Sly 2 values (fov 0.002 rad at height 500000, 510 units per crop) match the existing tiles.
# The other games use the same values until they're calibrated.
PRESETS = {
    Game.SLY1: Preset(fov=0.1146, distance=500000, step=510),
    Game.SLY2: Preset(fov=0.1146, distance=500000, step=510),
    Game.SLY3: Preset(fov=0.1146, distance=500000, step=510),
    Game.SLY4: Preset(fov=0.1146, distance=500000, step=510),
    Game.HACKPACK: Preset(fov=0.1146, distance=500000, step=510),
}
