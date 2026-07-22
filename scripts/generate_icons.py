#!/usr/bin/env python3
"""Regenerate the MagnetOS v2 app icon assets as larger, bolder glyphs."""

import io
import os
import shutil
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer
from PySide6.QtGui import QColor, QGuiApplication
from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from magnet_v2_glyph import GlyphRenderer, Theme


ASSETS = REPO_ROOT / "assets"
SIZES = [16, 32, 64, 128, 256, 512, 1024]


def render_glyph_to_pil(renderer: GlyphRenderer, color: QColor):
    """Render a GlyphRenderer to a PIL RGBA image."""
    app = QGuiApplication.instance() or QGuiApplication([])
    pixmap = renderer.pixmap(Theme(False), color)
    buffer = QBuffer()
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    pixmap.save(buffer, "PNG")
    buffer.close()
    return Image.open(io.BytesIO(buffer.data().data())).convert("RGBA")


def center_paste(background: Image.Image, foreground: Image.Image):
    x = (background.width - foreground.width) // 2
    y = (background.height - foreground.height) // 2
    background.paste(foreground, (x, y), foreground)


def main():
    app = QGuiApplication.instance() or QGuiApplication([])

    bg = QColor(36, 50, 74)       # navy panel
    fg = QColor(245, 245, 247)    # near-white glyph

    base_size = 1024
    renderer = GlyphRenderer(size=base_size, weight=1.3)
    renderer.set_state("idle")

    glyph = render_glyph_to_pil(renderer, fg)
    bbox = glyph.getbbox()
    if bbox:
        glyph = glyph.crop(bbox)

    # Scale the glyph so it fills ~70 % of the icon.
    target = int(base_size * 0.70)
    glyph.thumbnail((target, target), Image.Resampling.LANCZOS)

    icon = Image.new(
        "RGBA",
        (base_size, base_size),
        (bg.red(), bg.green(), bg.blue(), bg.alpha()),
    )
    center_paste(icon, glyph)

    for size in SIZES:
        scaled = icon.resize((size, size), Image.Resampling.LANCZOS)
        scaled.save(ASSETS / f"icon_{size}x{size}.png")

    icon.save(ASSETS / "icon.png")

    # Multi-size .ico — largest frame first so Pillow writes all requested sizes.
    ico_sizes = [256, 128, 64, 48, 32, 16]
    ico_images = [icon.resize((size, size), Image.Resampling.LANCZOS) for size in ico_sizes]
    ico_images[0].save(
        ASSETS / "icon.ico",
        format="ICO",
        append_images=ico_images[1:],
        sizes=[(size, size) for size in ico_sizes],
    )

    # .icns via icnsutil — uses an iconset folder with standard Apple names.
    iconset = ASSETS / "icon.iconset"
    iconset.mkdir(exist_ok=True)
    iconset_files = [
        ("icon_16x16.png", 16),
        ("icon_32x32.png", 32),
        ("icon_128x128.png", 128),
        ("icon_256x256.png", 256),
        ("icon_512x512.png", 512),
        ("icon_512x512@2x.png", 1024),
    ]
    for name, src_size in iconset_files:
        src = ASSETS / f"icon_{src_size}x{src_size}.png"
        if src_size == 1024:
            src = ASSETS / "icon_1024x1024.png"
        shutil.copy(src, iconset / name)

    cmd = (
        f"icnsutil compose -f {ASSETS / 'icon.icns'} "
        + " ".join(str(iconset / name) for name, _ in iconset_files)
    )
    os.system(cmd)

    # Clean up the temporary iconset folder once the .icns is built.
    shutil.rmtree(iconset, ignore_errors=True)

    print("Generated app icon assets.")


if __name__ == "__main__":
    main()
