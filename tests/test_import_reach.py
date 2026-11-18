"""Run vk_memory.cpp's actual scans down the import table with an import larger than 1 GiB behind a small one.

pool_lookup's merge escape may leave an import above 1 GiB over smaller ones inside it ("left overlapping"), and the device
allows imports up to max_import_size. The scans (pool_lookup's covering import and merge plan, bg_drain, prefetch_chunks,
import_in_background, memory_note_gpu_write, memory_guest_imported) stopped 1 GiB below their address and missed such an
import: the same bytes were imported twice. tests/import_reach_test.cpp records imports as ranges (no payload, no Vulkan, no
game) and checks that every scan finds the large import, and that import_reach.h's bound counts exactly the live imports.
The source check: the table has no way in or out but imported_add and imported_take, which keep that count, and no scan
keeps the 1 GiB stop.

python -I -B tests/test_import_reach.py --headers <Vulkan headers> [--cxx clang++] [--source <tree>]
"""
import argparse
from pathlib import Path
import re
import subprocess
import sys
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}", "--headers", "{vulkan_headers}"]

ROOT = Path(__file__).resolve().parents[1]
# (tests/import_reach_test.cpp: one case each, each in a process of its own; "header" only where import_reach.h exists)
CASES = ["lookup", "query", "note", "drain", "background", "prefetch", "retire"]
ADD = "std::map<uint64_t, Pool>::iterator imported_add("
TAKE = "std::map<uint64_t, Pool>::node_type imported_take("


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def excerpts(memory):
    """The types and bodies the fixture runs, and whether the source keeps the live imports' reach"""
    reach = ADD in memory
    types = "\n".join(block(memory, marker) + ";" for marker in ("struct Pool {", "struct GuestPool {"))
    code = ""
    if reach:
        start = memory.index("import_reach::Reach live_reach;")
        code += memory[start:memory.index(";", start) + 1] + "\n" + block(memory, ADD) + "\n" + block(memory, TAKE) + "\n"
    for marker in ("void retire_pool(std::map<uint64_t, Pool>::iterator it) {", "void bg_drain(", "void prefetch_chunks(",
                   "void span_game_pools(", "Pool* pool_lookup(uint64_t guest, uint64_t size) {", "Pool* pool_of(",
                   "bool import_in_background(", "void memory_note_gpu_write(", "int memory_guest_imported("):
        code += block(memory, marker) + "\n"
    return types, code, reach


def source_problems(memory):
    """Every way into or out of the table goes through the two helpers that keep live_reach, and no scan stops at 1 GiB"""
    problems = []
    if ADD not in memory or TAKE not in memory:
        return ["vk_memory.cpp has no imported_add / imported_take: nothing counts the live imports' spans"]
    rest = memory.replace(block(memory, ADD), "").replace(block(memory, TAKE), "")
    for use in re.findall(r"\bimported\s*(?:\.\s*(?:emplace|emplace_hint|try_emplace|insert|insert_or_assign|extract|erase|"
                          r"clear|merge|swap)\b|=[^=]|\[)", rest):
        problems.append("vk_memory.cpp changes the import table outside imported_add / imported_take: " + use.strip())
    if re.search(r"\.hi \+ \(1ull << 30\) <", memory):
        problems.append("vk_memory.cpp still has a scan that stops 1 GiB below its address")
    return problems


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, default=ROOT, help="the tree whose vk_memory.cpp is run (default: this one)")
    p.add_argument("--headers", type=Path, required=True)
    p.add_argument("--cxx", default="clang++")
    a = p.parse_args()
    memory = (a.source / "gpu/vk/vk_memory.cpp").read_text(encoding="utf-8")
    failed = ["source: " + problem for problem in source_problems(memory)]
    for problem in failed:
        print("FAIL", problem, flush=True)
    types, code, reach = excerpts(memory)
    fixture = (ROOT / "tests/import_reach_test.cpp").read_text(encoding="utf-8")
    fixture = fixture.replace("/* TYPES */", types).replace("/* ACTUAL */", code)
    with tempfile.TemporaryDirectory(prefix="import-reach-") as temp:
        cpp = Path(temp) / "fixture.cpp"
        cpp.write_text(fixture, encoding="utf-8")
        exe = Path(temp) / "fixture.exe"
        command = [a.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", "-Wno-unused-variable",
                   "-Wno-missing-field-initializers", "-pthread", "-DHAVE_REACH=" + str(int(reach)),
                   "-I" + str(a.headers), "-I" + str(a.source), str(cpp), "-o", str(exe)]
        print("COMPILE:", " ".join(command), flush=True)
        subprocess.run(command, check=True)
        for case in CASES + (["header"] if reach else []):   # (one that fails does not hide the others)
            print("RUN:", exe.name, case, flush=True)
            if subprocess.run([str(exe), case], timeout=60).returncode:
                failed.append(case)
    if failed:
        print("FAILED:", ", ".join(failed), flush=True)
        sys.exit(1)
    print("PASS: every scan finds the import above 1 GiB, and only imported_add / imported_take change the table", flush=True)


if __name__ == "__main__":
    main()
