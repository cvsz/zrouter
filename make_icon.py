#!/usr/bin/env python3
"""Generate nvidia.ico (multi-size) - a generic 'router' glyph. Requires: pip install pillow"""

from PIL import Image, ImageDraw

S = 1024  # draw big, downscale for smooth edges
BG, FG, DIM = (
    (17, 22, 12, 255),
    (118, 185, 0, 255),
    (62, 96, 12, 255),
)  # DIM is opaque on purpose


def line(d, a, b, w, col):
    d.line([a, b], fill=col, width=w)
    for x, y in (a, b):
        d.ellipse([x - w // 2, y - w // 2, x + w // 2, y + w // 2], fill=col)


def draw():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, S - 1, S - 1], radius=int(S * 0.22), fill=BG)

    src = (230, 512)
    outs = [(790, 270), (790, 512), (790, 754)]
    mid = 470
    w = 56
    # fallbacks dimmed first, active route drawn last so it sits on top
    for i in (0, 2, 1):
        o = outs[i]
        col = FG if i == 1 else DIM
        line(d, src, (mid, src[1]), w, col)
        line(d, (mid, src[1]), (mid, o[1]), w, col)
        line(d, (mid, o[1]), o, w, col)
        r = 70
        d.ellipse([o[0] - r, o[1] - r, o[0] + r, o[1] + r], fill=col)
    r = 92
    d.ellipse([src[0] - r, src[1] - r, src[0] + r, src[1] + r], fill=FG)
    d.ellipse([src[0] - 38, src[1] - 38, src[0] + 38, src[1] + 38], fill=BG)
    return img


if __name__ == "__main__":
    big = draw()
    sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)]
    big.save("nvidia.ico", format="ICO", sizes=sizes)
    big.resize((512, 512), Image.LANCZOS).save("nvidia.png")
    print("wrote nvidia.ico", [s[0] for s in sizes], "and nvidia.png")
