#!/usr/bin/env python3
"""
pdf_image_highlighter_smartscale.py

Fast class-based highlighter with robust scaling selection:
- Try multiple scale heuristics and pick the one with best initial darkness overlap
- Use numpy-based mask translation + scoring for fast autotune
- Returns BytesIO of final PNG and saves debug overlay files

Requirements:
    pip install pillow numpy
"""

from pathlib import Path
from typing import List, Tuple, Union
from io import BytesIO
from PIL import Image, ImageDraw, ImageOps
import numpy as np
import time


class PDFImageHighlighter:
    def __init__(
        self,
        fill_color=(255, 255, 0, 160),
        outline_color=(255, 0, 0, 220),
        outline_width=3,
        tune_radius=80,
        tune_step=8,
        manual_scale_x=1.0,
        manual_scale_y=1.0,
        auto_tune=True,
        debug_prefix="_fast_smart"
    ):
        self.fill_color = fill_color
        self.outline_color = outline_color
        self.outline_width = outline_width
        self.tune_radius = tune_radius
        self.tune_step = tune_step
        self.manual_scale_x = manual_scale_x
        self.manual_scale_y = manual_scale_y
        self.auto_tune = auto_tune
        self.debug_prefix = debug_prefix

    # -----------------------------
    # Helpers
    # -----------------------------
    @staticmethod
    def _flat_to_pairs(flat: List[float]) -> List[Tuple[float, float]]:
        if len(flat) % 2 != 0:
            raise ValueError("Polygon list must contain even number of entries.")
        return [(float(flat[i]), float(flat[i + 1])) for i in range(0, len(flat), 2)]

    @staticmethod
    def _map_and_flip(poly_pairs, img_size, sx, sy):
        w, h = img_size
        mapped = []
        for x, y in poly_pairs:
            px = x * sx
            py = y * sy
            py_flipped = h - py  # PDF bottom-left → top-left
            mapped.append((int(round(px)), int(round(py_flipped))))
        # Clamp inside image
        return [(max(0, min(w - 1, xx)), max(0, min(h - 1, yy))) for xx, yy in mapped]

    @staticmethod
    def _polygon_to_mask_numpy(poly, img_size):
        mask = Image.new("L", img_size, 0)
        draw = ImageDraw.Draw(mask)
        if poly:
            draw.polygon(poly, fill=255)
        arr = np.asarray(mask, dtype=np.uint8)
        return (arr // 255).astype(np.uint8)  # shape (h,w), values 0/1

    @staticmethod
    def _translate_mask(mask, tx, ty):
        if tx == 0 and ty == 0:
            return mask
        rolled = np.roll(mask, shift=(ty, tx), axis=(0, 1))
        h, w = mask.shape
        if tx > 0:
            rolled[:, :tx] = 0
        elif tx < 0:
            rolled[:, tx:] = 0
        if ty > 0:
            rolled[:ty, :] = 0
        elif ty < 0:
            rolled[ty:, :] = 0
        return rolled

    @staticmethod
    def _score_mask_on_gray(mask_bin: np.ndarray, gray_arr: np.ndarray) -> float:
        # darkness = 255 - brightness
        darkness = (255 - gray_arr).astype(np.int64)
        return float((darkness * mask_bin.astype(np.int64)).sum())

    @staticmethod
    def _translate_polygon(poly, tx, ty):
        return [(x + tx, y + ty) for x, y in poly]

    def _draw_overlay(self, img, mapped_poly, out_path, overlay_only=False):
        overlay = Image.new("RGBA", img.size, (255, 255, 255, 0))
        draw = ImageDraw.Draw(overlay)
        if mapped_poly:
            draw.polygon(mapped_poly, fill=self.fill_color)
            draw.line(list(mapped_poly) + [mapped_poly[0]], width=self.outline_width, fill=self.outline_color)
        out_img = overlay if overlay_only else Image.alpha_composite(img.convert("RGBA"), overlay)
        out_img.save(out_path, format="PNG", compress_level=1, optimize=True)

    # -----------------------------
    # Scale candidate evaluation
    # -----------------------------
    def _candidate_scales(self, poly_pairs: List[Tuple[float, float]], img_size: Tuple[int,int]):
        """
        Return list of (name, (sx, sy)) candidates.
        Candidate heuristics:
         - 'normalized10': scale by /10
         - 'auto_max': scale by max_x / max_y (original approach)
         - 'pixel': 1.0 (no scaling)
        """
        w,h = img_size
        xs = [abs(x) for x,_ in poly_pairs] or [1.0]
        ys = [abs(y) for _,y in poly_pairs] or [1.0]
        max_x, max_y = max(xs), max(ys)

        candidates = []

        # normalized10 candidate (for PDF-like 0..10 ranges)
        candidates.append(("normalized10", ( (w/10.0) * self.manual_scale_x, (h/10.0) * self.manual_scale_y )))

        # auto_max candidate (original slow script heuristic)
        if max_x > 0 and max_y > 0:
            candidates.append(("auto_max", ( (w / max_x) * self.manual_scale_x, (h / max_y) * self.manual_scale_y )))
        else:
            candidates.append(("auto_max", ( (w/10.0) * self.manual_scale_x, (h/10.0) * self.manual_scale_y )))

        # pixel-scale candidate
        candidates.append(("pixel", (1.0 * self.manual_scale_x, 1.0 * self.manual_scale_y)))

        return candidates

    # -----------------------------
    # Public method
    # -----------------------------
    def highlight_image(self, image_path: Union[str, Path], polygon_flat: List[float]) -> BytesIO:
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        img = Image.open(image_path)
        w, h = img.size
        print(f"[info] Image size: {w}x{h}")

        poly_pairs = self._flat_to_pairs(polygon_flat)
        print(f"[info] Raw polygon pairs: {poly_pairs}")

        # Prepare grayscale numpy array for scoring
        gray = np.asarray(ImageOps.grayscale(img), dtype=np.uint8)

        # Evaluate scale candidates by computing quick base darkness score (no translation)
        candidates = self._candidate_scales(poly_pairs, (w,h))
        best_name = None
        best_score = -1.0
        best_mapped = None
        best_base_mask = None

        print("[info] Evaluating scale candidates...")
        for name, (sx, sy) in candidates:
            mapped_candidate = self._map_and_flip(poly_pairs, (w,h), sx, sy)
            base_mask = self._polygon_to_mask_numpy(mapped_candidate, (w,h))  # shape (h,w)
            score = self._score_mask_on_gray(base_mask, gray)
            print(f"  [candidate] {name:12s} sx={sx:.2f}, sy={sy:.2f} -> base_score={score:.1f}, mask_pixels={base_mask.sum()}")
            if score > best_score:
                best_score = score
                best_name = name
                best_mapped = mapped_candidate
                best_base_mask = base_mask

        print(f"[info] Chosen scale: {best_name} (base_score={best_score:.1f})")
        mapped = best_mapped
        base_mask = best_base_mask

        # If bbox tiny, amplify for visibility (same as before)
        xs = [p[0] for p in mapped] if mapped else [0]
        ys = [p[1] for p in mapped] if mapped else [0]
        bbox_w = max(xs) - min(xs) if xs else 0
        bbox_h = max(ys) - min(ys) if ys else 0

        if bbox_w < 10 or bbox_h < 10:
            target = 40
            amp = max(target / max(1, bbox_w), target / max(1, bbox_h))
            print(f"[info] Amplifying small bbox by {amp:.2f} for visibility")
            cx = sum(xs) / len(xs)
            cy = sum(ys) / len(ys)
            mapped = [(int(round((x-cx)*amp + cx)), int(round((y-cy)*amp + cy))) for x,y in mapped]
            mapped = [(max(0, min(w-1, x)), max(0, min(h-1, y))) for x,y in mapped]
            base_mask = self._polygon_to_mask_numpy(mapped, (w,h))

        # Auto-tune translation (fast numpy approach) if requested
        best_tx = best_ty = 0
        if self.auto_tune:
            txs = list(range(-self.tune_radius, self.tune_radius + 1, self.tune_step))
            tys = list(range(-self.tune_radius, self.tune_radius + 1, self.tune_step))
            print(f"[info] Auto-tuning translation (radius={self.tune_radius}, step={self.tune_step}) -> {len(txs)*len(tys)} combos")
            t0 = time.time()
            darkness = (255 - gray).astype(np.int64)
            best_score = -1.0
            for tx in txs:
                for ty in tys:
                    rolled = self._translate_mask(base_mask, tx, ty)
                    score = float((darkness * rolled.astype(np.int64)).sum())
                    if score > best_score:
                        best_score = score
                        best_tx, best_ty = tx, ty
            t1 = time.time()
            print(f"[info] Auto-tune complete in {t1 - t0:.2f}s | best offset=({best_tx},{best_ty}), score={best_score:.1f}")
            mapped = self._translate_polygon(mapped, best_tx, best_ty)

        # Clip polygon coordinates to image bounds (safeguard)
        mapped = [(max(0, min(w-1, x)), max(0, min(h-1, y))) for x,y in mapped]

        # Save overlay + merged debug images
        output_path = image_path.with_name(image_path.stem + f"{self.debug_prefix}_highlighted.png")
        overlay_path = image_path.with_name(image_path.stem + f"{self.debug_prefix}_overlay.png")
        self._draw_overlay(img, mapped, output_path, overlay_only=False)
        self._draw_overlay(img, mapped, overlay_path, overlay_only=True)
        print(f"[output] Saved highlighted: {output_path}")
        print(f"[output] Saved overlay-only: {overlay_path}")

        # Return merged PNG as BytesIO
        out_stream = BytesIO()
        result_img = Image.alpha_composite(img.convert("RGBA"), Image.open(overlay_path).convert("RGBA"))
        result_img.save(out_stream, format="PNG")
        out_stream.seek(0)
        return out_stream


# -----------------------------
# Example usage
# -----------------------------
if __name__ == "__main__":
    IMAGE_PATH = r"C:\Users\SAHUAX19\Documents\page_1.png"
    POLYGON_FLAT = [3.2662, 1.8396, 5.7788, 1.83, 5.7801, 2.1552, 3.2675, 2.1649]

    highlighter = PDFImageHighlighter()
    result_stream = highlighter.highlight_image(IMAGE_PATH, POLYGON_FLAT)
    with open("highlight_result_smart.png", "wb") as f:
        f.write(result_stream.getvalue())
    print("Done - saved highlight_result_smart.png")