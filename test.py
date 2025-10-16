from io import BytesIO
from pathlib import Path
from PIL import Image
from app.highlighter import highlight_png   # adjust import path if needed


# =====================================================
# 1️⃣ MANUAL INPUT SECTION
# =====================================================

# ✅ Image path (change to your own local file)
IMAGE_PATH = r"E:\poc\data\output_images\sample\page_1.png"

# ✅ Flat polygon coordinates (from JSON)
POLYGON_FLAT = [3.2742, 1.5965, 5.7768, 1.5991, 5.7766, 1.8248, 3.274, 1.8221]

# =====================================================
# 2️⃣ HELPER FUNCTIONS
# =====================================================

def flat_to_pairs(flat_list):
    """Convert a flat polygon list [x1, y1, x2, y2, ...] → [[x1, y1], [x2, y2], ...]"""
    if len(flat_list) % 2 != 0:
        raise ValueError("Polygon list length must be even (x,y pairs).")
    return [[float(flat_list[i]), float(flat_list[i + 1])] for i in range(0, len(flat_list), 2)]


def scale_polygon(polygon, width, height):
    """
    Scale normalized or small coordinate polygons to pixel space.
    If all coordinates are <= 10, assume normalized or small unit values and scale up.
    """
    max_val = max(abs(v) for p in polygon for v in p)
    if max_val <= 10:  # normalized or small float
        fx = width / max_val
        fy = height / max_val
        return [[int(x * fx), int(y * fy)] for x, y in polygon]
    return [[int(x), int(y)] for x, y in polygon]


# =====================================================
# 3️⃣ MAIN LOGIC
# =====================================================

def main():
    try:
        # Step 1: Load image into memory
        img_path = Path(IMAGE_PATH)
        if not img_path.exists():
            raise FileNotFoundError(f"Image not found: {img_path}")

        img = Image.open(img_path)
        width, height = img.size
        img.close()

        with img_path.open("rb") as f:
            img_buf = BytesIO(f.read())

        # Step 2: Convert polygon and scale
        polygon_pairs = flat_to_pairs(POLYGON_FLAT)
        scaled_polygon = scale_polygon(polygon_pairs, width, height)

        # Step 3: Apply highlight
        out_buf = highlight_png(img_buf, [scaled_polygon])

        # Step 4: Save output
        output_path = img_path.with_name(img_path.stem + "_highlighted.png")
        with output_path.open("wb") as f:
            f.write(out_buf.getvalue())

        size_kb = output_path.stat().st_size / 1024
        print(f"✅ Highlighted image saved to: {output_path}")
        print(f"📏 File size: {size_kb:.2f} KB")

    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    main()