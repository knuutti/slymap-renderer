import cv2 as cv
import numpy as np
import os
import re

MAP = "china_new"

ROOT = os.path.dirname(os.path.abspath(__file__))
TILES_DIR = os.path.join(ROOT, 'tiles')
OUTPUT_DIR = os.path.join(ROOT, 'complete_maps')

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
    tile = cv.imread(f'{TILES_DIR}/{curr_map}/{curr_map}_block_{blocks[0][0]}_{blocks[0][1]}.png').shape[0]
    print(f"Blocks x={xmin}..{xmax}, y={ymin}..{ymax}, tile size {tile}px")

    xsize = ((xmax+1) - xmin) * tile
    ysize = ((ymax+1) - ymin) * tile
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    img = np.zeros((xsize, ysize, 3), dtype=np.uint8)
    missing_blocks_str = ""
    for bix in range(xmin, xmax+1):
        for biy in range(ymin, ymax+1):
            # check if file exists
            if not os.path.exists(f'{TILES_DIR}/{curr_map}/{curr_map}_block_{bix}_{biy}.png'):
                missing_blocks_str += f"({bix},{biy}),"
                continue
            img_part = cv.imread(f'{TILES_DIR}/{curr_map}/{curr_map}_block_{bix}_{biy}.png')
            img[(bix-xmin)*tile:(bix-xmin+1)*tile, (biy-ymin)*tile:(biy-ymin+1)*tile] = img_part
    cv.imwrite(f'{OUTPUT_DIR}/{curr_map}.png', img)
    if missing_blocks_str:
        print(f"Missing blocks found: {missing_blocks_str[:-1]}")

    # downscaled version
    img_small = cv.resize(img, (ysize//4, xsize//4), interpolation=cv.INTER_AREA)
    cv.imwrite(f'{OUTPUT_DIR}/{curr_map}_small.png', img_small)
    img_small = cv.resize(img, (ysize//20, xsize//20), interpolation=cv.INTER_AREA)
    cv.imwrite(f'{OUTPUT_DIR}/{curr_map}_xsmall.png', img_small)

if __name__ == "__main__":
    build_map()
