"""Draws KurtShape's loading screen (the image FreeCAD shows while it starts).

``ensure_splash`` writes ``kurtshape-splash.png`` and ``kurtshape-splash_2x.png`` into a folder and
returns it. FreeCAD picks the ``_2x`` file on a scaled display. The pair is redrawn only when the
version, the engine version or this drawing code changes. Needs Pillow, not FreeCAD or Qt.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

# Bump when the drawing below changes, so existing sessions redraw their image.
GENERATOR = 1
NAME = "kurtshape-splash"
WIDTH, HEIGHT = 620, 340          # logical pixels
PANEL_WIDTH = 232
RADIUS = 18
SUPERSAMPLE = 4
SURFACE = (255, 255, 255, 255)
PANEL = (230, 241, 250, 255)      # DESIGN.md selection
BORDER = (184, 193, 201, 255)
INK = (45, 51, 56, 255)           # DESIGN.md ink
MUTED = (89, 99, 108, 255)        # DESIGN.md muted
ACCENT = (24, 95, 165, 255)       # DESIGN.md accent


def ensure_splash(folder, version, engine_version, icon_image):
    """Return ``folder`` holding a current loading screen for this version, drawing it if needed."""
    folder = Path(folder)
    stamp = folder / "splash.json"
    key = {"generator": GENERATOR, "version": str(version), "engine": str(engine_version)}
    files = [folder / (NAME + ".png"), folder / (NAME + "_2x.png")]
    try:
        if json.loads(stamp.read_text(encoding="utf-8")) == key and all(path.is_file() for path in files):
            return folder
    except (OSError, ValueError):
        pass
    folder.mkdir(parents=True, exist_ok=True)
    for path, scale in zip(files, (1, 2)):
        temporary = path.with_suffix(".writing.png")
        render(version, engine_version, icon_image, scale).save(temporary, format="PNG")
        os.replace(temporary, path)
    stamp.write_text(json.dumps(key), encoding="utf-8")
    return folder


def render(version, engine_version, icon_image, scale=1):
    """The loading screen as an RGBA image, ``scale`` times the logical size."""
    from PIL import Image, ImageDraw

    factor = SUPERSAMPLE

    def px(value):
        return round(value * factor)

    size = (px(WIDTH), px(HEIGHT))
    card = Image.new("L", size, 0)
    ImageDraw.Draw(card).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=px(RADIUS), fill=255)
    face = Image.new("RGBA", size, SURFACE)
    draw = ImageDraw.Draw(face)
    draw.rectangle((0, 0, px(PANEL_WIDTH), size[1]), fill=PANEL)
    left = PANEL_WIDTH + 38
    draw.text((px(left - 2), px(112)), "KurtShape", font=_font("seguisb.ttf", px(54)), fill=INK)
    draw.text((px(left), px(186)), "Version " + str(version), font=_font("segoeui.ttf", px(19)), fill=MUTED)
    draw.rounded_rectangle((px(left), px(96), px(left + 44), px(100)), radius=px(2), fill=ACCENT)
    draw.text((px(left), px(HEIGHT - 44)), "Built on FreeCAD " + str(engine_version),
              font=_font("segoeui.ttf", px(13)), fill=MUTED)
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    image.paste(face, (0, 0), card)
    ImageDraw.Draw(image).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=px(RADIUS),
                                            outline=BORDER, width=px(1))
    image = image.resize((WIDTH * scale, HEIGHT * scale), Image.Resampling.LANCZOS)
    # The dodecahedron is pasted at its final size so it is resampled once.
    mark = 168 * scale
    with Image.open(icon_image) as source:
        icon = source.convert("RGBA").resize((mark, mark), Image.Resampling.LANCZOS)
    image.alpha_composite(icon, ((PANEL_WIDTH * scale - mark) // 2, (HEIGHT * scale - mark) // 2))
    return image


def _font(name, size):
    from PIL import ImageFont
    for candidate in (name, "segoeui.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default(size)
