"""A character's shadow map reserves the storage of the next step of sides up, so the targets made after it keep their place.

OoT sizes each near character's square depth map anew every frame (384 from far, up to 1920 near, a few pixels different each
frame) and makes a frame's render targets one after another in a first-fit heap, asking the host the storage size and
alignment of each: a map a few pixels larger moved every target made after it to a new address (host/shadow_slot.h). The host
now answers such a map with the storage of the next multiple of 384 up. This compiles shadow_slot.h with a small C fixture and
checks which textures get a slot and which side, then reads host/nvn_native.c: both the size and the alignment answer use the
slot's layout where it is larger, HOS_SHADOW_BUCKET sets the step, 0 turns it off, and the texture's own description is not
changed.

python -I -B tests/test_shadow_slot.py [--cc clang]
"""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cc", "clang"]

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r'''#include <stdio.h>
#include "shadow_slot.h"
static int fails;
#define CHECK(name, cond) do { if (!(cond)) { printf("FAIL: %s (line %d)\n", name, __LINE__); fails++; } } while (0)
#define SIDE(w) hos_shadow_slot_side(1, 0x34, 1, 1, (w), (w), HOS_SHADOW_SLOT_STEP)
int main(void) {
    CHECK("the step is 384, the format NVN 0x34, the cap 1920", HOS_SHADOW_SLOT_STEP == 384 && HOS_SHADOW_SLOT_FORMAT == 0x34 &&
                                                                HOS_SHADOW_SLOT_MAX == 1920);
    /* (the sides the game was seen to ask for in Castle Town's market, a frame apart) */
    CHECK("397..698 all reserve 768", SIDE(397) == 768 && SIDE(439) == 768 && SIDE(479) == 768 && SIDE(698) == 768 && SIDE(768) == 768);
    CHECK("769..1152 reserve 1152", SIDE(769) == 1152 && SIDE(1118) == 1152 && SIDE(1152) == 1152);
    CHECK("1153..1536 reserve 1536", SIDE(1156) == 1536 && SIDE(1277) == 1536 && SIDE(1536) == 1536);
    CHECK("1537..1920 reserve 1920", SIDE(1537) == 1920 && SIDE(1920) == 1920);
    /* (not a ramped map: its own storage) */
    CHECK("the common 384 x 384 map keeps its own", SIDE(384) == 0 && SIDE(256) == 0 && SIDE(1) == 0);
    CHECK("past the game's cap: its own (the 2400 and 4096 static maps)", SIDE(1921) == 0 && SIDE(2400) == 0 && SIDE(4096) == 0);
    CHECK("not square: its own (the frame's 1280 x 720 depth)", hos_shadow_slot_side(1, 0x34, 1, 1, 1280, 720, 384) == 0);
    CHECK("another format: its own", hos_shadow_slot_side(1, 0x32, 1, 1, 500, 500, 384) == 0 &&
                                     hos_shadow_slot_side(1, 0x25, 1, 1, 500, 500, 384) == 0);
    CHECK("more than one level: its own", hos_shadow_slot_side(1, 0x34, 2, 1, 500, 500, 384) == 0);
    CHECK("three-dimensional or not 2D: its own", hos_shadow_slot_side(1, 0x34, 1, 4, 500, 500, 384) == 0 &&
                                                  hos_shadow_slot_side(0, 0x34, 1, 1, 500, 500, 384) == 0);
    /* (the switch) */
    CHECK("step 0: off", hos_shadow_slot_side(1, 0x34, 1, 1, 500, 500, 0) == 0);
    CHECK("another step: its multiples, never past the cap", hos_shadow_slot_side(1, 0x34, 1, 1, 500, 500, 128) == 512 &&
                                                              hos_shadow_slot_side(1, 0x34, 1, 1, 500, 500, 1024) == 1024 &&
                                                              hos_shadow_slot_side(1, 0x34, 1, 1, 1500, 1500, 1024) == 1920);
    /* (a side never reserves less than its own) */
    for (unsigned w = 385; w <= 1920; w++) CHECK("the slot is at least the map", SIDE(w) >= w && SIDE(w) - w < 384);
    if (!fails) puts("PASS: a ramped shadow map reserves the next multiple of 384; every other texture its own storage");
    return fails ? 1 : 0;
}
'''


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def wiring():
    src = (ROOT / "host" / "nvn_native.c").read_text(encoding="utf-8")
    fails = []

    def need(cond, what):
        if not cond:
            fails.append(what)

    need('#include "shadow_slot.h"' in src, "nvn_native.c includes shadow_slot.h")
    slot = block(src, "static int shadow_slot_layout(const nvn_texdesc *d, nvn_texlayout *out)")
    need('getenv("HOS_SHADOW_BUCKET")' in slot and "HOS_SHADOW_SLOT_STEP" in slot, "HOS_SHADOW_BUCKET sets the step, 384 without it")
    need("hos_shadow_slot_side(d->target == NVN_TEXTURE_TARGET_2D, d->format, d->levels, d->depth, d->width," in slot,
         "the slot's side comes from shadow_slot.h")
    need("nvn_texdesc slot = *d;" in slot and "slot.width = slot.height = side;" in slot and "nvn_tex_layout(&slot, out);" in slot,
         "the slot's layout is a copy's: the texture's own description is not changed")
    size = block(src, "NV(nvnTextureBuilderGetStorageSize)")
    need("shadow_slot_layout(&CTB(P(0))->d, &slot) && slot.size > L.size) L.size = slot.size;" in size,
         "the storage size answers the slot's where it is larger")
    align = block(src, "NV(nvnTextureBuilderGetStorageAlignment)")
    need("shadow_slot_layout(&CTB(P(0))->d, &slot) && slot.align > L.align) L.align = slot.align;" in align,
         "the alignment answers the slot's where it is larger")
    own = block(src, "NV(nvnTextureGetStorageSize)")
    need("shadow_slot" not in own, "a made texture's own storage size is its own")
    return fails


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="clang", help="C compiler (clang or gcc)")
    a = p.parse_args()
    fails = wiring()
    for f in fails:
        print("FAIL: " + f)
    if fails:
        raise SystemExit("test_shadow_slot: failed")
    print("PASS: the storage size and alignment answers use the shadow map's slot")
    cc = shutil.which(a.cc)
    if not cc:
        raise SystemExit("test_shadow_slot: no C compiler %r (pass --cc)" % a.cc)
    with tempfile.TemporaryDirectory(prefix="shadow-slot-") as temp:
        d = Path(temp)
        src, exe = d / "fixture.c", d / "fixture.exe"
        src.write_text(FIXTURE, encoding="utf-8")
        subprocess.run([cc, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "host"), str(src), "-o", str(exe)],
                       check=True)
        result = subprocess.run([str(exe)], capture_output=True, text=True)
        print(result.stdout, end="")
        if result.returncode:
            raise SystemExit("test_shadow_slot: failed")


if __name__ == "__main__":
    main()
