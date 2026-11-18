"""Whether the pipeline cache's file is read at the start (gpu/vk/pcache_load.h, used by vk_draw.cpp's pcache_load_off), issue
388: not read by default on Linux with NVIDIA's own driver, 20 GB of RAM or less and programs loaded at their create calls,
where NVIDIA's own shader cache is on and its folder holds 512 MB or more; read as before everywhere else; RX_VK_PCACHE_LOAD
says either way.

Two parts, no game or GPU:
- the rule's table (pcache_load::choose), compiled and run;
- vk_draw.cpp's pcache_load_off itself, cut out of the source and compiled with stand-ins for the device (its driver ID), the
  load mode and the RAM, then run once a case (its answer is latched for the process) against real folders: NVIDIA's cache
  found where its driver keeps it (__GL_SHADER_DISK_CACHE_PATH's GLCache, XDG_CACHE_HOME, HOME, the earlier drivers' .nv),
  its size alone counted (an empty NVIDIA folder beside a full Mesa folder reads the file), a cache turned off, missing or
  not readable read as cold, NVK left alone, and the log line. The 600 MB files are sparse: they take no disk space.
  POSIX only for the folder cases (pcache_load_off reads the file on Windows whatever the folders hold: checked there).
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]

TABLE = r'''
#include "pcache_load.h"
#include <cstdio>
#include <initializer_list>
using namespace pcache_load;
static int fails;
#define NEED(c, what) do { if (!(c)) { fails++; std::printf("FAIL: %s\n", what); } } while (0)
constexpr Cache M = Cache::kMeasured;
// (the rule is constexpr: the table holds at build time too)
static_assert(!choose(-1, false, true, true, 15757, M, 1200).load, "a 16 GB Linux NVIDIA PC with a warm driver cache leaves the file");
static_assert(choose(-1, false, true, true, 32000, M, 1200).load, "a 32 GB PC reads the file");
int main() {
    const uint32_t pc16 = 15757;   // (a 16 GB PC: what it reports)
    // the small PC: not read
    Choice c = choose(-1, false, true, true, pc16, M, 1200);
    NEED(!c.load && c.why == Why::kSmallPc, "16 GB, Linux NVIDIA, create, warm driver cache: not read");
    NEED(!choose(-1, false, true, true, kSmallRamMb, M, kWarmMb).load, "at the limits: not read");
    NEED(needs_cache(-1, false, true, true, pc16), "the small PC looks at NVIDIA's cache");
    // read as before everywhere else
    NEED(choose(-1, false, true, true, kSmallRamMb + 1, M, 1200).why == Why::kRam, "over 20 GB: read");
    NEED(choose(-1, false, true, true, 0, M, 1200).why == Why::kRam, "RAM not known: read");
    NEED(choose(-1, false, true, false, pc16, M, 1200).why == Why::kNotLinuxNvidia, "Windows, AMD, Intel, NVK: read");
    NEED(choose(-1, false, false, true, pc16, M, 1200).why == Why::kStart, "programs loaded before the title: read");
    NEED(choose(-1, true, true, true, pc16, M, 1200).why == Why::kPreparing, "a --prepare-shaders run: read");
    NEED(choose(-1, false, true, true, pc16, M, kWarmMb - 1).why == Why::kColdDriverCache, "a nearly empty driver cache: read");
    NEED(choose(-1, false, true, true, pc16, Cache::kOff, 1200).why == Why::kDriverCacheOff, "NVIDIA's cache off: read");
    NEED(choose(-1, false, true, true, pc16, Cache::kUnknown, 1200).why == Why::kDriverCacheUnknown, "not measured: read");
    for (bool prep : {false, true})
        for (bool create : {false, true})
            for (bool nv : {false, true})
                for (uint32_t ram : {0u, pc16, 32000u})
                    NEED(needs_cache(-1, prep, create, nv, ram) == (!prep && create && nv && ram == pc16),
                         "NVIDIA's folder looked at only where the rest would leave the file");
    // the switch, whatever the rest says
    NEED(choose(1, false, true, true, pc16, M, 1200).load, "RX_VK_PCACHE_LOAD=1 reads it on the small PC");
    NEED(!choose(0, false, false, false, 64000, Cache::kOff, 0).load, "RX_VK_PCACHE_LOAD=0 does not read it anywhere");
    NEED(!choose(0, true, true, true, pc16, M, 1200).load, "RX_VK_PCACHE_LOAD=0 holds in a preparing run too, as before");
    NEED(!needs_cache(0, false, true, true, pc16) && !needs_cache(1, false, true, true, pc16), "the switch walks no folder");
    for (Why w : {Why::kSwitch, Why::kPreparing, Why::kStart, Why::kNotLinuxNvidia, Why::kRam, Why::kDriverCacheOff,
                  Why::kDriverCacheUnknown, Why::kColdDriverCache, Why::kSmallPc})
        NEED(why_text(w)[0] != 0, "every reason has its words for the log");
    if (!fails) std::printf("ok\n");
    return fails != 0;
}
'''

# vk_draw.cpp's pcache_load_off, with stand-ins: the device's driver (FAKE_DRIVER=nvk: Mesa's NVK), the load mode
# (FAKE_AT_CREATE=0: before the title) and the RAM (FAKE_RAM_MB, through sysconf). Exit 10: not read, 11: read
ADAPTER = r'''
#include "pcache_load.h"
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#ifndef _WIN32
#include <unistd.h>
static long fake_sysconf(int name) {
    const char* m = getenv("FAKE_RAM_MB");
    const long mb = m ? atol(m) : 0;
    return name == _SC_PAGE_SIZE ? 4096 : name == _SC_PHYS_PAGES ? mb * 256 : -1;
}
#define sysconf fake_sysconf
#endif
enum VkDriverId { VK_DRIVER_ID_NVIDIA_PROPRIETARY = 4, VK_DRIVER_ID_MESA_NVK = 24 };
struct { VkDriverId driver_id = VK_DRIVER_ID_NVIDIA_PROPRIETARY; } dev;
bool programs_load_at_create() { return !env_value_off(getenv("FAKE_AT_CREATE") ? getenv("FAKE_AT_CREATE") : "1"); }
void logf(const char* fmt, ...) {
    va_list a;
    va_start(a, fmt);
    std::vprintf(fmt, a);
    va_end(a);
    std::printf("\n");
}
#include "pcache_load_off.inc"
int main() {
    if (const char* d = getenv("FAKE_DRIVER"); d && !std::strcmp(d, "nvk")) dev.driver_id = VK_DRIVER_ID_MESA_NVK;
    const bool off = pcache_load_off();
    return off == pcache_load_off() ? (off ? 10 : 11) : 2;   // (decided once)
}
'''

MB600 = 600 << 20


def function(src, head):
    if src.count(head) != 1:
        raise SystemExit("FAIL: vk_draw.cpp has no single " + head)
    fn = src[src.index(head):]
    return fn[:fn.index("\n}\n") + 3]


def check_source(src):
    fn = function(src, "bool pcache_load_off() {")
    for needle, why in (
            ('#include "pcache_load.h"', "vk_draw.cpp does not include pcache_load.h"),
            ("dev.driver_id == VK_DRIVER_ID_NVIDIA_PROPRIETARY", "NVIDIA's own driver is not told apart (NVK has Mesa's cache)"),
            ("pcache_load::choose(sw, preparing, at_create, linux_nvidia, ram_mb, cache.cache, cache.bytes >> 20)",
             "pcache_load_off does not decide through the rule"),
            ("return !choice.load;", "pcache_load_off does not return the rule's answer"),
            ("static const bool off", "the answer is not decided once a run")):
        if needle not in (src if needle.startswith("#include") else fn):
            raise SystemExit(why + " (looked for: " + needle + ")")
    # (NVIDIA's folder alone counts: driver_cache_bytes adds Mesa's to it, PR 416's review)
    if "driver_cache_bytes" in fn:
        raise SystemExit("pcache_load_off counts the other drivers' cache folders")
    # (the rest of the pipeline cache still goes by the one answer: not saved when not read)
    init = function(src, "void pcache_init() {")
    if "const bool off = pcache_load_off();" not in init or "pcache_no_save = off;" not in init:
        raise SystemExit("pcache_init no longer takes pcache_load_off's answer for reading and saving")
    return fn


def sparse(path, size):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.truncate(size)


def cases():
    """(name, env, files {relative path: size}, dirs [relative], expected exit, words the log line has, words it lacks)"""
    nv, mesa = ".cache/nvidia/GLCache/0123abcd/entry", ".cache/mesa_shader_cache_db/part0/mesa_cache.db"
    small = {"FAKE_RAM_MB": "15757"}
    return [
        ("warm", dict(small, HOME="h"), {"h/" + nv: MB600}, [], 10, ["not read", "600 MB in", "RX_VK_PCACHE_LOAD=1 reads it"], []),
        # (the review's case: NVIDIA's folder empty and fresh, Mesa's full: the file is read)
        ("mesa-only", dict(small, HOME="h", __GL_SHADER_DISK_CACHE_PATH="p", MESA_SHADER_CACHE_DIR="m"),
         {"h/" + mesa: MB600, "m/part0/mesa_cache.db": MB600}, ["p/GLCache"], 11, ["read", "nearly empty", "0 MB in"], []),
        ("path-wins", dict(small, HOME="h", __GL_SHADER_DISK_CACHE_PATH="p"), {"h/" + nv: MB600}, ["p/GLCache"], 11,
         ["nearly empty"], []),
        ("path-warm", dict(small, HOME="h", __GL_SHADER_DISK_CACHE_PATH="p"), {"p/GLCache/0123abcd/entry": MB600}, [], 10,
         ["not read"], []),
        ("path-glcache-only", dict(small, __GL_SHADER_DISK_CACHE_PATH="p"), {"p/elsewhere/entry": MB600}, ["p/GLCache"], 11,
         ["nearly empty"], []),
        ("xdg", dict(small, HOME="h", XDG_CACHE_HOME="x"), {"x/nvidia/GLCache/0123abcd/entry": MB600}, [], 10, ["not read"], []),
        ("xdg-not-home", dict(small, HOME="h", XDG_CACHE_HOME="x"), {"h/" + nv: MB600}, [], 11, ["nearly empty"], []),
        ("earlier-driver", dict(small, HOME="h"), {"h/.nv/GLCache/0123abcd/entry": MB600}, ["h/.cache/nvidia/GLCache"], 10,
         ["not read", ".nv"], []),
        ("earlier-driver-empty", dict(small, HOME="h"), {"h/" + nv: MB600}, ["h/.nv/GLCache"], 11, ["nearly empty"], []),
        ("missing", dict(small, HOME="h"), {}, ["h"], 11, ["nearly empty", "0 MB in"], []),
        ("not-a-folder", dict(small, HOME="h"), {"h/.cache/nvidia/GLCache": 10}, [], 11, ["could not be measured"], []),
        ("switched-off", dict(small, HOME="h", __GL_SHADER_DISK_CACHE="0"), {"h/" + nv: MB600}, [], 11, ["is off"], ["MB in"]),
        ("no-folder", dict(small), {}, [], 11, ["is off"], []),
        ("nvk", dict(small, HOME="h", FAKE_DRIVER="nvk"), {"h/" + nv: MB600}, [], 11, ["NVIDIA's own driver"], ["MB in"]),
        ("ram", dict(HOME="h", FAKE_RAM_MB="32000"), {"h/" + nv: MB600}, [], 11, ["32000 MB of RAM"], ["MB in"]),
        ("start", dict(small, HOME="h", FAKE_AT_CREATE="0"), {"h/" + nv: MB600}, [], 11, ["before the title"], ["MB in"]),
        ("prepare", dict(small, HOME="h", HOOKSHOT_PREPARE_ONLY="1"), {"h/" + nv: MB600}, [], 11, ["--prepare-shaders"], ["MB in"]),
        ("switch-on", dict(small, HOME="h", RX_VK_PCACHE_LOAD="1"), {"h/" + nv: MB600}, [], 11, ["RX_VK_PCACHE_LOAD=1"],
         ["MB in", "MB of RAM"]),
        # (the switch wins over a preparation, and prints no cache size it did not measure)
        ("switch-off-prepare", dict(small, HOME="h", RX_VK_PCACHE_LOAD="0", HOOKSHOT_PREPARE_ONLY="1"), {}, ["h"], 10,
         ["not read", "RX_VK_PCACHE_LOAD=0"], ["MB in", "reads it"]),
    ]


def run_adapter(exe, root):
    failed = []
    keep = {k: v for k, v in os.environ.items() if k in ("PATH", "SYSTEMROOT", "TMP", "TEMP")}
    for name, env, files, dirs, want, has, lacks in cases():
        base = root / name
        base.mkdir()
        for rel, size in files.items():
            sparse(base / rel, size)
        for rel in dirs:
            (base / rel).mkdir(parents=True, exist_ok=True)
        e = dict(keep)
        for k, v in env.items():
            e[k] = str(base / v) if k in ("HOME", "XDG_CACHE_HOME", "__GL_SHADER_DISK_CACHE_PATH", "MESA_SHADER_CACHE_DIR") else v
        r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=30, env=e)
        line = r.stdout.strip()
        ok = r.returncode == want and line.count("\n") == 0 and all(w in line for w in has) and not any(w in line for w in lacks)
        print(("ok   " if ok else "FAIL ") + name + ": " + line)
        if not ok:
            failed.append(name)
    # (a folder in NVIDIA's cache that cannot be read: not measured, read; not as root, which reads it all the same)
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        base = root / "unreadable"
        sparse(base / "h/.cache/nvidia/GLCache/0123abcd/entry", MB600)
        locked = base / "h/.cache/nvidia/GLCache/0123abcd"
        locked.chmod(0)
        try:
            e = dict(keep, HOME=str(base / "h"), FAKE_RAM_MB="15757")
            r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=30, env=e)
        finally:
            locked.chmod(0o755)
        line = r.stdout.strip()
        ok = r.returncode == 11 and "could not be measured" in line and "could not be walked through" in line
        print(("ok   " if ok else "FAIL ") + "unreadable: " + line)
        if not ok:
            failed.append("unreadable")
    return failed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default=os.environ.get("CXX") or shutil.which("clang++") or shutil.which("g++") or "g++")
    args = parser.parse_args()
    fn = check_source((ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8"))
    flags = ["-std=c++20", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "gpu/vk")]
    if os.name == "nt":
        flags += ["-D_CRT_SECURE_NO_WARNINGS"]
    with tempfile.TemporaryDirectory(prefix="pcache-load-") as tmp:
        tmp = Path(tmp)
        cpp, exe = tmp / "table.cpp", tmp / "table.exe"
        cpp.write_text(TABLE, encoding="utf-8")
        subprocess.run([args.cxx, *flags, str(cpp), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
        (tmp / "pcache_load_off.inc").write_text(fn, encoding="utf-8")
        cpp, exe = tmp / "adapter.cpp", tmp / "adapter.exe"
        cpp.write_text(ADAPTER, encoding="utf-8")
        subprocess.run([args.cxx, *flags, "-I", str(tmp), "-include", str(ROOT / "gpu/vk/compat/hookshot_env.h"), str(cpp),
                        "-o", str(exe)], check=True)
        folders = tmp / "folders"
        folders.mkdir()
        if os.name == "nt":
            r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=30,
                               env=dict(os.environ, FAKE_RAM_MB="15757"))
            failed = [] if r.returncode == 11 and "NVIDIA's own driver" in r.stdout else ["windows"]
            print(r.stdout.strip())
        else:
            failed = run_adapter(exe, folders)
    if failed:
        print("FAIL: " + ", ".join(failed))
        return 1
    print("pipeline cache file: not read on a small Linux PC with NVIDIA's own driver and its warm cache, programs loaded at "
          "create; read as before elsewhere")
    return 0


if __name__ == "__main__":
    sys.exit(main())
