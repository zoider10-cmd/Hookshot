"""AMD FSR 4's unrolled layers survive an update that changes the translator (no game or GPU required).

The unrolled layers (gpu/vk/vk_fsr4.cpp build_unrolled) take the driver about 50 s and 3 GB of memory each to build cold on
an RX 6700 XT. When they were built into the translator's pipeline cache, every update that changed the translator dropped
them with that cache's files (gpu/vk/pcache_stamp.h), and the first FSR 4 frames of each update built them again. They go
into a cache file of their own now, and a layer found in the caches is taken without asking for the memory a compile
wants. This check:
- finds the file vk_fsr4.cpp builds and saves them through (kOwnCacheFile, own_cache_compute_pipeline, own_pipeline_cache_save),
  and that build_unrolled asks the caches (no compile) before it asks for kBuildHeadroom;
- runs pipeline_cache_file.h's sweep of cut-short saves on a leftover .tmp of that file: it goes;
- compiles pcache_stamp.h and runs its drop against a folder holding the translator's files and that file, made for another
  translator: the translator's files go, FSR 4's stays.

python -I -B tests/test_fsr4_own_cache.py [--cxx g++]
"""
import argparse
import re
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r'''
#include <cstdio>
#include <string>
#include "gpu/vk/pcache_stamp.h"
#include "gpu/vk/pipeline_cache_file.h"
using namespace pcache_stamp;
static void put(const std::string& path) {
    FILE* f = std::fopen(path.c_str(), "wb");
    std::fputs("data", f);
    std::fclose(f);
}
static bool there(const std::string& path) {
    FILE* f = std::fopen(path.c_str(), "rb");
    if (f) std::fclose(f);
    return f != nullptr;
}
int main(int, char** argv) {
    const std::string dir = std::string(argv[1]) + "/", own = argv[2];
    write(dir, 0x1111);   // (the old translator's stamp, as an update finds it)
    put(dir + kMainFile);
    put(dir + std::string(kPlayPrefix) + "3.bin");
    put(dir + own);
    const Dropped d = check(dir, 0x2222);   // (the new translator)
    if (there(dir + kMainFile) || there(dir + std::string(kPlayPrefix) + "3.bin") || d.files < 2) {
        std::fprintf(stderr, "the translator's files were not dropped (the fixture is wrong)\n");
        return 2;
    }
    if (!there(dir + own)) {
        std::fprintf(stderr, "%s was dropped with the translator's files\n", own.c_str());
        return 1;
    }
    // (a save cut short leaves its .tmp: the start's sweep takes FSR 4's as it takes the translator's, or the launcher would
    // carry it into every update's folder)
    const std::string tmp = dir + own + ".tmp-123-4";
    put(tmp);
    mkwvk::PipelineCacheFile::cleanup_temporaries(dir, 0);
    if (there(tmp)) {
        std::fprintf(stderr, "%s was not swept\n", (own + ".tmp-123-4").c_str());
        return 3;
    }
    std::puts("PASS: FSR 4's unrolled layers are kept when the translator changes, and their cut-short saves are swept");
    return 0;
}
'''


def body(text, head):
    start = text.index(head)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def own_file():
    fsr4 = (ROOT / "gpu/vk/vk_fsr4.cpp").read_text(encoding="utf-8")
    build = body(fsr4, "void build_unrolled(")
    if "shared_compute_pipeline(" in build or "pipeline_cache_save_play()" in build:
        raise SystemExit("vk_fsr4.cpp: the unrolled layers are built into the translator's pipeline cache, whose files a new "
                         "translator drops (pcache_stamp.h): every such update builds them cold again")
    m = re.search(r'constexpr const char\* kOwnCacheFile = "([^"]+)";', fsr4)
    if not m:
        raise SystemExit("vk_fsr4.cpp: no kOwnCacheFile, the unrolled layers' own pipeline cache file")
    if "own_cache_compute_pipeline(own_cache()" not in build or "own_pipeline_cache_save(own_cache(), kOwnCacheFile" not in build:
        raise SystemExit("vk_fsr4.cpp: build_unrolled does not build and save through its own cache (kOwnCacheFile)")
    # (a layer in the caches is taken before the memory a compile wants is asked for: a PC with less than kBuildHeadroom to
    # spare ran without the unrolled layers even when they were cached)
    ask = build.find("VK_PIPELINE_CREATE_FAIL_ON_PIPELINE_COMPILE_REQUIRED_BIT")
    if ask < 0 or ask > build.index("build_headroom("):
        raise SystemExit("vk_fsr4.cpp: build_unrolled asks for kBuildHeadroom before it asks the caches for the layer")
    return m.group(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    name = own_file()
    with tempfile.TemporaryDirectory(prefix="fsr4-own-cache-") as folder:
        source, exe = Path(folder) / "fixture.cpp", Path(folder) / "fixture.exe"
        cache = Path(folder) / "cache"
        cache.mkdir()
        source.write_text(FIXTURE, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-I" + str(ROOT), str(source), "-o", str(exe)],
                       check=True, timeout=60)
        raise SystemExit(subprocess.run([str(exe), str(cache), name], timeout=30).returncode)


if __name__ == "__main__":
    main()
