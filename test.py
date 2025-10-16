from io import BytesIO
from typing import List, Tuple, Optional, Union
from pathlib import Path
from PIL import Image, ImageDraw, ImageOps
import time

class PNGHighlighterFixed:
    def __init__(
        self,
        fill_color: Tuple[int,int,int,int] = (255, 255, 0, 180),
        outline_color: Tuple[int,int,int,int] = (255, 0, 0, 220),
        outline_width: int = 3,
        amplify_threshold_px: int = 6,
        amplify_target_px: int = 40,
        auto_expand_if_degenerate: bool = True,
    ):
        self.fill_color = fill_color
        self.outline_color = outline_color
        self.outline_width = outline_width
        self.amplify_threshold_px = amplify_threshold_px
        self.amplify_target_px = amplify_target_px
        self.auto_expand_if_degenerate = auto_expand_if_degenerate

    @staticmethod
    def _flat_to_pairs(flat: List[float]) -> List[Tuple[float,float]]:
        if len(flat) % 2 != 0:
            raise ValueError("Flat polygon list must have even number of elements (x,y pairs).")
        return [(float(flat[i]), float(flat[i+1])) for i in range(0, len(flat), 2)]

    @staticmethod
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

    @staticmethod
    def _map_to_pixels(pairs: List[Tuple[float,float]], img_size: Tuple[int,int],
                       coord_type: str = "auto", pdf_page_size: Optional[Tuple[float,float]] = None,
                       flip_y: bool = True):
        w,h = img_size
        if coord_type == "auto":
            coord_type = PNGHighlighterFixed._detect_coord_type(pairs, img_size)
        diag = {"coord_type_used": coord_type}

        if coord_type == "pixels":
            mapped = [(float(x), float(y)) for x,y in pairs]

        elif coord_type == "normalized":
            mapped = [(x * w, y * h) for x,y in pairs]
            diag["sx"], diag["sy"] = w, h

        elif coord_type == "points":
            if pdf_page_size:
                page_w_pts, page_h_pts = pdf_page_size
                sx = w / page_w_pts
                sy = h / page_h_pts
            else:
                xs = [x for x,_ in pairs] or [1.0]
                ys = [y for _,y in pairs] or [1.0]
                bbox_w = max(xs) - min(xs) if xs else 1.0
                bbox_h = max(ys) - min(ys) if ys else 1.0
                sx = w / max(1.0, bbox_w)
                sy = h / max(1.0, bbox_h)
            mapped = [(x * sx, y * sy) for x,y in pairs]
            diag["sx"], diag["sy"] = sx, sy

        else:
            raise ValueError("Unknown coord_type")

        if flip_y:
            mapped = [(mx, h - my) for mx,my in mapped]

        # convert to ints and clamp
        mapped_int = []
        for mx,my in mapped:
            ix = int(round(mx))
            iy = int(round(my))
            ix = max(0, min(w-1, ix))
            iy = max(0, min(h-1, iy))
            mapped_int.append((ix, iy))

        diag["mapped_clamped"] = mapped_int
        diag["img_size"] = (w,h)
        return mapped_int, diag

    def _bbox(self, poly_px: List[Tuple[int,int]]):
        if not poly_px:
            return 0,0,0,0
        xs = [p[0] for p in poly_px]; ys = [p[1] for p in poly_px]
        minx, maxx = min(xs), max(xs)
        miny, maxy = min(ys), max(ys)
        return minx,maxx,miny,maxy

    def _expand_degenerate(self, poly_px: List[Tuple[int,int]], img_size: Tuple[int,int], min_w:int=40, min_h:int=20):
        """If polygon degenerates to small box or line, expand to rectangle around centroid."""
        w,h = img_size
        if not poly_px:
            # make center box
            cx, cy = w//2, h//2
        else:
            xs = [p[0] for p in poly_px]; ys = [p[1] for p in poly_px]
            cx = int(round(sum(xs)/len(xs)))
            cy = int(round(sum(ys)/len(ys)))

        # half sizes
        half_w = max(min_w//2, 10)
        half_h = max(min_h//2, 8)
        left = max(0, cx - half_w)
        right = min(w-1, cx + half_w)
        top = max(0, cy - half_h)
        bottom = min(h-1, cy + half_h)
        rect = [(left, top), (right, top), (right, bottom), (left, bottom)]
        return rect

    def _maybe_amplify(self, poly_px: List[Tuple[int,int]], img_size: Tuple[int,int]):
        minx,maxx,miny,maxy = self._bbox(poly_px)
        bw = maxx - minx
        bh = maxy - miny
        if bw >= self.amplify_target_px and bh >= self.amplify_target_px:
            return poly_px, 1.0
        if bw < 2 or bh < 2:
            # degenerate: expand deterministically
            expanded = self._expand_degenerate(poly_px, img_size, min_w=self.amplify_target_px, min_h=self.amplify_target_px//2)
            return expanded, 1.0
        # compute factor and scale around centroid
        cx = (minx + maxx)/2; cy = (miny + maxy)/2
        factor_w = self.amplify_target_px / max(1, bw)
        factor_h = self.amplify_target_px / max(1, bh)
        factor = max(1.0, min(factor_w, factor_h))
        new = []
        for x,y in poly_px:
            nx = int(round((x - cx)*factor + cx)); ny = int(round((y - cy)*factor + cy))
            new.append((max(0, min(img_size[0]-1, nx)), max(0, min(img_size[1]-1, ny))))
        return new, factor

    def _draw_overlay_and_get_bytes(self, img: Image.Image, poly_px: List[Tuple[int,int]]):
        w,h = img.size
        overlay = Image.new("RGBA", (w,h), (255,255,255,0))
        draw = ImageDraw.Draw(overlay)
        if poly_px:
            draw.polygon(poly_px, fill=self.fill_color)
            draw.line(list(poly_px) + [poly_px[0]], width=self.outline_width, fill=self.outline_color)
        merged = Image.alpha_composite(img.convert("RGBA"), overlay)

        # also return overlay-only for debug if needed
        buf = BytesIO()
        merged.save(buf, format="PNG", compress_level=1, optimize=False)
        buf.seek(0)
        return buf, overlay

    def save_debug_overlay(self, overlay_image: Image.Image, base_path: Union[str, Path]):
        p = Path(base_path)
        overlay_path = p.with_name(p.stem + "_overlay_class_fixed.png")
        overlay_image.save(overlay_path, format="PNG", compress_level=1)
        return overlay_path

    def highlight_from_path(self, image_path: Union[str, Path], polygon_flat: List[float],
                            coord_type: str = "auto", pdf_page_size: Optional[Tuple[float,float]] = None,
                            auto_tune: bool = False):
        img_path = Path(image_path)
        if not img_path.exists():
            raise FileNotFoundError(f"Image not found: {img_path}")
        img = Image.open(img_path)
        return self.highlight_from_pil(img, polygon_flat, coord_type, pdf_page_size, auto_tune, img_path)

    def highlight_from_pil(self, img: Image.Image, polygon_flat: List[float],
                           coord_type: str = "auto", pdf_page_size: Optional[Tuple[float,float]] = None,
                           auto_tune: bool = False, debug_base_path: Optional[Union[str,Path]] = None):
        start = time.time()
        w,h = img.size
        print(f"[highlighter] image size: {w}x{h}")

        if not polygon_flat:
            # return original image bytes
            b = BytesIO()
            img.convert("RGBA").save(b, format="PNG", compress_level=1)
            b.seek(0)
            return b

        pairs = self._flat_to_pairs(polygon_flat)
        print(f"[highlighter] raw pairs: {pairs}")

        poly_px, diag = self._map_to_pixels(pairs, (w,h), coord_type=coord_type, pdf_page_size=pdf_page_size, flip_y=True)
        print(f"[highlighter] mapping diag: {diag}")

        # if polygon degenerate (point/line) or tiny, amplify/expand so visible
        poly_px2, factor = self._maybe_amplify(poly_px, (w,h))
        if factor != 1.0:
            print(f"[highlighter] amplified polygon by factor {factor:.2f}")
        # ensure integer tuples
        poly_px2 = [(int(x), int(y)) for x,y in poly_px2]

        # optional: auto_tune (not implemented heavy) - kept as placeholder
        if auto_tune:
            print("[highlighter] auto_tune requested but disabled in this fixed version to keep deterministic behaviour.")

        # draw overlay + get bytes and overlay image (for debug)
        out_buf, overlay_img = self._draw_overlay_and_get_bytes(img, poly_px2)

        # save debug overlay if base path provided
        if debug_base_path:
            try:
                overlay_path = self.save_debug_overlay(overlay_img, debug_base_path)
                print(f"[highlighter] saved overlay-only debug: {overlay_path}")
            except Exception as e:
                print(f"[highlighter] failed saving overlay debug: {e}")

        elapsed = time.time() - start
        print(f"[highlighter] done in {elapsed:.3f}s")
        return out_buf


# -------------------------
# Minimal main (only path + polygon + call)
# -------------------------
if __name__ == "__main__":
    # set your image path and polygon here (only these two items in main)
    IMAGE_PATH = r"C:\Users\SAHUAX19\Documents\page_1.png"
    POLYGON = [3.2742, 1.5965, 5.7768, 1.5991, 5.7766, 1.8248, 3.274, 1.8221]

    highlighter = PNGHighlighterFixed()
    try:
        result = highlighter.highlight_from_path(IMAGE_PATH, POLYGON, coord_type="auto", pdf_page_size=None, auto_tune=False)
        out_path = Path("page_1_highlighted_class_fixed.png")
        with open(out_path, "wb") as f:
            f.write(result.getvalue())
        print(f"Wrote merged highlighted image: {out_path}")
    except Exception as e:
        print("Error:", e)