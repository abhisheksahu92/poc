from pathlib import Path
from typing import List, Tuple, Union
from PIL import Image, ImageDraw
from io import BytesIO


class PNGHighlighter:
    def __init__(self, fill_color=(255, 255, 0, 150), outline_color=(255, 0, 0, 255), outline_width=3):
        self.fill_color = fill_color
        self.outline_color = outline_color
        self.outline_width = outline_width

    @staticmethod
    def flat_to_pairs(flat: List[float]) -> List[Tuple[float, float]]:
        return [(float(flat[i]), float(flat[i + 1])) for i in range(0, len(flat), 2)]

    def highlight_from_path(self, image_path: Union[str, Path], polygon_flat: List[float]) -> BytesIO:
        img = Image.open(image_path).convert("RGBA")
        w, h = img.size

        # Convert flat list to coordinate pairs
        polygon = self.flat_to_pairs(polygon_flat)

        # Scale from 0–10 coordinate range to image pixels
        scaled_poly = [(x * w / 10.0, (10 - y) * h / 10.0) for x, y in polygon]

        print(f"[info] Image size = {w}x{h}")
        print(f"[info] Input polygon = {polygon}")
        print(f"[info] Scaled polygon = {scaled_poly}")

        # Draw highlight
        overlay = Image.new("RGBA", img.size, (255, 255, 255, 0))
        draw = ImageDraw.Draw(overlay)
        draw.polygon(scaled_poly, fill=self.fill_color, outline=self.outline_color, width=self.outline_width)
        result = Image.alpha_composite(img, overlay)

        # Save overlay + merged for debugging
        out_overlay = Path(image_path).with_name("page_1_overlay_fixed.png")
        out_merged = Path(image_path).with_name("page_1_highlighted_fixed.png")
        overlay.save(out_overlay)
        result.save(out_merged)
        print(f"[output] overlay -> {out_overlay}")
        print(f"[output] merged  -> {out_merged}")

        # Return binary stream
        buf = BytesIO()
        result.save(buf, format="PNG")
        buf.seek(0)
        return buf


if __name__ == "__main__":
    IMAGE_PATH = r"C:\Users\SAHUAX19\Documents\page_1.png"
    POLYGON_FLAT = [3.2742, 1.5965, 5.7768, 1.5991, 5.7766, 1.8248, 3.274, 1.8221]

    highlighter = PNGHighlighter()
    out_stream = highlighter.highlight_from_path(IMAGE_PATH, POLYGON_FLAT)
    with open("output_test.png", "wb") as f:
        f.write(out_stream.getvalue())