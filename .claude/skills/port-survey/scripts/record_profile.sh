#!/bin/bash
# record_profile.sh <out.prof>: records the play profile the hot code is built with (work/hookshot_pieces.prof).
#
# Needs F:/Games/perf-ab/variants/pgogen/hookshot.exe, a profile-counting build of THIS checkout:
#   RX_PGO=gen HOOKSHOT_KEEP_BUILD_FILES=1 py -I nx2/make_game.py --update <game folder>   (then copy the exe out and put
#   the game folder's own build back). Runs it headless in the test copy (F:/Games/perf-ab/game) on a copy of the
#   owner's "All Items unlocked" save: the loading is left out (the counters are cleared after it), then a tour of
#   areas as a child and as an adult, walking and turning in each, then the counters are written (host/pgo_rt.c,
#   HOS_PGO). Several tours (TOURS=, default 2) are merged with llvm-profdata. Not while the game or launcher runs.
set -u
out=$1; P=/f/Games/perf-ab; G=$P/game; V=$P/variants; W=$P/runs/pgo; tours=${TOURS:-2}
SAVES="/f/Games/OOT Remake Rando/user/save_copies/save_rando/All Items unlocked"
if tasklist | grep -qi "hookshot.exe\|Mako Launcher\|Lost Woods Launcher"; then echo "the game or the launcher is running: not now"; exit 1; fi
[ -f "$V/pgogen/hookshot.exe" ] || { echo "no $V/pgogen/hookshot.exe"; exit 1; }
PROFDATA=/c/Users/beerc/Hookshot/llvm-mingw/bin/llvm-profdata.exe
cp "$V/pgogen/hookshot.exe" "$G/hookshot.exe"; [ -f "$V/pgogen/hookshot_vk.dll" ] && cp "$V/pgogen/hookshot_vk.dll" "$G/"
walk() { echo "8:0:LUP/6000"; echo "7:0:RRIGHT/2500"; echo "4:0:LUP/4000"; echo "5:0:LLEFT/3000"; echo "4:0:RLEFT/2500"; echo "4:0:LUP/3000"; }
tour() {
  echo "0:!cheat 1003"; echo "30:0:A"; walk
  for spot in "-82.6 122.3 33.0 KokiriForest CA" "-151.9 162.0 265.3 HyruleField CA" "-41.7 79.7 11.4 KakarikoVillage CA" \
              "-29.8 120.3 45.6 DeathMountainTrail CA" "-47.4 113.7 -5.2 GoronCity CA" "28.8 100.4 -4.9 ZoraDomain C"; do
    echo "3:GO $spot"; echo "35:0:A"; walk
  done
  echo "3:!cheat 999"; echo "30:0:A"
  for spot in "-151.9 162.0 265.3 HyruleField CA" "-41.7 79.7 11.4 KakarikoVillage CA" "-9.5 90.4 35.0 GerudoValley CA" \
              "-47.4 113.7 -5.2 GoronCity CA"; do
    echo "3:GO $spot"; echo "35:0:A"; walk
  done
}
mkdir -p "$W"; rm -f "$W"/*.profraw
for t in $(seq 1 "$tours"); do
  R=$W/tour$t; rm -rf "$R"; mkdir -p "$R/user"; cp -r "$SAVES" "$R/user/save_rando"; : > "$R/live.txt"
  raw="$(cygpath -w "$W/tour$t.profraw")"
  mapfile -t steps < <(tour); total=0; for s in "${steps[@]}"; do total=$((total + ${s%%:*})); done
  (
    sleep 95; : > "$W/tour$t.profraw.reset"
    for s in "${steps[@]}"; do
      sleep "${s%%:*}"; what="${s#*:}"
      case "$what" in GO\ *) echo "${what#GO }" > "$G/rando/goto_check.txt"; echo "!cheat 5" >> "$R/live.txt";; *) echo "$what" >> "$R/live.txt";; esac
    done
    sleep 3; : > "$W/tour$t.profraw.dump"; sleep 4
  ) &
  ( cd "$G" && HOS_PGO="$raw" HOS_HEADLESS=1 HOS_AUDIO=0 HOOKSHOT_NO_UPDATE_CHECK=1 HOS_NO_SAVE_FOLDER=1 RX_VK_FRAMEGEN=0 \
      HOS_INPUT_LIVE="$(cygpath -w "$R/live.txt")" HOS_INPUT_SCRIPT_BACKGROUND=1 HOS_INPUT_SCRIPT="30:A,44:A,46:A,49:A,60:A" \
      timeout $((95 + total + 20)) ./hookshot.exe --user "$(cygpath -w "$R/user")" > "$R/stdout.txt" 2>&1; echo "exit $?" >> "$R/stdout.txt" )
  wait
  echo "tour $t: $(tail -1 "$R/stdout.txt"), $(grep -c "go to a check" "$R/stdout.txt") teleports, raw $(stat -c %s "$W/tour$t.profraw" 2>/dev/null || echo missing) bytes"
done
cp "$V/current/hookshot.exe" "$V/current/hookshot_vk.dll" "$G/" 2>/dev/null
"$PROFDATA" merge -o "$out" "$W"/tour*.profraw && "$PROFDATA" show "$out" | tail -4
