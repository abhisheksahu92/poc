from io import BytesIO
from typing import List, Tuple, Optional, Union
from PIL import Image, ImageDraw
import time


def highlight_image_stream(
    image_or_bytes: Union[Image.Image, bytes],
    polygon_flat: List[float],
    coord_type: str = "auto",
    pdf_page_size: Optional[Tuple[float, float]] = None,
    fill_color: Tuple[int,int,int,int] = (255, 255, 0, 140),
    outline_color: Tuple[int,int,int,int] = (255, 0, 0, 220),
    outline_width: int = 2,
    amplify_threshold_px: int = 6,
    amplify_target_px: int = 40,
) -> BytesIO:
    """
    Fast highlight function — returns PNG bytes in BytesIO.
    """

    print("\n=== Starting highlight_image_stream ===")
    start_time = time.time()

    # ---------- helpers ----------
    def _flat_to_pairs(flat: List[float]) -> List[Tuple[float,float]]:
        print(f"Converting flat polygon with {len(flat)} elements -> pairs")
        if len(flat) % 2 != 0:
            raise ValueError("polygon_flat must contain even number of floats (x,y pairs)")
        return [(float(flat[i]), float(flat[i+1])) for i in range(0, len(flat), 2)]

    def _detect_coord_type(pairs: List[Tuple[float,float]], img_size: Tuple[int,int]) -> str:
        flat_vals = [abs(v) for p in pairs for v in p]
        max_val = max(flat_vals) if flat_vals else 0
        print(f"Auto-detecting coordinate type | max value: {max_val}")
        if max_val <= 1.0:
            return "normalized"
        if max_val < 200:
            return "points"
        return "pixels"

    def _map_to_pixels(pairs: List[Tuple[float,float]], img_size: Tuple[int,int], ctype: str) -> List[Tuple[int,int]]:
        w,h = img_size
        print(f"Mapping polygon to pixels | coord_type={ctype} | image size={img_size}")
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

        # flip vertically (PDF bottom-left -> image top-left)
        mapped = [(x, int(round(h - y))) for x,y in mapped]

        # clamp to image bounds
        mapped_clamped = []
        for x,y in mapped:
            x = max(0, min(x, w-1))
            y = max(0, min(y, h-1))
            mapped_clamped.append((x,y))

        print(f"Mapped polygon points: {mapped_clamped}")
        return mapped_clamped

    # ---------- open/prepare image ----------
    if isinstance(image_or_bytes, Image.Image):
        img = image_or_bytes
        print("Received PIL.Image input")
    else:
        print("Received bytes input — opening via PIL")
        img = Image.open(BytesIO(image_or_bytes))

    img_rgba = img.convert("RGBA")
    w, h = img_rgba.size
    print(f"Image loaded | size = ({w}, {h})")

    if not polygon_flat:
        print("No polygon provided, returning original image.")
        out = BytesIO()
        img_rgba.save(out, format="PNG", compress_level=1, optimize=False)
        out.seek(0)
        return out

    # ---------- polygon mapping ----------
    pairs = _flat_to_pairs(polygon_flat)
    polygon_px = _map_to_pixels(pairs, (w, h), coord_type)

    # ---------- small polygon amplification ----------
    xs = [p[0] for p in polygon_px]
    ys = [p[1] for p in polygon_px]
    bbox_w = max(xs) - min(xs)
    bbox_h = max(ys) - min(ys)
    print(f"Polygon bbox (w={bbox_w}, h={bbox_h})")

    if bbox_w < amplify_threshold_px or bbox_h < amplify_threshold_px:
        print(f"Polygon too small, amplifying by target={amplify_target_px}")
        cx = sum(xs) / len(xs)
        cy = sum(ys) / len(ys)
        factor = max(
            amplify_target_px / max(bbox_w, 1),
            amplify_target_px / max(bbox_h, 1)
        )
        polygon_px = [
            (
                max(0, min(w-1, int(round((x - cx) * factor + cx)))),
                max(0, min(h-1, int(round((y - cy) * factor + cy))))
            ) for (x,y) in polygon_px
        ]
        print(f"Amplified polygon: {polygon_px}")

    # ---------- draw overlay ----------
    print("Drawing overlay ...")
    overlay = Image.new("RGBA", (w, h), (255,255,255,0))
    draw = ImageDraw.Draw(overlay)
    draw.polygon(polygon_px, fill=fill_color)
    draw.line(list(polygon_px) + [polygon_px[0]], width=outline_width, fill=outline_color)

    print("Merging overlay ...")
    out_img = img_rgba.copy()
    out_img.paste(overlay, (0,0), overlay)

    # ---------- save to buffer ----------
    print("Saving image to buffer ...")
    out = BytesIO()
    out_img.save(out, format="PNG", compress_level=1, optimize=False)
    out.seek(0)

    elapsed = time.time() - start_time
    print(f"=== Highlight complete in {elapsed:.3f}s ===\n")
    return out


# ==================================================================
# 🧪 Example usage — runs when this file is executed directly
# ==================================================================
if __name__ == "__main__":
    IMAGE_PATH = r"C:\Users\SAHUAX19\Documents\page_1.png"
    POLYGON_FLAT = [3.2742, 1.5965, 5.7768, 1.5991, 5.7766, 1.8248, 3.274, 1.8221]

    print(f"Loading image: {IMAGE_PATH}")
    with open(IMAGE_PATH, "rb") as f:
        img_bytes = f.read()

    result_buf = highlight_image_stream(img_bytes, POLYGON_FLAT)

    output_path = "highlighted_output.png"
    with open(output_path, "wb") as f:
        f.write(result_buf.getvalue())

    print(f"✅ Highlighted image saved to: {output_path}")