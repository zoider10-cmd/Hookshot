"""A GPU unswizzle reads only a pool already imported (Reborn 6babdc2; gpu/vk/vk_texture.cpp upload_unswizzle_gpu): no game.

An import made for one texture upload took 22-25 ms on Reborn's replay thread (10-14 ms of vkAllocateMemory here, the
"vk: import ... allocate" lines), a hitch when new things come into view. So unless RX_VK_UNSWIZZLE_IMPORT=1, the
GPU path asks memory_guest_contained before gpu_buffer, and falls back to the CPU path when no pool holds the range.

- memory_guest_contained, compiled with a map of pools: one pool holding the whole range is 1; a range across two pools,
  past a pool's end or before the first is 0;
- the upload asks it, with the guest address of a virtual pool, before gpu_buffer, and the switch has its row.

    python -I -B tests/test_unswizzle_no_import.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))   # (python -I leaves the check's own folder off the path)
from srccut import block   # noqa: E402


def check(ok, why):
    if not ok:
        print("FAIL: %s" % why)
        sys.exit(1)


def main():
    memory = (ROOT / "gpu" / "vk" / "vk_memory.cpp").read_text(encoding="utf-8")
    texture = (ROOT / "gpu" / "vk" / "vk_texture.cpp").read_text(encoding="utf-8")
    fn = block(memory, "int memory_guest_contained(uint64_t lo, uint64_t hi) {", where="gpu/vk/vk_memory.cpp")
    upload = block(texture, "bool upload_unswizzle_gpu(Texture& tex, uint64_t total, const Ranges* dirty) {", where="gpu/vk/vk_texture.cpp")
    check('static const bool may_import = env_on("RX_VK_UNSWIZZLE_IMPORT");' in upload and
          "if (!memory_guest_contained(guest, guest + total)) return false;" in upload and
          "const uint64_t guest = tex.gpu < (1ull << 40) ? tex.gpu : host->gpu_guest(tex.gpu);" in upload and
          upload.index("memory_guest_contained(") < upload.index("gpu_buffer(tex.gpu, total)"),
          "the GPU unswizzle may still import a pool for one upload")
    table = (ROOT / "gpu" / "vk" / "switches.def").read_text(encoding="utf-8")
    check("SW(RX_VK_UNSWIZZLE_IMPORT, kill, bool," in table, "RX_VK_UNSWIZZLE_IMPORT has no row in gpu/vk/switches.def")

    cxx = shutil.which("clang++") or shutil.which("g++")
    if not cxx:
        print("PASS (the function not compiled: no C++ compiler here)")
        return
    src = """#include <cstdint>
#include <map>
#include <mutex>
struct Pool { uint64_t lo, hi; };
std::map<uint64_t, Pool> imported;
std::mutex pools_mu;
%s
int main() {
    imported[0x1000] = {0x1000, 0x5000};
    imported[0x8000] = {0x8000, 0x9000};
    int bad = 0;
    bad |= memory_guest_contained(0x1000, 0x5000) != 1;   // (the whole pool)
    bad |= (memory_guest_contained(0x2000, 0x3000) != 1) << 1;   // (inside)
    bad |= (memory_guest_contained(0x4000, 0x6000) != 0) << 2;   // (past its end)
    bad |= (memory_guest_contained(0x4000, 0x8800) != 0) << 3;   // (across two)
    bad |= (memory_guest_contained(0x0800, 0x1800) != 0) << 4;   // (before the first)
    bad |= (memory_guest_contained(0x8100, 0x8200) != 1) << 5;   // (the second)
    return bad;
}
""" % fn
    with tempfile.TemporaryDirectory() as d:
        c, exe = os.path.join(d, "t.cpp"), os.path.join(d, "t.exe")
        open(c, "w").write(src)
        r = subprocess.run([cxx, "-std=c++20", "-O1", c, "-o", exe], capture_output=True, text=True)
        check(r.returncode == 0, "memory_guest_contained does not compile alone:\n" + r.stderr[-2000:])
        r = subprocess.run([exe])
        check(r.returncode == 0, "memory_guest_contained answers wrongly (failed cases, as bits: %d)" % r.returncode)
    print("PASS: a GPU unswizzle reads only a pool already imported")


if __name__ == "__main__":
    main()
