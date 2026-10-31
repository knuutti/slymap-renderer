# slymap-renderer

Renders map images of Sly Cooper levels. The game's free camera is moved block by block
through [SluMAN's](https://github.com/knuutti/SluMAN) camera script API, each view is captured from the OBS Virtual Camera with
OpenCV, and the tiles are stitched into one large map.

## Setup

```
pip install -r requirements.txt
```

Outside the code:
- **SluMAN** attached to the game (PS3 or RPCS3), in **Practice Mode**, with
  **Script API on 127.0.0.1:9675** ticked on the Camera tab. The API only runs while the
  Practice window is open.
- On RPCS3, Sly 3 and Sly 4 / Hackpack need the **Interpreter** PPU decoder for the camera
  hook. Without it Sly 3's camera flickers, which spoils captures.
- **OBS Virtual Camera** running with the game as its source, output 1280x720. OpenCV opens it
  by device index (`CAPTURE_DEVICE = 3` in `render_tiles.py`); the index can change when other
  cameras are added, so check it if the wrong source is captured. Keep overlays out of the
  frame centre, as they'd end up in the tiles.

## Usage

1. **Render tiles**: edit the settings at the top of `render_tiles.py`:

   | Setting | |
   |---|---|
   | `GAME` | `Game.SLY1` ... `Game.HACKPACK`; picks the preset in `games.py` |
   | `MAP` | Output folder name under `tiles/` |
   | `ROWS`, `COLS` | Inclusive block ranges. Rows go down the image, columns right |
   | `HEIGHT` | How far above the map plane the camera sits (`None` = preset) |
   | `VIEW` | World units the frame shows top to bottom: how much each shot captures, and the map's scale (`None` = preset) |
   | `NEAR`, `FAR` | Near and far distance (`None` = the game's near, `FAR` = `2 * HEIGHT`) |
   | `AXIS` | The axis the camera sits back along (`None` = top-down) |
   | `ORTHO`, `ORTHO_MARGIN` | Orthographic camera, on by default, see [Orthographic mode](#orthographic-mode) |
   | `FOV`, `DISTANCE`, `STEP` | Perspective camera only (`ORTHO = False`) |

   Then run `python render_tiles.py`. Each block is one 1240x680 shot (the 1280x720 frame minus
   a 20 px margin), saved at `tiles/<map>/<map>_block_<row>_<col>.png`. The HUD is hidden, fog turned off and
   the game clock frozen while rendering; all three are restored and the free camera turned off
   at the end.

   Any of these can be given on the command line instead, which beats editing the file while
   tuning:

   ```
   python render_tiles.py --game sly2 --map paris --height 20000 --view 1500 --rows -5 5 --cols 0 8
   python render_tiles.py preview 0 3 --height 20000 --view 1500
   ```

   `--game`, `--map`, `--rows`, `--cols`, `--height`, `--view`, `--near`, `--far`, and
   `--perspective` for the old perspective camera.

2. **Stitch map**: set `MAP` in `build_map.py` and run `python build_map.py`. The block range
   and tile size come from the tile files. Output goes to `complete_maps/`: `<map>.png`,
   `<map>_small.png` (1/4 size) and `<map>_xsmall.png` (1/20 size).

`tiles/` and `complete_maps/` are git-ignored and only kept locally.

## Views

`AXIS` is the world axis the camera sits back along, `HEIGHT` away from the map plane (`DISTANCE`
in perspective)
through the origin:

- **Top-down** (`AXIS = None`, the game's up axis): pitch -90. Sly 1-3 have Z up, so rows are
  +X and columns +Y, as in the existing tiles. Sly 4 / Hackpack have Y up.
- **Side view** (`AXIS` a horizontal axis): pitch 0, looking along +`AXIS`, rows going down.

In Sly 2, Sly 4 and the Hackpack the camera's far distance is set to `2 * HEIGHT` (`2 * DISTANCE` in
perspective) so the map isn't clipped.

## Orthographic mode

The default. Sly 4's engine (and the Hackpack's) can draw a view orthographically, SluMAN makes Sly 1's, 2's and 3's renderer do the same
(through its camera hook, so RPCS3 needs the Interpreter (static) PPU decoder), and SluMAN's camera API exposes it as `ortho=`
(the height the view shows, in world units) and `near=`. Heights no longer shift anything, so a block is one shot of the whole frame minus
`ORTHO_MARGIN` px at each edge (1240x680 at 1280x720) instead of 2x2 crops of 370 px, about 6x
fewer shots for the same area.

- `VIEW` is how much each shot captures, and so the map's scale: `VIEW / 720` world units per
  pixel. A bigger `VIEW` covers a level in fewer blocks at a lower resolution. It doesn't depend
  on `HEIGHT`.
- `HEIGHT` is how far above the map plane the camera sits: put it just above the highest point,
  so the game draws everything up close and loads its textures properly. Everything from `NEAR`
  to `FAR` in front of the camera is drawn, so `FAR` has to reach the lowest point
  (`None` = `2 * HEIGHT`).
- Tune both with `preview` before rendering: `python render_tiles.py preview <row> <col> --height ... --view ...`
  leaves the camera at a block with those settings.
- Tiles aren't square, so block indices cover a different area than perspective tiles. The
  console prints the world size of a block at the start; use a separate `MAP` folder.
- The OBS output must show the game's whole frame at its own aspect ratio (no bars or cropping),
  since the frame's height is what the ortho height is set to. Check with `preview`.
- SluMAN keeps `ortho` set until it's set to 0 (`end_session` does that) or SluMAN restarts.
- In Sly 1 set `NEAR` to about the camera's height above the highest point: the game's culling is fitted to
  the frame from `NEAR` down (from half the ortho height when it's `None`), and opening it further crashes Sly 1.
- In Sly 2 and 3 the game's culling cone is opened to
  everything in front of the camera while orthographic, so everything below it within `FAR` is drawn.

## Presets and calibration

`games.py` holds each game's defaults: `height` and `view` for the orthographic camera, and
`fov` (degrees), `distance` and `step` (world units one 370 px crop covers) for perspective.
Sly 2's perspective values (`fov` 0.1146 = 0.002 rad, `distance` 500000, `step` 510) match the
existing tiles, and its `view` (990) keeps that scale, with `height` a tenth of that distance.
The other games use the same values until calibrated.

If `step` is left out, or `FOV` / `DISTANCE` are overridden in the script, it's worked out as
`2 * distance * tan(fov / 2) * 370 / 720`, assuming the API's fov is vertical.

To calibrate a game, move the camera to a block without capturing:

```
python render_tiles.py preview <row> <col>
```

then check that neighbouring crops line up (adjust `step`) and the orientation is right.
