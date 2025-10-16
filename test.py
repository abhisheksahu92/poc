#!/usr/bin/env python3
"""
pdf_image_highlighter_fixed_scale.py

Fast, class-based highlighter using numpy for fast autotune.
Scale heuristic matches your original working script:
- if coords max <= 1 -> normalized (sx = w, sy = h)
- else -> sx = w / max_x, sy = h / max_y

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
    ):
        self.fill_color = fill_color
        self.outline_color = outline_color
        self.outline_width = outline_width
        self.tune_radius = tune_radius
        self.tune_step = tune_step
        self.manual_scale_x = manual_scale_x
        self.manual_scale_y = manual_scale_y
        self.auto_tune = auto_tune

    # -----------------------------
    # Internal helpers
    # -----------------------------
    @staticmethod
    def _flat_to_pairs(flat: List[float]) -> List[Tuple[float, float]]:
        if len(flat) % 2 != 0:
            raise ValueError("Polygon list must contain even number of entries.")
        return [(float(flat[i]), float(flat[i + 1])) for i in range(0, len(flat), 2)]

    def _compute_auto_scale(self, poly_pairs, img_size):
        # THIS MATCHES YOUR ORIGINAL SLOW SCRIPT'S HEURISTIC
        w, h = img_size
        xs = [abs(x) for x, _ in poly_pairs] or [1.0]
        ys = [abs(y) for _, y in poly_pairs] or [1.0]
        max_x, max_y = max(xs), max(ys)

        if max_x <= 1.0 and max_y <= 1.0:
            sx = w
            sy = h
        else:
            sx = w / max_x
            sy = h / max_y

        return sx * self.manual_scale_x, sy * self.manual_scale_y

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
        return (arr // 255).astype(np.uint8)

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
    def _score_mask(mask, gray_arr):
        darkness = 255 - gray_arr
        return float((darkness.astype(np.int64) * mask.astype(np.int64)).sum())

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
    # Public main method
    # -----------------------------
    def highlight_image(self, image_path: Union[str, Path], polygon_flat: List[float]) -> BytesIO:
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        img = Image.open(image_path)
        w, h = img.size
        print(f"[info] Image size: {w}x{h}")

        poly_pairs = self._flat_to_pairs(polygon_flat)
        sx, sy = self._compute_auto_scale(poly_pairs, (w, h))
        mapped = self._map_and_flip(poly_pairs, (w, h), sx, sy)
        print("[info] Initial mapped polygon:", mapped)

        # Build grayscale + binary mask
        gray = np.asarray(ImageOps.grayscale(img), dtype=np.uint8)
        base_mask = self._polygon_to_mask_numpy(mapped, (w, h))

        best_tx = best_ty = 0
        best_score = -1.0
        chosen_mask = base_mask

        if self.auto_tune:
            txs = list(range(-self.tune_radius, self.tune_radius + 1, self.tune_step))
            tys = list(range(-self.tune_radius, self.tune_radius + 1, self.tune_step))
            total = len(txs) * len(tys)
            print(f"[info] Auto-tuning translation ({total} combos)...")
            t0 = time.time()
            darkness = (255 - gray).astype(np.int64)

            for tx in txs:
                for ty in tys:
                    rolled = self._translate_mask(base_mask, tx, ty)
                    score = float((darkness * rolled.astype(np.int64)).sum())
                    if score > best_score:
                        best_score = score
                        best_tx, best_ty = tx, ty
                        chosen_mask = rolled

            t1 = time.time()
            print(f"[info] Auto-tune complete in {t1 - t0:.2f}s | best offset=({best_tx},{best_ty})")

            mapped = self._translate_polygon(mapped, best_tx, best_ty)

        # Save debug overlay + merged
        output_path = image_path.with_name(image_path.stem + "_highlighted_fast_fixed.png")
        overlay_path = image_path.with_name(image_path.stem + "_overlay_fast_fixed.png")

        self._draw_overlay(img, mapped, output_path, overlay_only=False)
        self._draw_overlay(img, mapped, overlay_path, overlay_only=True)

        print(f"[output] Saved: {output_path}")
        print(f"[output] Saved: {overlay_path}")

        # Return image as BytesIO binary stream
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
    stream = highlighter.highlight_image(IMAGE_PATH, POLYGON_FLAT)

    with open("highlight_result_fast_fixed.png", "wb") as f:
        f.write(stream.getvalue())
    print("✅ Highlight completed and saved as highlight_result_fast_fixed.png")