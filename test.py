#!/usr/bin/env python3
"""
highlighter_autoselect_fixed.py

Fixed class-based highlighter that auto-selects coordinate mapping.
This version removes accidental recursion bugs and is safe to run.
"""

from pathlib import Path
from typing import List, Tuple, Optional, Union
from io import BytesIO
from PIL import Image, ImageDraw, ImageOps
import time

# numpy optional (used only for scoring in auto-select)
try:
    import numpy as np
except Exception:
    np = None


class PNGHighlighterAutoSelect:
    def __init__(
        self,
        fill_color: Tuple[int, int, int, int] = (255, 255, 0, 150),
        outline_color: Tuple[int, int, int, int] = (255, 0, 0, 220),
        outline_width: int = 3,
        tune_radius: int = 20,
        tune_step: int = 10,
        max_combinations: int = 2000,
        amplify_target_px: int = 40,
    ):
        self.fill_color = fill_color
        self.outline_color = outline_color
        self.outline_width = outline_width
        self.tune_radius = tune_radius
        self.tune_step = tune_step
        self.max_combinations = max_combinations
        self.amplify_target_px = amplify_target_px

    # ------------------- pure helpers (no alias recursion) -------------------
    @staticmethod
    def flat_to_pairs(flat: List[float]) -> List[Tuple[float, float]]:
        if len(flat) % 2 != 0:
            raise ValueError("Flat polygon must contain an even number of values (x,y pairs).")
        return [(float(flat[i]), float(flat[i + 1])) for i in range(0, len(flat), 2)]

    @staticmethod
    def detect_coord_type(pairs: List[Tuple[float, float]]) -> str:
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
    def map_pairs_to_pixels(pairs: List[Tuple[float, float]],
                            img_size: Tuple[int, int],
                            coord_type: str,
                            flip_y: bool,
                            pdf_page_size: Optional[Tuple[float, float]] = None) -> List[Tuple[int, int]]:
        """
        Convert coordinate pairs to pixel (int,int) pairs using specified coord_type and flip.
        coord_type: 'normalized'|'points'|'pixels'
        flip_y: if True, treat input origin as bottom-left (PDF) and flip to top-left
        """
        w, h = img_size

        if coord_type == "normalized":
            mapped = [(x * w, y * h) for x, y in pairs]

        elif coord_type == "points":
            if pdf_page_size:
                pw, ph = pdf_page_size
                sx, sy = w / pw, h / ph
            else:
                xs = [x for x, _ in pairs] or [1.0]
                ys = [y for _, y in pairs] or [1.0]
                bbox_w = max(xs) - min(xs) if xs else 1.0
                bbox_h = max(ys) - min(ys) if ys else 1.0
                sx, sy = w / max(1.0, bbox_w), h / max(1.0, bbox_h)
            mapped = [(x * sx, y * sy) for x, y in pairs]

        else:  # pixels
            mapped = [(x, y) for x, y in pairs]

        # flip if required
        if flip_y:
            mapped = [(int(round(px)), int(round(h - py))) for px, py in mapped]
        else:
            mapped = [(int(round(px)), int(round(py))) for px, py in mapped]

        # clamp inside image bounds
        mapped = [(max(0, min(w - 1, x)), max(0, min(h - 1, y))) for x, y in mapped]
        return mapped

    @staticmethod
    def polygon_mask_bool(poly_px: List[Tuple[int, int]], img_size: Tuple[int, int]):
        # returns boolean numpy mask if numpy present, else PIL mask image
        w, h = img_size
        mask = Image.new("L", (w, h), 0)
        if poly_px:
            ImageDraw.Draw(mask).polygon(poly_px, fill=255)
        if np is not None:
            return np.asarray(mask, dtype=np.uint8) > 0
        else:
            return mask  # PIL Image - caller must handle

    @staticmethod
    def score_mask_on_gray(mask_bool, gray_arr):
        # mask_bool can be numpy bool array or PIL Image
        if np is None:
            # approximate scoring without numpy (less efficient)
            mask_arr = np_none_to_list(mask_bool)
            # but since numpy is missing we'll return simple heuristic 0 to avoid crash
            return 0.0
        if mask_bool.sum() == 0:
            return 0.0
        darkness = (255 - gray_arr).astype(np.int64)
        return float((darkness * mask_bool).sum())

    @staticmethod
    def amplify_if_tiny(poly_px: List[Tuple[int, int]], img_size: Tuple[int, int], target_px: int):
        if not poly_px:
            return poly_px, 1.0
        xs = [p[0] for p in poly_px]; ys = [p[1] for p in poly_px]
        minx, maxx = min(xs), max(xs); miny, maxy = min(ys), max(ys)
        bw, bh = maxx - minx, maxy - miny
        smallest = min(bw if bw > 0 else 1, bh if bh > 0 else 1)
        if smallest >= target_px:
            return poly_px, 1.0
        cx, cy = (minx + maxx) / 2.0, (miny + maxy) / 2.0
        factor = max(1.0, target_px / max(1, smallest))
        w, h = img_size
        new = []
        for x, y in poly_px:
            nx = int(round((x - cx) * factor + cx))
            ny = int(round((y - cy) * factor + cy))
            nx = max(0, min(w - 1, nx)); ny = max(0, min(h - 1, ny))
            new.append((nx, ny))
        return new, factor

    @staticmethod
    def draw_overlay_and_merged(pil_img: Image.Image, poly_px: List[Tuple[int, int]], fill_color, outline_color, outline_width):
        w, h = pil_img.size
        overlay = Image.new("RGBA", (w, h), (255, 255, 255, 0))
        if poly_px:
            draw = ImageDraw.Draw(overlay)
            draw.polygon(poly_px, fill=fill_color)
            draw.line(list(poly_px) + [poly_px[0]], width=outline_width, fill=outline_color)
        merged = Image.alpha_composite(pil_img.convert("RGBA"), overlay)
        return overlay, merged

    # ------------------- main function -------------------
    def highlight_from_path(self,
                            image_path: Union[str, Path],
                            polygon_flat: List[float],
                            pdf_page_size: Optional[Tuple[float, float]] = None,
                            try_modes: Optional[List[str]] = None,
                            try_flips: Optional[List[bool]] = None,
                            enable_tuning: bool = True):
        """
        Main entry: tries multiple mappings and selects the best by scoring dark pixel overlap.
        Returns (BytesIO_of_merged_image, diagnostics_dict)
        """
        start = time.time()
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"{image_path} not found")
        pil = Image.open(image_path)
        w, h = pil.size
        img_size = (w, h)
        print(f"[auto-select] loaded {image_path} size={img_size}")

        pairs = self.flat_to_pairs(polygon_flat)
        print(f"[auto-select] raw pairs: {pairs}")

        if try_modes is None:
            # 'auto' replaced by detected ordering below
            try_modes = ["auto", "normalized", "points", "pixels"]
        if try_flips is None:
            try_flips = [True, False]

        # choose modes order if 'auto'
        modes_to_try = []
        if "auto" in try_modes:
            det = self.detect_coord_type(pairs)
            # put detected first, then others
            modes_to_try = [det] + [m for m in ["normalized", "points", "pixels"] if m != det]
        else:
            modes_to_try = try_modes

        # prepare grayscale numpy arr if available
        gray_arr = None
        if np is not None:
            gray_arr = np.asarray(ImageOps.grayscale(pil), dtype=np.uint8)

        best = {"score": -1.0}
        tested = 0

        # iterate candidates
        for mode in modes_to_try:
            for flip in try_flips:
                # map
                try:
                    mapped = self.map_pairs_to_pixels(pairs, img_size, coord_type=mode, flip_y=flip, pdf_page_size=pdf_page_size)
                except Exception as e:
                    print(f"[auto-select] mapping failed for mode={mode} flip={flip}: {e}")
                    continue

                # amplify for scoring so tiny shapes count
                mapped_for_scoring, factor = self.amplify_if_tiny(mapped, img_size, self.amplify_target_px)

                # get mask and score (skip scoring if numpy not available -> assign heuristic)
                if np is not None:
                    mask_bool = self.polygon_mask_bool(mapped_for_scoring, img_size)
                    score = self.score_mask_on_gray(mask_bool, gray_arr)
                else:
                    # heuristic: score based on area of mask (fallback)
                    area = 0
                    try:
                        tmp = Image.new("L", img_size, 0)
                        ImageDraw.Draw(tmp).polygon(mapped_for_scoring, fill=255)
                        area = sum(tmp.getdata()) // 255
                    except Exception:
                        area = 0
                    score = float(area)

                tested += 1
                if score > best["score"]:
                    best = {
                        "score": score,
                        "mode": mode,
                        "flip": flip,
                        "mapped": mapped,
                        "mapped_for_scoring": mapped_for_scoring,
                        "factor": factor,
                    }

                print(f"[candidate] mode={mode:10s} flip={flip} score={score:.1f} area_factor={factor:.2f}")

                if tested > self.max_combinations:
                    print("[auto-select] safety cap reached, stopping candidate search")
                    break

        print(f"[auto-select] chosen: mode={best['mode']} flip={best['flip']} score={best['score']:.1f}")

        # optional small local tuning (translation)
        final_poly = best["mapped"]
        if enable_tuning and best["score"] > 0 and np is not None:
            best_t = {"score": best["score"], "tx": 0, "ty": 0}
            txs = list(range(-self.tune_radius, self.tune_radius + 1, self.tune_step))
            tys = list(range(-self.tune_radius, self.tune_radius + 1, self.tune_step))
            # safety cap on tuning combos
            if len(txs) * len(tys) <= self.max_combinations:
                for tx in txs:
                    for ty in tys:
                        test_poly = [(x + tx, y + ty) for x, y in best["mapped"]]
                        mask_bool = self.polygon_mask_bool(test_poly, img_size)
                        sc = self.score_mask_on_gray(mask_bool, gray_arr)
                        if sc > best_t["score"]:
                            best_t = {"score": sc, "tx": tx, "ty": ty}
                if best_t["tx"] != 0 or best_t["ty"] != 0:
                    final_poly = [(x + best_t["tx"], y + best_t["ty"]) for x, y in best["mapped"]]
                    print(f"[tune] applied tx={best_t['tx']} ty={best_t['ty']} new_score={best_t['score']:.1f}")
            else:
                print("[tune] tuning grid too large, skipped")

        # ensure ints & clamp
        final_poly = [(int(round(x)), int(round(y))) for x, y in final_poly]
        final_poly = [(max(0, min(w - 1, x)), max(0, min(h - 1, y))) for x, y in final_poly]

        # draw & save overlay + merged
        overlay, merged = self.draw_overlay_and_merged(pil, final_poly, self.fill_color, self.outline_color, self.outline_width)
        base = image_path.stem
        overlay_path = image_path.with_name(f"{base}_overlay_selected_fixed.png")
        merged_path = image_path.with_name(f"{base}_highlighted_selected_fixed.png")
        overlay.save(overlay_path, format="PNG", compress_level=1)
        merged.save(merged_path, format="PNG", compress_level=1)

        elapsed = time.time() - start
        print(f"[auto-select] completed in {elapsed:.3f}s -> {overlay_path}, {merged_path}")

        # return bytesio and diagnostics
        buf = BytesIO()
        merged.save(buf, format="PNG", compress_level=1)
        buf.seek(0)
        diagnostics = {
            "overlay_path": str(overlay_path),
            "merged_path": str(merged_path),
            "chosen_mode": best["mode"],
            "chosen_flip": best["flip"],
            "score": best["score"],
        }
        return buf, diagnostics


# -------------------------
# Minimal main: only path + polygon + call
# -------------------------
if __name__ == "__main__":
    IMAGE_PATH = Path(r"C:\Users\SAHUAX19\Documents\page_1.png")
    POLYGON_FLAT = [3.2742, 1.5965, 5.7768, 1.5991, 5.7766, 1.8248, 3.274, 1.8221]

    highlighter = PNGHighlighterAutoSelect()
    buf, diag = highlighter.highlight_from_path(IMAGE_PATH, POLYGON_FLAT, enable_tuning=True)
    print("Diagnostics:", diag)
    # file outputs saved next to input image