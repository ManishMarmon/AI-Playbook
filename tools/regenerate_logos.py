"""
Regenerates the two Marmon logo PNGs used by the frontend from the source
images at the repo root. Records the exact crop/mask parameters used to
produce the shipped assets, so they can be rebuilt from source if ever
needed — though the replication guide also embeds the final PNGs byte-exact
(base64), which is the preferred path.

  small_logo2.jpg (white mark on blue)  -> mclegal-frontend/public/marmon-mark-white.png  (sidebar logo)
  small_logo1.png (blue mark on white)  -> mclegal-frontend/public/marmon-mark-blue.png   (favicon)

Both are cropped to the full mark (top hooked bars + embedded "MARMON" text
+ bottom feet — the mark's waist is where the text sits; cropping at the
waist loses the bottom half), upscaled 4x with LANCZOS, then the background
is keyed to transparency by per-pixel color distance from the background
color with a soft low/high ramp.

Usage (from repo root):  python tools/regenerate_logos.py
Requires: Pillow
"""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent

JOBS = [
    # (source, crop_box l/t/r/b, background RGB, out path)
    ("small_logo2.jpg", (27, 25, 152, 121), None, "mclegal-frontend/public/marmon-mark-white.png"),
    ("small_logo1.png", (14, 19, 160, 129), (255, 255, 255), "mclegal-frontend/public/marmon-mark-blue.png"),
]

SCALE = 4
ALPHA_LOW = 10    # color distance <= LOW  -> fully transparent
ALPHA_HIGH = 60   # color distance >= HIGH -> fully opaque; ramp between


def dist(c1, c2):
    return sum((a - b) ** 2 for a, b in zip(c1, c2)) ** 0.5


def main():
    for src_name, box, bg, out_rel in JOBS:
        src = Image.open(ROOT / src_name).convert("RGB")
        if bg is None:
            bg = src.getpixel((0, 0))  # sample background from the corner
        crop = src.crop(box).resize(
            ((box[2] - box[0]) * SCALE, (box[3] - box[1]) * SCALE), Image.LANCZOS
        )
        rgba = crop.convert("RGBA")
        px = rgba.load()
        for y in range(rgba.height):
            for x in range(rgba.width):
                r, g, b, _ = px[x, y]
                d = dist((r, g, b), bg)
                if d <= ALPHA_LOW:
                    alpha = 0
                elif d >= ALPHA_HIGH:
                    alpha = 255
                else:
                    alpha = int(255 * (d - ALPHA_LOW) / (ALPHA_HIGH - ALPHA_LOW))
                px[x, y] = (r, g, b, alpha)
        out = ROOT / out_rel
        out.parent.mkdir(parents=True, exist_ok=True)
        rgba.save(out)
        print(f"wrote {out_rel} {rgba.size}")


if __name__ == "__main__":
    main()
