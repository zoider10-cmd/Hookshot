#!/bin/bash
# run_headless.sh <label> <step>...: the game without a window, on a copy of a save, then each step in turn.
#
# A step is "<seconds to wait first>:<what>". What is one of:
#   GO x y z Folder ages    the Tracker tab's Go there (ages: C, A or CA; the map must be the age Link is now)
#   0:A  0:B  0:Y  0:R/2000  0:LUP/1500  ...   a live input line (button or stick, /ms held: host/control.c)
#   !cheat 999              a debug cheat line (999: switch Link's age; 1003: the Market's fountain)
# The first step waits for the game to have loaded the save (about 100 s pass before it).
#
# Environment:
#   GAME   the game folder (default /f/Games/OOT Remake Rando)
#   SAVE   a save copy's name under <GAME>/user/save_copies/save_rando (default: the live saves, the newest loaded)
#   WORK   where the run's files go (default: $TEMP/rando-test); pictures in $WORK/shots
#   EVERY  a picture every this many frames (default 60)
#   SETFLAG  flags set at the start (HOS_OOT_SETFLAG: hash=value,...)
#
# Prints the log's lines about items given, Go there, crashes and the exit code (124: ran to the end; 139: a crash).
# The player's saves are never written: the run uses its own user folder. Nothing runs while the game or the launcher is open.
set -u
label="$1"; shift
GAME="${GAME:-/f/Games/OOT Remake Rando}"
WORK="${WORK:-${TEMP:-/tmp}/rando-test}"
WORK="$(cygpath -u "$WORK" 2>/dev/null || echo "$WORK")"
if tasklist 2>/dev/null | grep -qi "hookshot.exe\|Mako Launcher"; then echo "the game or the launcher is running: not started"; exit 1; fi
mkdir -p "$WORK/shots" "$WORK/user"
rm -rf "$WORK/user/save_rando"
if [ -n "${SAVE:-}" ]; then
  src="$GAME/user/save_copies/save_rando/$SAVE"
  [ -d "$src" ] || { echo "no save copy named \"$SAVE\""; ls "$GAME/user/save_copies/save_rando/"; exit 1; }
  cp -r "$src" "$WORK/user/save_rando"
else
  cp -r "$GAME/user/save_rando" "$WORK/user/save_rando"
fi
total=0; for s in "$@"; do total=$((total + ${s%%:*})); done
secs=$((100 + total + 12))
rm -f "$WORK"/shots/*.png; : > "$WORK/live.txt"
# (the Tracker's record of what is collected and the junk marks are the game folder's (rando/collected.txt, junk.txt),
#  not the save's: a run's game writes them. Kept here and put back after the run, so the player's are as they were
#  (2026-11-19: test runs on a test seed left the owner's record another seed's))
mkdir -p "$WORK/keep"; for f in collected.txt junk.txt; do rm -f "$WORK/keep/$f"; [ -f "$GAME/rando/$f" ] && cp "$GAME/rando/$f" "$WORK/keep/$f"; done
(
  sleep 100
  for s in "$@"; do
    sleep "${s%%:*}"; what="${s#*:}"
    case "$what" in
      GO\ *) echo "${what#GO }" > "$GAME/rando/goto_check.txt"; echo "!cheat 5" >> "$WORK/live.txt";;
      *) echo "$what" >> "$WORK/live.txt";;
    esac
  done
) &
cd "$GAME" && HOS_OOT_SETFLAG="${SETFLAG:-}" HOS_HEADLESS=1 HOS_AUDIO=0 HOOKSHOT_NO_UPDATE_CHECK=1 HOS_NO_SAVE_FOLDER=1 RX_VK_FRAMEGEN=0 \
  RX_VK_SHOTS="$(cygpath -w "$WORK/shots")" RX_VK_SHOT_EVERY=${EVERY:-60} RX_VK_SHOT_W=960 RX_VK_SHOT_H=540 \
  HOS_INPUT_LIVE="$(cygpath -w "$WORK/live.txt")" HOS_INPUT_SCRIPT_BACKGROUND=1 HOS_INPUT_SCRIPT="30:A,44:A,46:A,49:A,60:A" \
  timeout "$secs" ./hookshot.exe --user "$(cygpath -w "$WORK/user")" > "$WORK/stdout.txt" 2>&1
echo "exit $?" >> "$WORK/stdout.txt"
wait
for f in collected.txt junk.txt; do if [ -f "$WORK/keep/$f" ]; then cp "$WORK/keep/$f" "$GAME/rando/$f"; else rm -f "$GAME/rando/$f"; fi; done
cp "$WORK/stdout.txt" "$WORK/stdout_$label.txt"
echo "run $label: $(ls "$WORK/shots" | wc -l) pictures in $WORK/shots, the log in $WORK/stdout_$label.txt"
grep -n "pouch add\|go to a check\|tracker: .* got\|CRASH: exception\|CRASH: guest\|exit " "$WORK/stdout.txt" | sed 's/\[hos [A-Za-z0-9:]*\] //' | cut -c1-200 | tail -30
