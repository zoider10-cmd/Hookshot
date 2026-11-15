"""What the page files can still grow by counts as room under Windows' commit limit.

The textures' budget gives commit back below RX_VK_COMMIT_RESERVE_MB of headroom (tests/test_commit_limit.py). The headroom was
GlobalMemoryStatusEx's ullAvailPageFile alone: the limit as it is now, RAM plus the page files at their size of the moment. A
page file Windows manages grows as the commit nears that limit. A 32 GB PC with a 2 GB page file at the start (issue 336)
played 90 minutes with 0.3 to 2.5 GB left under the limit of the moment while Windows raised it by more than 12 GB and refused
no commit; the rule cut the textures' budget the whole time, to 0 at its lowest, and the textures went black and were made
again. The rule (gpu/vk/commit_room.h) is compiled and run: the growth of each file up to its maximum and its drive's free
space, the reported run's numbers, and the reading of NtQuerySystemInformation's records inside their buffer. vk_texture.cpp is
checked to use it. No GPU or game.

python -I -B tests/test_commit_room.py [--cxx g++]
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


def need(where, text, needles):
    for needle in needles:
        if needle not in text:
            raise SystemExit(where + " no longer has: " + needle)


def check_source():
    tex = (ROOT / "gpu/vk/vk_texture.cpp").read_text(encoding="utf-8")
    need("vk_texture.cpp", tex, ['#include "commit_room.h"'])
    # (the headroom is what is left under the limit now and, below the reserve, what the page files can grow by)
    head = block(tex, "static bool commit_headroom(uint64_t* free_bytes)")
    need("vk_texture.cpp: commit_headroom()", head,
         ['getenv("RX_VK_COMMIT_GROWTH")',
          "if (commit_room::wants_growth(m.ullAvailPageFile, commit_reserve(), counted)) {",
          "grow = page_file_growth();",
          "*free_bytes = commit_room::headroom(m.ullAvailPageFile, grow);"])
    # (the growth comes from the page files' own sizes and maximums and their drives' free space, read at most once a second,
    # and is 0 where the query fails)
    grow = block(tex, "static uint64_t page_file_growth()")
    need("vk_texture.cpp: page_file_growth()", grow,
         ["if (at && now - at < 1000) return value;",
          '"NtQuerySystemInformation"',
          "if (!query || query(0x90, buf, sizeof buf, &len) < 0 || len > sizeof buf) return 0;",
          "commit_room::page_files(buf, len, si.dwPageSize, files, 16)",
          "value = commit_room::growth(files, n,",
          "GetDiskFreeSpaceExW(root, nullptr, nullptr, &free_bytes) ? free_bytes.QuadPart : 0"])
    if not tex.index("static uint64_t page_file_growth()") < tex.index("static bool commit_headroom(uint64_t* free_bytes)"):
        raise SystemExit("vk_texture.cpp: page_file_growth() is no longer defined before commit_headroom()")
    docs = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    need("docs/development.md", docs, ["`RX_VK_COMMIT_GROWTH=0`"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    check_source()
    with tempfile.TemporaryDirectory(prefix="commit-room-") as tmp:
        exe = Path(tmp) / "commit-room"
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", str(ROOT / "tests/test_commit_room.cpp"), "-o",
                        str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
