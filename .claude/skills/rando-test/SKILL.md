---
name: rando-test
description: Build, install and test the Mako randomizer fork on this PC, and read its files and saves - rebuild the game after a change to host/ or nx2/oot_patches.py, rewrite the seed or the cosmetics after a change to tools/rando, run the game without a window on a copy of a save (teleport, buttons, pictures), look at the pictures as a grid, read a crash's backtrace in the game's code, and look up a save's flags, a character's event flow, the logic that makes things appear, who says a line, and where an actor is placed. Use when a randomizer or cosmetics change needs trying in the game, when the user reports a crash or a bug seen in play, or when asked to test something without them playing.
---

# Testing the randomizer on this PC

The owner plays and reports; the fixes are tried here first, without a window, on copies of their saves. The scripts
are in `scripts/` beside this file (run them from the repository root with Git Bash and `py`, which has capstone,
zstandard and Pillow). Their files go to `$WORK` (default `$TEMP/rando-test`); the game folder is `$GAME` (default
`/f/Games/OOT Remake Rando`).

**Rules, before anything:**
- **Nothing made from the game leaves the PC** (AGENTS.md): pictures, logs, `image.bin`, the translated C, seeds and
  saves stay here. Describe what a picture shows; never upload one.
- **Never while the owner plays.** The scripts refuse when `hookshot.exe` or the launcher runs; also don't install a
  seed, cosmetics or a build then. Ask them to close the game, and wait.
- **Their saves are not touched.** Runs use copies (`SAVE=`); a test mod put in `$GAME/mods` is removed right after.
- Commit locally only; push to their fork (`origin`) only when asked; never to `forge`.

## 1. Put the change in the game

| Changed | Do |
|---|---|
| `host/*.c`, `nx2/oot_patches.py` (a lift patch), `gpu/` | `bash .claude/skills/rando-test/scripts/rebuild.sh` (~2 min; it keeps the translated C) |
| `tools/rando/rando_seed.py` | `cp tools/rando/rando_seed.py "$GAME/rando/"`, then in `$GAME`: `python -I rando/rando_seed.py romfs` (rewrites the seed the launcher last placed; its `FIXES_VERSION`/`PLACEMENT` decide what changes) |
| `tools/rando/rando_cosmetics.py` | `cp` it to `$GAME/rando/` too, then in `$GAME`: `py -I rando/rando_cosmetics.py romfs` (the owner's `hookshot_cosmetics.ini`), or with `--young-link "young zelda"` and the like for a test; run it again without them after, so their own choices are back |
| `launcher/Launcher.cs` | `powershell launcher/build.ps1`, then copy `launcher/Mako Launcher.exe` to `$GAME` |

The build's "button prompts of other controllers were not made" (an AssertionError) is old and harmless.

**A change to the seed tool's placement: write whole seeds into a scratch game folder** before installing. `--dry-run`
returns before the files and `checks.txt` are written, so a crash there is missed (seen 2026-11-18). The owner's seed is
not touched:

```bash
G="/f/Games/OOT Remake Rando"; T=/f/Games/perf-ab/seedtest; mkdir -p $T && cp "$G/hookshot_options.ini" $T/
(cd $T && py -I /c/Users/beerc/Hookshot/tools/rando/rando_seed.py "$(cygpath -w "$G/romfs")" --game "$(cygpath -w $T)" --seed 4242)
# read $T/mods/rando-seed/checks.txt and spoiler.txt, then rm -rf $T
```

## 2. Run it without a window

```bash
SAVE="All Items unlocked" bash .claude/skills/rando-test/scripts/run_headless.sh mytest \
  "5:!cheat 999" "20:GO -42.0 97.9 22.0 KakarikoVillage A" "30:0:Y" "3:0:R/2000" "5:0:LUP/10"
```

- Steps are `"<seconds>:<what>"`, run after ~100 s of loading. `GO x y z Folder ages` teleports (the map must be Link's
  age: switch with `!cheat 999` first); `0:A`, `0:B`, `0:Y`, `0:R/2000`, `0:LUP/1500`... press or hold (`host/control.c`
  has the names); `!cheat 1003` is the Market's fountain. Leave ~25-40 s after a teleport for the area to load.
- Checks' places: `$GAME/mods/rando-seed/checks.txt` (folder, ages, x y z per check).
- **Save copies** the owner made for tests are in `$GAME/user/save_copies/save_rando/` (`ls` it): "Early Save Test"
  (young Link, away from talk), "All Items unlocked" (young; switch age for adult), "Young Link in front of Potion Shop
  Owner, before bug errand", "Before Owl" (no Bomb Bag yet), and others. **Shops** (made 2026-11-16, each loads Link
  in front of the keeper with the A prompt showing, holding Deku Nuts, the Bow and Deku Sticks where the name says):
  "Child Kokiri Shop at day ...", "Adult Kokiri Shop ...", "Child Goron Shop ...", "Adult Goron Shop ...", "Child Zora
  shop ...", "Child Bazaar at Day With Deku Nuts and Bow", "Child Potion Shop at day ...", "Child Bombchu Shop at night
  ...", "Adult Kakariko Bazzaar Shop ..." (sic), "Adult Kakariko Potion Shop ..." (`ls` for the full names). **The
  Market from Hyrule Field:** "Child Link In hyrule field in front of market" (walk in to load the Market). **The royal
  tomb:** "Adult Sun Song Tombs" (adult, for the Sun's Song lesson, bug 61). **Great Fairies:** "Adult Death Mountain Great Fariy
  Fountain" (sic; adult, in front of the fountain: the reward needs Zelda's Lullaby played, by input or by asking for
  the fairy's event by name, as the boss teleports do). **The Deku Tree's end:** "Child Deku Tree Heart Container"
  (before Gohma's container) and "Child Deku Tree Blue warp" (at the blue warp: the story after Gohma). **Rainy Kakariko** (adult, the storm between the Nocturne scene and the Shadow Temple: made 2026-11-18): "Adult on Hyrule Field in front of Rainy Kakariko" (walk in), "Adult Rainy Kakariko Hyrule Field Entrance", "Adult Rainy Kakariko Graveyard entrance". A test that needs a place or a state no copy has: **ask the owner to make a save
  there** and a backup copy; they can save almost anywhere. Mind that the autosave overwrites their newest save.
- A character's talk can catch Link before a teleport (a shop keeper's greeting): start from a copy away from people.
- The exit line: 124 ran to its end; 139 crashed (the backtrace is printed).
- `SETFLAG="c1b29b0a=1"` sets flags from the start; `EVERY=20` takes pictures more often.

## 3. Look at it

```bash
py -I .claude/skills/rando-test/scripts/grid.py "$TEMP/rando-test/grid.png" --last 48 --step 4
py -I .claude/skills/rando-test/scripts/grid.py "$TEMP/rando-test/zoom.png" --last 40 --step 10 --crop 380,230,580,430 --zoom 0.9
```

Then Read the PNG. Pictures are 960x540; crop to a character or a shelf to see detail. Say what the pictures show in
the report; the owner confirms in play (`share/verify-list.md` holds what waits for them).

## 4. A crash

The log's `CRASH: guest backtrace: lr 0x...` gives the game's code addresses; the owner's own crashes are in
`$GAME/logs/hookshot_log*.txt` (newest first).

```bash
py -I .claude/skills/rando-test/scripts/disasm.py 0x8022e9bc            # the code around the first lr
py -I .claude/skills/rando-test/scripts/disasm.py --string 0x83d868d1   # a name the code looks up
py -I .claude/skills/rando-test/scripts/disasm.py --c 0x801d3620        # that function's translated C (after rebuild.sh)
```

```bash
bash .claude/skills/rando-test/scripts/decompile.sh 0x804d8240 0x801d3620   # Ghidra's C of those functions (~5 s)
```

Ghidra 12.2 and Java 25 are set up in `C:\Users\beerc\tools` (outside the repo; `scripts/ghidra/` has the project's
import and decompile scripts to set it up again). The project has the code loaded without the whole-program analysis
(that ran out of memory and failed): each call makes and decompiles only the functions asked for.

Fixes to the game's code are lift patches in `nx2/oot_patches.py`: find the function by its head line
(`void f_<addr>(Ctx *__restrict A64_NOESC c) {`) or a branch label (`L_<addr>:;`) in the translated C, insert a guard
or wrap the function (kept as `<name>_body`, as `patch_drop_name` and `patch_bone_fallback` do), and count it in
`apply`'s `done`. Read the real C first: guessing its text fails silently. Then rebuild and run again.

## 5. Reading the game's files and saves

Readers in `scripts/` (run from that folder or with its path; `--help` on each). All read only; add `--modded` to read
the mods' copy (the seed's or the cosmetics' rewrite) in place of the game's.

| Question | Command |
|---|---|
| Is a flag set in a save? What changed between two saves? | `py -I savedata.py get "<save copy>" <FlagName>...`, `py -I savedata.py diff "<copy A>" "<copy B>"` (`live` = the newest live save; `hash` gives HOS_OOT_SETFLAG's hex) |
| What does a character's or scene's flow do? Which flows set or ask a flag? | `py -I flow.py <Flow> --entries`, `--entry <Entry>` (its steps in order), `--find <Flag or text>` |
| What makes a thing appear, go or open? | `py -I logic.py --find <Flag>`, then `py -I logic.py <LogicName>`; `--where <LogicName>` gives the map that uses it |
| Who says a line, and its label? | `py -I text.py "words of the line"`, `--label <File>:<Label>`, `--file ActorMsg/PouchContent --grep Kokiri` |
| Where is a character or object, and when is it there? | `py -I actors.py <Name> --map <Folder>`, `--near x y z --map <Folder> --radius 5` |

Found so far, worth knowing: a true/false question's case 0 is its TRUE answer in `flow.py`'s dumps; a character's
behaviour can hang on its schedule (`Component/AIScheduleParam/<actor>`: `ConditionFlag`) as well as its flow; things in
a map often come and go by a flag (`actors.py` shows "when <flag>"). The save's layout, the name hash (murmur3) and the
name list (built once into `$WORK/flag_names.txt`) are in `savedata.py`'s notes.

## 6. Before committing

- `py -I -B tests/run_all.py` (with `PATH=$PWD/llvm-mingw/bin:$PATH`): 112 checks fail on this branch already; compare
  the failing list with a run without the change rather than the count alone. Checks read the source by its text: update
  the check with the change.
- Commit with `git -c user.name=Claude -c user.email=noreply@anthropic.com commit` and the attribution line; note the
  fix in `share/bugs.md` and what the owner should see in play in `share/verify-list.md`.
