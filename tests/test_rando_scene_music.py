"""Skip cutscenes passes over a quieted scene's own music (tools/rando/rando_seed.py SCENE_MUSIC): no game data.

The owner's run 2026-11-20: after the owl's first scene in Hyrule Field (Dm_HrlField_0010, quieted by Skip cutscenes) its
music (BGM_Dm_HrlField_0005, started by EventTriggerStartBgmSimple with CommandLife 2) played on across areas, the
title and a new game: in the game the owl's talk let it go, and the quieted scene ended at once. Seen without a window
(HOS_OOT_TEST_EVENT, HOS_FS_LOG_OPEN=Stream/BGM) on a copy of the owner's save: before, the owl's music stream opened;
after, it did not, and Hyrule Field's own came. Checked here:
- SCENE_MUSIC is the start of an event's music (CommandLife 2), not one that lasts (0: an area's music changed);
- scene_steps reads a music start's CommandLife, and quiet_scene passes over the steps SCENE_MUSIC names;
- the seeds are written again with it (FIXES_VERSION 52).

    python -I -B tests/test_rando_scene_music.py
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
    check(getattr(seed, "SCENE_MUSIC", None) == ("EventTriggerStartBgmSimple", 2),
          "a quieted scene's own music (EventTriggerStartBgmSimple, CommandLife 2) is not passed over")
    check(seed.FIXES_VERSION >= 52, "the seeds are not written again without the scenes' music (fixes 52)")
    src = path.read_text(encoding="utf-8")
    steps = src[src.index("def scene_steps(data):"):src.index("def quiet_scene(")]
    check('elif s["what"] == "EventTriggerStartBgmSimple":' in steps and 's["life"] = param(u64(e + 0x10), "CommandLife")' in steps,
          "scene_steps does not read a music start's CommandLife")
    quiet = src[src.index("def quiet_scene(data, entries=None, silent=False):"):]
    check('(s["what"], s.get("life")) == SCENE_MUSIC' in quiet[:quiet.index("passed, answer = set(")],
          "quiet_scene does not pass over a scene's own music")
    print("PASS: Skip cutscenes passes over a scene's own music")


if __name__ == "__main__":
    main()
