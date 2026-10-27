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

GAME = Game.SLY2
MAP = "paris"            # name of the output folder under tiles/

# Inclusive block ranges. Rows go down the image, columns go right.
# Top-down in Sly 1-3 that's rows = +X, columns = +Y.
ROWS = (0, 0)
COLS = (0, 0)

# None = use the game's preset from games.py
FOV = None               # degrees
DISTANCE = None          # camera distance from the map plane
STEP = None              # world units per 370 px crop
AXIS = None              # "X", "Y" or "Z" the camera sits back along. None = game's up axis (top-down)

CAPTURE_DEVICE = 3      # OpenCV device index of the OBS Virtual Camera
CAPTURE_WIDTH, CAPTURE_HEIGHT = 1280, 720

# ----------------------------------------------------------------------------

ROOT = os.path.dirname(os.path.abspath(__file__))
TILES_DIR = os.path.join(ROOT, 'tiles')

CROP = 370               # px taken from the centre of each frame; a tile is 2x2 crops
SETTLE_DELAY = 0.1       # s to wait after the API confirms the move before reading frames
SETTLE_TIMEOUT = 3.0     # s to wait for a new, still frame before using the latest one
CHANGED_DIFF = 2.0       # mean pixel difference that counts as "the view moved"
STABLE_DIFF = 1.0        # mean pixel difference that counts as "the view is still"
STABLE_FRAMES = 3        # consecutive still frames needed before a frame is used
UNCHANGED_ACCEPT = 0.5   # s the view may look identical to the last shot (void, water) before it's used; 0 = off
BUFFERED_READ = 0.01     # s; a read faster than this came from the capture buffer, not a new frame
SET_RETRIES = 5


def resolve_settings(frame_height):
    preset = PRESETS[GAME]
    fov = FOV if FOV is not None else preset.fov
    distance = DISTANCE if DISTANCE is not None else preset.distance
    axis = AXIS if AXIS is not None else preset.axis
    if STEP is not None:
        step = STEP
    elif preset.step is not None and FOV is None and DISTANCE is None:
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
            self.far = self.distance * 2
        self.prev_crop = None
        print(f"{GAME.name} (up {self.up}): fov {self.fov}, distance {self.distance}, step {self.step:.2f}, "
              f"yaw {self.yaw}, pitch {self.pitch}")

    def shot_position(self, row, col):
        """Camera position for shot (row, col) in crop units: a block is 2x2 shots."""
        point = row * self.step * self.down + col * self.step * self.right
        return point - self.forward * self.distance

    def place_camera(self, row, col):
        x, y, z = self.shot_position(row, col)
        for attempt in range(SET_RETRIES):
            try:
                cam = freecam_api.set_camera(x, y, z, self.yaw, self.pitch, self.fov, self.far)
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
        cy, cx = frame.shape[0] // 2, frame.shape[1] // 2
        return frame[cy - CROP // 2:cy + CROP // 2, cx - CROP // 2:cx + CROP // 2]

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
        changed = self.prev_crop is None
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
                elif UNCHANGED_ACCEPT > 0 and time.time() - unchanged_since >= UNCHANGED_ACCEPT:
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
        img = np.zeros((2 * CROP, 2 * CROP, 3), dtype=np.uint8)
        for x_idx in range(0, 2):
            for y_idx in range(0, 2):
                self.place_camera(2 * bix + x_idx, 2 * biy + y_idx)
                img[x_idx*CROP:(x_idx+1)*CROP, y_idx*CROP:(y_idx+1)*CROP] = self.settled_crop()
        cv.imwrite(f'{TILES_DIR}/{MAP}/{MAP}_block_{bix}_{biy}.png', img)

    def move_to_block(self, bix, biy):
        self.place_camera(2 * bix, 2 * biy)


def start_session():
    for request, call in (("Hide HUD", lambda: freecam_api.set_hud(True)),
                          ("No fog", lambda: freecam_api.set_fog(True)),
                          ("Freeze clock", lambda: freecam_api.set_clock(True))):
        try:
            call()
        except ApiError as e:
            print(f"{request} not available: {e}")


def end_session():
    for call in (lambda: freecam_api.set_hud(False), lambda: freecam_api.set_fog(False),
                 lambda: freecam_api.set_clock(False), freecam_api.camera_off):
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
