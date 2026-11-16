"""The game's code read around an address, for a crash's backtrace (CRASH: guest backtrace: lr 0x...).

    py -I disasm.py <address> [--before 0x40] [--after 0x20] [--image <game>/image.bin]
    py -I disasm.py --string <address>          the C string at an address (a name a function looks up)
    py -I disasm.py --c <function address>      where the translated C of f_<address> is, and its first lines

The code image is <game folder>/image.bin, loaded at 0x80000000 (the game's own code: it stays on this PC, nothing of it
goes into the repository or out). The translated C is kept by rebuild.sh in %LOCALAPPDATA%/HookshotBuilder/sa/gen.
Needs capstone (py has it here).
"""
import argparse
import glob
import os
import sys

BASE = 0x80000000


def main():
    p = argparse.ArgumentParser()
    p.add_argument("address", nargs="?")
    p.add_argument("--before", default="0x40")
    p.add_argument("--after", default="0x20")
    p.add_argument("--string")
    p.add_argument("--c", dest="c_of")
    p.add_argument("--image", default=os.path.join(os.environ.get("GAME", r"F:\Games\OOT Remake Rando"), "image.bin"))
    a = p.parse_args()
    if a.c_of:
        name = "f_%x" % int(a.c_of, 0)
        gen = os.path.join(os.environ.get("LOCALAPPDATA", ""), "HookshotBuilder", "sa", "gen")
        for path in sorted(glob.glob(os.path.join(gen, "code_*.c"))):
            with open(path, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            for i, line in enumerate(lines):
                if line.startswith("void %s(Ctx *__restrict" % name):
                    print("%s:%d" % (path, i + 1))
                    sys.stdout.writelines(lines[i:i + 40])
                    return
        sys.exit("%s is not in %s (rebuild.sh keeps the C files)" % (name, gen))
    image = open(a.image, "rb").read()
    if a.string:
        at = int(a.string, 0) - BASE
        print(image[at:at + 120].split(b"\0")[0].decode("ascii", "replace"))
        return
    import capstone
    md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
    addr = int(a.address, 0)
    start = addr - int(a.before, 0)
    for ins in md.disasm(image[start - BASE:addr - BASE + int(a.after, 0)], start):
        print("%s%x  %s %s" % ("=>" if ins.address == addr else "  ", ins.address, ins.mnemonic, ins.op_str))


if __name__ == "__main__":
    main()
