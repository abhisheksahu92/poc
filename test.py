def _compute_auto_scale(self, poly_pairs, img_size):
    """Smart adaptive scaling for mixed coordinate systems."""
    w, h = img_size
    xs = [abs(x) for x, _ in poly_pairs] or [1.0]
    ys = [abs(y) for _, y in poly_pairs] or [1.0]
    max_x, max_y = max(xs), max(ys)

    # Case 1: normalized (0..1 or 0..10) — scale up
    if max_x <= 20 and max_y <= 20:
        sx = w / max_x
        sy = h / max_y
        print(f"[scale] Detected normalized polygon (<=20 units) → sx={sx:.2f}, sy={sy:.2f}")

    # Case 2: PDF points (hundreds–thousands range)
    elif 20 < max_x < w * 2 and 20 < max_y < h * 2:
        sx = w / max_x
        sy = h / max_y
        print(f"[scale] Detected PDF coordinate scale → sx={sx:.2f}, sy={sy:.2f}")

    # Case 3: already pixel coordinates (similar to image)
    else:
        sx, sy = 1.0, 1.0
        print(f"[scale] Detected pixel-scale polygon → sx=1.0, sy=1.0")

    return sx * self.manual_scale_x, sy * self.manual_scale_y