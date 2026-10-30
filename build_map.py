import cv2 as cv
import numpy as np
import os
import re
import struct
import zlib

MAP = "japan"

ROOT = os.path.dirname(os.path.abspath(__file__))
TILES_DIR = os.path.join(ROOT, 'tiles')
OUTPUT_DIR = os.path.join(ROOT, 'complete_maps')

PNG_COMPRESSION = 6      # zlib level 0-9; higher is smaller but slower
DOWNSCALES = {'small': 4, 'xsmall': 20}

class PngWriter:
    """Writes an RGB PNG a strip of rows at a time, so the whole image is never in memory."""

    def __init__(self, path, width, height):
        try:
            self.file = open(path, 'wb')
        except OSError as e:
            # Windows can't overwrite a file another program has open (errno 13 or, if it's mapped, 22)
            raise OSError(f"Can't write {path} ({e.strerror}). Is it open in an image viewer?") from e
        self.compressor = zlib.compressobj(PNG_COMPRESSION)
        self.file.write(b'\x89PNG\r\n\x1a\n')
        self._chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))

    def _chunk(self, kind, data):
        self.file.write(struct.pack('>I', len(data)) + kind + data)
        self.file.write(struct.pack('>I', zlib.crc32(data, zlib.crc32(kind))))

    def write_rows(self, bgr):
        rgb = bgr[:, :, ::-1].reshape(bgr.shape[0], -1)
        # Each row starts with filter type 1 (Sub): every byte minus the same channel one pixel left
        rows = np.empty((rgb.shape[0], rgb.shape[1] + 1), dtype=np.uint8)
        rows[:, 0] = 1
        rows[:, 1:] = rgb
        rows[:, 4:] -= rgb[:, :-3]
        data = self.compressor.compress(rows.tobytes())
        if data:
            self._chunk(b'IDAT', data)

    def close(self):
        self._chunk(b'IDAT', self.compressor.flush())
        self._chunk(b'IEND', b'')
        self.file.close()

def find_blocks(curr_map):
    pattern = re.compile(rf'^{re.escape(curr_map)}_block_(-?\d+)_(-?\d+)\.png$')
    blocks = []
    for name in os.listdir(f'{TILES_DIR}/{curr_map}'):
        match = pattern.match(name)
        if match:
            blocks.append((int(match.group(1)), int(match.group(2))))
    return blocks

def build_map(curr_map=MAP):

    blocks = find_blocks(curr_map)
    if not blocks:
        print(f"No tiles found in {TILES_DIR}/{curr_map}")
        return
    xmin, xmax = min(b[0] for b in blocks), max(b[0] for b in blocks)
    ymin, ymax = min(b[1] for b in blocks), max(b[1] for b in blocks)
    # Orthographic tiles are as wide as the frame, so not square
    tile_h, tile_w = cv.imread(f'{TILES_DIR}/{curr_map}/{curr_map}_block_{blocks[0][0]}_{blocks[0][1]}.png').shape[:2]
    print(f"Blocks x={xmin}..{xmax}, y={ymin}..{ymax}, tile size {tile_w}x{tile_h}px")

    rows = (xmax+1) - xmin
    ysize = ((ymax+1) - ymin) * tile_w
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    # The map is built and written one row of blocks at a time, along with its downscaled versions
    writers = {}
    missing_blocks_str = ""
    try:
        writers[''] = PngWriter(f'{OUTPUT_DIR}/{curr_map}.png', ysize, rows * tile_h)
        for suffix, factor in DOWNSCALES.items():
            writers[suffix] = PngWriter(f'{OUTPUT_DIR}/{curr_map}_{suffix}.png', ysize // factor, rows * (tile_h // factor))
        for bix in range(xmin, xmax+1):
            strip = np.zeros((tile_h, ysize, 3), dtype=np.uint8)
            for biy in range(ymin, ymax+1):
                # check if file exists
                if not os.path.exists(f'{TILES_DIR}/{curr_map}/{curr_map}_block_{bix}_{biy}.png'):
                    missing_blocks_str += f"({bix},{biy}),"
                    continue
                img_part = cv.imread(f'{TILES_DIR}/{curr_map}/{curr_map}_block_{bix}_{biy}.png')
                strip[:, (biy-ymin)*tile_w:(biy-ymin+1)*tile_w] = img_part
            writers[''].write_rows(strip)
            for suffix, factor in DOWNSCALES.items():
                writers[suffix].write_rows(cv.resize(strip, (ysize // factor, tile_h // factor), interpolation=cv.INTER_AREA))
            print(f"Row {bix - xmin + 1}/{rows} written")
    except BaseException:
        for writer in writers.values():
            writer.file.close()
        raise
    for writer in writers.values():
        writer.close()
    if missing_blocks_str:
        print(f"Missing blocks found: {missing_blocks_str[:-1]}")

def build_tile_index(curr_map=MAP, cell=160):
    """Writes a low-res map with a grid and each tile's (bix,biy) label, for finding tiles to re-render."""
    blocks = find_blocks(curr_map)
    if not blocks:
        print(f"No tiles found in {TILES_DIR}/{curr_map}")
        return
    xmin, xmax = min(b[0] for b in blocks), max(b[0] for b in blocks)
    ymin, ymax = min(b[1] for b in blocks), max(b[1] for b in blocks)
    # Same layout as build_map: bix runs down the rows, biy across the columns
    img = np.full(((xmax+1-xmin) * cell, (ymax+1-ymin) * cell, 3), 40, dtype=np.uint8)
    for bix, biy in blocks:
        # Reduced decode keeps reading the full-res tiles fast
        tile = cv.imread(f'{TILES_DIR}/{curr_map}/{curr_map}_block_{bix}_{biy}.png', cv.IMREAD_REDUCED_COLOR_4)
        y0, x0 = (bix-xmin) * cell, (biy-ymin) * cell
        img[y0:y0+cell, x0:x0+cell] = cv.resize(tile, (cell, cell), interpolation=cv.INTER_AREA)

    present = set(blocks)
    font, scale, thick = cv.FONT_HERSHEY_SIMPLEX, cell / 320, max(1, cell // 120)
    for bix in range(xmin, xmax+1):
        for biy in range(ymin, ymax+1):
            y0, x0 = (bix-xmin) * cell, (biy-ymin) * cell
            cv.rectangle(img, (x0, y0), (x0+cell-1, y0+cell-1), (0, 255, 255), 1)
            label = f"{bix},{biy}"
            color = (255, 255, 255) if (bix, biy) in present else (80, 80, 255)
            # Dark outline under the text so it stays readable on any background
            cv.putText(img, label, (x0+4, y0+4+int(22*scale)), font, scale, (0, 0, 0), thick+2, cv.LINE_AA)
            cv.putText(img, label, (x0+4, y0+4+int(22*scale)), font, scale, color, thick, cv.LINE_AA)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = f'{OUTPUT_DIR}/{curr_map}_index.png'
    if not cv.imwrite(path, img):
        raise OSError(f"Can't write {path}. Is it open in an image viewer?")
    print(f"Tile index written to {path}")

if __name__ == "__main__":
    build_map()
    build_tile_index()
