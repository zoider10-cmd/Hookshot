"""The app icon from a picture: an .ico for the builder and a .res the game's exe links in (nx2/build.py).

    python nx2/make_icon.py <picture.png> [out folder, default work]

The picture is the user's and stays out of the repository, so these go to work/. Needs Pillow. The builder makes the game's
own (its icon, and the name Windows shows for the exe) with the same functions: nx2/game_title.py.
"""
import io
import os
import struct
import sys

SIZES = (16, 24, 32, 48, 64, 128, 256)


def square(im, size):
    """fitted in a transparent square, not stretched"""
    from PIL import Image
    im = im.convert("RGBA")
    k = size / max(im.size)
    fit = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(fit, ((size - fit.width) // 2, (size - fit.height) // 2), fit)
    return out


def png_of(im):
    b = io.BytesIO()
    im.save(b, "PNG", optimize=True)
    return b.getvalue()


def images_of(im):
    """[(size, PNG bytes)] at each of SIZES"""
    return [(s, png_of(square(im, s))) for s in SIZES]


def res_entry(kind, name, data, flags=0x1010):
    header = struct.pack("<II", len(data), 32) + struct.pack("<HHHH", 0xFFFF, kind, 0xFFFF, name)
    header += struct.pack("<IHHII", 0, flags, 0x0409, 0, 0)
    return header + data + b"\0" * (-len(data) & 3)


def ico_of(images):
    head = struct.pack("<HHH", 0, 1, len(images))
    offset = len(head) + 16 * len(images)
    entries, body = b"", b""
    for s, data in images:
        b = s & 255
        entries += struct.pack("<BBBBHHII", b, b, 0, 0, 1, 32, len(data), offset + len(body))
        body += data
    return head + entries + body


def icon_entries(images):
    """RT_ICON and RT_GROUP_ICON entries of a .res: group 1, what the window class loads (host/display.c)"""
    group = struct.pack("<HHH", 0, 1, len(images))
    res = b""
    for i, (s, data) in enumerate(images):
        b = s & 255
        group += struct.pack("<BBBBHHIH", b, b, 0, 0, 1, 32, len(data), i + 1)
        res += res_entry(3, i + 1, data)   # RT_ICON
    return res + res_entry(14, 1, group, 0x1030)   # RT_GROUP_ICON


def _node(key, value=b"", text=False, children=()):
    """one VS_VERSIONINFO node: wLength, wValueLength (in WCHARs for text), wType, key, value, children, each 4-aligned"""
    body = key.encode("utf-16-le") + b"\0\0"
    body += b"\0" * (-(6 + len(body)) & 3)
    body += value
    for child in children:
        body += b"\0" * (-(6 + len(body)) & 3)
        body += child
    count = len(value) // 2 if text else len(value)
    return struct.pack("<HHH", 6 + len(body), count, 1 if text else 0) + body


def version_entry(strings):
    """RT_VERSION 1: what Windows shows for the exe (Task Manager, the taskbar, its Properties): strings {name: text}"""
    fixed = struct.pack("<13I", 0xFEEF04BD, 0x00010000, 0, 0, 0, 0, 0x3F, 0, 0x00040004, 1, 0, 0, 0)   # (VOS_NT_WINDOWS32, VFT_APP)
    table = [_node(k, v.encode("utf-16-le") + b"\0\0", True) for k, v in strings.items()]
    info = _node("VS_VERSION_INFO", fixed, children=[
        _node("StringFileInfo", text=True, children=[_node("040904b0", text=True, children=table)]),
        _node("VarFileInfo", text=True, children=[_node("Translation", struct.pack("<HH", 0x0409, 1200))])])
    return res_entry(16, 1, info, 0x0030)


def res_of(images=(), strings=None):
    """a .res: the icon (images_of's), and the version strings when given"""
    res = res_entry(0, 0, b"", 0)   # (a .res file starts with an empty entry)
    if images:
        res += icon_entries(images)
    if strings:
        res += version_entry(strings)
    return res


def main():
    from PIL import Image
    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "work")
    images = images_of(Image.open(src))
    with open(os.path.join(out, "hookshot.ico"), "wb") as f:
        f.write(ico_of(images))
    res = res_of(images)
    with open(os.path.join(out, "hookshot.res"), "wb") as f:
        f.write(res)
    print("make_icon: %d sizes, %d KB" % (len(images), len(res) >> 10))


if __name__ == "__main__":
    main()
