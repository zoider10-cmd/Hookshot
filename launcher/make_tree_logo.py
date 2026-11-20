"""Lost Woods: the launcher's logo, an old world tree, drawn from code (no outside picture): launcher/lostwoods_logo.png
(transparent, 680x400) and launcher/lostwoods.ico. Run: py -I launcher/make_tree_logo.py (needs Pillow)."""
import math
import os
import random

from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
S = 4                      # (drawn at 4x, then made smaller: smooth edges)
W, H = 680, 400
rnd = random.Random(7)


def big(v):
    return int(v * S)


def blob(d, cx, cy, r, fill):
    d.ellipse([big(cx - r), big(cy - r), big(cx + r), big(cy + r)], fill=fill)


def limb(d, pts, w0, w1, fill):
    """A branch or root: a line of circles along a curve, from width w0 to w1"""
    n = 600
    for i in range(n + 1):
        t = i / n
        # (a quadratic curve through the points)
        (x0, y0), (x1, y1), (x2, y2) = pts
        x = (1 - t) ** 2 * x0 + 2 * (1 - t) * t * x1 + t * t * x2
        y = (1 - t) ** 2 * y0 + 2 * (1 - t) * t * y1 + t * t * y2
        r = (w0 + (w1 - w0) * t) / 2
        blob(d, x, y, r, fill)


def tree():
    img = Image.new("RGBA", (W * S, H * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx, ground = W / 2, 356
    bark, bark_dark, bark_light = (96, 70, 44, 255), (60, 42, 27, 255), (134, 100, 64, 255)

    # (roots, spreading wide over the ground, each tapering to a point)
    for side in (-1, 1):
        for k, (reach, drop, w) in enumerate([(240, 22, 24), (175, 34, 20), (110, 40, 16), (290, 8, 12)]):
            limb(d, [(cx + side * 24, ground - 34), (cx + side * reach * 0.45, ground - 4 + k * 3), (cx + side * reach, ground + drop * 0.3)],
                 w, 1.2, bark_dark if k % 2 else bark)
    # (the trunk: wide at the foot, a little twisted, narrowing up to the branches)
    top_y = 178
    for i in range(0, 201):
        t = i / 200
        y = ground - 22 - t * (ground - 22 - top_y)
        wob = math.sin(t * 6.0) * 7 * (1 - t)
        half = 54 * (1 - t) ** 1.3 + 24
        d.rectangle([big(cx - half + wob), big(y), big(cx + half + wob), big(y + 2)], fill=bark)
    # (bark lines, and light down one side)
    for j in range(-3, 4):
        x0 = cx + j * 13
        limb(d, [(x0, ground - 14), (x0 + j * 3 + rnd.uniform(-5, 5), ground - 100), (cx + j * 7, top_y + 6)], 4.5, 1.5, bark_dark)
    limb(d, [(cx - 34, ground - 30), (cx - 26, ground - 110), (cx - 14, top_y + 10)], 6, 2, bark_light)

    # (the crown: clusters of leaves at the ends of great branches, a wide umbrella like a world tree's)
    clusters = [(cx, 70, 92, 52), (cx - 150, 98, 84, 48), (cx + 152, 94, 84, 48), (cx - 248, 146, 64, 40),
                (cx + 250, 142, 64, 40), (cx - 70, 124, 70, 40), (cx + 78, 128, 70, 40)]
    for (x, y, rx, ry) in clusters:
        limb(d, [(cx + (x - cx) * 0.08, top_y + 14), (cx + (x - cx) * 0.55, (top_y + y) / 2 + 14), (x, y + ry * 0.4)],
             max(10, 30 - abs(x - cx) / 14), 5, bark)
    shades = [(28, 62, 30, 255), (40, 86, 38, 255), (60, 116, 50, 255), (88, 150, 62, 255), (132, 186, 84, 255)]
    for layer in range(4):
        for (x, y, rx, ry) in clusters:
            for _ in range(16 if layer < 3 else 9):
                a = rnd.uniform(0, math.pi * 2)
                rr = math.sqrt(rnd.random()) * (1 - layer * 0.18)
                bx, by = x + math.cos(a) * rr * rx, y + math.sin(a) * rr * ry - layer * 7
                r = rnd.uniform(18, 30) * (1 - layer * 0.12)
                k = layer + (1 if by < y - ry * 0.3 and layer >= 2 else 0)
                blob(d, bx, by, r, shades[min(4, k)])

    img = img.resize((W, H), Image.LANCZOS)

    # (fairy lights drifting around the crown, softly glowing)
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    for _ in range(18):
        x, y = rnd.uniform(70, 610), rnd.uniform(30, 300)
        r = rnd.uniform(1.6, 3.4)
        g.ellipse([x - r * 3.5, y - r * 3.5, x + r * 3.5, y + r * 3.5], fill=(214, 240, 140, 55))
        g.ellipse([x - r, y - r, x + r, y + r], fill=(250, 255, 210, 255))
    glow = glow.filter(ImageFilter.GaussianBlur(1.0))
    return Image.alpha_composite(img, glow)


def icon(logo):
    sq = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
    part = logo.crop((140, 0, 540, 400))
    sq.alpha_composite(part)
    sq.save(os.path.join(HERE, "lostwoods.ico"), sizes=[(256, 256), (64, 64), (48, 48), (32, 32), (16, 16)])


if __name__ == "__main__":
    logo = tree()
    logo.save(os.path.join(HERE, "lostwoods_logo.png"))
    icon(logo)
    print("wrote lostwoods_logo.png and lostwoods.ico")
