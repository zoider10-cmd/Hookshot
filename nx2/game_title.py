"""The game's own name and icon, read from its .nup, for what the build makes of them: the window's title and icon, and on
Windows the exe's icon and the name Windows shows for it (Task Manager, the taskbar, its Properties). Without them the game
was "Hookshot" with no icon.

    python -I nx2/game_title.py <file.nup>          the name and the icon's size, nothing written

A .nup title's metadata (nx2/nup.py, at +0x20 of its record) is a list of records, each u32 kind, u32 size, then its bytes:
1 the NPDM, 3 the icon (a JPEG), 4 the version ("1.1.1"), 5 the name, 8 a short name (seen on Ocarina of Time 1.1.1).

What is read is kept in the game folder, so an update (built from the folder, with no .nup) makes them again, and the game
reads the title from there: hookshot_title.txt (its first line, the window's title: host/hos_paths.h hos_game_title) and
.hookshot_icon.jpg (the icon as the game has it). Both are the player's own game's and stay in the folder.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # (python -I leaves the script folder off)
import nup as _nup  # noqa: E402

TITLE_FILE = "hookshot_title.txt"
ICON_FILE = ".hookshot_icon.jpg"
RES_FILE = "hookshot_game.res"   # (in the work folder: linked into the exe instead of a developer's hookshot.res, nx2/build.py)
SUFFIX = " (Hookshot)"
ICON, NAME = 3, 5
# (the names in a .nup are fit for a file name: its dumper drops what Windows refuses in one, so the colon of the name the game
# itself shows is gone. These are the names as the games write them, by title id)
NAMES = {0x0400486024DEC000: "The Legend of Zelda: Ocarina of Time"}


def records(blob):
    """{kind: bytes} of a title's metadata; what does not parse ends the list"""
    out, at = {}, 0
    while at + 8 <= len(blob):
        kind, size = struct.unpack_from("<II", blob, at)
        if at + 8 + size > len(blob):
            break
        out.setdefault(kind, blob[at + 8:at + 8 + size])
        at += 8 + size
    return out


def clean(name):
    """one line of printable text, or "" """
    name = "".join(c for c in name if c.isprintable()).strip()
    return name[:200]


def from_nup(path):
    """(name, icon JPEG bytes or None) of the title nup.py extracts (the newest), or None when the .nup has no metadata"""
    nup = _nup.Nup(path)
    try:
        t = _nup.pick_title(nup, None)
        nup.f.seek(0xb0 + 0x40 * t["index"] + 0x20)
        offset, size = struct.unpack("<QQ", nup.f.read(16))
        if not size or size > 16 << 20 or offset + size > os.fstat(nup.f.fileno()).st_size:
            return None
        nup.f.seek(offset)
        meta = records(nup.f.read(size))
    finally:
        nup.f.close()
    name = NAMES.get(t["id"]) or clean(meta.get(NAME, b"").decode("utf-8", "replace"))
    icon = meta.get(ICON)
    if icon is not None and icon[:3] != b"\xff\xd8\xff":
        icon = None
    if not name and not icon:
        return None
    return name, icon


def write_if_changed(path, data):
    try:
        with open(path, "rb") as f:
            if f.read() == data:
                return
    except OSError:
        pass
    with open(path + ".new", "wb") as f:
        f.write(data)
    os.replace(path + ".new", path)


def keep(out, name, icon):
    """the folder's copy of what was read"""
    if name:
        write_if_changed(os.path.join(out, TITLE_FILE), (name + SUFFIX + "\n").encode("utf-8"))
    if icon:
        write_if_changed(os.path.join(out, ICON_FILE), icon)


def kept(out):
    """(window title, icon JPEG bytes or None) the folder has, or (None, None)"""
    title = icon = None
    try:
        with open(os.path.join(out, TITLE_FILE), encoding="utf-8") as f:
            title = clean(f.readline()) or None
    except (OSError, UnicodeDecodeError):
        pass
    try:
        with open(os.path.join(out, ICON_FILE), "rb") as f:
            icon = f.read() or None
    except OSError:
        pass
    return title, icon


def picture(icon):
    """the icon as a Pillow image, or None (no Pillow, or a picture it cannot read)"""
    if not icon:
        return None
    try:
        import io
        from PIL import Image
        im = Image.open(io.BytesIO(icon))
        im.load()
        return im
    except Exception as e:   # (Pillow's errors are many kinds: a picture that does not read leaves the game without it)
        print("the game's icon could not be read (%s: %s): the game has none" % (type(e).__name__, e), flush=True)
        return None


def write_res(out, path):
    """(Windows) the exe's icon and the name Windows shows for it, at path; True when written. Removed when the folder has
    neither, so a developer's own hookshot.res (nx2/make_icon.py) is linked instead"""
    import make_icon
    title, icon = kept(out)
    im = picture(icon)
    if not title and im is None:
        if os.path.exists(path):
            os.remove(path)
        return False
    strings = {"FileDescription": title, "ProductName": title, "InternalName": "hookshot",
               "OriginalFilename": "hookshot.exe"} if title else None
    write_if_changed(path, make_icon.res_of(make_icon.images_of(im) if im is not None else (), strings))
    return True


def write_png(out, path, size=256):
    """(Linux) the window's icon at path, from the game's; False when the folder has none to make it from"""
    im = picture(kept(out)[1])
    if im is None:
        return False
    import make_icon
    write_if_changed(path, make_icon.png_of(make_icon.square(im, size)))
    return True


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    got = from_nup(sys.argv[1])
    if not got:
        raise SystemExit("no name or icon in this .nup")
    name, icon = got
    print("%s%s, icon: %s" % (name, SUFFIX, "%d bytes" % len(icon) if icon else "none"))


if __name__ == "__main__":
    main()
