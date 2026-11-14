#!/bin/bash
# The Linux AppImage: Hookshot Builder, its Python and Hookshot's sources. No game data and nothing made from it is in it:
# the game is built from the player's own copy, as on Windows. Its build tools (the compiler, the sysroot, FFmpeg, SDL2,
# the Vulkan headers) are not in it either: they are tools.lock's linux-x64 lines, which the Hookshot Launcher installs
# beside it, or the AppImage itself at its first start (builder/linux/linux_tools.py; docs/releases.md, "tools.lock").
#
#   scripts/linux/deps.sh        (first: Python, the AppImage packer, into build-linux/deps)
#   scripts/linux/appimage.sh    -> build-linux/Hookshot-<version>-x86_64.AppImage: the Linux builder a release ships, which
#                                   the Hookshot Launcher installs (docs/releases.md)
# The same image builds the game and, with --play, starts the one it saved.
#
# The tools this build itself uses (clang for the Vulkan back end, the headers, the sysroot for the check below) are
# tools.lock's, installed into build-linux/tools ($TOOLS) by scripts/tools.py install, as the builder installs them.
# work/ (hot_funcs.txt, hot_order.txt, hookshot_pieces.prof, image/chunks.txt: addresses and counts from playing, no game
# code) is carried along when it is there.
set -euo pipefail
cd "$(dirname "$0")/../.."
ROOT=$PWD
B=$ROOT/build-linux
DEPS=${DEPS:-$B/deps}
APPDIR=$B/AppDir
# (a release's tag, or the nightly's name nightly-<count>-<commit>, from the release workflow; a build of a checkout is named by git
# describe --long, which is on no channel: the launcher installs only released versions, docs/releases.md)
VERSION=${HOOKSHOT_VERSION:-$(git describe --tags --long --always --match "v[0-9]*" 2>/dev/null || echo dev)}
PY=$DEPS/python/bin/python3
# ---- the build tools, tools.lock's linux-x64 lines, at their places under $TOOLS (as in an installed builder) ----
TOOLS=${TOOLS:-$B/tools}
"$PY" -I scripts/tools.py install "$TOOLS" --system linux-x64 --cache "${TOOLS_CACHE:-$B/tools-cache}"
export EMSDK=$TOOLS/usr/lib/hookshot/emsdk RX_CPM=$TOOLS/usr/share/hookshot/cpm
S=$TOOLS/usr/lib/hookshot/sysroot

# ---- the Vulkan back end, built here once (it needs no game) ----
VKW=$B/vk-work
rm -rf "$VKW/sa/build/hookshot_vk.so"
OOT_WORK=$VKW RX_MARCH=x86-64-v3 RX_VK_ONLY=1 RX_RELEASE=1 "$PY" -I nx2/build.py --standalone --jobs "${JOBS:-$(nproc)}"
VK=$VKW/sa/build/hookshot_vk.so
[ -f "$VK" ] || { echo "hookshot_vk.so was not built"; exit 1; }

# ---- the tools' native helpers, built now: the AppImage is read-only. a64emit with its C++ runtime inside (the one this system
# builds with is newer than older systems have), and the stamp build_emit.py checks, so it is not built again ----
E=third_party/a64-kit/lift
"$EMSDK/upstream/bin/clang++" -std=c++20 -O2 -shared -fPIC -static-libstdc++ -static-libgcc -Wno-everything \
    -o "$E/liba64emit.so" "$E/a64emit.cpp"
"$PY" -I -c "import hashlib, sys; f = ['$E/a64emit.cpp', '$E/suyu/arm64_to_c.h']; open('$E/liba64emit.so.sha1', 'w').write(hashlib.sha1(b''.join(open(x, 'rb').read() for x in f)).hexdigest())"
"$PY" -I third_party/a64-kit/lift/build_emit.py
"$PY" -I -c "import sys; sys.path.insert(0, 'nx2'); import zbic; zbic.lib()"

rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/share/hookshot" "$APPDIR/usr/lib/hookshot"
T=$APPDIR/usr/share/hookshot
L=$APPDIR/usr/lib/hookshot

# ---- the tools (the sources the player's build compiles, and the scripts) ----
cp -a nx2 host scripts LICENSE README.md assets tools.lock "$T/"
printf '%s
' "$VERSION" > "$T/VERSION"   # (no git history in here: nx2/version.py reads the release name from it)
mkdir -p "$T/builder" "$T/gpu/render" "$T/gpu/vk" "$T/third_party"
cp -a builder/linux "$T/builder/"
cp -a gpu/render/*.h "$T/gpu/render/"
# (every gpu/vk header the host's sources include: v2.0.6 shipped without oot_cheat_items.h and no Linux build finished, issue 990.
# tests/test_appimage_headers.py checks that this covers what host/ includes)
for h in $(grep -rhoE 'gpu/vk/[A-Za-z0-9_/]+[.]h' host | sort -u); do if [ -f "$h" ]; then mkdir -p "$T/$(dirname "$h")" && cp -a "$h" "$T/$h"; fi; done
cp -a third_party/opus "$T/third_party/"
cp -a third_party/kenney_input "$T/third_party/"
cp -a third_party/kenney_input_keyboard "$T/third_party/"
# (NVIDIA DLSS, when ticked in the builder: scripts/ngx_sdk.py and the Vulkan back end's sources, compiled with HOOKSHOT_NGX_SDK)
mkdir -p "$T/scripts"
cp scripts/ngx_sdk.py "$T/scripts/"
cp -a gpu/vk gpu/compat gpu/third_party "$T/gpu/"
cp -a third_party/imgui third_party/zstd third_party/fonts "$T/third_party/"
# (AMD FSR 4, when chosen: AMD's MIT FSR API headers, which the Vulkan back end compiled here builds with (make_game.py --fsr,
# nx2/build.py). AMD's runtime is not among them: on Linux the player's own amd_fidelityfx_upscaler_vk.so, the readme)
cp -a third_party/fidelityfx "$T/third_party/"
mkdir -p "$T/third_party/zbic" "$T/third_party/a64-kit"
# (zbic's single-file zstd too: the Vulkan back end compiled here, with DLSS, builds zstd.c and includes zstd.h; v2.2.0-rc.1
# carried only zbic.so, and every Linux build with DLSS stopped at FileNotFoundError: zstd.h)
cp -a third_party/zbic/zbic.so third_party/zbic/zstd.c third_party/zbic/zstd.h third_party/zbic/zstd_errors.h \
      third_party/zbic/LICENSE third_party/zbic/PROVENANCE.md "$T/third_party/zbic/"
cp -a third_party/a64-kit/* "$T/third_party/a64-kit/"
rm -f "$T/third_party/a64-kit/tools/lld-link.exe"
if [ -d work ]; then
    mkdir -p "$T/work/image"
    for f in hot_funcs.txt hot_order.txt hookshot_pieces.prof; do [ -f "work/$f" ] && cp "work/$f" "$T/work/"; done
    [ -f work/image/chunks.txt ] && cp work/image/chunks.txt "$T/work/image/"
fi
# (the pipeline state list's sources, assets/pipeline_states/, came with assets/ above, and are required: nx2/make_game.py merges
# them beside the game, and without them a new install's first field load is drawn white for seconds while its pipelines
# compile; v2.0.8 to v2.0.14 shipped none. scripts/linux/check_player_build.sh reads them back from the image)
[ -n "$(find "$T/assets/pipeline_states" -name "*.bin.xz" 2>/dev/null)" ] || { echo "assets/pipeline_states/ holds no pipeline state list: a release ships them (docs/development.md, \"The pipeline state list\")"; exit 1; }
find "$T" -name __pycache__ -prune -exec rm -rf {} +

# ---- what it starts with: its Python (the tools' download, nx2/make_game.py) and the Vulkan back end ----
cp -a "$DEPS/python" "$APPDIR/usr/python"
cp "$VK" "$L/hookshot_vk.so"
# ---- the licences of the third-party parts compiled into hookshot_vk.so (tests/test_appimage_licenses.py) ----
mkdir -p "$T/licenses/imgui" "$T/licenses/zstd" "$T/licenses/libertinus" "$T/licenses/fidelityfx"
cp third_party/imgui/LICENSE.txt third_party/imgui/PROVENANCE.md "$T/licenses/imgui/"
cp third_party/zstd/LICENSE third_party/zstd/PROVENANCE.md "$T/licenses/zstd/"
cp third_party/fonts/libertinus/OFL.txt third_party/fonts/PROVENANCE.md "$T/licenses/libertinus/"
cp third_party/fidelityfx/LICENSE.md third_party/fidelityfx/PROVENANCE.md "$T/licenses/fidelityfx/"   # (with AMD FSR 4)
# ---- end of the licences ----

# ---- check: tools.lock's compiler builds and links a program against its sysroot, and it runs ----
cat > "$B/t.c" <<'EOF'
#include <pthread.h>
#include <stdio.h>
#include <math.h>
static void *f(void *p) { return p; }
int main(void) { pthread_t t; pthread_create(&t, 0, f, 0); pthread_join(t, 0); printf("ok %g\n", sqrt(2.0)); return 0; }
EOF
"$EMSDK/upstream/bin/clang" --sysroot="$S" -fuse-ld=lld -O2 -march=x86-64-v3 "$B/t.c" -o "$B/t" -lpthread -lm
"$B/t"
cat > "$B/t.cpp" <<'EOF'
#include <algorithm>
#include <filesystem>
#include <format>
#include <string>
extern "C" int t_cpp(int v) { return (int)std::format("{}", v).size(); }
EOF
"$EMSDK/upstream/bin/clang++" --sysroot="$S" -fuse-ld=lld -std=c++20 -O2 -march=x86-64-v3 -shared -fPIC -static-libstdc++ -static-libgcc \
    "$B/t.cpp" -o "$B/t.so" -ldl -lpthread -lm

# ---- the AppDir's own files ----
cp builder/linux/AppRun "$APPDIR/AppRun"
cp builder/linux/hookshot-builder.desktop "$APPDIR/"
# (RecompLauncher reads this from inside the AppImage, at /recomplauncher.json: docs/releases.md, "RecompLauncher")
cp recomplauncher.json "$APPDIR/recomplauncher.json"
cp assets/hookshot.png "$APPDIR/hookshot.png"
mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp assets/hookshot.png "$APPDIR/usr/share/icons/hicolor/256x256/apps/hookshot.png"

# (no update information: players get the Hookshot Launcher, which installs this AppImage from a release and checks it
# against the release's signed SHA256SUMS; on its own it is a way to try a build on this PC)
OUT=$B/Hookshot-$VERSION-x86_64.AppImage
rm -f "$OUT"
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$DEPS/appimagetool" --runtime-file "$DEPS/runtime-x86_64" --comp zstd "$APPDIR" "$OUT"
echo "$OUT: $(du -h "$OUT" | cut -f1)"
