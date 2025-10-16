from io import BytesIO
from typing import List, Tuple, Optional, Union
from PIL import Image, ImageDraw

def highlight_image_stream(
    image_or_bytes: Union[Image.Image, bytes],
    polygon_flat: List[float],
    coord_type: str = "auto",
    pdf_page_size: Optional[Tuple[float, float]] = None,
    fill_color: Tuple[int,int,int,int] = (255, 255, 0, 140),
    outline_color: Tuple[int,int,int,int] = (255, 0, 0, 220),
    outline_width: int = 2,
    amplify_threshold_px: int = 6,      # if bbox smaller than this, amplify to be visible
    amplify_target_px: int = 40,        # amplify so min dimension ~ this many pixels
) -> BytesIO:
    """
    Fast highlight function — returns PNG bytes in BytesIO.

    - image_or_bytes: PIL.Image or raw bytes of image (PNG/JPEG)
    - polygon_flat: flat list [x0,y0,x1,y1,...] (must be even length)
    - coord_type: "auto"|"normalized"|"points"|"pixels" (auto attempts heuristic)
    - pdf_page_size: optional (width_points, height_points) for accurate 'points' mapping
    - returns: BytesIO (PNG), position at start (seek(0))

    Performance notes:
      - Uses simple heuristics for coordinate mapping (auto detection).
      - Writes PNG with low compression for speed.
      - Avoids numpy and heavy per-pixel loops.
    """
    # ---------- helpers (inner functions to keep single paste) ----------
    def _flat_to_pairs(flat: List[float]) -> List[Tuple[float,float]]:
        if len(flat) % 2 != 0:
            raise ValueError("polygon_flat must contain even number of floats (x,y pairs)")
        return [(float(flat[i]), float(flat[i+1])) for i in range(0, len(flat), 2)]

    def _detect_coord_type(pairs: List[Tuple[float,float]], img_size: Tuple[int,int]) -> str:
        flat_vals = [abs(v) for p in pairs for v in p]
        if not flat_vals:
            return "pixels"
        m = max(flat_vals)
        if m <= 1.0:
            return "normalized"
        if m < 200:
            return "points"
        return "pixels"

    def _map_to_pixels(pairs: List[Tuple[float,float]], img_size: Tuple[int,int], ctype: str) -> List[Tuple[int,int]]:
        w,h = img_size
        if ctype == "auto":
            ctype = _detect_coord_type(pairs, img_size)

        if ctype == "pixels":
            mapped = [(int(round(x)), int(round(y))) for x,y in pairs]

        elif ctype == "normalized":
            mapped = [(int(round(x * w)), int(round(y * h))) for x,y in pairs]

        elif ctype == "points":
            if pdf_page_size:
                page_w_pts, page_h_pts = pdf_page_size
                sx = w / page_w_pts
                sy = h / page_h_pts
            else:
                xs = [x for x,_ in pairs]
                ys = [y for _,y in pairs]
                bbox_w = max(xs)-min(xs) if xs else 1.0
                bbox_h = max(ys)-min(ys) if ys else 1.0
                sx = w / max(1.0, bbox_w)
                sy = h / max(1.0, bbox_h)
            mapped = [(int(round(x * sx)), int(round(y * sy))) for x,y in pairs]
        else:
            raise ValueError("Unknown coord_type")

        # flip vertical (PDF bottom-left -> image top-left)
        mapped = [(x, int(round(h - y))) for x,y in mapped]

        # clamp
        mapped_clamped = []
        max_x = w - 1
        max_y = h - 1
        for x,y in mapped:
            if x < 0: x = 0
            elif x > max_x: x = max_x
            if y < 0: y = 0
            elif y > max_y: y = max_y
            mapped_clamped.append((x,y))
        return mapped_clamped

    # ---------- open/prepare image ----------
    if isinstance(image_or_bytes, Image.Image):
        img = image_or_bytes
    else:
        img = Image.open(BytesIO(image_or_bytes))

    # ensure RGBA for overlay compatibility
    img_rgba = img.convert("RGBA")
    w,h = img_rgba.size

    # ---------- polygon mapping ----------
    if not polygon_flat:
        # No polygon provided -> just return original image fast
        out = BytesIO()
        img_rgba.save(out, format="PNG", compress_level=1, optimize=False)
        out.seek(0)
        return out

    pairs = _flat_to_pairs(polygon_flat)
    ctype = coord_type if coord_type != "auto" else "auto"
    polygon_px = _map_to_pixels(pairs, (w,h), ctype)

    # ---------- tiny amplification if polygon extremely small ----------
    xs = [p[0] for p in polygon_px] or [0]
    ys = [p[1] for p in polygon_px] or [0]
    bbox_w = max(xs) - min(xs)
    bbox_h = max(ys) - min(ys)
    if bbox_w < amplify_threshold_px or bbox_h < amplify_threshold_px:
        # make it visible: scale around centroid
        cx = sum(xs)/len(xs)
        cy = sum(ys)/len(ys)
        # factor to reach amplify_target_px in smallest dimension
        factor_w = (amplify_target_px / max(1, bbox_w)) if bbox_w>0 else (amplify_target_px)
        factor_h = (amplify_target_px / max(1, bbox_h)) if bbox_h>0 else (amplify_target_px)
        factor = max(1.0, min(factor_w, factor_h))  # avoid crazy huge
        # apply factor
        polygon_px = [
            (
                max(0, min(w-1, int(round((x - cx) * factor + cx)))),
                max(0, min(h-1, int(round((y - cy) * factor + cy))))
            ) for (x,y) in polygon_px
        ]

    # ---------- draw overlay quickly and composite ----------
    # Use overlay + paste with mask (fast)
    overlay = Image.new("RGBA", (w,h), (255,255,255,0))
    draw = ImageDraw.Draw(overlay)
    # fill
    draw.polygon(polygon_px, fill=fill_color)
    # outline (close path)
    if polygon_px:
        draw.line(list(polygon_px) + [polygon_px[0]], width=outline_width, fill=outline_color)

    # paste overlay onto img_rgba using overlay itself as mask (fast)
    # create a copy to avoid mutating passed image
    out_img = img_rgba.copy()
    out_img.paste(overlay, (0,0), overlay)

    # ---------- write to BytesIO (fast settings) ----------
    out = BytesIO()
    # compress_level=1 for faster write; optimize=False to avoid extra CPU
    out_img.save(out, format="PNG", compress_level=1, optimize=False)
    out.seek(0)
    return out