"""OCR for light text on coloured buttons, which tesseract misses on the plain screenshot.

Finds solid coloured rectangles the size of buttons or chips, turns the light label pixels inside each into
dark text on white, and reads each one as a single line. Prints words as JSON lines {text, x, y, w, h, line}
in the original image's pixels.

Usage: python3 button_text.py in.png
"""
import json
import os
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image, ImageFilter

SCALE = 3


def runs(profile: np.ndarray, gap: int) -> list[tuple[int, int]]:
    """Index ranges where profile is true, merging holes up to gap."""
    idx = np.flatnonzero(profile)
    if not idx.size:
        return []
    out, start, prev = [], int(idx[0]), int(idx[0])
    for i in idx[1:]:
        if i - prev > gap:
            out.append((start, prev + 1))
            start = int(i)
        prev = int(i)
    out.append((start, prev + 1))
    return out


def buttons(fill: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Axis-aligned solid coloured rectangles the size of a button or chip (row bands, then column runs)."""
    dense_rows = fill.sum(axis=1) >= 40
    out = []
    for y0, y1 in runs(dense_rows, 2):
        for x0, x1 in runs(fill[y0:y1].mean(axis=0) > 0.35, 3):
            sub = fill[y0:y1, x0:x1]
            ry = runs(sub.mean(axis=1) > 0.35, 2)
            if not ry:
                continue
            by0, by1 = y0 + ry[0][0], y0 + ry[-1][1]
            w, h = x1 - x0, by1 - by0
            if 60 <= w <= 700 and 22 <= h <= 110 and fill[by0:by1, x0:x1].mean() > 0.45:
                out.append((x0, by0, x1, by1))
    return out


def read_line(img: Image.Image) -> list[tuple[str, int, int, int, int]]:
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "b.png")
        img.save(path)
        tsv = subprocess.run(["tesseract", path, "stdout", "--psm", "7", "tsv"], capture_output=True, text=True,
                             env={**os.environ, "OMP_THREAD_LIMIT": "1"}, check=True).stdout
    words = []
    for row in tsv.splitlines()[1:]:
        c = row.split("\t")
        if len(c) >= 12 and c[11].strip() and float(c[10]) >= 30:
            words.append((c[11].strip(), *(int(v) for v in c[6:10])))
    return words


def main(src: str) -> None:
    a = np.asarray(Image.open(src).convert("RGB")).astype(np.int16)
    mx, mn = a.max(axis=2), a.min(axis=2)
    fill = (mx - mn > 50) & (mx < 235)
    for k, (x0, y0, x1, y1) in enumerate(buttons(fill)):
        light = mn[y0:y1, x0:x1] > 120
        crop = Image.fromarray(np.where(light, 0, 255).astype(np.uint8))
        crop = crop.resize((crop.width * SCALE, crop.height * SCALE), Image.BICUBIC).filter(ImageFilter.GaussianBlur(1.2))
        framed = Image.new("L", (crop.width + 60, crop.height + 60), 255)
        framed.paste(crop, (30, 30))
        for text, sx, sy, sw, sh in read_line(framed):
            print(json.dumps({"text": text, "x": int(x0 + (sx - 30) // SCALE), "y": int(y0 + (sy - 30) // SCALE),
                              "w": int(sw // SCALE), "h": int(sh // SCALE), "line": f"b{k}"}))


if __name__ == "__main__":
    main(sys.argv[1])
