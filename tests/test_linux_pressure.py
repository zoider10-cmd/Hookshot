# SPDX-License-Identifier: GPL-3.0-or-later
"""Linux dynamic memory pressure (gpu/vk/linux_pressure.h, vk_texture.cpp, vk_memory.cpp, vk_draw.cpp, vk_progcache.cpp).

On a 16 GB Steam Deck OLED, guest shmem (5.6-6.0 GB), renderer anon (~3.9-7.5 GB) and kernel-pinned VMA blocks share one
memory pool while RADV's device-heap budget (~7.5 GB) stays under 50% used, so MemAvailable dipped to 180-440 MB with swap
nearly full and earlyoom killed the process. Checked here without a GPU or game:
- linux_pressure.h parses /proc/meminfo's MemAvailable, SwapFree, SwapTotal and MemTotal and computes the shortfall below
  RX_VK_AVAIL_RESERVE_MB (1536 MB) and RX_VK_COMMIT_RESERVE_MB (2560 MB);
- texture_frame() samples /proc/meminfo every 30 frames, cuts the texture budget on integrated GPUs with PressureHold, drains
  the target pool (pool_pressed), wakes VRAM compaction at its pressed thresholds (compact.pressed), frees idle staging arenas
  on entry and after 5 s idle, and checks malloc_trim every 600 frames;
- imports_give_back() acts once per sample, trims spare capture buffers to 32 MB and unpins idle unmirrored guest-pool imports
  for the shortfall less dead_import_bytes and evicted_import_bytes;
- pipeline_cache_play() on Linux (<= 20 GB RAM or under pressure) drops ready programs' VkShaderModules whose pipelines were
  built in the precompile (remade from hookshot_programs.bin by program_cache_complete_graphics when play builds a new pipeline
  variant), then runs malloc_trim(0).

python -I -B tests/test_linux_pressure.py [--cxx g++]
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
    mem = (ROOT / "gpu/vk/vk_memory.cpp").read_text(encoding="utf-8")
    draw = (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")
    dev_doc = (ROOT / "docs/development.md").read_text(encoding="utf-8")

    need("vk_texture.cpp", tex, ['#include "linux_pressure.h"', 'linux_pressure::avail_reserve(getenv("RX_VK_AVAIL_RESERVE_MB"))'])
    frame = block(tex, "void texture_frame(uint64_t completed)")
    need("vk_texture.cpp: texture_frame()", frame,
         ["static linux_pressure::PressureHold hold;",
          "const bool sampled_now = !have_meminfo || frame_no % 30 == 0;",
          "have_meminfo = linux_pressure::read_meminfo(&cached_avail, &cached_swap, nullptr, nullptr, &cached_has_swap);",
          "linux_shortfall_bytes.store(over, std::memory_order_relaxed);",
          "linux_shortfall_seq.fetch_add(1, std::memory_order_release);",
          "held_cached = hold.step(total_bytes, cached_avail, cached_swap, avail_res, commit_res,",
          "const bool igpu = dev.props.deviceType == VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU;",
          "budget = std::min(budget, held);",
          "rule_budget = std::min(rule_budget, held);",
          "pool_pressed = true;",
          "compact.pressed = true;",
          "stale || linux_entered_pressure",
          "const bool log_malloc = frame_no % 1800 == 0;",
          "const bool check_malloc = log_malloc || (linux_pressed && frame_no % 600 == 0);",
          "textures' budget is not cut on a discrete GPU",
          "vk: memory pressure on Linux:"])
    if frame.index("linux_pressure::read_meminfo") > frame.index("vram_compact::rule_target(total_bytes, size_budget, rule_budget)"):
        raise SystemExit("vk_texture.cpp: the Linux memory-pressure rule comes after rule_target reads rule_budget")

    need("vk_memory.cpp", mem, ['#include "linux_pressure.h"', "void cap_free_trim(uint64_t keep_bytes)", "uint64_t evicted_import_bytes = 0;"])
    imp = block(mem, "void imports_give_back()")
    need("vk_memory.cpp: imports_give_back()", imp,
         ["if (const uint64_t over = linux_pressure_shortfall(&over_seq)) {",
          "if (over_seq != last_over_seq) {",
          "cap_free_trim(32ull << 20);",
          "episode_deepest = std::max(episode_deepest, over);",
          "linux_want = linux_pressure::episode_want(linux_pressure::import_want(over, dead_import_bytes + evicted_import_bytes),",
          "episode_deepest = episode_given = 0;",
          "const uint64_t want_bytes = std::max(want, linux_want);",
          "if (for_linux) episode_given += freed - std::min(freed, want);",
          "vk: memory pressure on Linux: %d idle imports given back",
          "evicted_import_bytes -= std::min(evicted_import_bytes, p.hi - p.lo);",
          "evicted_import_bytes += p.hi - p.lo;",
          "if (freed >= want_bytes) break;"])
    if "read_meminfo" in imp:
        raise SystemExit("vk_memory.cpp: imports_give_back() still reads /proc/meminfo under pools_mu")

    play = block(draw, "void pipeline_cache_play()")
    need("vk_draw.cpp: pipeline_cache_play()", play,
         ["#ifdef __linux__",
          "linux_pressure::should_drop_modules(total_bytes, over, getenv(\"RX_VK_KEEP_MODULES\"), getenv(\"RX_VK_DROP_MODULES\"))",
          "program_cache_drop_modules()",
          "if (dropped_modules) malloc_trim(0);"])
    if "vkDestroyPipelineCache" in play:
        raise SystemExit("vk_draw.cpp: pipeline_cache_play() destroys pcache, losing start-cache hits for in-play builds")
    pre = block(draw, "void precompile_run(")
    need("vk_draw.cpp: precompile_run()", pre,
         ["wanted_variants.insert(mix(n->prog, n->variant))",
          "if (!p.compute && wanted_variants.count(mix(p.key, p.variant))) program_cache_note_built(p);"])
    pipe = block(draw, "PipeEntry* graphics_pipeline(")
    need("vk_draw.cpp: graphics_pipeline()", pipe,
         ["if (program_cache_complete_graphics(p)) e->pipeline = build_graphics(p, s, at, topo);",
          "if (!program_cache_complete_graphics(p)) {\n            e->ready.store(true, std::memory_order_release);\n            return remember(e);\n        }",
          "if (!program_cache_complete_graphics(*job->p)) {\n            job->e->ready.store(true, std::memory_order_release);\n            return;\n        }"])
    bg = block(draw, "VkPipeline build_graphics(const Program& p, const NvnState& s, const Targets& at, VkPrimitiveTopology topo, int part, bool* cold) {")
    need("vk_draw.cpp: build_graphics()", bg, ["program_modules_dropped(p)"])
    qp = block(draw, "bool quick_pipeline(PipeEntry& e,")
    need("vk_draw.cpp: quick_pipeline()", qp, ["program_modules_dropped(p)"])
    need("docs/development.md", dev_doc, ["RX_VK_AVAIL_RESERVE_MB", "RX_VK_DROP_MODULES", "RX_VK_KEEP_MODULES"])
    progcache = (ROOT / "gpu/vk/vk_progcache.cpp").read_text(encoding="utf-8")
    comp_gfx = block(progcache, "bool program_cache_complete_graphics(const Program& prog)")
    tail = comp_gfx[comp_gfx.index("std::lock_guard lk(light_mu);"):]
    if tail.index("it->second.program != &prog") > tail.index("it->second.failed = true;"):
        raise SystemExit("vk_progcache.cpp: program_cache_complete_graphics() marks a failed remake before checking, under light_mu, "
                         "that the modules are still let go")
    # (the per-program state of the module drop stays out of Program: sizeof(Program) is part of translator_stamp, and a member
    # more there made every player prepare every shader again)
    header = (ROOT / "gpu/vk/vk_shader.h").read_text(encoding="utf-8")
    program = block(header, "struct Program {")
    for member in ("modules_dropped", "remake_failed", "graphics_built", "record_at", "record_size"):
        if member in program:
            raise SystemExit("vk_shader.h: Program has " + member + " again, which changes sizeof(Program) and the translator's stamp")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    check_source()

    shader = (ROOT / "gpu/vk/vk_shader.cpp").read_text(encoding="utf-8")
    cache = (ROOT / "gpu/vk/vk_progcache.cpp").read_text(encoding="utf-8")
    cache_h = (ROOT / "gpu/vk/vk_progcache.h").read_text(encoding="utf-8")
    header = (ROOT / "gpu/vk/vk_shader.h").read_text(encoding="utf-8")

    structs = "\n".join(block(header, m) + ";" for m in ("struct Stage {", "struct Program {"))
    structs += "\n" + block(cache_h, "struct DiskRecord {") + ";"
    functions = "\n".join(block(shader, m) for m in ("uint64_t answers_hash(", "bool answers_fit("))
    functions += "\n" + block(cache, "void idx_put(")
    functions += "\n" + block(cache_h, "struct Reader {") + ";\n"
    functions += cache[cache.index("void put_bytes("):cache.index("void program_cache_save(")]
    functions += block(cache, "void program_cache_save(") + "\n" + block(cache, "bool program_cache_payload(") + "\n"
    functions += block(cache, "void program_cache_read(") + "\n"
    functions += "namespace {\nstd::mutex light_mu;\n}\n"
    functions += block(cache, "namespace module_remake {") + "\n"
    functions += block(cache, "void program_cache_note_built(") + "\n"
    functions += block(cache, "bool program_modules_dropped(") + "\n"
    functions += block(cache, "bool program_cache_complete_graphics(") + "\n"
    functions += block(cache, "size_t program_cache_drop_modules(") + "\n"

    with tempfile.TemporaryDirectory(prefix="linux-pressure-") as tmp:
        folder = Path(tmp).resolve()
        (folder / "cache_types.inc").write_text(structs, encoding="utf-8")
        (folder / "cache_functions.inc").write_text(functions, encoding="utf-8")
        exe = folder / "linux-pressure-test.exe"
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-D_CRT_SECURE_NO_WARNINGS",
                        "-I" + str(folder), str(ROOT / "tests/linux_pressure_test.cpp"), "-o", str(exe)],
                       check=True, cwd=folder)
        subprocess.run([str(exe), str(folder)], check=True, timeout=30)


if __name__ == "__main__":
    main()
