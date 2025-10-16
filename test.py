from io import BytesIO
from pathlib import Path
from PIL import Image
from app.highlighter import highlight_png   # adjust import if needed


# ✅ 1. Manually provide the image path (absolute or relative)
IMAGE_PATH = r"E:\poc\data\output_images\sample\page_1.png"

# ✅ 2. Manually define polygon coordinates
# Example: coordinates from your JSON snippet (can be flat or nested)
POLYGON = [
    [3.2742, 1.5965],
    [5.7768, 1.5991],
    [5.7766, 1.8248],
    [3.274,  1.8221]
]

# ✅ 3. Open image into memory
try:
    img_path = Path(IMAGE_PATH)
    if not img_path.exists():
        raise FileNotFoundError(f"❌ Image not found: {img_path}")

    with img_path.open("rb") as f:
        img_buf = BytesIO(f.read())
except Exception as e:
    print(f"Error reading image: {e}")
    exit(1)

# ✅ 4. Normalize polygon coordinates (scale to image size if needed)
def scale_polygon(poly, width, height):
    """Scale normalized or small unit polygons up to image pixel coords."""
    flat_vals = [v for p in poly for v in p]
    max_val = max(flat_vals) if flat_vals else 0

    if max_val <= 10:  # assume normalized or small float coords
        factor_x = width / max_val
        factor_y = height / max_val
        return [[int(x * factor_x), int(y * factor_y)] for x, y in poly]

    return [[int(x), int(y)] for x, y in poly]

try:
    img = Image.open(img_path)
    width, height = img.size
    scaled_poly = scale_polygon(POLYGON, width, height)
    img.close()
except Exception as e:
    print(f"Error scaling polygon: {e}")
    exit(1)

# ✅ 5. Apply highlight using your existing highlight_png function
try:
    out_buf = highlight_png(img_buf, [scaled_poly])
except Exception as e:
    print(f"Error applying highlight: {e}")
    exit(1)

# ✅ 6. Save the highlighted image locally
OUTPUT_PATH = img_path.with_name(img_path.stem + "_highlighted.png")
try:
    with OUTPUT_PATH.open("wb") as f:
        f.write(out_buf.getvalue())

    size_kb = OUTPUT_PATH.stat().st_size / 1024
    print(f"✅ Highlighted image saved to: {OUTPUT_PATH}")
    print(f"📏 File size: {size_kb:.2f} KB")
except Exception as e:
    print(f"Error saving output: {e}")
    exit(1)