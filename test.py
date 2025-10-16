#!/usr/bin/env python3
"""
highlighter_autoselect.py

Class-based highlighter that attempts multiple mapping strategies and selects
the one that best overlaps dark pixels (text).

- Tries coord types: 'normalized', 'points', 'pixels'
- Tries both flips for Y (PDF origin vs image origin)
- Small grid search for local translation (optional, short)
- Prints diagnostics and writes overlay + merged image for the selected mapping.

Edit IMAGE_PATH and POLYGON_FLAT in __main__ only.
"""

from pathlib import Path
from typing import List, Tuple, Optional, Union
from io import BytesIO
from PIL import Image, ImageDraw, ImageOps
import numpy as np
import time

class PNGHighlighterAutoSelect:
    def __init__(
        self,
        fill_color: Tuple[int,int,int,int] = (255,255,0,150),
        outline_color: Tuple[int,int,int,int] = (255,0,0,220),
        outline_width: int = 3,
        tune_radius: int = 20,   # local translation search radius (px)
        tune_step: int = 10,     # step for translation search
        max_combinations: int = 2000,  # safety cap
        amplify_target_px: int = 40,   # if polygon tiny -> amplify for visibility
    ):
        self.fill_color = fill_color
        self.outline_color = outline_color
        self.outline_width = outline_width
        self.tune_radius = tune_radius
        self.tune_step = tune_step
        self.max_combinations = max_combinations
        self.amplify_target_px = amplify_target_px

    # ------------------- mapping helpers -------------------
    @staticmethod
    def flat_to_pairs(flat: List[float]) -> List[Tuple[float,float]]:
        if len(flat) % 2 != 0:
            raise ValueError("Flat polygon must contain even number of elements")
        return [(float(flat[i]), float(flat[i+1])) for i in range(0, len(flat), 2)]

    @staticmethod
    def detect_coord_type(pairs: List[Tuple[float,float]]) -> str:
        vals = [abs(v) for p in pairs for v in p]
        if not vals:
            return "pixels"
        m = max(vals)
        if m <= 1.0:
            return "normalized"
        if m < 200:
            return "points"
        return "pixels"

    def map_to_pixels(self,
                      pairs: List[Tuple[float,float]],
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
                sx, sy = w/pw, h/ph
            else:
                xs = [x for x,_ in pairs]; ys = [y for _,y in pairs]
                bbox_w = max(xs)-min(xs) if xs else 1.0
                bbox_h = max(ys)-min(ys) if ys else 1.0
                sx, sy = w/max(1.0,bbox_w), h/max(1.0,bbox_h)
            mapped = [(x * sx, y * sy) for x,y in pairs]
        else: # pixels
            mapped = [(x, y) for x,y in pairs]

        # optionally flip Y (PDF bottom-left -> image top-left)
        if flip_y:
            mapped = [(int(round(px)), int(round(h - py))) for px,py in mapped]
        else:
            mapped = [(int(round(px)), int(round(py))) for px,py in mapped]

        # clamp
        mapped = [(max(0, min(w-1,x)), max(0, min(h-1,y))) for x,y in mapped]
        return mapped

    # ---------- scoring helpers ----------
    @staticmethod
    def polygon_mask_bool(poly_px: List[Tuple[int,int]], img_size: Tuple[int,int]) -> np.ndarray:
        w,h = img_size
        mask = Image.new("L", (w,h), 0)
        if poly_px:
            ImageDraw.Draw(mask).polygon(poly_px, fill=255)
        return np.asarray(mask, dtype=np.uint8) > 0

    @staticmethod
    def score_mask_on_gray(mask_bool: np.ndarray, gray_arr: np.ndarray) -> float:
        if mask_bool.sum() == 0:
            return 0.0
        darkness = (255 - gray_arr).astype(np.int64)
        return float((darkness * mask_bool).sum())

    @staticmethod
    def amplify_if_tiny(poly_px: List[Tuple[int,int]], img_size: Tuple[int,int], target_px:int) -> Tuple[List[Tuple[int,int]], float]:
        if not poly_px:
            return poly_px, 1.0
        xs = [p[0] for p in poly_px]; ys = [p[1] for p in poly_px]
        minx, maxx = min(xs), max(xs); miny, maxy = min(ys), max(ys)
        bw, bh = maxx-minx, maxy-miny
        smallest = min(bw if bw>0 else 1, bh if bh>0 else 1)
        if smallest >= target_px:
            return poly_px, 1.0
        # centroid
        cx, cy = (minx+maxx)/2, (miny+maxy)/2
        factor = max(1.0, target_px / max(1, smallest))
        new = []
        w,h = img_size
        for x,y in poly_px:
            nx = int(round((x-cx)*factor + cx))
            ny = int(round((y-cy)*factor + cy))
            nx = max(0, min(w-1, nx)); ny = max(0, min(h-1, ny))
            new.append((nx, ny))
        return new, factor

    # ------------------- drawing helpers -------------------
    def draw_overlay_and_merged(self, pil_img: Image.Image, poly_px: List[Tuple[int,int]]):
        w,h = pil_img.size
        overlay = Image.new("RGBA", (w,h), (255,255,255,0))
        if poly_px:
            draw = ImageDraw.Draw(overlay)
            draw.polygon(poly_px, fill=self.fill_color)
            draw.line(list(poly_px) + [poly_px[0]], width=self.outline_width, fill=self.outline_color)
        merged = Image.alpha_composite(pil_img.convert("RGBA"), overlay)
        return overlay, merged

    # ------------------- main method -------------------
    def highlight_from_path(self,
                            image_path: Union[str, Path],
                            polygon_flat: List[float],
                            pdf_page_size: Optional[Tuple[float,float]] = None,
                            try_modes: Optional[List[str]] = None,
                            try_flips: Optional[List[bool]] = None,
                            enable_tuning: bool = True):
        """
        image_path: path to image
        polygon_flat: flat list [x,y,x,y,...]
        pdf_page_size: optional (width_points, height_points) if 'points' mapping should use exact scale
        try_modes: list of coord_type strings to try (default ['auto','normalized','points','pixels'])
        try_flips: list of booleans to try for flip_y (default [True, False])
        enable_tuning: do a small translation tune around best candidate
        """
        start = time.time()
        img_path = Path(image_path)
        if not img_path.exists():
            raise FileNotFoundError(f"{image_path} not found")
        pil = Image.open(img_path)
        w,h = pil.size
        img_size = (w,h)
        print(f"[auto-select] loaded {image_path} size={img_size}")

        pairs = self.flat_to_pairs(polygon_flat) if False else PNGHighlighterAutoSelect.flat_to_pairs(polygon_flat)
        print(f"[auto-select] raw pairs: {pairs}")

        # default candidates
        if try_modes is None:
            try_modes = ["auto","normalized","points","pixels"]
        if try_flips is None:
            try_flips = [True, False]

        # prepare grayscale array once
        gray = np.asarray(ImageOps.grayscale(pil), dtype=np.uint8)

        best_overall = {"score": -1.0}
        candidates_tested = 0

        # if 'auto' in try_modes we will replace it with a detected sensible order
        modes_to_try = []
        if "auto" in try_modes:
            det = self.detect_coord_type(pairs)
            # try detected first, then others
            modes_to_try = [det] + [m for m in ["normalized","points","pixels"] if m != det]
        else:
            modes_to_try = try_modes

        for mode in modes_to_try:
            for flip in try_flips:
                # map to pixels
                try:
                    poly_px = self.map_to_pixels(pairs, img_size, coord_type=mode if mode!="auto" else mode, flip_y=flip, pdf_page_size=pdf_page_size)
                except Exception as e:
                    print(f"[auto-select] mapping failed for mode={mode} flip={flip}: {e}")
                    continue

                # amplify tiny polygons for scoring so they actually overlap some pixels
                poly_px2, factor = PNGHighlighterAutoSelect.amplify_if_tiny(poly_px, img_size, self.amplify_target_px)

                # scoring: quick mask and darkness sum
                mask_bool = PNGHighlighterAutoSelect.polygon_mask_bool(poly_px2, img_size)
                score = PNGHighlighterAutoSelect.score_mask_on_gray(mask_bool, gray)

                candidates_tested += 1
                if score > best_overall["score"]:
                    best_overall = {
                        "score": score,
                        "mode": mode,
                        "flip": flip,
                        "poly_px": poly_px,
                        "poly_px_scoring": poly_px2,
                        "factor": factor
                    }

                print(f"[candidate] mode={mode:10s} flip={flip} score={score:.1f} bbox_factor={factor:.2f}")

                # safety cap
                if candidates_tested > self.max_combinations:
                    print("[auto-select] reached safety cap, stopping candidates search.")
                    break

        print(f"[auto-select] best candidate: mode={best_overall['mode']} flip={best_overall['flip']} score={best_overall['score']:.1f}")

        # optionally fine-tune local translation around best candidate
        final_poly = best_overall["poly_px"]
        if enable_tuning and best_overall["score"] > 0:
            # small grid search around final_poly
            txs = list(range(-self.tune_radius, self.tune_radius+1, self.tune_step))
            tys = list(range(-self.tune_radius, self.tune_radius+1, self.tune_step))
            best = {"score": best_overall["score"], "tx":0, "ty":0}
            for tx in txs:
                for ty in tys:
                    test_poly = [(x+tx, y+ty) for x,y in best_overall["poly_px"]]
                    mask_bool = PNGHighlighterAutoSelect.polygon_mask_bool(test_poly, img_size)
                    sc = PNGHighlighterAutoSelect.score_mask_on_gray(mask_bool, gray)
                    if sc > best["score"]:
                        best = {"score": sc, "tx": tx, "ty": ty}
            if best["tx"] != 0 or best["ty"] != 0:
                final_poly = [(x+best["tx"], y+best["ty"]) for x,y in best_overall["poly_px"]]
                print(f"[tune] applied tx={best['tx']} ty={best['ty']} new_score={best['score']:.1f}")

        # ensure final poly is integers and clamped
        final_poly = [(int(round(x)), int(round(y))) for x,y in final_poly]
        final_poly = [(max(0,min(w-1,x)), max(0,min(h-1,y))) for x,y in final_poly]

        # draw overlay and merged
        overlay, merged = self.draw_overlay_and_merged(pil, final_poly)

        # save debug outputs
        base = img_path.stem
        overlay_path = img_path.with_name(f"{base}_overlay_selected.png")
        merged_path = img_path.with_name(f"{base}_highlighted_selected.png")
        overlay.save(overlay_path, format="PNG", compress_level=1)
        merged.save(merged_path, format="PNG", compress_level=1)

        elapsed = time.time() - start
        print(f"[auto-select] done in {elapsed:.3f}s saved: {overlay_path}, {merged_path}")
        print(f"[auto-select] final_poly sample: {final_poly[:10]} ...")

        # return BytesIO of merged image
        buf = BytesIO()
        merged.save(buf, format="PNG", compress_level=1)
        buf.seek(0)
        return buf, {
            "overlay_path": str(overlay_path),
            "merged_path": str(merged_path),
            "chosen_mode": best_overall["mode"],
            "chosen_flip": best_overall["flip"],
            "score": best_overall["score"]
        }

    # helpers reused from above for mapping/draw
    @staticmethod
    def flat_to_pairs(flat: List[float]) -> List[Tuple[float,float]]:
        return PNGHighlighterAutoSelect.flat_to_pairs(flat)  # just alias

    def map_to_pixels(self, pairs, img_size, coord_type, flip_y, pdf_page_size=None):
        return PNGHighlighterAutoSelect.map_to_pixels(self, pairs, img_size, coord_type, flip_y, pdf_page_size)

    def draw_overlay_and_merged(self, pil_img, poly_px):
        return PNGHighlighterAutoSelect.draw_overlay_and_merged(self, pil_img, poly_px)

# -------------------------
# minimal main: only set image & polygon here
# -------------------------
if __name__ == "__main__":
    IMAGE_PATH = Path(r"C:\Users\SAHUAX19\Documents\page_1.png")
    POLYGON_FLAT = [3.2742, 1.5965, 5.7768, 1.5991, 5.7766, 1.8248, 3.274, 1.8221]

    highlighter = PNGHighlighterAutoSelect()
    buf, info = highlighter.highlight_from_path(IMAGE_PATH, POLYGON_FLAT, pdf_page_size=None, enable_tuning=True)
    print("Result info:", info)
    # you will find overlay + merged written next to the image