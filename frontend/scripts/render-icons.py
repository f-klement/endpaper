"""Render the PWA icon set from public/icons/books-icon.svg.

Run it after changing the artwork or the accent colour:

    uv run --no-project --with cairosvg python scripts/render-icons.py

Deliberately not a project dependency and not part of the build. The icons
change roughly never, the output is committed, and adding a native rasteriser
to a Bun frontend to redraw three rectangles on every build is not a trade
worth making.

Maskable icons are cropped to a circle of radius 40% by Android, so the glyph
is scaled to 58% of the canvas and centred: anything wider risks having its
outer spine shaved off on a device that masks aggressively.
"""
import re, pathlib, cairosvg

SRC = pathlib.Path("public/icons/books-icon.svg")
OUT = pathlib.Path("public/icons")

ACCENT = "#13816f"   # --color-accent-600, the bookbinder's green
GLYPH = "#ffffff"

source = SRC.read_text()
paths = re.findall(r'<path[^>]*\bd="([^"]+)"', source)
assert len(paths) == 3, f"expected three spines, found {len(paths)}"

VB_W, VB_H = 122.88, 99.45


def square(size: int, *, fraction: float = 0.58) -> str:
    scale = (size * fraction) / VB_W
    width, height = VB_W * scale, VB_H * scale
    dx, dy = (size - width) / 2, (size - height) / 2
    body = "".join(f'<path d="{d}" fill="{GLYPH}" fill-rule="evenodd"/>' for d in paths)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 {size} {size}">'
        f'<rect width="{size}" height="{size}" fill="{ACCENT}"/>'
        f'<g transform="translate({dx},{dy}) scale({scale})">{body}</g>'
        f"</svg>"
    )


for name, size in (("icon-192.png", 192), ("icon-512.png", 512), ("apple-touch-icon.png", 180)):
    cairosvg.svg2png(
        bytestring=square(size).encode(), write_to=str(OUT / name),
        output_width=size, output_height=size,
    )
    print("wrote", name, size)
