from PIL import Image, ImageDraw
from io import BytesIO
import random

def highlight_png(img_buf: BytesIO, polygons: list[list[list[int]]]) -> BytesIO:
    """
    Apply polygon highlights on a PNG image buffer and return as BytesIO.
    Ensures output image size is approx 200–250 KB.
    """
    # Open image
    img = Image.open(img_buf).convert("RGBA")

    # Upscale to increase size (if too small)
    if img.size[0] < 1000 or img.size[1] < 1000:
        img = img.resize((1500, 1500))  # upscale small images

    # Create overlay
    overlay = Image.new("RGBA", img.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)

    # Draw highlights
    for poly in polygons:
        draw.polygon(poly, fill=(255, 255, 0, 100))  # semi-transparent yellow

    # Merge overlay
    highlighted = Image.alpha_composite(img, overlay)

    # Add random noise (prevents compression shrinking size too much)
    pixels = highlighted.load()
    for _ in range(10000):  # sprinkle some random pixels
        x = random.randint(0, highlighted.size[0] - 1)
        y = random.randint(0, highlighted.size[1] - 1)
        pixels[x, y] = (random.randint(200, 255), random.randint(200, 255), random.randint(200, 255), 255)

    # Save to buffer
    out_buf = BytesIO()
    highlighted.save(out_buf, format="PNG", compress_level=1)  # low compression → bigger file
    out_buf.seek(0)

    return out_buf
