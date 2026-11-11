"""Fast forward (hold ` or both stick clicks: the game runs 4x): the menu's row, the option's number, the host's use
of it and the launcher's selector agree.

python -I -B tests/test_fast_forward.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
failed = []


def check(ok, what):
    if not ok:
        failed.append(what)


def main():
    read = lambda *p: ROOT.joinpath(*p).read_text(encoding="utf-8")
    menu, option, vi, launcher = (read("gpu", "vk", "vk_menu.cpp"), read("gpu", "vk", "vk_replay.cpp"),
                                  read("host", "nn_vi.c"), read("launcher", "Launcher.cs"))
    check('"Fast forward", &opts.fast_forward, 0, 2, 1' in menu, "the Insert menu has no row for it")
    # (a number of its own since the merge of Mako 3.3, whose gyro is option 18)
    api = read("gpu", "vk", "vk_api.h")
    check("enum { HOS_OPT_FAST_FORWARD = 48 };" in api and "HOS_OPT_GYRO = 18" in api, "the fast forward's option number is not its own")
    check("if (id == HOS_OPT_FAST_FORWARD) return opts.fast_forward;" in option, "the host cannot see the menu's row (HOS_OPT_FAST_FORWARD)")
    check("rx_option(HOS_OPT_FAST_FORWARD, 0)" in vi, "the host does not read the option")
    held = vi.index("if (fast_forward_held())")
    check(held < vi.index("if (!rx_option(0, 1) && fps_max() <= 60)"), "Game speed: Per frame returns before the fast forward is looked at")
    check("*slot = 15;" in vi[held:held + 300], "the held key does not ask for the game's longest step")
    # (a frame rate cap above 60 steps the game by the frames' own time: not while this is held)
    check("hos_frame_seconds_bits = 0;" in vi[held:vi.index("return;", held)], "with a frame rate cap above 60 the frames' own step would win over the long one")
    check('"fast_forward", "Fast forward"' in launcher and '{ "fast_forward", 0 }' in launcher, "the launcher has no selector for it")
    for f in failed:
        print("FAIL:", f)
    print("fast forward: %s" % ("FAILED" if failed else "ok"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
