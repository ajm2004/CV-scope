"""Draw the CV-Scope icon and the setup wizard images (Pillow).

    python installer/make_assets.py installer/build

writes cvscope.ico (16-256 px), wizard-small-*.png (top right of the wizard)
and wizard-large-*.png (Welcome and Finished pages) at the sizes Inno Setup
picks from for 100-250 % display scaling. The pictures are generated at build
time because the repository keeps binary media out of the source tree.

The mark: a camera viewfinder (four corner brackets) around a tracked path
whose latest position is drawn in the colour the Scene Builder uses for
counting lines. Colours are the app's accent tokens.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ACCENT = (11, 107, 138)  # --accent
ACCENT_DEEP = (6, 63, 82)
WHITE = (255, 255, 255)
TRACK = (242, 182, 50)  # --c-line
SS = 8  # supersampling factor


def _gradient(size: tuple[int, int], top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    w, h = size
    img = Image.new("RGB", size)
    px = img.load()
    for y in range(h):
        t = y / max(1, h - 1)
        c = tuple(round(a + (b - a) * t) for a, b in zip(top, bottom, strict=True))
        for x in range(w):
            px[x, y] = c
    return img


def _mark(draw: ImageDraw.ImageDraw, box: tuple[float, float, float], detail: bool) -> None:
    """Viewfinder and path inside the square (x, y, side); coordinates on a 0-100 grid."""
    x0, y0, side = box

    def p(u: float, v: float) -> tuple[float, float]:
        return x0 + u * side / 100, y0 + v * side / 100

    stroke = side * (0.085 if detail else 0.12)
    arm = 17 if detail else 22
    lo, hi = (20, 80) if detail else (16, 84)
    for cx, cy, dx, dy in ((lo, lo, 1, 1), (hi, lo, -1, 1), (lo, hi, 1, -1), (hi, hi, -1, -1)):
        corner = p(cx, cy)
        draw.line([p(cx + dx * arm, cy), corner, p(cx, cy + dy * arm)], fill=WHITE, width=round(stroke), joint="curve")
        r = stroke / 2
        for end in (p(cx + dx * arm, cy), p(cx, cy + dy * arm), corner):
            draw.ellipse([end[0] - r, end[1] - r, end[0] + r, end[1] + r], fill=WHITE)
    if detail:
        # a tracked path: earlier positions small, the latest one large
        path = [(33, 69), (41, 62), (50, 57), (58, 50), (65, 41)]
        draw.line([p(*q) for q in path], fill=WHITE, width=round(side * 0.035), joint="curve")
        for i, q in enumerate(path[:-1]):
            c = p(*q)
            r = side * (0.022 + 0.006 * i)
            draw.ellipse([c[0] - r, c[1] - r, c[0] + r, c[1] + r], fill=WHITE)
    c = p(*((65, 41) if detail else (50, 50)))
    r = side * (0.075 if detail else 0.13)
    draw.ellipse([c[0] - r, c[1] - r, c[0] + r, c[1] + r], fill=TRACK)


def tile(size: int) -> Image.Image:
    """The icon: a rounded tile in the accent colour with the mark."""
    big = size * SS
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, big - 1, big - 1], radius=round(big * 0.22), fill=255)
    img.paste(_gradient((big, big), ACCENT, ACCENT_DEEP), (0, 0), mask)
    _mark(ImageDraw.Draw(img), (0, 0, big), detail=size >= 32)
    return img.resize((size, size), Image.Resampling.LANCZOS)


def wizard_large(w: int, h: int) -> Image.Image:
    """Side panel of the Welcome and Finished pages: accent gradient, faint
    scene grid, the mark and a few tracks crossing a counting line."""
    W, H = w * SS, h * SS
    img = _gradient((W, H), ACCENT, ACCENT_DEEP).convert("RGBA")
    over = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    step = W / 6
    for i in range(1, 6):
        d.line([(i * step, 0), (i * step, H)], fill=(255, 255, 255, 18), width=SS)
    for j in range(1, int(H / step) + 1):
        d.line([(0, j * step), (W, j * step)], fill=(255, 255, 255, 18), width=SS)
    line_y = H * 0.74
    d.line([(W * 0.08, line_y), (W * 0.92, line_y)], fill=(*TRACK, 150), width=round(2.2 * SS))
    for k, (sx, ex) in enumerate(((0.22, 0.34), (0.5, 0.62), (0.78, 0.7))):
        pts = [(W * (sx + (ex - sx) * t), H * (0.95 - 0.35 * t) + (k - 1) * SS * 2) for t in (0, 0.25, 0.5, 0.75, 1)]
        d.line(pts, fill=(255, 255, 255, 90), width=round(1.6 * SS), joint="curve")
        for q in pts[:-1]:
            r = 1.8 * SS
            d.ellipse([q[0] - r, q[1] - r, q[0] + r, q[1] + r], fill=(255, 255, 255, 110))
        q, r = pts[-1], 3.4 * SS
        d.ellipse([q[0] - r, q[1] - r, q[0] + r, q[1] + r], fill=(*TRACK, 230))
    img = Image.alpha_composite(img, over)
    side = W * 0.56
    _mark(ImageDraw.Draw(img), ((W - side) / 2, H * 0.2, side), detail=True)
    return img.convert("RGB").resize((w, h), Image.Resampling.LANCZOS)


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    frames = [tile(s) for s in sizes]
    frames[-1].save(out / "cvscope.ico", sizes=[(s, s) for s in sizes], append_images=frames[:-1])
    tile(256).save(out / "cvscope-256.png")
    for s in (58, 97, 124, 159):  # WizardSmallImageFile at 100, 150, 200, 250 %
        tile(s).save(out / f"wizard-small-{s}.png")
    for w, h in ((202, 386), (336, 643), (430, 824), (534, 1022)):  # WizardImageFile at 100, 150, 200, 250 %
        wizard_large(w, h).save(out / f"wizard-large-{w}.png")
    print(f"assets written to {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent / "build"))
