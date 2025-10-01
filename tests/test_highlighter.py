import pytest
from io import BytesIO
from pathlib import Path
from PIL import Image
from app.highlighter import highlight_png


@pytest.fixture
def dummy_png_buf():
    """Create a simple small PNG in memory as BytesIO."""
    img = Image.new("RGB", (200, 200), color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def test_highlight_png_changes_pixels_and_size(dummy_png_buf, tmp_path):
    # Polygon to highlight (square in the middle)
    polygons = [[[10, 10], [180, 10], [180, 180], [10, 180]]]

    # Run highlight function
    out_buf = highlight_png(dummy_png_buf, polygons)

    # Save to disk for manual/manual inspection
    out_file = tmp_path / "highlighted.png"
    with open(out_file, "wb") as f:
        f.write(out_buf.getvalue())

    # Reload image
    img = Image.open(out_file).convert("RGB")

    # Pixel inside polygon should not be pure white
    inside_pixel = img.getpixel((50, 50))
    assert inside_pixel != (255, 255, 255), "Pixel inside polygon should be highlighted"

    # Pixel outside polygon should still be white
    outside_pixel = img.getpixel((190, 190))
    assert outside_pixel == (255, 255, 255), "Pixel outside polygon should remain white"

    # File size check
    size_kb = out_file.stat().st_size / 1024
    print(f"Generated image size: {size_kb:.2f} KB")

    assert 200 <= size_kb <= 250, f"Expected size 200–250 KB, got {size_kb:.2f} KB"
