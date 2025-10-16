#!/usr/bin/env python3
"""
highlighter_force_visible.py

Deterministic, class-based highlighter that forces a visible overlay for testing.
Main is minimal: only set IMAGE_PATH and POLYGON_FLAT, then run.

Outputs (next to source image):
 - <basename>_overlay_debug.png   (overlay-only, transparent background)
 - <basename>_highlighted_debug.png (merged)
"""

from pathlib import Path
from typing import List, Tuple, Optional, Union
from io import BytesIO
from PIL import Image, ImageDraw, ImageOps
import time

class PNGHighlighterVisible:
    def __init__(
        self,
        fill_color: Tuple[int,int,int,int] = (255, 255, 0, 200),
        outline_color: Tuple[int,int,int,int] = (255, 0, 0, 255),
        outline_width: int = 4,
        # If mapped polygon bbox smaller than this, expand to visible rectangle
        expand_min_w: int = 200,
        expand_min_h: int = 100,
    ):
        self.fill_color = fill_color
        self.outline_color = outline_color
        self.outline_width = outline_width
        self.expand_min_w = expand_min_w
        self.expand_min_h = expand_min_h

    @staticmethod
    def _flat_to_pairs(flat: List[float]) -> List[Tuple[float,float]]:
        if len(flat) % 2 != 0:
            raise ValueError("polygon_flat must contain even number of entries")
        return [(float(flat[i]), float(flat[i+1])) for i in range(0, len(flat), 2)]

    @staticmethod
    def _detect_coord_type(pairs: List[Tuple[float,float]]) -> str:
        vals = [abs(v) for p in pairs for v in p]
        if not vals:
            return "pixels"
        m = max(vals)
        if m <= 1.0:
            return "normalized"
        if m < 200:
            return "points"
        return "pixels"

    @staticmethod
    def _map_pairs_to_pixels(pairs: List[Tuple[float,float]],
                              img_size: Tuple[int,int],
                              coord_type: str,
                              flip_y: bool,
                              pdf_page_size: Optional[Tuple[float,float]] = None) -> List[Tuple[int,int]]:
        w,h = img_size
        if coord_type == "normalized":
            mapped = [(x * w, y * h) for x,y in pairs]
        elif coord_type == "points":
            if pdf_page_size:
                pw, ph = pdf_page_size
                sx, sy = w / pw, h / ph
            else:
                xs = [x for x,_ in pairs] or [1.0]
                ys = [y for _,y in pairs] or [1.0]
                bbox_w = max(xs)-min(xs) if xs else 1.0
                bbox_h = max(ys)-min(ys) if ys else 1.0
                sx, sy = w/max(1.0,bbox_w), h/max(1.0,bbox_h)
            mapped = [(x * sx, y * sy) for x,y in pairs]
        else:  # pixels
            mapped = [(x, y) for x,y in pairs]

        if flip_y:
            mapped = [(int(round(px)), int(round(h - py))) for px,py in mapped]
        else:
            mapped = [(int(round(px)), int(round(py))) for px,py in mapped]

        # clamp to image
        mapped_clamped = [(max(0, min(w-1, int(x))), max(0, min(h-1, int(y)))) for x,y in mapped]
        return mapped_clamped

    @staticmethod
    def _bbox(poly_px: List[Tuple[int,int]]):
        if not poly_px:
            return 0,0,0,0
        xs = [p[0] for p in poly_px]; ys = [p[1] for p in poly_px]
        return min(xs), max(xs), min(ys), max(ys)

    def _expand_to_visible_rect(self, poly_px: List[Tuple[int,int]], img_size: Tuple[int,int]):
        """Return a rectangle polygon (4 pts) centered at polygon centroid with configured size."""
        w,h = img_size
        if poly_px:
            xs = [p[0] for p in poly_px]; ys = [p[1] for p in poly_px]
            cx = int(sum(xs)/len(xs)); cy = int(sum(ys)/len(ys))
        else:
            cx, cy = w//2, h//2
        half_w = self.expand_min_w // 2
        half_h = self.expand_min_h // 2
        left = max(0, cx - half_w)
        right = min(w-1, cx + half_w)
        top = max(0, cy - half_h)
        bottom = min(h-1, cy + half_h)
        rect = [(left, top), (right, top), (right, bottom), (left, bottom)]
        return rect

    def _draw_and_save(self, pil_img: Image.Image, poly_px: List[Tuple[int,int]], base_path: Path):
        w,h = pil_img.size
        overlay = Image.new("RGBA", (w,h), (255,255,255,0))
        if poly_px:
            d = ImageDraw.Draw(overlay)
            d.polygon(poly_px, fill=self.fill_color)
            d.line(list(poly_px) + [poly_px[0]], fill=self.outline_color, width=self.outline_width)
        merged = Image.alpha_composite(pil_img.convert("RGBA"), overlay)

        overlay_path = base_path.with_name(base_path.stem + "_overlay_debug.png")
        merged_path = base_path.with_name(base_path.stem + "_highlighted_debug.png")
        # Save overlay-only and merged for debugging (overlay-only we also save as transparent background)
        overlay.save(overlay_path, format="PNG", compress_level=1)
        merged.save(merged_path, format="PNG", compress_level=1)
        return overlay_path, merged_path

    def highlight_from_path(self,
                            image_path: Union[str, Path],
                            polygon_flat: List[float],
                            coord_type: str = "auto",
                            pdf_page_size: Optional[Tuple[float,float]] = None,
                            flip_try_order: Tuple[bool,bool] = (True, False)):
        """
        Minimal public method. Main should only call this method with path and polygon.
        Returns BytesIO of merged image and prints diagnostics and writes debug files.
        """
        base_path = Path(image_path)
        if not base_path.exists():
            raise FileNotFoundError(f"Image not found: {base_path}")
        pil = Image.open(base_path)
        w,h = pil.size
        print(f"[info] Image loaded: {base_path} size=({w},{h})")

        if len(polygon_flat) % 2 != 0:
            raise ValueError("polygon_flat must have even number of entries")

        pairs = self._flat_to_pairs(polygon_flat)
        print(f"[info] Input pairs (raw units): {pairs}")

        # decide coord types to try: if 'auto' then detect and try sensible order
        modes = []
        if coord_type == "auto":
            det = self._detect_coord_type(pairs)
            modes = [det] + [m for m in ("normalized","points","pixels") if m != det]
            print(f"[info] Auto-detected coord type: {det}. Try order: {modes}")
        else:
            modes = [coord_type]

        chosen = None
        mapped_debug = None

        # Try combinations (modes x flips) and choose first mapping that places polygon inside central area.
        # We'll pick the mapping with largest bbox area (heuristic) to avoid corner collapse.
        best_area = -1
        for m in modes:
            for flip in flip_try_order:
                mapped = self._map_pairs_to_pixels(pairs, (w,h), coord_type=m, flip_y=flip, pdf_page_size=pdf_page_size)
                minx,maxx,miny,maxy = self._bbox(mapped)
                bw = maxx - minx
                bh = maxy - miny
                area = bw * bh
                print(f"[try] mode={m} flip={flip} -> bbox w={bw} h={bh} area={area}")
                # prefer larger area mapping (avoids corner/line mapping)
                if area > best_area:
                    best_area = area
                    chosen = {"mode": m, "flip": flip}
                    mapped_debug = mapped

        print(f"[chosen] coord_type={chosen['mode']} flip={chosen['flip']} (area={best_area})")
        if mapped_debug is None:
            mapped_debug = []

        # If mapped polygon is tiny or degenerate, expand to visible rectangle
        minx,maxx,miny,maxy = self._bbox(mapped_debug)
        bw = maxx - minx
        bh = maxy - miny
        print(f"[mapped] bbox before expansion w={bw} h={bh} points sample={mapped_debug[:10]}")
        if bw < self.expand_min_w or bh < self.expand_min_h:
            print("[action] mapped polygon is small/degenerate -> expanding to visible rect for debugging")
            final_poly = self._expand_to_visible_rect(mapped_debug, (w,h))
            expanded = True
        else:
            final_poly = mapped_debug
            expanded = False

        # Ensure ints & clamped
        final_poly = [(int(round(x)), int(round(y))) for x,y in final_poly]
        final_poly = [(max(0,min(w-1,x)), max(0,min(h-1,y))) for x,y in final_poly]
        print(f"[final] final polygon pixels (sample): {final_poly[:12]} (expanded={expanded})")

        # Draw and save overlay + merged
        overlay_path, merged_path = self._draw_and_save(pil, final_poly, base_path)
        print(f"[output] overlay saved: {overlay_path}")
        print(f"[output] merged saved:  {merged_path}")

        # return BytesIO of merged image
        out = BytesIO()
        merged = Image.open(merged_path)
        merged.save(out, format="PNG", compress_level=1)
        out.seek(0)
        return out


# -------------------------
# Minimal main (only image path + polygon)
# -------------------------
if __name__ == "__main__":
    # only change these two lines if needed
    IMAGE_PATH = r"C:\Users\SAHUAX19\Documents\page_1.png"
    POLYGON_FLAT = [3.2742, 1.5965, 5.7768, 1.5991, 5.7766, 1.8248, 3.274, 1.8221]

    highlighter = PNGHighlighterVisible()
    try:
        result_stream = highlighter.highlight_from_path(IMAGE_PATH, POLYGON_FLAT, coord_type="auto")
        # write merged to confirm (already saved in debug file, this is redundant)
        with open("out_highlighted_debug.png", "wb") as f:
            f.write(result_stream.getvalue())
        print("Wrote out_highlighted_debug.png for inspection")
    except Exception as e:
        print("Error:", e)