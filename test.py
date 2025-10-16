#!/usr/bin/env python3
"""
pdf_image_highlighter_integrated.py

Single-file, class-based highlighter with robust adaptive scaling selection,
penalized candidate scoring, and adaptive autotune radius.

Public interface:
    highlighter = PDFImageHighlighter(...)
    stream = highlighter.highlight_image(image_path, polygon_flat)

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
        debug_prefix="_fast_smart",
        # penalties / heuristics (tweakable)
        max_mask_frac: float = 0.25,     # >25% mask = penalize
        max_scale_ratio: float = 3.0,    # sx/sy > 3 => penalize
        area_penalty_power: float = 1.5, # penalty non-linearity
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

        # penalties
        self.max_mask_frac = max_mask_frac
        self.max_scale_ratio = max_scale_ratio
        self.area_penalty_power = area_penalty_power

    # -----------------------------
    # Basic helpers
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
            py_flipped = h - py  # PDF bottom-left -> image top-left
            mapped.append((int(round(px)), int(round(py_flipped))))
        # clamp inside image
        return [(max(0, min(w - 1, xx)), max(0, min(h - 1, yy))) for xx, yy in mapped]

    @staticmethod
    def _polygon_to_mask_numpy(poly, img_size):
        """Rasterize polygon to binary mask using PIL; return (h,w) array of 0/1."""
        mask = Image.new("L", img_size, 0)
        draw = ImageDraw.Draw(mask)
        if poly:
            draw.polygon(poly, fill=255)
        arr = np.asarray(mask, dtype=np.uint8)
        return (arr // 255).astype(np.uint8)

    @staticmethod
    def _translate_mask(mask, tx, ty):
        """Fast roll with zeroing wrapped parts to avoid wrapping artifacts."""
        if tx == 0 and ty == 0:
            return mask
        rolled = np.roll(mask, shift=(ty, tx), axis=(0, 1))
        h, w = mask.shape
        # zero out wrapped-in regions
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
    # Candidate scale generation
    # -----------------------------
    def _candidate_scales(self, poly_pairs: List[Tuple[float, float]], img_size: Tuple[int,int]):
        """
        Return name->(sx,sy) list of plausible candidate scalings:
         - normalized10: assume coords in ~0..10
         - auto_max: scale by dividing by max_x/max_y (original)
         - pixel: treat coords as already pixel coords
        """
        w, h = img_size
        xs = [abs(x) for x, _ in poly_pairs] or [1.0]
        ys = [abs(y) for _, y in poly_pairs] or [1.0]
        max_x, max_y = max(xs), max(ys)

        candidates = []
        # normalized 0..10 style
        candidates.append(("normalized10", ((w / 10.0) * self.manual_scale_x, (h / 10.0) * self.manual_scale_y)))
        # auto_max (original approach)
        if max_x > 0 and max_y > 0:
            candidates.append(("auto_max", ((w / max_x) * self.manual_scale_x, (h / max_y) * self.manual_scale_y)))
        else:
            candidates.append(("auto_max", ((w / 10.0) * self.manual_scale_x, (h / 10.0) * self.manual_scale_y)))
        # pixel coords (no scaling)
        candidates.append(("pixel", (1.0 * self.manual_scale_x, 1.0 * self.manual_scale_y)))
        return candidates

    # -----------------------------
    # Main method
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

        # prepare grayscale array for scoring
        gray = np.asarray(ImageOps.grayscale(img), dtype=np.uint8)

        # Evaluate candidate scalings with penalized effective score
        candidates = self._candidate_scales(poly_pairs, (w, h))
        image_area = float(w * h)
        best_name = None
        best_mapped = None
        best_base_mask = None
        best_effective_score = -1.0
        chosen_sx_sy = (1.0, 1.0)

        print("[info] Evaluating scale candidates (penalized)...")
        for name, (sx, sy) in candidates:
            mapped_candidate = self._map_and_flip(poly_pairs, (w, h), sx, sy)
            base_mask = self._polygon_to_mask_numpy(mapped_candidate, (w, h))
            # base raw darkness score under mask
            darkness = (255 - gray).astype(np.int64)
            base_score = float((darkness * base_mask.astype(np.int64)).sum())
            mask_pixels = float(base_mask.sum())
            mask_frac = mask_pixels / image_area if image_area > 0 else 0.0

            # area penalty (bigger mask => stronger penalty)
            if mask_frac <= self.max_mask_frac:
                area_penalty = 1.0
            else:
                # taper penalty as mask_frac grows above threshold
                area_penalty = max(0.01, 1.0 - (mask_frac - self.max_mask_frac) ** self.area_penalty_power)

            # scale ratio penalty (avoid extreme sx/sy)
            ratio = (max(sx, sy) / (min(sx, sy) + 1e-9))
            if ratio <= self.max_scale_ratio:
                ratio_penalty = 1.0
            else:
                ratio_penalty = max(0.01, 1.0 / (ratio / self.max_scale_ratio))

            effective_score = base_score * area_penalty * ratio_penalty

            print(
                f"  [candidate] {name:12s} sx={sx:.2f}, sy={sy:.2f} -> base={base_score:.1f}, "
                f"mask_frac={mask_frac:.3f}, ratio={ratio:.2f}, eff={effective_score:.1f}"
            )

            if effective_score > best_effective_score:
                best_effective_score = effective_score
                best_name = name
                best_mapped = mapped_candidate
                best_base_mask = base_mask
                chosen_sx_sy = (sx, sy)

        print(f"[info] Chosen scale candidate: {best_name} (effective_score={best_effective_score:.1f})")
        mapped = best_mapped
        base_mask = best_base_mask

        # if mapped bbox is tiny, amplify for visibility (same approach as earlier)
        xs = [p[0] for p in mapped] if mapped else [0]
        ys = [p[1] for p in mapped] if mapped else [0]
        bbox_w = (max(xs) - min(xs)) if xs else 0
        bbox_h = (max(ys) - min(ys)) if ys else 0

        if bbox_w < 10 or bbox_h < 10:
            target = 40
            amp = max(target / max(1, bbox_w), target / max(1, bbox_h))
            print(f"[info] Amplifying small bbox by {amp:.2f} for visibility")
            cx = sum(xs) / len(xs)
            cy = sum(ys) / len(ys)
            mapped = [(int(round((x - cx) * amp + cx)), int(round((y - cy) * amp + cy))) for x, y in mapped]
            mapped = [(max(0, min(w - 1, x)), max(0, min(h - 1, y))) for x, y in mapped]
            base_mask = self._polygon_to_mask_numpy(mapped, (w, h))
            xs = [p[0] for p in mapped]; ys = [p[1] for p in mapped]
            bbox_w = (max(xs) - min(xs)) if xs else bbox_w
            bbox_h = (max(ys) - min(ys)) if ys else bbox_h

        # Adaptive autotune radius derived from bbox (so large masks don't move huge distances)
        adaptive_radius = max(20, int(max(bbox_w, bbox_h) * 0.5))  # half bbox, min 20
        adaptive_radius = min(adaptive_radius, self.tune_radius)
        adaptive_step = max(4, int(self.tune_step))  # reasonable min
        txs = list(range(-adaptive_radius, adaptive_radius + 1, adaptive_step))
        tys = list(range(-adaptive_radius, adaptive_radius + 1, adaptive_step))

        if self.auto_tune:
            print(f"[info] Auto-tuning translation (adaptive radius={adaptive_radius}, step={adaptive_step}) -> {len(txs)*len(tys)} combos")
            t0 = time.time()
            darkness = (255 - gray).astype(np.int64)
            best_score = -1.0
            best_tx = best_ty = 0
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
        else:
            print("[info] Auto-tune disabled; skipping translation search.")

        # Clip polygon coordinates to image bounds (safeguard)
        mapped = [(max(0, min(w - 1, x)), max(0, min(h - 1, y))) for x, y in mapped]

        # Save overlay & merged debug images
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
# Example usage (minimal)
# -----------------------------
if __name__ == "__main__":
    # Edit these to test locally
    IMAGE_PATH = r"C:\Users\SAHUAX19\Documents\page_1.png"  # change to your path
    POLYGON_FLAT = [
        3.2742, 1.5965, 5.7768, 1.5991, 5.7766, 1.8248, 3.274, 1.8221
    ]  # flat list from your OCR system / JSON

    highlighter = PDFImageHighlighter(
        tune_radius=80,
        tune_step=8,
        auto_tune=True,
        debug_prefix="_integrated"
    )

    print("Running highlight...")
    stream = highlighter.highlight_image(IMAGE_PATH, POLYGON_FLAT)

    out_file = Path("highlight_result_integrated.png")
    with out_file.open("wb") as f:
        f.write(stream.getvalue())
    print("Saved final result to", out_file.resolve())