import argparse
import os
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from PIL import Image
import numpy as np
import math


def create_random_image(path: str, width: int, height: int):
    """Generate a random PNG image of given resolution."""
    img_array = (np.random.rand(height, width, 3) * 255).astype("uint8")
    Image.fromarray(img_array).save(path, "PNG")


def estimate_resolution(target_kb: int):
    """
    Estimate width/height so one image ≈ target_kb.
    Uncompressed RGB ≈ width*height*3 bytes.
    PNG compresses, so overshoot factor ≈ 1.5x.
    """
    bytes_needed = target_kb * 1024 * 1.5
    side = int(math.sqrt(bytes_needed / 3))
    return max(256, side), max(256, side)


def generate_pdf(output_path: Path, target_size_mb: int, num_pages: int, tolerance: int):
    target_size_bytes = target_size_mb * 1024 * 1024
    per_page_bytes = target_size_bytes // num_pages
    per_page_kb = per_page_bytes // 1024

    width, height = estimate_resolution(per_page_kb)
    print(f"🎯 Target {target_size_mb} MB ± {tolerance} MB with {num_pages} pages")
    print(f"   Per-page target ≈ {per_page_kb} KB → image size {width}x{height}px")

    c = canvas.Canvas(str(output_path), pagesize=A4, pageCompression=0)

    for i in range(1, num_pages + 1):
        tmp_img = f"tmp_page_{i}.png"
        create_random_image(tmp_img, width, height)

        c.setFont("Helvetica-Bold", 18)
        c.drawString(100, 800, f"Dummy PDF - Page {i}")
        c.drawImage(tmp_img, 20, 100, width=550, height=550)
        c.showPage()

        os.remove(tmp_img)

        if i % 20 == 0:
            print(f"   Added {i}/{num_pages} pages...")

    c.save()

    final_size = os.path.getsize(output_path) / (1024 * 1024)
    print(f"✅ Final PDF: {output_path} ({final_size:.2f} MB, {num_pages} pages)")

    lower = target_size_mb - tolerance
    upper = target_size_mb + tolerance
    if final_size < lower or final_size > upper:
        print(f"⚠️ Warning: file size {final_size:.2f} MB is outside tolerance "
              f"({lower}–{upper} MB)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a large dummy PDF with given size & pages.")
    parser.add_argument("--size", type=int, default=100, help="Target size in MB")
    parser.add_argument("--pages", type=int, default=200, help="Number of pages")
    parser.add_argument("--tolerance", type=int, default=10, help="Size tolerance in MB")
    parser.add_argument("--output", type=str, default="dummy_large.pdf", help="Output PDF filename")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    output_dir = project_root / "data" / "source_pdfs"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / args.output

    generate_pdf(output_path, args.size, args.pages, args.tolerance)
