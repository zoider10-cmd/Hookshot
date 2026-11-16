"""The parallel replay's gate (gpu/vk/vk_replay.cpp, RX_VK_PARALLEL; the idea is Project ReLink's): a command buffer goes
to the threads only when the one at its place in the last frame had RX_VK_PARALLEL_MIN draws and dispatches (default
700), one that ran OoT's exposure programs stays on the replay thread for 600 frames, and the dry pass makes the render
targets. Source checks plus a compiled check of the gate's history, no game or GPU required.

Ungated, every command buffer of 320 draws and more went to the threads: in the Market by day (RX 9070 XT, 9800X3D) that
was 56.5 and 59.6 fps on 3 threads against 74.2 on the replay thread alone, the threads waiting on their lock.

python -I -B tests/test_parallel_gate.py [--cxx g++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]


def body(text, start, end):
    i = text.index(start)
    return text[i:text.index(end, i)]


def block(text, marker):
    """From marker to the brace closing its first one"""
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="g++")
    a = p.parse_args()
    vk = ROOT / "gpu" / "vk"
    replay = (vk / "vk_replay.cpp").read_text(encoding="utf-8")
    draw = (vk / "vk_draw.cpp").read_text(encoding="utf-8")
    internal = (vk / "vk_internal.h").read_text(encoding="utf-8")

    # (off unless RX_VK_PARALLEL asks: the gate does not turn it on)
    threads = block(replay, "int par_threads()")
    if 'getenv("RX_VK_PARALLEL") ? atoi(getenv("RX_VK_PARALLEL")) : 0' not in threads:
        raise SystemExit("vk_replay.cpp: par_threads is no longer off unless RX_VK_PARALLEL is set")
    if 'getenv("RX_VK_PARALLEL_MIN")' not in block(replay, "int64_t par_min_work()") or ": 700;" not in block(replay, "int64_t par_min_work()"):
        raise SystemExit("vk_replay.cpp: the gate's RX_VK_PARALLEL_MIN (default 700) is gone")
    for switch in ("RX_VK_PARALLEL_EXPOSURE", "RX_VK_NO_DRY_RTS"):
        if f'env_on("{switch}")' not in replay:
            raise SystemExit(f"vk_replay.cpp: the switch {switch} is gone")

    # (the gate is decided before the dry pass, after the serial path's own cases, and a small one is replayed and noted)
    handle = block(replay, "const uint8_t* replay_handle(")
    off = handle.index("if (threads < 2 || !rec_cur")
    gate = handle.index("par_gate.big(place, frame, par_min_work(), exposure_serial)")
    dry = handle.index("rmode = Mode::Dry;")
    if not off < gate < dry:
        raise SystemExit("vk_replay.cpp: the gate is not decided between the serial cases and the dry pass")
    small = body(handle, "if (!par_gate.big(", "return suspend_at;")
    for need in ("replay(cmd, state, h);", "serial_work - w0", "replay_saw_exposure.store(false",
                 "par_gate.note(place, frame,"):
        if need not in small:
            raise SystemExit("vk_replay.cpp: a small command buffer is not replayed and noted as the gate needs: " + need)
    if "par_gate.note(place, frame, total, false);" not in handle:
        raise SystemExit("vk_replay.cpp: a command buffer in segments does not note its dry pass's work")
    if "struct ExposureNote" not in handle:
        raise SystemExit("vk_replay.cpp: the exposure programs a command buffer in segments ran are not noted")
    if "serial_work++;" not in body(replay, "if (op_is_work(h.op)) {", "p += h.size;"):
        raise SystemExit("vk_replay.cpp: the replay thread's work is not counted")

    # (dispatch() flags OoT's exposure programs, on any thread)
    if "exposure_program(cp->key)) replay_saw_exposure.store(true" not in block(draw, "void dispatch("):
        raise SystemExit("vk_draw.cpp: dispatch() no longer flags OoT's exposure programs")
    if "extern std::atomic<bool> replay_saw_exposure;" not in internal:
        raise SystemExit("vk_internal.h: replay_saw_exposure is not shared by the threads")
    expo = block(internal, "inline bool exposure_program(uint64_t key)")
    for key in ("0x6ccba775ea111ee9ull", "0x499dbfd0721d2858ull", "0xab7699ee7f536755ull"):
        if key not in expo:
            raise SystemExit("vk_internal.h: exposure_program no longer knows " + key)

    # (the dry pass makes the render targets)
    rt = body(replay, "case NOP_SET_RT:", "break;\n        case NOP_VIEWPORTS")
    if "if (dry && dry_rts_on())" not in rt or "texture_get(s.rt.color[i], false)" not in rt or "texture_get(s.rt.depth, false)" not in rt:
        raise SystemExit("vk_replay.cpp: the dry pass no longer makes NOP_SET_RT's render targets")

    gate_src = block(replay, "struct ParGate {")
    fixture = f'''#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <vector>
#define CHECK(x) do {{ if (!(x)) {{ std::fprintf(stderr, "FAIL:%d %s\\n", __LINE__, #x); std::exit(1); }} }} while (0)
{gate_src};
int main() {{
    ParGate g;
    // frame 10: three buffers, never seen: none goes to the threads
    for (int i = 0; i < 3; i++) {{
        const size_t at = g.next(10);
        CHECK(at == (size_t)i);
        CHECK(!g.big(at, 10, 700, true));
    }}
    g.note(0, 10, 120, false), g.note(1, 10, 2400, false), g.note(2, 10, 900, true);
    // frame 11: the big one goes; the one that ran the exposure programs stays; a fourth, new, stays
    size_t at = g.next(11);
    CHECK(at == 0 && !g.big(at, 11, 700, true));
    at = g.next(11);
    CHECK(at == 1 && g.big(at, 11, 700, true));
    CHECK(!g.big(at, 11, 3000, true));   // (RX_VK_PARALLEL_MIN)
    at = g.next(11);
    CHECK(at == 2 && !g.big(at, 11, 700, true));
    CHECK(g.big(at, 11, 700, false));    // (RX_VK_PARALLEL_EXPOSURE=1)
    at = g.next(11);
    CHECK(at == 3 && !g.big(at, 11, 700, true));
    // a buffer that shrank: back on the replay thread the frame after
    g.note(1, 11, 300, false);
    g.next(12);
    CHECK(!g.big(g.next(12), 12, 700, true));
    // the exposure: 600 frames from the last one it ran them in, then out; seen again (on the threads too), back
    CHECK(!g.big(2, 10 + 599, 700, true));
    CHECK(g.big(2, 10 + 600, 700, true));
    g.note(2, 700, 900, true);
    CHECK(!g.big(2, 701, 700, true));
    // frame 0 is a frame like any other (the history's "never" is not frame 0)
    ParGate z;
    CHECK(z.next(0) == 0);
    z.note(0, 0, 800, false);
    CHECK(z.big(0, 1, 700, true));
    z.note(0, 0, 800, true);
    CHECK(!z.big(0, 1, 700, true));
    std::printf("PASS: the parallel replay's gate goes by the last frame's buffer at the same place\\n");
}}
'''
    with tempfile.TemporaryDirectory(prefix="parallel-gate-") as tmp:
        cpp = Path(tmp) / "fixture.cpp"
        exe = Path(tmp) / "fixture"
        cpp.write_text(fixture, encoding="utf-8")
        subprocess.run([a.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", str(cpp), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
