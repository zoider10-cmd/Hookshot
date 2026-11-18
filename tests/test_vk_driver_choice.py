"""The Vulkan back end leaves the choice of Vulkan drivers to the system's loader (gpu/vk/vk_main.cpp load_global), no game
or GPU required.

Since 8e3dfde6 (#637), load_global set VK_ICD_FILENAMES to the first nv*\\nv-vk64.json in Windows' DriverStore. That
variable makes the loader use that one driver file and ignore every other driver. DriverStore keeps the packages of
NVIDIA drivers that are no longer in use (an older version, a card that has been replaced), and the first one found is
often not the driver in use. On those PCs Vulkan listed no GPU at all, on NVIDIA and AMD cards alike: "vk: no Vulkan 1.3
GPU", a black window (Hookshot #821, #1312, v3.0.0-rc.6), while vulkaninfo listed the GPUs.

The check cuts load_global out of vk_main.cpp, compiles its Windows branch with stand-ins for the Win32 calls (a
DriverStore holding an old NVIDIA package), runs it, and checks that none of the loader's driver variables (VK_ICD_FILENAMES,
VK_DRIVER_FILES, VK_ADD_DRIVER_FILES, VK_LOADER_DRIVERS_SELECT, VK_LOADER_DRIVERS_DISABLE) was set, and that vulkan-1.dll
is still loaded from System32 only. The program runs without those variables, so one set on this PC changes nothing.

python -I -B tests/test_vk_driver_choice.py [--cxx g++]
"""
import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # (python -I leaves the check's own folder off the path)
from srccut import block

ROOT = Path(__file__).resolve().parents[1]

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

HARNESS = r"""
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#ifndef _WIN32
#define _WIN32 1   // (the function's Windows branch, on any OS: the Win32 calls are the stand-ins below)
#endif

// Win32 stand-ins: a DriverStore with an NVIDIA package that is not the driver in use
typedef void* HANDLE;
typedef void* HMODULE;
typedef unsigned long DWORD;
typedef int BOOL;
typedef void (*FARPROC)(void);
#define MAX_PATH 260
#define INVALID_HANDLE_VALUE ((HANDLE)(intptr_t)-1)
#define FILE_ATTRIBUTE_DIRECTORY 0x10
#define INVALID_FILE_ATTRIBUTES ((DWORD)-1)
#define LOAD_LIBRARY_SEARCH_SYSTEM32 0x00000800
struct WIN32_FIND_DATAA { DWORD dwFileAttributes; char cFileName[MAX_PATH]; };

static const char* const kStore[] = {"nv_dispi.inf_amd64_0a1b2c3d4e5f6a7b", "nvhda.inf_amd64_1122334455667788"};
static size_t g_next;
static std::vector<std::string> g_env_set;   // (every NAME=VALUE the code set)
static std::string g_loaded;
static DWORD g_load_flags;

HANDLE FindFirstFileA(const char*, WIN32_FIND_DATAA* fd) {
    g_next = 0;
    fd->dwFileAttributes = FILE_ATTRIBUTE_DIRECTORY;
    std::snprintf(fd->cFileName, MAX_PATH, "%s", kStore[g_next++]);
    return (HANDLE)(intptr_t)1;
}
BOOL FindNextFileA(HANDLE, WIN32_FIND_DATAA* fd) {
    if (g_next >= sizeof kStore / sizeof *kStore) return 0;
    fd->dwFileAttributes = FILE_ATTRIBUTE_DIRECTORY;
    std::snprintf(fd->cFileName, MAX_PATH, "%s", kStore[g_next++]);
    return 1;
}
BOOL FindClose(HANDLE) { return 1; }
DWORD GetFileAttributesA(const char* path) {   // (every package's nv-vk64.json is there)
    return std::strstr(path, "nv-vk64.json") ? 0x20 : INVALID_FILE_ATTRIBUTES;
}
BOOL SetEnvironmentVariableA(const char* name, const char* value) {
    g_env_set.push_back(std::string(name) + "=" + (value ? value : ""));
    return 1;
}
HMODULE LoadLibraryExA(const char* name, HANDLE, DWORD flags) {
    g_loaded = name;
    g_load_flags = flags;
    return (HMODULE)(intptr_t)1;
}

// Vulkan stand-ins: the loader's vkGetInstanceProcAddr, which knows vkCreateInstance
typedef void (*PFN_vkVoidFunction)(void);
typedef PFN_vkVoidFunction (*PFN_vkGetInstanceProcAddr)(void*, const char*);
typedef PFN_vkVoidFunction PFN_vkCreateInstance;
#define VKX_GLOBAL(X) X(vkCreateInstance)
static void fake_create_instance(void) {}
static PFN_vkVoidFunction fake_gipa(void*, const char* name) {
    return std::strcmp(name, "vkCreateInstance") ? nullptr : fake_create_instance;
}
FARPROC GetProcAddress(HMODULE, const char* name) {
    return std::strcmp(name, "vkGetInstanceProcAddr") ? nullptr : (FARPROC)fake_gipa;
}
static PFN_vkGetInstanceProcAddr get_instance_proc;
PFN_vkCreateInstance vkCreateInstance;

@LOAD_GLOBAL@

int main() {
    // (the loader's variables that choose drivers: the files to take, more files, or which drivers it may use)
    const char* const driver_vars[] = {"VK_ICD_FILENAMES", "VK_DRIVER_FILES", "VK_ADD_DRIVER_FILES",
                                       "VK_LOADER_DRIVERS_SELECT", "VK_LOADER_DRIVERS_DISABLE"};
    for (const char* v : driver_vars)
        if (std::getenv(v)) {   // (the Python side starts this without them)
            std::printf("FAIL: %s is set before load_global ran\n", v);
            return 2;
        }
    if (!load_global()) {
        std::printf("FAIL: load_global returned false with a loader that has vkCreateInstance\n");
        return 1;
    }
    int bad = 0;
    for (const std::string& s : g_env_set)
        for (const char* v : driver_vars)
            if (!s.compare(0, std::strlen(v) + 1, std::string(v) + "=")) {
                std::printf("FAIL: load_global chose the Vulkan driver itself: %s (the loader then ignores every other "
                            "driver, and lists no GPU when that file is not the driver in use)\n", s.c_str());
                bad = 1;
            }
    for (const char* v : driver_vars)
        if (const char* e = std::getenv(v)) {
            std::printf("FAIL: load_global chose the Vulkan driver itself: %s=%s\n", v, e);
            bad = 1;
        }
    if (g_loaded != "vulkan-1.dll" || !(g_load_flags & LOAD_LIBRARY_SEARCH_SYSTEM32)) {
        std::printf("FAIL: the loader is not vulkan-1.dll from System32 only (%s, flags %#lx)\n", g_loaded.c_str(),
                    g_load_flags);
        bad = 1;
    }
    if (!bad) std::printf("ok: no Vulkan driver variable set; vulkan-1.dll from System32\n");
    return bad;
}
"""


DRIVER_VARS = ("VK_ICD_FILENAMES", "VK_DRIVER_FILES", "VK_ADD_DRIVER_FILES", "VK_LOADER_DRIVERS_SELECT",
               "VK_LOADER_DRIVERS_DISABLE")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    src = (ROOT / "gpu" / "vk" / "vk_main.cpp").read_text(encoding="utf-8")
    code = HARNESS.replace("@LOAD_GLOBAL@", block(src, "bool load_global() {", where="gpu/vk/vk_main.cpp"))
    # (run without the loader's driver variables, so one set on this PC neither passes nor fails the check)
    env = {k: v for k, v in os.environ.items() if k.upper() not in DRIVER_VARS}
    with tempfile.TemporaryDirectory(prefix="vk-driver-choice-") as tmp:
        cpp = Path(tmp) / "vk_driver_choice.cpp"
        exe = Path(tmp) / "vk_driver_choice"
        cpp.write_text(code, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", str(cpp), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], env=env)
        if r.returncode == 1:
            raise SystemExit("load_global picks the Vulkan driver instead of the system's loader (see FAIL above)")
        if r.returncode:
            raise SystemExit("the check's program ended with code %d without its result (a runtime library it could not "
                             "load, or a crash)" % r.returncode)


if __name__ == "__main__":
    main()
