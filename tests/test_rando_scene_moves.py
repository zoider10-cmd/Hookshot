"""Skip cutscenes keeps an animation that moves its character (bug 88, tools/rando/rando_seed.py SCENE_MOVES): no game data.

The owner's run 2026-11-19: King Zora given Ruto's Letter said his lines and took the letter, and stayed in the way of
Zora's Fountain until the map was loaded again. His scene (Dm_Zora_0010) moves him aside by his animation C10, an
EventPlayAS that Skip cutscenes passed over as one that only shows something. Seen without a window after the fix, on
a copy of the owner's save: he moves aside after "Leave it to me". Checked here:
- the king's C10 is in SCENE_MOVES, by (the actor, the animation's name);
- scene_steps reads each EventPlayAS's actor and animation, and quiet_scene's steps that only show leave those out.

    python -I -B tests/test_rando_scene_moves.py
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check(ok, why):
    if not ok:
        print("FAIL: %s" % why)
        sys.exit(1)


def main():
    path = ROOT / "tools" / "rando" / "rando_seed.py"
    spec = importlib.util.spec_from_file_location("rando_seed", path)
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    check(("Npc_Zora_KingZora_child", "C10") in seed.SCENE_MOVES, "King Zora's move aside (C10) is not kept")
    check("EventPlayAS" in seed.SCENE_SHOWS, "an animation is no longer passed over at all: SCENE_MOVES would not be needed")
    src = path.read_text(encoding="utf-8")
    steps = src[src.index("def scene_steps(data):"):src.index("def quiet_scene(")]
    check('elif s["what"] == "EventPlayAS":' in steps and 's["as"] = (text(u64(actor)), param(u64(e + 0x10), "ASName") or "")' in steps,
          "scene_steps does not read an animation's actor and name")
    quiet = src[src.index("def quiet_scene(data, entries=None, silent=False):"):]
    check('s.get("as") not in SCENE_MOVES' in quiet[:quiet.index("passed, answer = set(")],
          "quiet_scene passes over an animation that moves its character")
    print("PASS: Skip cutscenes keeps King Zora's move aside")


if __name__ == "__main__":
    main()
