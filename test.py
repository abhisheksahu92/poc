# app/highlighter.py
from PIL import Image, ImageDraw
from io import BytesIO
from typing import List, Tuple, Optional

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
      - normalized: coords in [0..1] relative to page
      - points: PDF points (1 pt = 1/72 inch) — use pdf_page_size if available
      - pixels: already pixel coords
    - pdf_page_size: (width_points, height_points) in points (optional)
    - flip_y: if True, convert from PDF bottom-left origin to image top-left
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

    # flip y if needed (PDF origin bottom-left -> image top-left)
    if flip_y:
        mapped = [[int(px), int(round(height - py))] for px, py in mapped]

    # clamp to image bounds
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
    - pdf_page_size: (width_points, height_points) optional for better 'points' mapping
    - debug_overlay: if True returns overlay-only image (transparent bg + highlights) for inspection
    """
    # open image (seek to start if needed)
    img_buf.seek(0)
    img = Image.open(img_buf).convert("RGBA")
    width, height = img.size

    # convert flat list to pairs
    poly_pairs = flat_to_pairs(polygon_flat)

    # map to pixel coords
    mapped = map_polygon_to_pixels(poly_pairs, (width, height), coord_type=coord_type, pdf_page_size=pdf_page_size, flip_y=True)

    # overlay and drawing
    overlay = Image.new("RGBA", img.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)

    # fill polygon
    draw.polygon(mapped, fill=fill_color)

    # outline for visibility
    if draw_outline:
        # closing the path
        draw.line(mapped + [mapped[0]], width=max(1, int(round(min(width, height) / 400))), fill=outline_color)

    # merged image
    result = Image.alpha_composite(img, overlay)

    out_img = overlay if debug_overlay else result

    out_buf = BytesIO()
    # Use low compress_level to keep file reasonably sized for demo, optimize to reduce weird extra metadata
    out_img.save(out_buf, format="PNG", compress_level=1, optimize=True)
    out_buf.seek(0)
    return out_buf