"""Without VRAM mirrors the bookkeeping for their write-backs is not kept (gpu/vk/vk_memory.cpp; no game/GPU).

A mirror's write-back needs two things noted as the replay goes: the report words the replay wrote on the CPU
(memory_cpu_owned), which it leaves out, and the guest pages the CPU wrote (shadow_written_to), which its diff reads
again. Where the pools have no mirrors (an integrated GPU, a GCN card, RX_VK_MIRROR=0) there is no write-back to read
either: the words piled up to 65,536 and were sorted, merged and thrown away, the page lists to 8 million entries
(32 MB) before being dropped, about 1 % of the replay thread on a Steam Deck in bursts. Nothing is noted there now.

Cuts the bookkeeping out of the source into tests/mirror_bookkeeping_test.cpp and runs it without mirrors, then with.

python -I -B tests/test_mirror_bookkeeping.py [--cxx g++]
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


def cut(text, start, end):
    if text.count(start) != 1:
        raise SystemExit("marker not found once: " + start)
    a = text.index(start)
    return text[a:text.index(end, a)]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="g++")
    a = p.parse_args()
    mem = (ROOT / "gpu" / "vk" / "vk_memory.cpp").read_text(encoding="utf-8")
    # (what reads the bookkeeping is a write-back, and a write-back is a mirror's: the rule the early returns rest on)
    wb = cut(mem, "if (!writebacks.empty()) {", "static thread_local std::vector<WbdChunk> chunks;")
    if "shadows_forget_written()" not in wb or mem.count("shadows_forget_written()") != 2:
        raise SystemExit("the CPU-written page lists are read somewhere else than a write-back: update this test")
    if mem.count("cut_cpu_words(") != 2 or "cut_cpu_words(*p, runs);" not in mem[mem.index("if (!writebacks.empty()) {"):]:
        raise SystemExit("the replay's report words are read somewhere else than a write-back: update this test")
    bind = block(mem, "BufferRef gpu_buffer_bind(")
    if not bind.index("p->mstate != Pool::MIRROR_ON") < bind.index("writebacks.push_back("):
        raise SystemExit("a write-back is noted for a pool without a mirror: update this test")
    actual = cut(mem, "std::mutex cpu_words_mu;", "} // namespace\nvoid memory_cpu_owned(")
    actual += block(mem, "void memory_cpu_owned(uint64_t guest, uint64_t size) {") + "\n"
    actual += cut(mem, "std::mutex shadow_written_mu;", "int64_t st_wbd_known_game")
    for marker in ("void shadow_written_to(", "void shadow_written(const uint32_t* pages, int64_t n) {",
                   "void shadow_written_collected(const uint32_t* pages, int64_t n) {", "void guest_cpu_wrote(uint64_t gpu, uint64_t n) {"):
        actual += block(mem, marker) + "\n"
    fixture = (ROOT / "tests/mirror_bookkeeping_test.cpp").read_text(encoding="utf-8").replace("/* ACTUAL */", actual)
    with tempfile.TemporaryDirectory(prefix="mirror-bookkeeping-") as tmp:
        cpp, exe = Path(tmp) / "t.cpp", Path(tmp) / "t"
        cpp.write_text(fixture, encoding="utf-8")
        subprocess.run([a.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", str(cpp), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
