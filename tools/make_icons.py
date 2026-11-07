"""Draw the application icons from the logo (card T18).

Run once after a change of the logo, then commit the files:

    python -m tools.make_icons

The logo is the three roofs of the style guide (ui/templatetags/icons.py,
``roofs``), drawn on a white tile. Pillow is a development dependency only:
the icons are plain files in ui/static/ui/icons/.
Docs: https://pillow.readthedocs.io/en/stable/reference/ImageDraw.html
"""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "ui" / "static" / "ui" / "icons"
SCALE = 8  # drawn larger, then reduced: smooth edges

# The three roofs, in the 30 x 20 box of the logo SVG.
ROOFS = (
    ("#8bc34a", [(1, 12), (6, 5), (11, 12), (11, 19), (1, 19)]),
    ("#03a9f4", [(9, 9), (15, 1), (21, 9), (21, 19), (9, 19)]),
    ("#ffc107", [(19, 12), (24, 5), (29, 12), (29, 19), (19, 19)]),
)
LOGO_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
    '<rect width="32" height="32" rx="7" fill="#fff"/>'
    '<g transform="translate(1 6)">'
    '<path d="M1 12 6 5l5 7v7H1z" fill="#8BC34A"/>'
    '<path d="M9 9 15 1l6 8v10H9z" fill="#03A9F4"/>'
    '<path d="M19 12l5-7 5 7v7H19z" fill="#FFC107"/>'
    "</g></svg>\n"
)


def draw(size, logo_share, background="#ffffff", radius=0.0):
    """An icon of ``size`` px; the logo takes ``logo_share`` of the width."""
    big = size * SCALE
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)
    if background:
        pen.rounded_rectangle((0, 0, big - 1, big - 1), radius=int(radius * big), fill=background)
    unit = big * logo_share / 28  # the roofs span x = 1 to 29
    left = (big - 28 * unit) / 2 - unit
    top = (big - 18 * unit) / 2 - unit  # they span y = 1 to 19
    for color, points in ROOFS:
        pen.polygon([(left + x * unit, top + y * unit) for x, y in points], fill=color)
    return image.resize((size, size), Image.Resampling.LANCZOS)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    # "any" icons: the logo on a white tile, as in the app header.
    draw(192, 0.66).save(OUT / "icon-192.png", optimize=True)
    draw(512, 0.66).save(OUT / "icon-512.png", optimize=True)
    # "maskable": the system may cut the edges; the logo stays in the safe circle (80 %).
    draw(512, 0.56).save(OUT / "icon-maskable-512.png", optimize=True)
    # iPhone and iPad home screen (no transparency: iOS would fill it in black).
    draw(180, 0.66).convert("RGB").save(OUT / "apple-touch-icon.png", optimize=True)
    # Browser tab: a small white tile (readable on a dark tab bar), logo as large as possible.
    sizes = [(16, 16), (32, 32), (48, 48)]
    draw(48, 0.84, background="#ffffff", radius=0.2).save(OUT / "favicon.ico", sizes=sizes)
    (OUT / "icon.svg").write_text(LOGO_SVG)
    for path in sorted(OUT.iterdir()):
        print(path.name, path.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
