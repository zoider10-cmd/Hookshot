#!/bin/bash
# decompile.sh <address>...: Ghidra's C of the game's functions at those addresses (a crash's lr, a function f_<addr>),
# printed. Uses the Ghidra set up on this PC (TOOLS, default C:\Users\beerc\tools: Ghidra 12.2, Java 25, the project
# ghidra-projects/OotRemake with image.bin loaded at 0x80000000, no whole-program analysis: ghidra/import.bat makes it).
# About 5 s a call; nothing is saved to the project. The output is the game's code: it stays on this PC.
TOOLS="${TOOLS:-/c/Users/beerc/tools}"
[ -f "$TOOLS/ghidra-projects/decompile.bat" ] || { echo "no Ghidra project in $TOOLS/ghidra-projects (see ghidra/ beside this script)"; exit 1; }
out="$(cygpath -w "${TEMP:-/tmp}/rando-test-decompile.c")"
cmd //c "$(cygpath -w "$TOOLS/ghidra-projects/decompile.bat") $out $*" > "${TEMP:-/tmp}/rando-test-decompile.log" 2>&1
cat "$(cygpath -u "$out")" 2>/dev/null || { echo "failed: ${TEMP:-/tmp}/rando-test-decompile.log"; tail -5 "${TEMP:-/tmp}/rando-test-decompile.log"; exit 1; }
