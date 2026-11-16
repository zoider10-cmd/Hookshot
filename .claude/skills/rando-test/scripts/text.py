"""The game's words: find a line by its text or its label, and which file (character) says it.

    py -I text.py "use that empty bottle"            the lines that have those words (any case), with file and label
    py -I text.py --label Npc_Hylia_020_Shop_Child:Talk_106     one line by file:label (a flow's MessageId)
    py -I text.py --file ActorMsg/PouchContent --grep Kokiri    lines of one file whose label or text has a word
    options: --lang USen (the archive Mals/<lang>.Product.*.sarc.zs; default USen), --modded (the seed's rewrite)

The texts are the language archive's MSBT files (UTF-8 here); tags in a line (colours, names put in, pauses) are shown
as <tag> and line breaks as " / ". A flow's talk names its message as EventFlowMsg/<file>:<label> (flow.py shows them).
Reading only; tools/rando/rando_seed.py msbt_text/msbt_set are what the seed edits texts with.
"""
import argparse
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # (-I leaves this folder out)
import romfs   # noqa: E402


def archive(lang, modded):
    names = [n for n in os.listdir(os.path.join(romfs.ROMFS, "Mals")) if n.startswith(lang + ".") and n.endswith(".sarc.zs")]
    if not names:
        sys.exit("no archive for %s in Mals" % lang)
    return romfs.R.sarc_read(romfs.read("Mals/" + names[0], modded))


def lines(data):
    """{label: raw text bytes} of an MSBT"""
    sec, p = {}, 0x20
    while p + 16 <= len(data):
        name, size = data[p:p + 4], struct.unpack_from("<I", data, p + 4)[0]
        sec[name] = data[p + 16:p + 16 + size]
        p = (p + 16 + size + 15) & ~15
    lbl, txt = sec.get(b"LBL1"), sec.get(b"TXT2")
    if lbl is None or txt is None:
        return {}
    labels = {}
    for g in range(struct.unpack_from("<I", lbl, 0)[0]):
        cnt, at = struct.unpack_from("<II", lbl, 4 + 8 * g)
        for _ in range(cnt):
            ln = lbl[at]
            labels[struct.unpack_from("<I", lbl, at + 1 + ln)[0]] = lbl[at + 1:at + 1 + ln].decode("utf-8", "replace")
            at += 1 + ln + 4
    n = struct.unpack_from("<I", txt, 0)[0]
    offs = [struct.unpack_from("<I", txt, 4 + 4 * i)[0] for i in range(n)] + [len(txt)]
    return {labels.get(i, str(i)): txt[offs[i]:offs[i + 1]].rstrip(b"\0") for i in range(n)}


def plain(raw):
    out, i = [], 0
    while i < len(raw):
        if raw[i] == 0x0E and i + 7 <= len(raw):   # (a tag: group, type, its parameters' size, the parameters)
            size = struct.unpack_from("<H", raw, i + 5)[0]
            out.append("<tag>")
            i += 7 + size
            continue
        if raw[i] == 0x0F and i + 5 <= len(raw):   # (a tag's end)
            i += 5
            continue
        out.append(chr(raw[i]) if raw[i] >= 0x20 or raw[i] == 0x0A else "")
        i += 1
    text = "".join(out).encode("latin-1", "replace").decode("utf-8", "replace")
    return re.sub(r"(<tag>)+", "<tag>", text).replace("\n", " / ")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("words", nargs="?")
    p.add_argument("--label")
    p.add_argument("--file")
    p.add_argument("--grep")
    p.add_argument("--lang", default="USen")
    p.add_argument("--modded", action="store_true")
    a = p.parse_args()
    files = archive(a.lang, a.modded)
    if a.label:
        name, _, label = a.label.partition(":")
        name = name if name.endswith(".msbt") else name + ".msbt"
        rel = next((k for k in files if k.endswith("/" + name) or k == name), None)
        if rel is None:
            sys.exit("no text file %s" % name)
        raw = lines(files[rel]).get(label)
        print("%s:%s | %s" % (rel, label, plain(raw) if raw is not None else "(no such line)"))
        return
    if a.file:
        name = a.file if a.file.endswith(".msbt") else a.file + ".msbt"
        if name not in files:
            sys.exit("no text file %s" % name)
        for label, raw in lines(files[name]).items():
            t = plain(raw)
            if not a.grep or a.grep.lower() in label.lower() or a.grep.lower() in t.lower():
                print("%-40s | %s" % (label, t[:160]))
        return
    if not a.words:
        p.error("words to find, --label or --file")
    want = a.words.lower()
    for rel in sorted(files):
        if not rel.endswith(".msbt"):
            continue
        for label, raw in lines(files[rel]).items():
            t = plain(raw)
            if want in re.sub(r"\s+", " ", t.replace("<tag>", "")).lower():   # (tags between the words left out)
                print("%s:%s | %s" % (rel[:-5], label, t[:180]))


if __name__ == "__main__":
    main()
