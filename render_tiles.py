import math
import os
import sys
import time

import cv2 as cv
import numpy as np

import freecam_api
from freecam_api import ApiError, GameRefused
from games import Game, PRESETS

# --- Settings ---------------------------------------------------------------

GAME = Game.SLY4
MAP = "japan"            # name of the output folder under tiles/

# Inclusive block ranges. Rows go down the image, columns go right.
# Top-down in Sly 1-3 that's rows = +X, columns = +Y.
ROWS = (-13, 13)
COLS = (11, 19)
# Render only these blocks instead of ROWS x COLS, e.g. build_map.py's "Missing blocks found"
# list pasted between the brackets: [(1,2),(3,4)]. None = use ROWS and COLS.
BLOCKS = None

# None = use the game's preset from games.py
FOV = None               # degrees
DISTANCE = None          # camera distance from the map plane
STEP = None              # world units per 370 px crop
AXIS = None              # "X", "Y" or "Z" the camera sits back along. None = game's up axis (top-down)

# Orthographic camera (every game, needs SluMAN with the camera API's ortho=). A block is then one
# shot of nearly the whole frame instead of 2x2 centre crops, and heights don't shift anything.
# The camera sits DISTANCE from the map plane, so put it just above the highest point. The scale
# stays STEP world units per 370 px.
ORTHO = False
ORTHO_MARGIN = 20        # px left out at each edge of the frame
NEAR = None              # near distance in ortho mode. None = the game's
FAR = None               # far distance in games that have one. None = 2 * DISTANCE

CAPTURE_DEVICE = 1      # OpenCV device index of the OBS Virtual Camera
CAPTURE_WIDTH, CAPTURE_HEIGHT = 1280, 720

# ----------------------------------------------------------------------------

ROOT = os.path.dirname(os.path.abspath(__file__))
TILES_DIR = os.path.join(ROOT, 'tiles')

CROP = 370               # px taken from the centre of each frame in perspective; a tile is 2x2 crops
SETTLE_DELAY = 0.2       # s to wait after the API confirms the move before reading frames
SETTLE_TIMEOUT = 1.0     # s to wait for a new, still frame before using the latest one
CHANGED_DIFF = 2.0       # mean pixel difference that counts as "the view moved"
STABLE_DIFF = 1.0        # mean pixel difference that counts as "the view is still"
STABLE_FRAMES = 3        # consecutive still frames needed before a frame is used
# s the view may look identical to the last shot (void, water) before it's used.
# 0 = don't wait for the view to change at all, only for it to hold still. None = always wait for a change.
UNCHANGED_ACCEPT = 0.5
BUFFERED_READ = 0.01     # s; a read faster than this came from the capture buffer, not a new frame
SET_RETRIES = 3
START_DELAY = 0.5        # s to wait at the first block's position before the first capture


def resolve_settings(frame_height):
    preset = PRESETS[GAME]
    fov = FOV if FOV is not None else preset.fov
    distance = DISTANCE if DISTANCE is not None else preset.distance
    axis = AXIS if AXIS is not None else preset.axis
    if STEP is not None:
        step = STEP
    elif preset.step is not None and (ORTHO or (FOV is None and DISTANCE is None)):
        # In ortho mode the scale doesn't depend on the camera, so the preset's resolution is kept
        step = preset.step
    else:
        # Assumes fov is vertical: the frame's height covers 2 * distance * tan(fov / 2)
        step = 2 * distance * math.tan(math.radians(fov) / 2) * CROP / frame_height
    return fov, distance, step, axis


def view_basis(up, yaw, pitch):
    """Forward, screen-right and screen-down world vectors for a camera, per the API's conventions."""
    y, p = math.radians(yaw), math.radians(pitch)
    if up == "Z":
        forward = np.array([math.cos(p) * math.cos(y), math.cos(p) * math.sin(y), math.sin(p)])
        screen_up = np.array([-math.sin(p) * math.cos(y), -math.sin(p) * math.sin(y), math.cos(p)])
    else:
        forward = np.array([math.cos(p) * math.sin(y), math.sin(p), math.cos(p) * math.cos(y)])
        screen_up = np.array([-math.sin(p) * math.sin(y), math.cos(p), -math.sin(p) * math.cos(y)])
    right = np.cross(forward, screen_up)
    return forward.round(12), right.round(12), -screen_up.round(12)


def view_angles(up, axis):
    """Yaw and pitch for a camera sitting back along `axis`, looking at the map plane."""
    if axis is None or axis == up:
        # Top-down. Sly 1-3: rows = +X, columns = +Y, as in the existing tiles.
        return (180.0 if up == "Z" else -90.0), -90.0
    # Side view, looking along +axis with the up axis up
    yaws = {("Z", "X"): 0.0, ("Z", "Y"): 90.0, ("Y", "X"): 90.0, ("Y", "Z"): 0.0}
    if (up, axis) not in yaws:
        raise ValueError(f"Axis {axis} doesn't work with up axis {up}")
    return yaws[(up, axis)], 0.0


class Renderer:

    def __init__(self, capture):
        self.capture = capture
        self.up = freecam_api.up_axis()
        self.far = None
        self.fov, self.distance, self.step, axis = resolve_settings(CAPTURE_HEIGHT)
        self.yaw, self.pitch = view_angles(self.up, axis)
        self.forward, self.right, self.down = view_basis(self.up, self.yaw, self.pitch)
        if freecam_api.supports_far():
            self.far = FAR if FAR is not None else self.distance * 2
        self.ortho = None
        self.near = None
        if ORTHO:
            if not freecam_api.supports_ortho():
                raise RuntimeError("This game's free camera can't be orthographic (or SluMAN is too old for ortho=)")
            units_per_px = self.step / CROP
            # The frame shows the ortho height top to bottom; the width follows the game's aspect ratio
            self.ortho = CAPTURE_HEIGHT * units_per_px
            self.near = NEAR
            self.shot_h = CAPTURE_HEIGHT - 2 * ORTHO_MARGIN
            self.shot_w = CAPTURE_WIDTH - 2 * ORTHO_MARGIN
            self.shots = 1
            self.row_step = self.shot_h * units_per_px
            self.col_step = self.shot_w * units_per_px
        else:
            self.shot_h = self.shot_w = CROP
            self.shots = 2
            self.row_step = self.col_step = self.step
        self.prev_crop = None
        print(f"{GAME.name} (up {self.up}): fov {self.fov}, distance {self.distance}, step {self.step:.2f}, "
              f"yaw {self.yaw}, pitch {self.pitch}")
        if self.ortho:
            print(f"Orthographic: {self.ortho:.2f} units top to bottom, near {self.near}, far {self.far}")
        print(f"A block is {self.shots * self.shot_w}x{self.shots * self.shot_h} px, "
              f"{self.shots * self.col_step:.2f} x {self.shots * self.row_step:.2f} world units")

    def shot_position(self, row, col):
        """Camera position for shot (row, col): a block is shots x shots of them."""
        point = row * self.row_step * self.down + col * self.col_step * self.right
        return point - self.forward * self.distance

    def place_camera(self, row, col):
        x, y, z = self.shot_position(row, col)
        for attempt in range(SET_RETRIES):
            try:
                cam = freecam_api.set_camera(x, y, z, self.yaw, self.pitch, self.fov, self.far, self.ortho, self.near)
                if cam["on"] and all(abs(cam[k] - v) <= max(1.0, 1e-5 * abs(v))
                                     for k, v in (("x", x), ("y", y), ("z", z))):
                    return
                print(f"  Camera not where it was sent (on={cam['on']}), retrying")
            except GameRefused as e:
                print(f"  Game refused: {e}. Retrying")
            time.sleep(1)
        raise RuntimeError(f"Couldn't place the camera at {x:.1f},{y:.1f},{z:.1f}")

    def read_crop(self):
        ok, frame = self.capture.read()
        if not ok:
            raise RuntimeError("Capture device returned no frame (is the OBS Virtual Camera running?)")
        top = (frame.shape[0] - self.shot_h) // 2
        left = (frame.shape[1] - self.shot_w) // 2
        return frame[top:top + self.shot_h, left:left + self.shot_w]

    def drain_buffer(self):
        """Throw away frames the capture backend buffered before the camera moved."""
        for _ in range(30):
            start = time.time()
            if not self.capture.grab():
                break
            if time.time() - start > BUFFERED_READ:
                break  # had to wait for a fresh frame, so the buffer is empty

    def settled_crop(self):
        """Wait until the view differs from the last shot and then holds still for a few frames."""
        time.sleep(SETTLE_DELAY)
        self.drain_buffer()
        start = time.time()
        changed = self.prev_crop is None or UNCHANGED_ACCEPT == 0
        last = None
        still = 0
        unchanged_since = start
        while True:
            crop = self.read_crop()
            if not changed:
                diff = np.mean(cv.absdiff(crop, self.prev_crop))
                changed = diff > CHANGED_DIFF
                if diff >= STABLE_DIFF:
                    unchanged_since = time.time()
                elif UNCHANGED_ACCEPT is not None and time.time() - unchanged_since >= UNCHANGED_ACCEPT:
                    # The clock is frozen, so a view that stays identical to the last shot
                    # most likely just looks the same from here
                    break
            elif last is not None:
                still = still + 1 if np.mean(cv.absdiff(crop, last)) < STABLE_DIFF else 0
                if still >= STABLE_FRAMES:
                    break
            if time.time() - start > SETTLE_TIMEOUT:
                # Flat areas (water, void) can look the same from shot to shot
                print("  Frame didn't settle, using the latest one")
                break
            last = crop if changed else None
        self.prev_crop = crop
        return crop

    def render_block(self, bix, biy):
        os.makedirs(f'{TILES_DIR}/{MAP}', exist_ok=True)
        n, h, w = self.shots, self.shot_h, self.shot_w
        img = np.zeros((n * h, n * w, 3), dtype=np.uint8)
        for x_idx in range(n):
            for y_idx in range(n):
                self.place_camera(n * bix + x_idx, n * biy + y_idx)
                img[x_idx*h:(x_idx+1)*h, y_idx*w:(y_idx+1)*w] = self.settled_crop()
        cv.imwrite(f'{TILES_DIR}/{MAP}/{MAP}_block_{bix}_{biy}.png', img)

    def move_to_block(self, bix, biy):
        self.place_camera(self.shots * bix, self.shots * biy)


def start_session():
    for request, call in (("Hide HUD", lambda: freecam_api.set_hud(True)),
                          ("No fog", lambda: freecam_api.set_fog(True)),
                          ("Freeze clock", lambda: freecam_api.set_clock(True))):
        try:
            call()
        except ApiError as e:
            print(f"{request} not available: {e}")


def end_session():
    # SluMAN keeps ortho set until it's turned off, also for the Camera tab
    reset_ortho = (lambda: freecam_api.get("/camera/set", ortho=0)) if ORTHO else (lambda: None)
    for call in (lambda: freecam_api.set_hud(False), lambda: freecam_api.set_fog(False),
                 lambda: freecam_api.set_clock(False), reset_ortho, freecam_api.camera_off):
        try:
            call()
        except ApiError as e:
            print(f"Cleanup failed: {e}")


def main():
    capture = cv.VideoCapture(CAPTURE_DEVICE)
    capture.set(cv.CAP_PROP_FRAME_WIDTH, CAPTURE_WIDTH)
    capture.set(cv.CAP_PROP_FRAME_HEIGHT, CAPTURE_HEIGHT)
    capture.set(cv.CAP_PROP_BUFFERSIZE, 0)

    if BLOCKS is not None:
        blocks_to_render = list(BLOCKS)
    else:
        blocks_to_render = [(x, y) for x in range(ROWS[0], ROWS[1] + 1) for y in range(COLS[0], COLS[1] + 1)]

    start_session()
    try:
        renderer = Renderer(capture)
        total_blocks = len(blocks_to_render)
        print(f"Total blocks to render: {total_blocks}")
        if blocks_to_render:
            # Give the game time to load and draw the first view before anything is captured
            renderer.move_to_block(*blocks_to_render[0])
            time.sleep(START_DELAY)
        start_time = time.time()
        block_count = 0
        for block in blocks_to_render:
            print(f"Rendering block {block[0]},{block[1]}")
            renderer.render_block(block[0], block[1])
            block_count += 1
            elapsed_time = time.time() - start_time
            print(f"Progress: {block_count}/{total_blocks} blocks rendered. Estimated time left: {((elapsed_time / block_count) * (total_blocks - block_count)) / 60:.2f} minutes")
    finally:
        # end_session()
        capture.release()


def preview(bix, biy):
    """Move the camera to a block with the current settings, without capturing."""
    start_session()
    Renderer(capture=None).move_to_block(bix, biy)
    print("Camera left in place. Run without arguments to render, or turn the camera off in SluMAN.")


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "preview":
        preview(int(sys.argv[2]), int(sys.argv[3]))
    else:
        main()
