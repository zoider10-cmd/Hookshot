"""A draw whose vertex streams changed binds the bindings that changed, not all 16 (gpu/vk/vk_draw.cpp; no game/GPU).

The driver takes every binding it is handed. A draw whose streams differed from the last ones bound handed it all 16,
the unused ones with the zero buffer again: 1.1 % of the replay thread on a Steam Deck, in the driver. vertex_bind_range
gives the bindings that differ from what this command buffer has, and only those are bound. RX_VK_VB_RANGE=0: all 16.

Cuts vertex_bind_range out of the source and runs it; checks draw() binds its range and still remembers all 16. A
partial bind is right only while the 16 remembered (last_vb) are what the command buffer has, strides included, so it also
checks the places that could change that: draw()'s is the only vertex bind of the renderer; a graphics pipeline of the
host's (the masked clear) and every temporal_upscale call (its actor pass binds one) clear last_vb_valid, and graphics
pipelines are bound in vk_draw.cpp and vk_temporal.cpp only; a static-stride (fallback) pipeline clears it; a new
recording (begin_recording, each parallel segment's worker) clears it; no secondary command buffers.
From Hookshot 33ed7b81a / HeyListen 28623fcf (tests/test_vertex_bind_range.py), adapted to our tree.

python -I -B tests/test_vertex_bind_range.py [--cxx clang++]
"""
import argparse
import re
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def need(cond, why):
    if not cond:
        raise SystemExit("FAIL: " + why)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="clang++")
    a = p.parse_args()
    source = (VK / "vk_draw.cpp").read_text(encoding="utf-8")
    draw = block(source, "void draw(VkCommandBuffer cmd, NvnState& s, const DrawArgs& d)")
    ask = "vertex_bind_range(vbufs, voffs, vsizes, vstrides, last_vb.b, last_vb.o, last_vb.z, last_vb.s, last_vb_valid, &vb_first, &vb_count);"
    bind = "vkCmdBindVertexBuffers2(cmd, vb_first, vb_count, vbufs + vb_first, voffs + vb_first, vsizes + vb_first, vstrides + vb_first);"
    for needle in (ask, bind, 'const char* e = getenv("RX_VK_VB_RANGE"); return !(e && env_value_off(e));',
                   "if (vb_count && !vb_range) vb_first = 0, vb_count = 16;"):
        need(needle in draw, "draw() no longer has: " + needle)
    need(draw.index(ask) < draw.index(bind) < draw.index("std::memcpy(last_vb.b, vbufs, sizeof vbufs)"),
         "draw() binds before it asks for the range, or remembers the streams before it binds them")
    for needle in ("std::memcpy(last_vb.b, vbufs, sizeof vbufs), std::memcpy(last_vb.o, voffs, sizeof voffs);",
                   "std::memcpy(last_vb.z, vsizes, sizeof vsizes), std::memcpy(last_vb.s, vstrides, sizeof vstrides);"):
        need(needle in draw, "draw() no longer remembers all 16 bindings after a bind: " + needle)
    # (the renderer's own sources: draw()'s range is the only vertex bind, and nothing executes secondary command buffers)
    own = {f.name: f.read_text(encoding="utf-8", errors="replace") for f in sorted(VK.glob("*.cpp"))}
    for name, text in own.items():
        for m in re.finditer(r"vkCmdBindVertexBuffers2?\(", text):
            need(name == "vk_draw.cpp" and text.startswith(bind, m.start()),
                 "a vertex bind last_vb does not know of: %s: %s" % (name, text[m.start():text.index("\n", m.start())].strip()))
        need("vkCmdExecuteCommands(" not in text, name + " executes a secondary command buffer: its bindings are not last_vb's")
        if "VK_PIPELINE_BIND_POINT_GRAPHICS," in text:
            need(name in ("vk_draw.cpp", "vk_temporal.cpp"),
                 name + " binds a graphics pipeline: if on a replay command buffer, the next draw must bind all 16 again")
    # (a graphics pipeline of the host's, bound on the replay's command buffer, sets the strides from itself: the next draw
    # binds all 16 again. draw()'s own, a game program's pipeline, clears it when its strides are static (the fallback))
    for m in re.finditer(r"vkCmdBindPipeline\(cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, (\w+)\)", source):
        line = source[m.start():source.index("\n", m.start())]
        if "last_pipeline = " in line:
            after = source[m.end():m.end() + 400]
            need("if (p.fallback) {" in after and "last_vb_valid = false;" in after,
                 "a static-stride (fallback) pipeline is bound without clearing last_vb_valid")
            continue
        need("last_vb_valid = false" in source[m.end():m.end() + 300],
             "a host graphics pipeline is bound without clearing last_vb_valid: " + line.strip())
    # (vk_temporal.cpp's graphics pipeline: the actor motion pass, run by temporal_upscale only, which only vk_draw.cpp calls)
    temporal = own["vk_temporal.cpp"]
    actor = block(temporal, "int actor_motion(VkCommandBuffer cmd,")
    need(temporal.count("vkCmdBindPipeline(cmd, VK_PIPELINE_BIND_POINT_GRAPHICS,") == actor.count("vkCmdBindPipeline(cmd, VK_PIPELINE_BIND_POINT_GRAPHICS,") == 1,
         "vk_temporal.cpp binds a graphics pipeline outside its actor motion pass")
    need(len(re.findall(r"\bactor_motion\(", temporal)) == 2 and
         "actor_motion(cmd" in block(temporal, "bool temporal_upscale(VkCommandBuffer cmd,"),
         "the actor motion pass runs from somewhere other than temporal_upscale")
    for name, text in own.items():
        need(name in ("vk_draw.cpp", "vk_temporal.cpp") or not re.search(r"\btemporal_upscale\(", text),
             name + " runs the temporal passes: the draws after them must bind all 16 again")
    calls = list(re.finditer(r"temporal_upscale\(cmd", source))
    need(len(calls) >= 2, "the temporal passes' calls in vk_draw.cpp are not where this check looks")
    for m in calls:
        need("last_vb_valid = false" in source[m.end():m.end() + 400],
             "a temporal pass (its actor binds a graphics pipeline) is followed by a draw that trusts last_vb")
    need("last_vb_valid = false" in block(source, "void draw_begin_recording("), "a new recording keeps the last one's vertex bindings")
    replay = own["vk_replay.cpp"]
    need("draw_begin_recording(r.slot, r.cmd, value);" in block(replay, "Recording& begin_recording(uint64_t value) {"),
         "a recording begins without draw_begin_recording")
    job = replay[replay.index("draw_begin_recording(j->r->slot, j->r->cmd, j->r->value);"):]
    need(job.index("draw_begin_recording(") < job.index("record_segment(c, j->g);"),
         "a parallel segment is recorded before its worker clears what it last bound")
    fn = block(source, "void vertex_bind_range(")
    fixture = f'''#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
using VkBuffer = uint64_t;
using VkDeviceSize = uint64_t;
#define CHECK(x) do {{ if (!(x)) {{ std::fprintf(stderr, "FAIL:%d %s\\n", __LINE__, #x); std::exit(1); }} }} while (0)
{fn}
int main() {{
    VkBuffer b[16], lb[16];
    VkDeviceSize o[16], z[16], s[16], lo[16], lz[16], ls[16];
    for (int i = 0; i < 16; i++) b[i] = lb[i] = 100 + i, o[i] = lo[i] = 8 * i, z[i] = lz[i] = 65536, s[i] = ls[i] = 12;
    uint32_t first = 99, count = 99;
    vertex_bind_range(b, o, z, s, lb, lo, lz, ls, false, &first, &count);   // (nothing bound on this command buffer yet)
    CHECK(first == 0 && count == 16);
    vertex_bind_range(b, o, z, s, lb, lo, lz, ls, true, &first, &count);    // (the same 16: nothing to bind)
    CHECK(count == 0);
    b[3] = 7;                                                               // (one stream's buffer)
    vertex_bind_range(b, o, z, s, lb, lo, lz, ls, true, &first, &count);
    CHECK(first == 3 && count == 1);
    o[9] = 4096;                                                            // (and another's offset: the range over both)
    vertex_bind_range(b, o, z, s, lb, lo, lz, ls, true, &first, &count);
    CHECK(first == 3 && count == 7);
    b[3] = lb[3], o[9] = lo[9], s[0] = 16;                                  // (a stride alone, the first binding)
    vertex_bind_range(b, o, z, s, lb, lo, lz, ls, true, &first, &count);
    CHECK(first == 0 && count == 1);
    s[0] = ls[0], z[15] = 1;                                                // (a size alone, the last binding)
    vertex_bind_range(b, o, z, s, lb, lo, lz, ls, true, &first, &count);
    CHECK(first == 15 && count == 1);
    b[0] = 1;                                                               // (the first and the last: all 16)
    vertex_bind_range(b, o, z, s, lb, lo, lz, ls, true, &first, &count);
    CHECK(first == 0 && count == 16);
    // (over which bindings changed: the range covers every changed one, and binding it over what was bound gives the new 16)
    for (uint32_t mask = 0; mask < (1u << 16); mask += 37) {{
        for (int i = 0; i < 16; i++) b[i] = lb[i], o[i] = lo[i], z[i] = lz[i], s[i] = ls[i];
        for (int i = 0; i < 16; i++)
            if (mask >> i & 1) o[i] += 64;
        vertex_bind_range(b, o, z, s, lb, lo, lz, ls, true, &first, &count);
        VkDeviceSize bound[16];
        for (int i = 0; i < 16; i++) bound[i] = lo[i];
        for (uint32_t i = first; i < first + count; i++) bound[i] = o[i];
        CHECK(first + count <= 16);
        CHECK(std::memcmp(bound, o, sizeof bound) == 0);
        CHECK((count == 0) == (mask == 0));
    }}
    std::puts("vertex bind range: ok");
    return 0;
}}
'''
    with tempfile.TemporaryDirectory(prefix="vertex-bind-range-") as tmp:
        cpp, exe = Path(tmp) / "t.cpp", Path(tmp) / "t.exe"
        cpp.write_text(fixture, encoding="utf-8")
        subprocess.run([a.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", str(cpp), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    print("PASS: a draw binds the vertex bindings that changed; every other bind clears what it remembers")


if __name__ == "__main__":
    main()
