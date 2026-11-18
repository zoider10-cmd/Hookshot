"""A texture the GPU never wrote into is told so without the lock and the walk (gpu/vk/wrote_regions.h; no game/GPU).

Each texture a submission samples asked gpu_wrote_into whether a GPU buffer write reached its storage: a lock and a walk
of the map of written ranges, 0.6 % of the replay thread on a Steam Deck, for an answer that is nearly always no. The
writes' 2 MB regions are now noted in a table; a texture in none of them is answered from the table.

Compiles tests/test_wrote_regions.cpp, and checks vk_texture.cpp notes a write's regions before the map has it and asks
the table before the lock.

python -I -B tests/test_wrote_regions.py [--cxx g++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def check_source():
    tex = (ROOT / "gpu/vk/vk_texture.cpp").read_text(encoding="utf-8")
    wrote = block(tex, "void texture_gpu_wrote(uint64_t gpu, uint64_t size) {")
    if "wrote_regions::mark(lo, hi);" not in wrote:
        raise SystemExit("texture_gpu_wrote no longer notes the write's regions")
    if wrote.index("wrote_regions::mark(lo, hi);") > wrote.index("std::lock_guard lk(gpu_wrote_mu);"):
        raise SystemExit("texture_gpu_wrote notes the regions after the map may have the write: a texture could be told no")
    into = block(tex, "bool gpu_wrote_into(Texture& tex) {")
    if "wrote_regions::any(lo, hi)" not in into:
        raise SystemExit("gpu_wrote_into no longer asks the table")
    if into.index("wrote_regions::any(lo, hi)") > into.index("std::lock_guard lk(gpu_wrote_mu);"):
        raise SystemExit("gpu_wrote_into takes its lock before it asks the table")
    for needle in ("it->second.second <= completed_value", "tex.gpu_wrote_seen = newest;"):
        if needle not in into:
            raise SystemExit("gpu_wrote_into's walk no longer has: " + needle)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    check_source()
    with tempfile.TemporaryDirectory(prefix="wrote-regions-") as tmp:
        exe = Path(tmp) / "wrote-regions"
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", str(ROOT / "tests/test_wrote_regions.cpp"),
                        "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
