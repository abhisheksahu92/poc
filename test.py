"""
highlighter.py

Class-based PNG highlighter.

Usage (example at bottom):
    from highlighter import PNGHighlighter
    hl = PNGHighlighter()
    buf = hl.highlight_from_path("C:/path/page_1.png", [3.27,1.59,5.77,1.59,5.77,1.82,3.27,1.82])
    # 'buf' is BytesIO containing PNG bytes (seek 0)
"""

from io import BytesIO
from typing import List, Tuple, Optional, Union
from pathlib import Path
from PIL import Image, ImageDraw, ImageOps
import time

# numpy is only needed for auto_tune scoring; keep optional usage light
try:
    import numpy as np
except Exception:
    np = None


class PNGHighlighter:
    def __init__(
        self,
        fill_color: Tuple[int, int, int, int] = (255, 255, 0, 150),
        outline_color: Tuple[int, int, int, int] = (255, 0, 0, 220),
        outline_width: int = 3,
        amplify_threshold_px: int = 6,
        amplify_target_px: int = 40,
    ):
        """
        Create a highlighter instance.

        Args:
            fill_color: RGBA fill color for highlight.
            outline_color: RGBA outline color.
            outline_width: Outline thickness in pixels.
            amplify_threshold_px: If resulting bbox smaller than this (px), amplify.
            amplify_target_px: Target min dimension when amplifying.
        """
        self.fill_color = fill_color
        self.outline_color = outline_color
        self.outline_width = outline_width
        self.amplify_threshold_px = amplify_threshold_px
        self.amplify_target_px = amplify_target_px

    # -------------------------
    # utility helpers (internal)
    # -------------------------
    @staticmethod
    def _flat_to_pairs(flat: List[float]) -> List[Tuple[float, float]]:
        if len(flat) % 2 != 0:
            raise ValueError("Flat polygon list must contain even number of entries (x,y pairs).")
        return [(float(flat[i]), float(flat[i + 1])) for i in range(0, len(flat), 2)]

    @staticmethod
    def _detect_coord_type(poly_pairs: List[Tuple[float, float]], img_size: Tuple[int, int]) -> str:
        flat_vals = [abs(v) for p in poly_pairs for v in p]
        if not flat_vals:
            return "pixels"
        maxv = max(flat_vals)
        if maxv <= 1.0:
            return "normalized"
        if maxv < 200:
            return "points"
        return "pixels"

    @staticmethod
    def _map_to_pixels(poly_pairs: List[Tuple[float, float]],
                       img_size: Tuple[int, int],
                       coord_type: str = "auto",
                       pdf_page_size: Optional[Tuple[float, float]] = None,
                       flip_y: bool = True) -> Tuple[List[Tuple[int, int]], dict]:
        """
        Map polygon coordinate pairs to pixel coordinates; returns (mapped_pairs, diagnostics).
        diagnostics contains used coord_type and scale factors for 'points' or 'normalized'.
        """
        w, h = img_size
        diag = {"coord_type_requested": coord_type}
        if coord_type == "auto":
            coord_type = PNGHighlighter._detect_coord_type(poly_pairs, img_size)
        diag["coord_type_used"] = coord_type

        if coord_type == "pixels":
            mapped = [(int(round(x)), int(round(y))) for x, y in poly_pairs]

        elif coord_type == "normalized":
            mapped = [(int(round(x * w)), int(round(y * h))) for x, y in poly_pairs]
            diag["sx"], diag["sy"] = w, h

        elif coord_type == "points":
            if pdf_page_size:
                page_w_pts, page_h_pts = pdf_page_size
                sx = w / page_w_pts
                sy = h / page_h_pts
            else:
                xs = [x for x, _ in poly_pairs]
                ys = [y for _, y in poly_pairs]
                bbox_w = max(xs) - min(xs) if xs else 1.0
                bbox_h = max(ys) - min(ys) if ys else 1.0
                sx = w / max(1.0, bbox_w)
                sy = h / max(1.0, bbox_h)
            diag["sx"], diag["sy"] = sx, sy
            mapped = [(int(round(x * sx)), int(round(y * sy))) for x, y in poly_pairs]

        else:
            raise ValueError(f"Unknown coord_type: {coord_type}")

        # flip vertical axis if PDF-like coords
        if flip_y:
            mapped = [(int(px), int(round(h - py))) for px, py in mapped]

        # clamp inside image bounds
        mapped_clamped = []
        for px, py in mapped:
            px = max(0, min(px, w - 1))
            py = max(0, min(py, h - 1))
            mapped_clamped.append((px, py))

        diag["mapped_raw"] = mapped
        diag["mapped_clamped"] = mapped_clamped
        diag["img_size"] = (w, h)
        return mapped_clamped, diag

    def _maybe_amplify(self, poly_px: List[Tuple[int, int]], img_size: Tuple[int, int]) -> Tuple[List[Tuple[int, int]], float]:
        """
        If polygon bbox is too small (< amplify_threshold_px), amplify to amplify_target_px.
        Returns (new_polygon_px, factor_used)
        """
        w, h = img_size
        xs = [p[0] for p in poly_px]
        ys = [p[1] for p in poly_px]
        if not xs or not ys:
            return poly_px, 1.0
        bbox_w = max(xs) - min(xs)
        bbox_h = max(ys) - min(ys)
        smallest = min(bbox_w if bbox_w > 0 else 1, bbox_h if bbox_h > 0 else 1)
        if smallest >= self.amplify_target_px:
            return poly_px, 1.0
        # compute factor
        factor_w = self.amplify_target_px / max(1, bbox_w)
        factor_h = self.amplify_target_px / max(1, bbox_h)
        factor = max(1.0, min(factor_w, factor_h))
        cx = sum(xs) / len(xs)
        cy = sum(ys) / len(ys)
        new = []
        for x, y in poly_px:
            nx = int(round((x - cx) * factor + cx))
            ny = int(round((y - cy) * factor + cy))
            nx = max(0, min(w - 1, nx))
            ny = max(0, min(h - 1, ny))
            new.append((nx, ny))
        return new, factor

    def _draw_overlay(self, img: Image.Image, polygon_px: List[Tuple[int, int]]) -> Image.Image:
        overlay = Image.new("RGBA", img.size, (255, 255, 255, 0))
        draw = ImageDraw.Draw(overlay)
        if polygon_px:
            draw.polygon(polygon_px, fill=self.fill_color)
            draw.line(list(polygon_px) + [polygon_px[0]], width=self.outline_width, fill=self.outline_color)
        merged = Image.alpha_composite(img.convert("RGBA"), overlay)
        return merged

    # -------------------------
    # public APIs
    # -------------------------
    def highlight_from_path(
        self,
        image_path: Union[str, Path],
        polygon_flat: List[float],
        coord_type: str = "auto",
        pdf_page_size: Optional[Tuple[float, float]] = None,
        auto_tune: bool = False,
        tune_radius: int = 40,
        tune_step: int = 8,
    ) -> BytesIO:
        """
        Read an image from disk and return highlighted PNG bytes (BytesIO).
        Minimal main-like usage: main should only call this with path and polygon.
        """
        img_path = Path(image_path)
        if not img_path.exists():
            raise FileNotFoundError(f"Image not found: {img_path}")
        img = Image.open(img_path)
        return self.highlight_from_pil(img, polygon_flat, coord_type, pdf_page_size, auto_tune, tune_radius, tune_step)

    def highlight_from_bytes(
        self,
        image_bytes: bytes,
        polygon_flat: List[float],
        coord_type: str = "auto",
        pdf_page_size: Optional[Tuple[float, float]] = None,
        auto_tune: bool = False,
        tune_radius: int = 40,
        tune_step: int = 8,
    ) -> BytesIO:
        """
        Take raw image bytes (PNG/JPEG), return highlighted PNG bytes (BytesIO).
        """
        img = Image.open(BytesIO(image_bytes))
        return self.highlight_from_pil(img, polygon_flat, coord_type, pdf_page_size, auto_tune, tune_radius, tune_step)

    def highlight_from_pil(
        self,
        img: Image.Image,
        polygon_flat: List[float],
        coord_type: str = "auto",
        pdf_page_size: Optional[Tuple[float, float]] = None,
        auto_tune: bool = False,
        tune_radius: int = 40,
        tune_step: int = 8,
    ) -> BytesIO:
        """
        Core method: accepts PIL.Image and returns PNG bytes (BytesIO).
        - coord_type: "auto"/"normalized"/"points"/"pixels"
        - auto_tune: if True, performs a small grid search using numpy to maximize dark pixel overlap.
        """
        t0 = time.time()
        print("Highlighting start")
        w, h = img.size
        print(f"Image size: {w} x {h}")

        if len(polygon_flat) % 2 != 0:
            raise ValueError("polygon_flat must have even number of values")

        # convert flat list to pairs (float)
        poly_pairs = self._flat_to_pairs(polygon_flat)
        print("Original polygon (units):", poly_pairs)

        # detect/scale to pixels
        polygon_px, diag = self._map_to_pixels(poly_pairs, (w, h), coord_type=coord_type, pdf_page_size=pdf_page_size, flip_y=True)
        print("Mapping diagnostics:", diag)

        # small amplifier for visibility
        bbox_w = (max(p[0] for p in polygon_px) - min(p[0] for p in polygon_px)) if polygon_px else 0
        bbox_h = (max(p[1] for p in polygon_px) - min(p[1] for p in polygon_px)) if polygon_px else 0
        print(f"Mapped bbox (w={bbox_w}, h={bbox_h})")
        if bbox_w < self.amplify_threshold_px or bbox_h < self.amplify_threshold_px:
            polygon_px, factor = self._maybe_amplify(polygon_px, (w, h))
            print(f"Amplified polygon by factor ~{factor:.2f}; new bbox approx: {max(p[0] for p in polygon_px)-min(p[0] for p in polygon_px)} x {max(p[1] for p in polygon_px)-min(p[1] for p in polygon_px)}")

        # optional auto-tune (translation) to align with dark text
        if auto_tune:
            if np is None:
                print("Auto-tune requested but numpy is not installed; skipping auto-tune.")
            else:
                print("Auto-tune: grid-searching small translations to maximize dark pixel coverage")
                gray_arr = np.asarray(ImageOps.grayscale(img), dtype=np.uint8)
                best_score = -1.0
                best_tx = best_ty = 0
                txs = list(range(-tune_radius, tune_radius + 1, tune_step))
                tys = list(range(-tune_radius, tune_radius + 1, tune_step))
                total = len(txs) * len(tys)
                if total > 5000:
                    print(f"Tuning grid ({total}) too large; reduce radius/step. Skipping tuning.")
                else:
                    for tx in txs:
                        for ty in tys:
                            test_poly = [(x + tx, y + ty) for x, y in polygon_px]
                            # render mask quickly into numpy and score
                            mask = Image.new("L", (w, h), 0)
                            ImageDraw.Draw(mask).polygon(test_poly, fill=255)
                            mask_np = np.asarray(mask, dtype=np.uint8) > 0
                            if mask_np.sum() == 0:
                                continue
                            score = float(((255 - gray_arr) * mask_np).sum())
                            if score > best_score:
                                best_score = score
                                best_tx = tx
                                best_ty = ty
                    print(f"Auto-tune best tx={best_tx}, ty={best_ty}, score={best_score:.1f}")
                    polygon_px = [(x + best_tx, y + best_ty) for x, y in polygon_px]

        print("Final polygon (pixels):", polygon_px[:12], ("(...)" if len(polygon_px) > 12 else ""))

        # draw overlay and compose
        merged = self._draw_overlay(img, polygon_px)

        # save to BytesIO (fast settings)
        out = BytesIO()
        merged.save(out, format="PNG", compress_level=1, optimize=False)
        out.seek(0)
        elapsed = time.time() - t0
        print(f"Highlight complete in {elapsed:.3f}s")
        return out


# -------------------------
# Minimal main usage block
# -------------------------
if __name__ == "__main__":
    # ONLY define path and polygon here — keep main minimal per request
    IMAGE_PATH = r"C:\Users\SAHUAX19\Documents\page_1.png"
    POLYGON = [3.2742, 1.5965, 5.7768, 1.5991, 5.7766, 1.8248, 3.274, 1.8221]

    print("Simple test run of PNGHighlighter (main will only call the class)...")
    highlighter = PNGHighlighter()
    # call with auto_tune True for best alignment (set False to skip tuning)
    try:
        result_stream = highlighter.highlight_from_path(IMAGE_PATH, POLYGON, coord_type="auto", auto_tune=True, tune_radius=40, tune_step=8)
        # write out for inspection
        out_file = Path("page_1_highlighted_class.png")
        with open(out_file, "wb") as f:
            f.write(result_stream.getvalue())
        print(f"Saved highlighted output to: {out_file}")
    except Exception as exc:
        print("Error during highlight:", exc)