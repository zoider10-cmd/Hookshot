#!/bin/bash
# bench.sh <name> <variant A> <variant B> [reps=5, stops at 3 when clear] [seconds=150]   (or: VARIANTS="A B C D" bench.sh <name> - - [reps] [secs])
# The Market A/B: the test copy of the game (F:/Games/perf-ab/game) runs headless with each variant's files in turn,
# interleaved A B A B..., from the copy's newest save, teleported to the Market's fountain by day and walking, frame
# rate uncapped, from one pinned options file (bench_options.ini), after a warm-up run of each side (WARMUP=0: none). STEPS="<s>:<what>;..." another route ("GO x y z Folder ages" teleports as the Tracker's Go there). A variant is a folder under F:/Games/perf-ab/variants/ holding hookshot.exe and/or hookshot_vk.dll
# (a missing file is the base's) and/or env.txt (switches for the run, one NAME=value a line). Frame times go to runs/<name>_<variant>_<rep>/frames.csv; gate.py reads them.
P=/f/Games/perf-ab; G=$P/game; V=$P/variants; name=$1; A=$2; B=$3; reps=${4:-5}; secs=${5:-150}
if tasklist | grep -qi "hookshot.exe\|Mako Launcher"; then echo "the game or the launcher is running: not now"; exit 1; fi
VS=${VARIANTS:-"$A $B"}
for v in $VS; do [ -d "$V/$v" ] || { echo "no variant $V/$v"; exit 1; }; done
[ -d "$V/base" ] || { echo "no $V/base (the installed build's hookshot.exe and hookshot_vk.dll)"; exit 1; }
# (CACHES=1: each variant keeps its own shader cache in variants/<v>/cache, moved into the game copy for its runs: for
# sides whose shader stamp or renderer API differ, which would otherwise drop and rebuild the one cache at every switch)
CUR=$P/cache_owner.txt
swap_cache() { [ "${CACHES:-0}" = 1 ] || return 0; local was; was=$(cat "$CUR" 2>/dev/null); [ "$was" = "$1" ] && return 0
  [ -n "$was" ] && [ -d "$G/cache" ] && mv "$G/cache" "$V/$was/cache"; [ -d "$V/$1/cache" ] && mv "$V/$1/cache" "$G/cache"; echo "$1" > "$CUR"; }
# (the default route: the Market's fountain by day, then running in circles round the square with the camera swinging,
# as a player does: the crowd and the buildings keep coming on screen. The measured window is the last 50 s)
ROUTE="72:!cheat 1003;10:0:LUP/2000"; for i in $(seq 1 14); do ROUTE="$ROUTE;2:0:LUP/1400;2:0:LRIGHT/700;1:0:RRIGHT/600"; done
put() { swap_cache "$1"; cp "$V/base/hookshot.exe" "$V/base/hookshot_vk.dll" "$G/"; for f in hookshot.exe hookshot_vk.dll; do [ -f "$V/$1/$f" ] && cp "$V/$1/$f" "$G/"; done; }
run() {  # run <label>
  local R=$P/runs/$1; rm -rf "$R"; mkdir -p "$R/shots" "$R/user"; cp -r "$G/user/save_rando" "$R/user/save_rando"
  : > "$R/live.txt"; ( IFS=";"; for s in ${STEPS:-$ROUTE}; do sleep "${s%%:*}"; w="${s#*:}"; case "$w" in GO\ *) echo "${w#GO }" > "$G/rando/goto_check.txt"; echo "!cheat 5" >> "$R/live.txt";; *) echo "$w" >> "$R/live.txt";; esac; done ) &
  ( cd "$G" && HOS_HEADLESS=1 HOS_AUDIO=0 HOOKSHOT_NO_UPDATE_CHECK=1 HOS_NO_SAVE_FOLDER=1 RX_VK_FRAMEGEN=0 HOS_FPS_MAX=1000 \
    RX_VK_FRAME_LOG="$(cygpath -w "$R/frames.csv")" RX_VK_SHOTS="$(cygpath -w "$R/shots")" RX_VK_SHOT_EVERY=${EVERY:-1200} \
    RX_VK_SHOT_W=960 RX_VK_SHOT_H=540 HOS_INPUT_LIVE="$(cygpath -w "$R/live.txt")" HOS_INPUT_SCRIPT_BACKGROUND=1 \
    HOS_INPUT_SCRIPT="30:A,44:A,46:A,49:A,60:A" env $EXTRA $VENV timeout "$secs" ./hookshot.exe --user "$(cygpath -w "$R/user")" \
    > "$R/stdout.txt" 2>&1; echo "exit $?" >> "$R/stdout.txt" ); wait
}
# (Mako's measure skill: one settings file for every run, and a warm-up run of each side first, not counted)
OPTS=$P/bench_options.ini; [ -f "$OPTS" ] || cp "$G/hookshot_options.ini" "$OPTS"; export HOS_OPTIONS_FILE="$(cygpath -w "$OPTS")"
# (WARMUP=1 after a build or a cache change: a cold cache's first run is slow)
if [ "${WARMUP:-0}" = 1 ]; then for v in $VS; do put "$v"; VENV=$(cat "$V/$v/env.txt" 2>/dev/null | tr '\n' ' '); run "${name}w_${v}"; echo "${name}w_${v} (warm-up): $(tail -1 $P/runs/${name}w_${v}/stdout.txt)"; done; fi
for rep in $(seq 1 "$reps"); do
  for v in $VS; do put "$v"; VENV=$(cat "$V/$v/env.txt" 2>/dev/null | tr '\n' ' '); run "${name}_${v}_$rep"; echo "${name}_${v}_$rep: $(tail -1 $P/runs/${name}_${v}_$rep/stdout.txt)"; done
  # (early stop: from the 3rd pair, a clear PASS or FAIL of two variants ends the A/B; NOISE runs on to `reps`)
  set -- $VS
  if [ "$rep" -ge "${EARLY:-3}" ] && [ $# -eq 2 ] && py -I "$(dirname "$0")/gate.py" "$name" "$1" "$2" 2>/dev/null | tail -1 | grep -qE "^(PASS|FAIL)$"; then echo "clear after $rep pairs"; break; fi
done
CACHES=0 put base   # (the game copy's files back to the base's; its cache stays where it is, cache_owner.txt says whose)
set -- $VS; first=$1; shift
for v in "$@"; do echo "== $first vs $v"; py -I "$(dirname "$0")/gate.py" "$name" "$first" "$v"; done
