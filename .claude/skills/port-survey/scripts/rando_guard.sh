#!/bin/bash
# rando_guard.sh <base commit> [label]: keeps the randomizer safe from a port.
# 1. Lists the files the port touched that the randomizer owns or leans on (stop and read each one: a port must not
#    change a lift patch, the randomizer's host code, the seed tool or the launcher's settings without a reason).
# 2. Runs every game-free check and compares the failing list with the one saved for <base commit> (the branch has old
#    failures; only new ones count). The randomizer's own checks (tests/test_rando_*) must all pass as before.
# Exit 1 on a new failure. The in-game check (a seed's item, a shop, the tracker) is run_headless.sh's: see SKILL.md.
cd /c/Users/beerc/Hookshot || exit 1
base=$1; label=${2:-port}; W=${TEMP:-/tmp}/port-survey; mkdir -p "$W"
export PATH=$PWD/llvm-mingw/bin:$PATH
echo "== files the randomizer owns or leans on, touched since $base:"
git diff --name-only "$base" HEAD | grep -E '^(nx2/oot_patches\.py|nx2/make_game\.py|nx2/lift|host/oot_|host/hos_oot|host/hos_main\.c|host/control\.c|host/prompts\.c|tools/rando/|launcher/|gpu/vk/vk_menu\.cpp|tests/test_rando_)' | sed 's/^/   /' || true
fails() {  # fails <commit> <out>: the failing checks' names at that commit (a worktree, so this checkout is not moved)
  local wt="$W/wt_$1"; [ -s "$2" ] && return
  rm -rf "$wt"; git worktree add -q --detach "$wt" "$1" || return 1
  ( cd "$wt" && py -I -B tests/run_all.py --jobs 12 > "$2.log" 2>&1 )
  grep -E '^(FAIL|TIMEOUT) +[0-9.]+s +' "$2.log" | awk '{print $3}' | sort -u > "$2"
  git worktree remove --force "$wt"
}
fails "$(git rev-parse --short "$base")" "$W/fails_$(git rev-parse --short "$base").txt"
py -I -B tests/run_all.py --jobs 12 > "$W/fails_$label.txt.log" 2>&1
grep -E '^(FAIL|TIMEOUT) +[0-9.]+s +' "$W/fails_$label.txt.log" | awk '{print $3}' | sort -u > "$W/fails_$label.txt"
new=$(comm -13 "$W/fails_$(git rev-parse --short "$base").txt" "$W/fails_$label.txt")
echo "== checks failing before: $(wc -l < "$W/fails_$(git rev-parse --short "$base").txt"), now: $(wc -l < "$W/fails_$label.txt")"
if [ -n "$new" ]; then echo "== NEW failures:"; echo "$new" | sed 's/^/   /'; exit 1; fi
echo "== no new failures"
