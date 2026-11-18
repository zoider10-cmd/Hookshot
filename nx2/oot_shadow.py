"""Raise the sun's shadow map size before the game sizes its cascades (OoT 1.1.1).

The sun's shadow object (vtable 0x84baa0a8) keeps a table of sizes by quality level, set once when the renderer is made:
1000/1400/1600, 1600/2000/2200 and 3072 for its three levels. The game runs at level 1 and takes that level's first
entry, so its cascades are 1600 texels a side, which is coarse at a PC's resolutions: thin casters near the camera (chains, ivy, fences) cast stair-stepped
shadows. Every frame the cascade function picks a size from that table, scales it, rounds it up to a multiple of 8 and
stores it as the cascades' width and height. The hook runs after that rounding and raises the size to the Shadow
resolution row's (host/oot_shadow.c), so the game's own level, its other branches and every later use of the size
stay the game's.
"""

MAIN = 0x80020000
BUILD_ID = "e0f3ccfaf50065ae4ea01eb5aeb13b1a45da3348"
SITE = MAIN + 0x4729f0
# The rounding to a multiple of 8, the size packed into the width and height pair, and its store at the object's +0xe0.
WORDS = (0x121d7117, 0xd343fee8, 0xaa1703e9, 0xb35d7109, 0xf9007269)
HOOK = ("{ extern void hos_oot_shadow(Ctx *c, uint64_t shadow); hos_oot_shadow(c, c->x[19]); }"
        "   /* (nx2/oot_shadow.py: the sun's shadow resolution) */")


def install(lifter, img, build_id):
    if build_id != BUILD_ID or any(img.word(SITE + 4 * i) != word for i, word in enumerate(WORDS)):
        print("shadow resolution: unsupported cascade code, left out")
        return 0
    lifter.after[SITE] = (lifter.after[SITE] + "\n" if SITE in lifter.after else "") + HOOK
    print("shadow resolution: sun cascades hooked")
    return 1
