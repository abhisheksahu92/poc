#!/usr/bin/env python3
"""
manual_highlight_fixed.py

Reads a local image, maps a flat polygon (small numeric coords) into image pixel space,
applies a semi-transparent highlight + outline, and writes highlighted PNG.

Edit POLYGON_FLAT or MANUAL_SCALE if you need to tweak placement.
"""

from pathlib import Path
from io import BytesIO
from typing import List, Tuple
from PIL import Image, ImageDraw

# ---------------------------
# Configuration (edit if needed)
# ---------------------------
IMAGE_PATH = Path(r"C:\Users\SAHUAX19\Documents\page_1.png")
# Flat polygon coordinates (from your JSON / screenshot)
POLYGON_FLAT = [3.2742, 1.5965, 5.7768, 1.5991, 5.7766, 1.8248, 3.274, 1.8221]

# If auto-scaling is close but needs manual tweak, set MANUAL_SCALE >0 (1.0 = no change)
MANUAL_SCALE = 1.0

# Output file
OUTPUT_PATH = IMAGE_PATH.with_name(IMAGE_PATH.stem + "_highlighted_fixed.png")

# Visual style
FILL_COLOR = (255, 255, 0, 160)   # semi-transparent yellow
OUTLINE_COLOR = (255, 0, 0, 220)  # red outline
OUTLINE_WIDTH = 4


# ---------------------------
# Helpers
# ---------------------------
def flat_to_pairs(flat: List[float]) -> List[Tuple[float, float]]:
    if len(flat) % 2 != 0:
        raise ValueError("Flat polygon list must contain even number of entries (x,y pairs).")
    return [(float(flat[i]), float(flat[i + 1])) for i in range(0, len(flat), 2)]


def compute_auto_scale(poly_pairs: List[Tuple[float, float]], img_size: Tuple[int, int]) -> Tuple[float, float]:
    """
    Compute scale factors from polygon coordinate units -> image pixels.

    Strategy:
    - If max coords are <= 1.0 → likely normalized (0..1) → sx = width, sy = height
    - Else compute sx = width / max_x, sy = height / max_y (maps largest coordinate to image edge).
      This yields visible footprint; we then apply MANUAL_SCALE to dial placement.
    """
    width, height = img_size
    xs = [abs(x) for x, _ in poly_pairs]
    ys = [abs(y) for _, y in poly_pairs]
    max_x = max(xs) if xs else 1.0
    max_y = max(ys) if ys else 1.0

    if max_x <= 1.0 and max_y <= 1.0:
        # normalized coords
        sx = width
        sy = height
    else:
        sx = width / max_x
        sy = height / max_y

    return sx, sy


def map_and_flip(poly_pairs: List[Tuple[float, float]], img_size: Tuple[int,int], sx: float, sy: float, manual_scale: float=1.0) -> List[Tuple[int,int]]:
    """
    Apply scale, manual multiplier and vertical flip (PDF->image).
    Returns integer pixel pairs clamped to image bounds.
    """
    w, h = img_size
    mapped = []
    for x, y in poly_pairs:
        px = x * sx * manual_scale
        py = y * sy * manual_scale
        # flip y coordinate: PDF origin bottom-left -> image top-left
        py_flipped = h - py
        # clamp
        px_i = max(0, min(w - 1, int(round(px))))
        py_i = max(0, min(h - 1, int(round(py_flipped))))
        mapped.append((px_i, py_i))
    return mapped


def draw_highlight_on_image(img_path: Path, mapped_polygon: List[Tuple[int,int]], out_path: Path):
    img = Image.open(img_path).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (255,255,255,0))
    draw = ImageDraw.Draw(overlay)
    draw.polygon(mapped_polygon, fill=FILL_COLOR)
    # draw outline (close path by adding first point)
    draw.line(list(mapped_polygon) + [mapped_polygon[0]], width=OUTLINE_WIDTH, fill=OUTLINE_COLOR)
    merged = Image.alpha_composite(img, overlay)
    merged.save(out_path, format="PNG", compress_level=1, optimize=True)
    return out_path


# ---------------------------
# Main
# ---------------------------
def main():
    print("Manual highlight fixer — using auto-scaling and optional manual multiplier")
    if not IMAGE_PATH.exists():
        print(f"ERROR: image not found: {IMAGE_PATH}")
        return

    # open image to get dimensions
    with Image.open(IMAGE_PATH) as tmp:
        w, h = tmp.size
    print(f"Image size: {w} x {h}")

    poly_pairs = flat_to_pairs(POLYGON_FLAT)
    print("Original polygon pairs:", poly_pairs)

    sx, sy = compute_auto_scale(poly_pairs, (w,h))
    print(f"Auto scale factors -> sx: {sx:.3f}, sy: {sy:.3f} (before manual multiplier)")

    # apply manual scale multiplier
    sx *= MANUAL_SCALE
    sy *= MANUAL_SCALE
    if MANUAL_SCALE != 1.0:
        print(f"Applying MANUAL_SCALE={MANUAL_SCALE} -> sx: {sx:.3f}, sy: {sy:.3f}")

    mapped = map_and_flip(poly_pairs, (w,h), sx, sy, manual_scale=1.0)
    print("Mapped pixel coords (after flip):", mapped)

    # If mapped polygon is extremely small (e.g. all coords within a few pixels), upscale further
    xs = [p[0] for p in mapped]
    ys = [p[1] for p in mapped]
    bbox_w = (max(xs) - min(xs)) if xs else 0
    bbox_h = (max(ys) - min(ys)) if ys else 0
    print(f"Polygon bbox in pixels: width={bbox_w}, height={bbox_h}")
    if bbox_w < 10 or bbox_h < 10:
        # amplify mapping to make it visible
        amplify = max(10 / max(1,bbox_w), 10 / max(1,bbox_h))
        print(f"Auto-amplifying polygon by ~{amplify:.2f} to make visible")
        # re-map with amplification centered around polygon centroid
        cx = sum(xs)/len(xs)
        cy = sum(ys)/len(ys)
        mapped = [ ( int(round((x - cx)*amplify + cx)), int(round((y - cy)*amplify + cy)) ) for (x,y) in mapped ]
        # clamp again
        mapped = [ (max(0,min(w-1,x)), max(0,min(h-1,y))) for x,y in mapped ]
        print("Mapped pixel coords after amplify:", mapped)

    # draw and save
    out = draw_highlight_on_image(IMAGE_PATH, mapped, OUTPUT_PATH)
    size_kb = out.stat().st_size / 1024
    print(f"Saved highlighted image to: {out}  ({size_kb:.1f} KB)")

    print("Done. If placement is off, tweak MANUAL_SCALE at top of the script (e.g. 1.2 or 0.5) and re-run.")

if __name__ == "__main__":
    main()