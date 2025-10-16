#!/usr/bin/env python3
"""
manual_highlight_autotune.py

Single-file tool to map a flat polygon and auto-tune translation to align with dark text.

Requirements:
    pip install pillow numpy

Usage:
    python manual_highlight_autotune.py

Edit IMAGE_PATH and POLYGON_FLAT below as needed.
"""

from pathlib import Path
from io import BytesIO
from typing import List, Tuple, Optional
from PIL import Image, ImageDraw, ImageStat, ImageOps
import numpy as np

# -----------------------------
# Config - edit these
# -----------------------------
IMAGE_PATH = Path(r"C:\Users\SAHUAX19\Documents\page_1.png")   # image path
POLYGON_FLAT = [
                                        3.2662,
                                        1.8396,
                                        5.7788,
                                        1.83,
                                        5.7801,
                                        2.1552,
                                        3.2675,
                                        2.1649
                                    ]  # flat list
# whether to run automatic translation tuning (True recommended)
AUTO_TUNE = True
# grid search radius (pixels) and step - tuning range; keep small for speed
TUNE_RADIUS = 80    # test offsets in [-R, R]
TUNE_STEP = 8       # step between offsets
# manual fudge factors if you want to change the initial scaling
MANUAL_SCALE_X = 1.0
MANUAL_SCALE_Y = 1.0

# visual style
FILL_COLOR = (255, 255, 0, 160)   # semi-transparent yellow
OUTLINE_COLOR = (255, 0, 0, 220)  # red outline
OUTLINE_WIDTH = 3

# output file
OUTPUT_PATH = IMAGE_PATH.with_name(IMAGE_PATH.stem + "_highlighted_autotuned.png")
OVERLAY_PATH = IMAGE_PATH.with_name(IMAGE_PATH.stem + "_overlay_autotuned.png")


# -----------------------------
# Helpers
# -----------------------------
def flat_to_pairs(flat: List[float]) -> List[Tuple[float, float]]:
    if len(flat) % 2 != 0:
        raise ValueError("Flat polygon list must have even number of entries (x,y pairs).")
    return [(float(flat[i]), float(flat[i + 1])) for i in range(0, len(flat), 2)]


def compute_auto_scale(poly_pairs: List[Tuple[float, float]], img_size: Tuple[int, int]) -> Tuple[float, float]:
    w, h = img_size
    xs = [abs(x) for x, _ in poly_pairs]
    ys = [abs(y) for _, y in poly_pairs]
    max_x = max(xs) if xs else 1.0
    max_y = max(ys) if ys else 1.0
    if max_x <= 1.0 and max_y <= 1.0:
        sx = w
        sy = h
    else:
        sx = w / max_x
        sy = h / max_y
    return sx * MANUAL_SCALE_X, sy * MANUAL_SCALE_Y


def map_and_flip(poly_pairs: List[Tuple[float, float]], img_size: Tuple[int,int], sx: float, sy: float) -> List[Tuple[int,int]]:
    w, h = img_size
    mapped = []
    for x,y in poly_pairs:
        px = x * sx
        py = y * sy
        # flip Y (PDF bottom-left -> image top-left)
        py_flipped = h - py
        mapped.append((int(round(px)), int(round(py_flipped))))
    # clamp
    mapped_clamped = [(max(0,min(w-1,xx)), max(0,min(h-1,yy))) for xx,yy in mapped]
    return mapped_clamped


def polygon_to_mask(poly: List[Tuple[int,int]], img_size: Tuple[int,int]) -> Image.Image:
    """Return a binary (L) mask with polygon filled white."""
    mask = Image.new("L", img_size, 0)
    draw = ImageDraw.Draw(mask)
    draw.polygon(poly, fill=255)
    return mask


def score_mask_on_image(mask: Image.Image, gray_img: Image.Image) -> float:
    """
    Compute score: sum of (darkness) under mask.
    We'll compute inverted brightness so dark text => higher score.
    """
    # convert to numpy arrays for speed
    m = np.asarray(mask, dtype=np.uint8) / 255.0        # 0..1
    g = np.asarray(gray_img, dtype=np.uint8) / 255.0   # 0..1 brightness
    # darkness = (1 - brightness), zero where mask=0
    darkness = (1.0 - g) * m
    return float(darkness.sum())


def translate_polygon(poly: List[Tuple[int,int]], tx: int, ty: int) -> List[Tuple[int,int]]:
    return [(x + tx, y + ty) for x,y in poly]


def draw_and_save(img: Image.Image, mapped_poly: List[Tuple[int,int]], out_path: Path, overlay_only: bool=False):
    overlay = Image.new("RGBA", img.size, (255,255,255,0))
    draw = ImageDraw.Draw(overlay)
    draw.polygon(mapped_poly, fill=FILL_COLOR)
    draw.line(list(mapped_poly) + [mapped_poly[0]], width=OUTLINE_WIDTH, fill=OUTLINE_COLOR)
    if overlay_only:
        out_img = overlay
    else:
        out_img = Image.alpha_composite(img.convert("RGBA"), overlay)
    out_img.save(out_path, format="PNG", compress_level=1, optimize=True)


# -----------------------------
# Main routine
# -----------------------------
def main():
    if not IMAGE_PATH.exists():
        print("ERROR: image not found:", IMAGE_PATH)
        return

    img = Image.open(IMAGE_PATH)
    w,h = img.size
    print("Image size:", (w,h))

    poly_pairs = flat_to_pairs(POLYGON_FLAT)
    print("Original polygon pairs (units):", poly_pairs)

    sx, sy = compute_auto_scale(poly_pairs, (w,h))
    print(f"Auto scale: sx={sx:.3f}, sy={sy:.3f}")

    mapped = map_and_flip(poly_pairs, (w,h), sx, sy)
    print("Mapped pixel coords (before tune):", mapped)

    # quick bbox info
    xs = [p[0] for p in mapped]; ys = [p[1] for p in mapped]
    bbox_w = max(xs)-min(xs) if xs else 0
    bbox_h = max(ys)-min(ys) if ys else 0
    print(f"BBox px: w={bbox_w}, h={bbox_h}")

    # if bbox tiny, amplify so visible (visual-only, not used for scoring)
    if bbox_w < 10 or bbox_h < 10:
        # amplify by factor so min dimension ~ 40 px
        target = 40
        amp = max(target/max(1,bbox_w), target/max(1,bbox_h))
        print(f"Auto-amplify by {amp:.2f} for visibility")
        cx = sum(xs)/len(xs)
        cy = sum(ys)/len(ys)
        mapped = [ (int(round((x-cx)*amp + cx)), int(round((y-cy)*amp + cy))) for x,y in mapped ]
        mapped = [ (max(0,min(w-1,x)), max(0,min(h-1,y))) for x,y in mapped ]
        xs = [p[0] for p in mapped]; ys=[p[1] for p in mapped]
        bbox_w = max(xs)-min(xs); bbox_h = max(ys)-min(ys)
        print("Mapped pixel coords (after amplify):", mapped)
        print(f"New bbox px: w={bbox_w}, h={bbox_h}")

    # Prepare gray image for scoring (normalize 0..1 brightness)
    gray = ImageOps.grayscale(img)

    # Auto-tune small translations by maximizing dark pixel coverage under polygon mask
    best_tx, best_ty, best_score = 0,0,-1.0
    if AUTO_TUNE:
        print(f"Auto-tuning translation in radius {TUNE_RADIUS} step {TUNE_STEP} ...")
        # base mask for mapped polygon (without translation)
        base_poly = mapped
        # precompute center offsets to search around
        txs = list(range(-TUNE_RADIUS, TUNE_RADIUS+1, TUNE_STEP))
        tys = list(range(-TUNE_RADIUS, TUNE_RADIUS+1, TUNE_STEP))
        # limit total combos for speed
        max_iters = len(txs)*len(tys)
        print(f"Testing {max_iters} translations ...")
        # do the brute force search
        for tx in txs:
            for ty in tys:
                test_poly = translate_polygon(base_poly, tx, ty)
                # make mask
                mask = polygon_to_mask(test_poly, (w,h))
                sc = score_mask_on_image(mask, gray)
                if sc > best_score:
                    best_score = sc
                    best_tx = tx
                    best_ty = ty
        print("Best translation:", best_tx, best_ty, "score:", best_score)
        mapped = translate_polygon(mapped, best_tx, best_ty)

    # Save overlay and final image
    draw_and_save(img, mapped, OUTPUT_PATH, overlay_only=False)
    draw_and_save(img, mapped, OVERLAY_PATH, overlay_only=True)
    print("Saved highlighted:", OUTPUT_PATH)
    print("Saved overlay-only (transparent background):", OVERLAY_PATH)

    # print final mapped coords
    print("Final mapped polygon (px):", mapped)
    print("Done.")

if __name__ == "__main__":
    main()
