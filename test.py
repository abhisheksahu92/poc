#!/usr/bin/env python3
"""
manual_highlight_single_file.py

Single-file tool to test polygon highlighting on a local image.

- Reads image from IMAGE_PATH (update below if needed)
- Uses a flat polygon list (POLYGON_FLAT)
- Tries multiple coordinate mapping modes (auto, normalized, points, pixels)
- Writes output images next to the source with suffixes:
    _highlighted_auto.png, _highlighted_normalized.png, etc.
- Also writes an overlay-only image for the 'auto' mode to help debug mapping.

Requirements:
    pip install pillow

Run:
    python manual_highlight_single_file.py
"""

from pathlib import Path
from io import BytesIO
from typing import List, Tuple, Optional
from PIL import Image, ImageDraw

# -----------------------
# MANUAL CONFIG (edit)
# -----------------------
IMAGE_PATH = Path(r"C:\Users\SAHUAX19\Documents\page_1.png")
# Flat polygon from your JSON / screenshot (edit if you want different coords)
POLYGON_FLAT = [3.2742, 1.5965, 5.7768, 1.5991, 5.7766, 1.8248, 3.274, 1.8221]
# -----------------------


# -----------------------
# Helper functions
# -----------------------
def flat_to_pairs(flat: List[float]) -> List[Tuple[float, float]]:
    """Convert flat [x,y,x,y,...] -> [[x,y],...]."""
    if len(flat) % 2 != 0:
        raise ValueError("Flat polygon list must have even length (x,y pairs).")
    return [[float(flat[i]), float(flat[i + 1])] for i in range(0, len(flat), 2)]


def detect_coord_type(poly_pairs: List[Tuple[float, float]], img_size: Tuple[int, int]) -> str:
    """
    Heuristic to guess coordinate space:
      - 'normalized' if max coord <= 1
      - 'points' if coords look small (< 200)
      - otherwise 'pixels'
    """
    flat = [abs(v) for p in poly_pairs for v in p]
    if not flat:
        return "pixels"
    maxv = max(flat)
    if maxv <= 1.0:
        return "normalized"
    if maxv < 200:
        return "points"
    return "pixels"


def map_polygon_to_pixels(
    poly_pairs: List[Tuple[float, float]],
    img_size: Tuple[int, int],
    coord_type: str = "auto",
    pdf_page_size: Optional[Tuple[float, float]] = None,
    flip_y: bool = True,
) -> List[Tuple[int, int]]:
    """
    Map polygon coordinates to image pixel coordinates.
    - coord_type: "auto" | "normalized" | "points" | "pixels"
    - pdf_page_size: optional (width_points, height_points) for accurate 'points' mapping
    - flip_y: flip vertical axis (PDF bottom-left -> image top-left)
    """
    width, height = img_size
    if coord_type == "auto":
        coord_type = detect_coord_type(poly_pairs, img_size)

    mapped = []
    if coord_type == "pixels":
        mapped = [[int(round(x)), int(round(y))] for x, y in poly_pairs]

    elif coord_type == "normalized":
        mapped = [[int(round(x * width)), int(round(y * height))] for x, y in poly_pairs]

    elif coord_type == "points":
        # If pdf_page_size provided, use that to compute scale; otherwise use bbox heuristic
        if pdf_page_size:
            page_w_pts, page_h_pts = pdf_page_size
            sx = width / page_w_pts
            sy = height / page_h_pts
        else:
            xs = [x for x, _ in poly_pairs]
            ys = [y for _, y in poly_pairs]
            bbox_w_pts = max(xs) - min(xs) if xs else 1.0
            bbox_h_pts = max(ys) - min(ys) if ys else 1.0
            sx = width / max(bbox_w_pts, 1.0)
            sy = height / max(bbox_h_pts, 1.0)
        mapped = [[int(round(x * sx)), int(round(y * sy))] for x, y in poly_pairs]
    else:
        raise ValueError(f"Unknown coord_type: {coord_type}")

    # flip y (PDF origin bottom-left -> image top-left)
    if flip_y:
        mapped = [[int(px), int(round(height - py))] for px, py in mapped]

    # clamp within image
    for i, (px, py) in enumerate(mapped):
        px = max(0, min(px, width - 1))
        py = max(0, min(py, height - 1))
        mapped[i] = (px, py)

    return mapped


def highlight_png_buf(
    img_buf: BytesIO,
    polygon_flat: List[float],
    coord_type: str = "auto",
    pdf_page_size: Optional[Tuple[float, float]] = None,
    fill_color=(255, 255, 0, 130),
    outline_color=(255, 0, 0, 230),
    draw_outline=True,
    debug_overlay=False,
) -> BytesIO:
    """
    Apply polygon highlight to an image buffer and return resulting PNG as BytesIO.
    - polygon_flat: flat list [x0,y0,x1,y1,...]
    - coord_type: 'auto'|'normalized'|'points'|'pixels'
    - pdf_page_size: optional for better 'points' mapping
    - debug_overlay: if True returns overlay-only image (transparent background)
    """
    img_buf.seek(0)
    img = Image.open(img_buf).convert("RGBA")
    width, height = img.size

    poly_pairs = flat_to_pairs(polygon_flat)
    mapped = map_polygon_to_pixels(poly_pairs, (width, height), coord_type=coord_type, pdf_page_size=pdf_page_size, flip_y=True)

    overlay = Image.new("RGBA", img.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)

    # fill polygon
    draw.polygon(mapped, fill=fill_color)
    # outline for visibility
    if draw_outline:
        draw.line(mapped + [mapped[0]], width=max(1, int(round(min(width, height) / 400))), fill=outline_color)

    result = Image.alpha_composite(img, overlay)
    out_img = overlay if debug_overlay else result

    out_buf = BytesIO()
    out_img.save(out_buf, format="PNG", compress_level=1, optimize=True)
    out_buf.seek(0)
    return out_buf


# -----------------------
# Runner
# -----------------------
def read_image_buf(path: Path) -> BytesIO:
    with path.open("rb") as f:
        b = BytesIO(f.read())
    b.seek(0)
    return b


def save_buf(out_buf: BytesIO, out_path: Path):
    with out_path.open("wb") as f:
        f.write(out_buf.getvalue())
    print(f"WROTE: {out_path}  ({out_path.stat().st_size/1024:.1f} KB)")


def main():
    print("Manual highlight tester — single-file script")
    if not IMAGE_PATH.exists():
        print(f"ERROR: input image not found: {IMAGE_PATH}")
        return

    # read once
    src_buf = read_image_buf(IMAGE_PATH)

    # modes to try
    modes = ["auto", "normalized", "points", "pixels"]
    for mode in modes:
        src_buf.seek(0)
        try:
            out_buf = highlight_png_buf(src_buf, POLYGON_FLAT, coord_type=mode, debug_overlay=False)
        except Exception as e:
            print(f"Mode {mode} failed: {e}")
            continue
        out_path = IMAGE_PATH.with_name(f"{IMAGE_PATH.stem}_highlighted_{mode}.png")
        save_buf(out_buf, out_path)

    # overlay-only debug for auto
    src_buf.seek(0)
    try:
        overlay_buf = highlight_png_buf(src_buf, POLYGON_FLAT, coord_type="auto", debug_overlay=True)
        save_buf(overlay_buf, IMAGE_PATH.with_name(f"{IMAGE_PATH.stem}_overlay_auto.png"))
    except Exception as e:
        print("Overlay generation failed:", e)

    print("Done. Inspect the generated images and pick the coordinate mode that aligns best.")


if __name__ == "__main__":
    main()