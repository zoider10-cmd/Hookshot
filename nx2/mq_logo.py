"""(Mako) The Master Quest title logo, made at build time from the player's own RomFS (no game art ships with Mako).

    python -I nx2/mq_logo.py --romfs <dir> --out <game folder>/prompts      (also called by nx2/prompt_assets.py)

The title's logo is in two texture files: UI/Layout2Archive/Title.*.bntx (Logo, Text, GlowL, GlowS, Effect: the logo fading in)
and UI/Layout2Archive/Common.*.bntx (Logo, Text, Text_Glow: the logo once it is in place). Both get the same look, after the
GameCube's Master Quest: "ZELDA" in blue foil, the subtitles in silver, "MASTER QUEST" in gold foil below them with the game's
Ocarina of Time icon. The glows are the new logo blurred as much as the game's glows are its logo (found by trying radii).

Writes, in the HPTX format of nx2/prompt_assets.py (one entry, Switch button 0xff: always written):
  <out>/mq/Title.bntx   the game's Title bntx, decompressed
  <out>/mq/title.bin    the blocks to write over it
  <out>/mq/common.bin   the blocks to write over <out>/Common.bntx (the prompts' copy of the game's Common bntx)
host/prompts.c writes them over the game's files when Master Quest is on (hookshot_options.ini master_quest=1).

Only the English/European logo (the *_USEU_00 textures) is known: other regions keep the game's. The "MASTER QUEST" letters are
drawn with Constantia Bold from the system's fonts (not shipped); without it, or without Pillow, numpy, astc_encoder and
texture2ddecoder, no logo is made and the game shows its own.
"""
import argparse
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)   # (python -I leaves the script folder off)

TITLE = "UI/Layout2Archive/Title.Product.100.Nin_Ounce_NVN2.bntx.zs"
COMMON = "UI/Layout2Archive/Common.Product.100.Nin_Ounce_NVN2.bntx.zs"
OCARINA = "UI/Tex/Icon/Item_Ocarina_Time.bntx.zs"
LOGO, TEXT = "Logo_USEU_00", "Logo_Text_USEU_00"
TITLE_GLOWS = ("Logo_GlowL_USEU_00", "Logo_GlowS_USEU_00", "Logo_Effect_USEU_00")
COMMON_GLOWS = ("Logo_Text_Glow_USEU_00",)
LOGO_SIZE = (1664, 1280)   # (the places below are the USEU logo's)
FONTS = [os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "constanb.ttf"),
         "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"]

# the foil colours: blue for ZELDA (dark navy -> royal blue -> pale highlight), silver for the subtitles
DARK, MID, HI = (4, 8, 55), (22, 45, 165), (130, 160, 235)


def _foil(rgba, sub):
    """rgba's colours as blue foil, silver where sub (H, W, 1) is 1, by its lightness"""
    import numpy as np
    lum = (0.3 * rgba[..., 0] + 0.59 * rgba[..., 1] + 0.11 * rgba[..., 2])[..., None] / 255
    lum = np.clip((lum - 0.15) / 0.8, 0, 1)
    dark, mid, hi = (np.array(c, np.float32) for c in (DARK, MID, HI))
    blue = np.where(lum < 0.6, dark + (mid - dark) * (lum / 0.6), mid + (hi - mid) * ((lum - 0.6) / 0.4))
    silver = np.clip(lum ** 0.9 * np.array([235, 238, 245]) + 15, 0, 255) * np.ones(3)
    return blue * (1 - sub) + silver * sub


def new_logo(logo, foil, ocarina, font_path):
    """the Master Quest logo from the game's (logo, RGBA), its gold foil text layer (foil) and the ocarina icon"""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    W, H = logo.size
    # ---- 1. the gold foil: ZELDA blue, the subtitles silver (the triforce on the shield and the sword's gem stay gold)
    hsv = np.array(logo.convert("RGB").convert("HSV")).astype(np.float32)
    rgba = np.array(logo).astype(np.float32)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    gold = ((h > 12) & (h < 48) & (s > 85) & (v > 40) & (rgba[..., 3] > 0)).astype(np.float32)
    gold[0:420, :] = 0
    gm = Image.fromarray((gold * 255).astype(np.uint8))
    core = gm.filter(ImageFilter.MinFilter(9)).filter(ImageFilter.MaxFilter(9))   # (no isolated warm specks on the shield)
    keep = np.array(core.filter(ImageFilter.MaxFilter(13))).copy()
    keep[430:515, 690:1460] = 255   # THE LEGEND OF
    keep[895:990, 690:1560] = 255   # OCARINA OF TIME
    gm = Image.fromarray(np.minimum(np.array(gm), keep)).filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.GaussianBlur(1))
    g = np.array(gm).astype(np.float32)[..., None] / 255
    sub = np.zeros((H, W, 1), np.float32)
    sub[430:515, 690:1460] = 1
    sub[895:990, 690:1560] = 1
    rgba[..., :3] = rgba[..., :3] * (1 - g) + _foil(rgba, sub) * g
    out = Image.fromarray(rgba.clip(0, 255).astype(np.uint8), "RGBA")
    # ---- 2. MASTER QUEST in small capitals, gold foil turning orange downwards (as the GameCube's), under the subtitle
    big, small = ImageFont.truetype(font_path, 108), ImageFont.truetype(font_path, 80)
    parts = [("M", big), ("ASTER", small), (" ", small), ("Q", big), ("UEST", small)]
    m = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(m)
    x, base, sp = 700, 1088, 6
    for t, f in parts:
        for c in t:
            d.text((x, base - f.getmetrics()[0]), c, font=f, fill=255)
            x += d.textlength(c, font=f) + sp
    m = m.filter(ImageFilter.GaussianBlur(0.8)).point(lambda q: 255 if q > 110 else 0)
    bb = m.getbbox()
    sh = m.filter(ImageFilter.MaxFilter(21)).filter(ImageFilter.GaussianBlur(16)).point(lambda q: int(q * 0.6))
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    lay.putalpha(sh)
    out = Image.alpha_composite(out, lay)
    rim = m.filter(ImageFilter.MaxFilter(7)).filter(ImageFilter.GaussianBlur(0.8))
    lay = Image.new("RGBA", (W, H), (20, 8, 0, 255))
    lay.putalpha(rim)
    out = Image.alpha_composite(out, lay)
    patch = foil.convert("RGB").crop((560, 150, 1360, 470))   # (the game's own gold foil, from the big Z)
    fill = Image.new("RGB", (W, H))
    for ty in range(bb[1] - 10, bb[3] + 10, patch.height):
        for tx in range(bb[0] - 10, bb[2] + 10, patch.width):
            fill.paste(patch, (tx, ty))
    fa = np.array(fill).astype(np.float32)
    yy = np.clip((np.arange(H) - bb[1]) / max(1, bb[3] - bb[1]), 0, 1)[:, None, None]
    tint = np.array([1.08, 1.0, 0.85]) * (1 - yy) + np.array([1.15, 0.62, 0.28]) * yy
    lay = Image.fromarray(np.clip(fa * tint, 0, 255).astype(np.uint8)).convert("RGBA")
    lay.putalpha(m)
    out = Image.alpha_composite(out, lay)
    # ---- 3. the ocarina at the end of the words, with its shadow
    if ocarina is not None:
        oc = ocarina.crop(ocarina.getbbox()).transpose(Image.FLIP_LEFT_RIGHT)
        ow = 215
        oc = oc.resize((ow, round(oc.height * ow / oc.width)), Image.LANCZOS).rotate(-12, expand=True, resample=Image.BICUBIC)
        ox, oy = int(x - 16), int(base - oc.height * 0.62)
        osh = Image.new("L", (W, H), 0)
        osh.paste(oc.getchannel("A"), (ox, oy))
        osh = osh.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(14)).point(lambda q: int(q * 0.6))
        lay = Image.new("RGBA", (W, H), (0, 0, 0, 255))
        lay.putalpha(osh)
        out = Image.alpha_composite(out, lay)
        ol = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ol.paste(oc, (ox, oy))
        out = Image.alpha_composite(out, ol)
    return out


def new_text(text, big_size):
    """the text layer (the logo's lettering) recoloured as the logo: blue foil, silver subtitles (places for the Title's size;
    another size, the Common's, by the same proportions)"""
    import numpy as np
    from PIL import Image
    rgba = np.asarray(text.convert("RGBA")).astype(np.float32).copy()
    H, W = rgba.shape[:2]
    sy, sx = H / big_size[1], W / big_size[0]
    sub = np.zeros((H, W, 1), np.float32)
    sub[int(30 * sy):int(110 * sy), int(640 * sx):int(1320 * sx)] = 1
    sub[int(505 * sy):int(600 * sy), int(550 * sx):int(1440 * sx)] = 1
    rgba[..., :3] = _foil(rgba, sub)
    return Image.fromarray(rgba.clip(0, 255).astype(np.uint8), "RGBA")


def _blur(im, r):
    """a blur of premultiplied colour (no dark fringes where it fades out)"""
    import numpy as np
    from PIL import Image, ImageFilter
    a = np.asarray(im).astype(np.float32)
    al = a[..., 3:] / 255
    pm = Image.fromarray(np.dstack([a[..., :3] * al, a[..., 3:]]).clip(0, 255).astype(np.uint8), "RGBA").filter(
        ImageFilter.GaussianBlur(r))
    p = np.asarray(pm).astype(np.float32)
    den = p[..., 3:] / 255
    rgb = np.where(den > 0.002, p[..., :3] / np.maximum(den, 0.002), 255)
    return Image.fromarray(np.dstack([rgb, p[..., 3:]]).clip(0, 255).astype(np.uint8), "RGBA")


def new_glow(glow, sources):
    """the glow made again: of the (old, new) source pairs, the old one and blur radius that best give the game's glow, then the
    same blur of the new one"""
    import numpy as np
    from PIL import Image
    best = None
    want = np.asarray(glow.convert("RGBA")).astype(np.float32)
    for i, (old, _) in enumerate(sources):
        small = old.resize(glow.size, Image.LANCZOS)
        for r in (0.5, 1, 1.5, 2, 3, 4, 6, 8, 10, 12, 14, 16, 20, 24, 28, 32):
            e = np.abs(np.asarray(_blur(small, r)).astype(np.float32) - want).mean()
            if best is None or e < best[0]:
                best = (e, r, i)
    return _blur(sources[best[2]][1].resize(glow.size, Image.LANCZOS), best[1])


def first_texture(pa, b):
    tex = pa.bntx_textures(b)
    return pa.decode(b, next(iter(tex.values()))).convert("RGBA") if tex else None


def build(romfs, out, dictionary=None, common=None, log=print):
    """writes <out>/mq/{Title.bntx,title.bin,common.bin}; 1 when made. common: the game's Common bntx (decompressed), if read"""
    import prompt_assets as pa
    from PIL import Image
    font = next((f for f in FONTS if os.path.isfile(f)), None)
    if not font:
        log("master quest: no logo (no Constantia Bold font on this system)")
        return 0
    dictionary = dictionary or pa.zs_dictionary(romfs)
    title = pa.read_zs(romfs, TITLE, dictionary)
    ttex = pa.bntx_textures(title)
    if LOGO not in ttex or TEXT not in ttex or ttex[LOGO][2:4] != LOGO_SIZE:
        log("master quest: no logo (this game's title logo is not the English/European one known)")
        return 0
    logo, text = pa.decode(title, ttex[LOGO]).convert("RGBA"), pa.decode(title, ttex[TEXT]).convert("RGBA")
    try:
        ocarina = first_texture(pa, pa.read_zs(romfs, OCARINA, dictionary))
    except OSError:
        ocarina = None
    mq_logo, mq_text = new_logo(logo, text, ocarina, font), new_text(text, text.size)
    title_layers = {LOGO: mq_logo, TEXT: mq_text}
    for name in TITLE_GLOWS:
        if name in ttex:
            title_layers[name] = new_glow(pa.decode(title, ttex[name]), [(logo, mq_logo), (text, mq_text)])
    d = os.path.join(out, "mq")
    os.makedirs(d, exist_ok=True)
    # (the launcher's Master Quest page shows it: made here from the player's own files, never shipped)
    shown = mq_logo.crop(mq_logo.getbbox() or (0, 0) + mq_logo.size)   # (the logo alone, its empty edges cut)
    shown.resize((shown.width // 2, shown.height // 2), Image.LANCZOS).save(os.path.join(d, "logo.png"))
    with open(os.path.join(d, "Title.bntx"), "wb") as f:
        f.write(title)
    pa.write_textures(os.path.join(d, "title.bin"), [(0xFF, 0, [r for n, im in title_layers.items()
                                                              for r in pa.runs(ttex[n], im)])])
    made = sorted(title_layers)
    if common is None:
        common = pa.read_zs(romfs, COMMON, dictionary)
    ctex = pa.bntx_textures(common)
    common_layers = {}
    for name, im in ((LOGO, mq_logo), (TEXT, mq_text)):
        if name in ctex:
            w, h = ctex[name][2:4]
            common_layers[name] = im if im.size == (w, h) else im.resize((w, h), Image.LANCZOS)
    for name in COMMON_GLOWS:
        if name in ctex:
            common_layers[name] = new_glow(pa.decode(common, ctex[name]), [(text, mq_text), (logo, mq_logo)])
    pa.write_textures(os.path.join(d, "common.bin"), [(0xFF, 0, [r for n, im in common_layers.items()
                                                               for r in pa.runs(ctex[n], im)])])
    log("master quest: the logo (%s; Common: %s)" % (", ".join(made), ", ".join(sorted(common_layers)) or "none"))
    return 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--romfs", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--png", help="also write the made logo as PNG files into this folder (to look at)")
    a = ap.parse_args()
    ok = build(a.romfs, a.out, log=lambda s: print(s, file=sys.stderr))
    if ok and a.png:
        import prompt_assets as pa
        os.makedirs(a.png, exist_ok=True)
        for base, binname in (("Title.bntx", "title.bin"),):
            b = bytearray(open(os.path.join(a.out, "mq", base), "rb").read())
            apply_hptx(b, os.path.join(a.out, "mq", binname))
            tex = pa.bntx_textures(bytes(b))
            for n in (LOGO, TEXT) + TITLE_GLOWS:
                if n in tex:
                    pa.decode(bytes(b), tex[n]).save(os.path.join(a.png, n + ".png"))
    sys.exit(0 if ok else 1)


def apply_hptx(b, path):
    """the runs of an HPTX file written over b (as host/prompts.c does for Switch button 0xff)"""
    with open(path, "rb") as f:
        t = f.read()
    assert t[:4] == b"HPTX"
    count, = struct.unpack_from("<I", t, 4)
    at = 8
    for _ in range(count):
        n, = struct.unpack_from("<I", t, at + 4)
        at += 8
        for _ in range(n):
            off, ln = struct.unpack_from("<II", t, at)
            b[off:off + ln] = t[at + 8:at + 8 + ln]
            at += 8 + ln


if __name__ == "__main__":
    main()
