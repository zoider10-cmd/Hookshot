"""(hookshot) The game's texts with the console's wording made the PC's: python -I nx2/text_assets.py --romfs R --out DIR

One of the game's texts names the console: the hint for playing the ocarina by microphone says to use its built-in one. On a
PC that is the wrong advice: the game listens to the microphone the menu's Microphone row chooses. This rewords that string
in the player's own text archives at build time, as nx2/prompt_assets.py redraws the button icons, and host/texts.c serves the
result in place of the game's file (a mod's own file wins; HOS_TEXTS=0: the game's own texts).

The texts are romfs/Mals/<language>.Product.<n>.sarc.zs, one archive a language: a zstd frame (made with the game's zs
dictionary, in Pack/ZsDic.pack.zs) of a SARC of MSBT files, UTF-8 in this game. STRINGS names each string by its MSBT and its
label, and gives its edit for every wording of it the game has: the bytes from start to end of the string become the
replacement, and the rest (the other sentences, the menu's icon, the reading aids over the kanji) stays the game's. A wording
is known by its fingerprint, so no game text is in this file, and a string that is not one of them (another game version, a
text a mod's author changed) is left as it is and said.

A replacement is never longer than what it replaces: the string is rewritten where it is and what is left of its room is
filled with NULs, so no offset in the MSBT or the SARC moves and the archive keeps its size, which is what the game's resource
size table goes by (a larger file would need the table grown, as the prompts' font does).

Every language whose string was reworded gets DIR/<the archive's name in lower case> (host/texts.c looks it up by the RomFS
path's lower-case key); the others keep the game's own. The output is a zstd frame made without the dictionary, which the
game's decoder takes (as the prompts' files: host/prompts.c).

--show prints each language's string as the build would leave it, from your own files, to check a wording: it is game text,
so it stays on your PC (CONTRIBUTING.md)."""
import argparse
import glob
import hashlib
import os
import struct
import sys

# [(msbt, label, {a wording's fingerprint: (start, end, replacement)})]: the string's bytes [start, end) become the replacement
STRINGS = [
    # the "Ocarina Audio Input" hint: the console's built-in microphone -> your microphone (the languages that have that wording)
    ("LayoutMsg/ActionGuide_00.msbt", "Pa_ActionGuide_01-T_Description_00", {
        "b816b30394a86b8a": (4, 38, "your microphone"),       # USen, EUen
        "9925b429328b1fd2": (21, 69, "votre microphone\n"),   # USfr, EUfr
        "e4bd22fcea2f8529": (16, 60, "un micrófono"),         # USes, EUes
        "0dd1fb25d15aec84": (4, 46, "o seu microfone"),       # USpt
        "3179003a18de9124": (9, 64, "dein Mikrofon"),         # EUde
        "7fa2434137fc436c": (11, 54, "il tuo microfono"),     # EUit
        "7f5339bb84e3bb77": (8, 56, "je microfoon"),          # EUnl
        "21bce07f220b2409": (8, 57, "mikrofonowi"),           # EUpl
        "54935b14b603297c": (0, 55, "Микрофон"),              # EUru
        "ed6bdf6d1550bdad": (0, 50, ""),                      # JPja: "the console's" goes, the microphone stays
        "01467ba53d125ec9": (0, 28, ""),                      # KRko: the same
        "cd07456de7b137ad": (6, 32, ""),                      # CNzh: the same
        "c52f433f130e10eb": (6, 32, ""),                      # TWzh: the same
    }),
]


def fingerprint(text):
    """A wording's name in STRINGS: of the string's whole room, its terminator too"""
    return hashlib.sha1(bytes(text)).hexdigest()[:16]


def sarc_entries(data):
    """A SARC's files: [(name, start, end)], the offsets into data"""
    if data[:4] != b"SARC":
        raise ValueError("not a SARC")
    e = "<" if data[6:8] == b"\xff\xfe" else ">"
    header = struct.unpack_from(e + "H", data, 4)[0]
    base = struct.unpack_from(e + "I", data, 12)[0]
    if data[header:header + 4] != b"SFAT":
        raise ValueError("a SARC without its file table")
    count = struct.unpack_from(e + "H", data, header + 6)[0]
    names = header + 12 + 16 * count + 8   # (after SFNT's header)
    out = []
    for i in range(count):
        _, attr, start, end = struct.unpack_from(e + "IIII", data, header + 12 + 16 * i)
        name = None
        if attr & 0x01000000:
            at = names + 4 * (attr & 0xFFFF)
            name = bytes(data[at:data.index(b"\0", at)]).decode("utf-8")
        out.append((name, base + start, base + end))
    return out


def msbt_strings(m):
    """An MSBT's strings by label: {label: (start, end)}, each string's room in m (its bytes, tags and terminator, up to the
    next string's start). None when it is not a UTF-8 MSBT with labels and texts"""
    if m[:8] != b"MsgStdBn" or m[8:10] != b"\xff\xfe" or m[12] != 0:   # (little-endian, UTF-8)
        return None
    at, sections = 0x20, {}
    while at + 16 <= len(m):
        size = struct.unpack_from("<I", m, at + 4)[0]
        sections[bytes(m[at:at + 4])] = (at + 16, size)
        at = (at + 16 + size + 15) & ~15
    if b"LBL1" not in sections or b"TXT2" not in sections:
        return None
    lbl, _ = sections[b"LBL1"]
    txt, txt_size = sections[b"TXT2"]
    count = struct.unpack_from("<I", m, txt)[0]
    starts = list(struct.unpack_from("<%dI" % count, m, txt + 4)) + [txt_size]
    out = {}
    for slot in range(struct.unpack_from("<I", m, lbl)[0]):
        n, at = struct.unpack_from("<II", m, lbl + 4 + 8 * slot)
        at += lbl
        for _ in range(n):
            length = m[at]
            index = struct.unpack_from("<I", m, at + 1 + length)[0]
            if index < count:
                out[bytes(m[at + 1:at + 1 + length]).decode("utf-8")] = (txt + starts[index], txt + starts[index + 1])
            at += 5 + length
    return out


def reword(data, strings=None):
    """data (a text archive, decompressed) with the strings' edits made: (the new bytes, the same length; the labels reworded;
    the labels left as they are, each with why)"""
    out, done, left = bytearray(data), [], []
    files = {name: (start, end) for name, start, end in sarc_entries(data)}
    for msbt, label, edits in STRINGS if strings is None else strings:
        if msbt not in files:
            left.append((label, "no %s" % msbt))
            continue
        base, end = files[msbt]
        rooms = msbt_strings(out[base:end])
        if rooms is None or label not in rooms:
            left.append((label, "no such string"))
            continue
        a, b = (base + at for at in rooms[label])
        text = bytes(out[a:b])
        if fingerprint(text) not in edits:
            left.append((label, "its text is not one this was written for"))
            continue
        start, stop, new = edits[fingerprint(text)]
        new = new.encode("utf-8")
        if not 0 <= start <= stop < len(text) or len(new) > stop - start:
            raise ValueError("%s: the replacement does not fit what it replaces" % label)
        text = text[:start] + new + text[stop:]
        out[a:b] = text + b"\0" * (b - a - len(text))   # (in its own room: nothing after it moves)
        done.append(label)
    return bytes(out), done, left


def zs_dictionary(romfs):
    """The game's dictionary for .zs files (Pack/ZsDic.pack.zs: a SARC of dictionaries, itself a frame made without one)"""
    import zstandard
    pack = zstandard.ZstdDecompressor().decompress(open(os.path.join(romfs, "Pack", "ZsDic.pack.zs"), "rb").read(),
                                                   max_output_size=1 << 28)
    for name, start, end in sarc_entries(pack):
        if name == "zs.zsdic":
            return zstandard.ZstdCompressionDict(pack[start:end])
    raise ValueError("no zs.zsdic in Pack/ZsDic.pack.zs")


def archives(romfs):
    """The game's text archives, decompressed: (name, bytes) for each language"""
    import zstandard
    dictionary = None
    for path in sorted(glob.glob(os.path.join(romfs, "Mals", "*.sarc.zs"))):
        dictionary = dictionary or zs_dictionary(romfs)
        yield os.path.basename(path), zstandard.ZstdDecompressor(dict_data=dictionary).decompress(
            open(path, "rb").read(), max_output_size=1 << 30)


def make(romfs, out):
    """out/<archive, lower case> for each language with a string reworded; the ones made. Files of an earlier build that this
    one does not make are deleted"""
    import zstandard
    made = []
    for name, data in archives(romfs):
        new, done, left = reword(data)
        for label, why in left:
            print("texts: %s: %s left as it is (%s)" % (name, label, why), flush=True)
        if not done:
            continue
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, name.lower()), "wb") as f:   # (the content size in the frame: the game sizes its buffer by it)
            f.write(zstandard.ZstdCompressor(level=3, write_content_size=True).compress(new))
        made.append(name.lower())
    if os.path.isdir(out):
        for old in os.listdir(out):
            if old not in made:
                os.remove(os.path.join(out, old))
        if not made:
            os.rmdir(out)
    return made


def show(romfs):
    """Each language's strings as the build would leave them (control tags as <>), for checking a wording"""
    for name, data in archives(romfs):
        new, done, _ = reword(data)
        files = {n: (start, end) for n, start, end in sarc_entries(new)}
        for msbt, label, _ in STRINGS:
            if label not in done:
                print("%s: %s: left as it is" % (name, label))
                continue
            base, end = files[msbt]
            a, b = msbt_strings(new[base:end])[label]
            text, shown, at = new[base + a:base + b], "", 0
            while at < len(text) and text[at]:
                if text[at] == 0x0E:   # (a tag: its group, type and size, then its bytes)
                    at += 7 + struct.unpack_from("<H", text, at + 5)[0]
                    shown += "<>"
                else:
                    stop = at
                    while stop < len(text) and text[stop] not in (0, 0x0E):
                        stop += 1
                    shown += text[at:stop].decode("utf-8", "replace")
                    at = stop
            print("%s: %s" % (name, shown.replace("\n", " / ")))


def main():
    p = argparse.ArgumentParser(description="The game's texts with the console's wording made the PC's")
    p.add_argument("--romfs", required=True)
    p.add_argument("--out")
    p.add_argument("--show", action="store_true", help="print the reworded strings from your own files instead (game text: keep it to yourself)")
    a = p.parse_args()
    if a.show:
        show(a.romfs)
        return 0
    if not a.out:
        p.error("--out or --show")
    made = make(a.romfs, a.out)
    print("texts: %d languages reworded for a PC" % len(made) if made else "texts: none reworded: the game shows its own", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
