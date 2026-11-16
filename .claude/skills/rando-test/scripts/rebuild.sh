#!/bin/bash
# rebuild.sh: the game rebuilt into the game folder from this checkout (nx2/make_game.py --update), keeping the translated
# C files so a function can be read after (%LOCALAPPDATA%/HookshotBuilder/sa/gen/code_*.c). About 1.5 to 2 minutes for a
# change to host/ or to nx2/oot_patches.py. Prints the patches applied, errors and the time; the whole log goes to
# $WORK/build.log. GAME as in run_headless.sh. Not while the game or the launcher is open.
set -u
GAME="${GAME:-/f/Games/OOT Remake Rando}"
WORK="${WORK:-${TEMP:-/tmp}/rando-test}"
WORK="$(cygpath -u "$WORK" 2>/dev/null || echo "$WORK")"
mkdir -p "$WORK"
if tasklist 2>/dev/null | grep -qi "hookshot.exe\|Mako Launcher"; then echo "the game or the launcher is running: not built"; exit 1; fi
root="$(cd "$(dirname "$0")/../../../.." && pwd)"
cd "$root" || exit 1
HOOKSHOT_KEEP_BUILD_FILES=1 PATH="$root/llvm-mingw/bin:$PATH" py -I nx2/make_game.py --update "$(cygpath -w "$GAME")" > "$WORK/build.log" 2>&1
code=$?
echo "build exit $code (the log: $WORK/build.log)"
# (the button prompts' AssertionError is old and harmless: "the button prompts of other controllers were not made")
grep -E "^oot_patches: |error:|failed|the build took" "$WORK/build.log" | grep -v "WARNING: the model swap guards" | head -40
exit $code
