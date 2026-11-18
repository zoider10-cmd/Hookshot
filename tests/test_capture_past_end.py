# SPDX-License-Identifier: GPL-3.0-or-later
"""A word past a program's end that reads as a branch outside it ends the capture there, and a program over 1 MiB translates.

parse_code (gpu/vk/vk_shader.cpp) reads an NVN2 stage's Ampere instructions until ProgramCaptureState says the program
ended. Its end rules are narrower than the lowering's: a loop left only by predicated EXITs ends at its closing branch to
itself, which the lowering takes as the end and the capture does not, so the capture read on past the end. A word there
that decodes as a branch to before the start, between two instructions or past the largest program refused the whole
program ("the branch at instruction N (+X) goes outside the program"). Now the capture ends before that word, and the
program is refused for it only if the code before it does not lower.

The largest program was 65,536 instructions (1 MiB) in the capture, the lowering and the native address map. Compute
program 79116b290d46542f has 0x104680 bytes of code, and its branch at instruction 16404 goes to past 1 MiB: refused on
every platform. The GPU has no such limit (a 32-bit program offset; an Ampere BRA's offset has 50 bits), so the limit is
now the largest code area the renderer reads, 16 MiB. A lowered branch past the 8 MiB reach of Maxwell's BRA, CAL and BRX
takes their absolute forms, JMP, JCAL and JMX.

Compiled from the real source: vk_shader.cpp's hash_bytes, Code, code_key and parse_code, with the recompiler's headers,
over packages (control section and code area) built here:
- a loop left by predicated EXITs, its closing branch to itself, padding, then a word that reads as a branch outside
  every program: a BRA between two instructions (at instruction 16404, +0x40140), 16 MiB or more on or before the
  start, a BSSY before the start, a CALL between two instructions; the same in a graphics stage, after its 128-byte
  header. Each translates, to the same Maxwell code as the program without what follows it, with one line in the log
  for it however often it is read;
- a program that branches over such a word to code after it: still refused, the message naming the word as before;
- programs the capture ends itself, or that reach the code's end: unchanged;
- a program of 0x104680 bytes whose @P0 BRA at instruction 16404 goes to its EXIT, past 1 MiB, and back: it translates,
  each branch lands on its target, and the address map finds both;
- 12.8 MB programs whose branches and call are more than 8 MiB of lowered code apart: JMP and JCAL, each holding its
  target's address, the predicate kept.
Then the three other copies of the capture loop (the bake tools, shadertool) end before the word too, not at it.

python -I -B tests/test_capture_past_end.py [--cxx clang++] [--source <checkout>]
"""
import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]


def block(text, marker):
    """The function or block that starts at marker, through its closing brace"""
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def statement(text, marker):
    """The declaration that starts at marker, through its semicolon"""
    start = text.index(marker)
    return text[start:text.index(";", start) + 1]


CODE = r"""
#include <atomic>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <string>
#include <unordered_set>
#include <vector>
#include "shader_recompiler/frontend/ampere/lower_to_maxwell.h"
#include "shader_recompiler/frontend/ampere/program_address_map.h"
#include "shader_recompiler/frontend/ampere/program_capture.h"
#include "shader_recompiler/program_header.h"

static std::vector<std::string> logged;
void logf(const char* fmt, ...) {
    char line[1024];
    va_list ap;
    va_start(ap, fmt);
    std::vsnprintf(line, sizeof line, fmt, ap);
    va_end(ap);
    logged.push_back(line);
}
struct { bool native_mma = false; } dev;

@CONSTANTS@
@HASH_BYTES@
@CODE@
@CODE_KEY@
Code parse_code(const uint8_t* ctl, const std::vector<uint8_t>& area);
@PARSE_CODE@

using Shader::Ampere::Instruction;
static Instruction insn(uint32_t a, uint32_t b, uint32_t c, uint32_t d) {
    Instruction i{};
    i.words[0] = a, i.words[1] = b, i.words[2] = c, i.words[3] = d;
    return i;
}
static const Instruction exit_p0 = insn(0x0000094d, 0, 0x03800000, 0x000fea00);   // @P0 EXIT
static const Instruction exit_pt = insn(0x0000794d, 0, 0x03800000, 0x000fea00);   // EXIT
static const Instruction nop = insn(0x00007918, 0, 0, 0x000fc000);
// a branch-class word (BRA 0x947, CALL.REL 0x944: 50-bit offset at bit 32; BSSY 0x945: 32-bit) at instruction `at`
// whose offset in bytes from the next instruction is `rel`
static Instruction branch(uint32_t op, int64_t rel, uint32_t predicate = 7) {
    const uint64_t r = static_cast<uint64_t>(rel);
    return insn(op | (predicate << 12), static_cast<uint32_t>(r), 0x03800000 | static_cast<uint32_t>((r >> 32) & 0x3ffff),
                0x000fea00);
}
static Instruction bra(int64_t at, int64_t to, uint32_t predicate = 7) { return branch(0x947, to * 16 - (at * 16 + 16), predicate); }

struct Package { std::vector<uint8_t> ctl, area; };
// A stage's package as the game's memory holds it: the control section (magic, code length +0x38, c1 at +0x40..+0x44,
// stage +0x56, a compute stage's workgroup +0x58) and the code area: a graphics stage's 128-byte header, the
// instructions, then 64 bytes of c1 constants
static Package package(uint16_t stage, const std::vector<Instruction>& code) {
    Package p;
    const uint32_t hdr = stage == 5 ? 0 : kAmpereHeader;
    p.area.assign(hdr, 0);
    if (hdr) p.area[1] = 5 << 2;   // (common0.shader_type 5, a pixel program: bits 10..14)
    for (const Instruction& i : code) {
        const uint8_t* b = reinterpret_cast<const uint8_t*>(&i);
        p.area.insert(p.area.end(), b, b + sizeof i);
    }
    const uint32_t len = static_cast<uint32_t>(p.area.size());
    for (uint32_t k = 0; k < 64; k++) p.area.push_back(static_cast<uint8_t>(0x40 + k));
    const uint32_t end = static_cast<uint32_t>(p.area.size()), one = 1;
    p.ctl.assign(kControlSize, 0);
    std::memcpy(p.ctl.data(), &kControlMagic, 4);
    std::memcpy(p.ctl.data() + 0x38, &len, 4);
    std::memcpy(p.ctl.data() + 0x40, &len, 4);
    std::memcpy(p.ctl.data() + 0x44, &end, 4);
    std::memcpy(p.ctl.data() + 0x56, &stage, 2);
    if (stage == 5) for (int k = 0; k < 3; k++) std::memcpy(p.ctl.data() + 0x58 + 4 * k, &one, 4);
    return p;
}
static Code parse(const Package& p) { return parse_code(p.ctl.data(), p.area); }

static int failures = 0;
static void check(bool ok, const char* what, const std::string& got = "") {
    std::printf("%s: %s%s%s\n", ok ? "PASS" : "FAIL", what, got.empty() ? "" : ": got ", got.c_str());
    failures += !ok;
}
static size_t lines_with(const std::string& text) {
    size_t n = 0;
    for (const std::string& l : logged) n += l.find(text) != std::string::npos;
    return n;
}
// the first Maxwell word native instruction `at` lowered to, and its address, through the program's native address map
static bool lowered_at(const Code& c, uint32_t at, uint32_t* address, uint64_t* word) {
    const auto a = Shader::Ampere::NativeProgramAddress(c.code, at * 16);
    if (!a || *a / 8 >= c.code.size()) return false;
    *address = *a, *word = c.code[*a / 8];
    return true;
}
// native instruction `at` lowered to opcode `op` (BRA 0xe24) with predicate `pred`, whose 24-bit offset (bits 20-43)
// lands on what native instruction `to` lowered to
static bool near(const Code& c, uint32_t at, uint32_t to, uint64_t op, uint32_t pred) {
    uint32_t from = 0, target = 0;
    uint64_t word = 0, unused = 0;
    if (!lowered_at(c, at, &from, &word) || !lowered_at(c, to, &target, &unused)) return false;
    const int64_t relative = static_cast<int64_t>(word << 20) >> 40;
    return (word >> 52) == op && ((word >> 16) & 15) == pred && relative == int64_t{target} - from - 8;
}
// the same with an absolute form (JMP 0xe21, JCAL 0xe22): the target's address in bits 20-51, the flow test kept, and
// the target out of a 24-bit offset's reach
static bool far(const Code& c, uint32_t at, uint32_t to, uint64_t op, uint32_t pred) {
    uint32_t from = 0, target = 0;
    uint64_t word = 0, unused = 0;
    if (!lowered_at(c, at, &from, &word) || !lowered_at(c, to, &target, &unused)) return false;
    const int64_t distance = int64_t{target} - from - 8;
    return (word >> 52) == op && ((word >> 16) & 15) == pred && ((word >> 20) & 0xffffffffu) == target &&
           (word & 0x1f) == 0xf && (distance > 0x7fffff || distance < -0x800000);
}

int main() {
    // the program: a loop that leaves only by @P0 EXIT, its jump back and NVIDIA's closing branch to itself
    const std::vector<Instruction> loop{exit_p0, bra(1, 0), bra(2, 2)};
    struct Word { const char* name; uint32_t at; Instruction word; };
    const Word words[] = {
        {"a BRA between two instructions", 16404, branch(0x947, 8)},
        {"a BRA 16 MiB or more on", 7, branch(0x947, 16 << 20)},
        {"a BRA to before the start", 7, branch(0x947, -0x100)},
        {"a BSSY to before the start", 9, branch(0x945, -0x200)},
        {"a CALL between two instructions", 5, branch(0x944, 4)},
    };
    for (const uint16_t stage : {uint16_t{5}, uint16_t{1}}) {
        const Code clean = parse(package(stage, loop));
        check(clean.ok, stage == 5 ? "compute: the loop alone translates" : "graphics: the loop alone translates", clean.why);
        for (const Word& w : words) {
            if (stage != 5 && w.at > 64) continue;
            std::vector<Instruction> code = loop;
            while (code.size() < w.at) code.push_back(nop);
            code.push_back(w.word);
            for (int k = 0; k < 3; k++) code.push_back(nop);
            const Package p = package(stage, code);
            const size_t before = logged.size();
            const Code c = parse(p);
            const std::string what = std::string(stage == 5 ? "compute" : "graphics") + ", " + w.name + " at instruction " +
                                     std::to_string(w.at) + " after the end";
            check(c.ok && c.why.empty(), (what + ": translates").c_str(), c.why);
            check(c.code == clean.code && c.c1 == clean.c1 && c.texture_bound == clean.texture_bound,
                  (what + ": the same code as the program alone").c_str());
            char line[160];
            std::snprintf(line, sizeof line, "vk: NVN2 program %016llx (stage %u) ends at +0x30, before the word at +%#x "
                          "that would branch outside it", (unsigned long long)c.key, stage, w.at * 16);
            parse(p);
            check(logged.size() == before + 1 && lines_with(line) == 1, (what + ": one log line, read twice").c_str(),
                  logged.size() > before ? logged.back() : std::string("no line"));
        }
    }
    {   // the code goes on after the word: a branch over it to an EXIT after it. Still refused, naming the word
        const Code c = parse(package(5, {exit_p0, bra(1, 4), branch(0x947, 8), nop, exit_pt}));
        const std::string want = "the branch at instruction 2 (+0x20) goes outside the program";
        check(!c.ok && c.why.compare(0, want.size(), want) == 0, "a program that goes on past the word: refused for it", c.why);
    }
    {   // programs that parse as before: ended by the capture before the word, or reaching the code's end
        const size_t before = logged.size();
        const Code ended = parse(package(5, {exit_pt, nop, branch(0x947, 8), nop}));
        const Code alone = parse(package(5, {exit_pt}));
        check(ended.ok && ended.code == alone.code, "an EXIT the capture ends at: the word after it is never read", ended.why);
        const Code reach = parse(package(5, {exit_p0, bra(1, 0), bra(2, 2), nop, nop}));
        check(reach.ok && reach.code == parse(package(5, loop)).code, "a loop padded to the code's end: as before", reach.why);
        check(logged.size() == before, "no log line for them", logged.size() > before ? logged.back() : std::string());
    }
    {   // a program over 1 MiB: 79116b29's size, a @P0 BRA at instruction 16404 to the EXIT at its end, a @P1 BRA back
        const uint32_t n = 0x104680 / 16;
        std::vector<Instruction> code(n, nop);
        code[16404] = bra(16404, n - 2, 0);
        code[n - 3] = bra(n - 3, 1, 1);
        code[n - 2] = exit_pt;
        const Code c = parse(package(5, code));
        check(c.ok, "0x104680 bytes, a branch at instruction 16404 to past 1 MiB: translates", c.why);
        check(near(c, 16404, n - 2, 0xe24, 0) && near(c, n - 3, 1, 0xe24, 1),
              "0x104680 bytes: each BRA lands on its target, the address map finds both ends");
    }
    {   // more than 8 MiB of lowered code between a branch and its target: JMP (and back)
        const uint32_t n = 800000;
        std::vector<Instruction> code(n, nop);
        code[0] = bra(0, n - 2, 0);
        code[n - 3] = bra(n - 3, 1, 1);
        code[n - 2] = exit_pt;
        const Code c = parse(package(5, code));
        check(c.ok, "12.8 MB, branches more than 8 MiB of lowered code apart: translates", c.why);
        check(far(c, 0, n - 2, 0xe21, 0) && far(c, n - 3, 1, 0xe21, 1), "12.8 MB: each branch is a JMP to its target");
    }
    {   // and a call: MOV R10, its return address; CALL.REL.NOINC to a function at the end; EXIT; the function's RET R10
        const uint32_t n = 800000, f = n - 2;
        std::vector<Instruction> code(n, nop);
        code[0] = insn(0x00007802 | (10u << 16), 2 * 16, 0xf00, 0x000fe200);
        const uint64_t to_f = static_cast<uint64_t>(int64_t{f} * 16 - 2 * 16), back = static_cast<uint64_t>(-(int64_t{f} + 1) * 16);
        code[1] = insn(0x00007944, static_cast<uint32_t>(to_f), 0x03c00000 | static_cast<uint32_t>((to_f >> 32) & 0x3ffff), 0x000fea00);
        code[2] = exit_pt;
        code[f] = insn(0x0a007950, static_cast<uint32_t>(back), 0x03c00000 | static_cast<uint32_t>((back >> 32) & 0x3ffff), 0x000fea00);
        const Code c = parse(package(5, code));
        check(c.ok, "12.8 MB, a call more than 8 MiB of lowered code away: translates", c.why);
        check(far(c, 1, f, 0xe22, 7), "12.8 MB: the call is a JCAL to the function");
    }
    std::printf(failures ? "FAIL: %d checks\n" : "PASS: a word past the program's end that reads as a branch outside it "
                "ends the capture; programs over 1 MiB translate\n", failures);
    return failures ? 1 : 0;
}
"""

CALLERS = ("gpu/shaderbatch.cpp", "nx2/bake_ds/bake_ds.cpp", "gpu/shadertool.cpp", "gpu/vk/vk_shader.cpp")


def callers(root):
    """Every capture loop ends before the word (drops it and stops) instead of refusing the program at it"""
    bad = []
    for name in CALLERS:
        text = (root / name).read_text(encoding="utf-8")
        at = text.find("Result::InvalidTarget")
        if at < 0:
            bad.append(name + ": no capture loop")
            continue
        after = text[at:text.index("Result::Complete", at)]
        if "native.pop_back();" not in after or "break;" not in after or "return" in after or "throw" in after:
            bad.append(name + ": the capture refuses the program at the word")
    return bad


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--cxx", default=shutil.which("clang++") and "clang++" or "g++")
    p.add_argument("--source", type=Path, default=ROOT, help="the checkout whose source is tested (default this one)")
    a = p.parse_args()
    root = a.source.resolve()
    shader = (root / "gpu/vk/vk_shader.cpp").read_text(encoding="utf-8")
    parts = {
        "@CONSTANTS@": "\n".join(statement(shader, "constexpr uint32_t " + k)
                                 for k in ("kControlMagic", "kControlSize", "kAmpereHeader")),
        "@HASH_BYTES@": block(shader, "uint64_t hash_bytes("),
        "@CODE@": block(shader, "struct Code {") + ";",
        "@CODE_KEY@": block(shader, "uint64_t code_key("),
        "@PARSE_CODE@": block(shader, "Code parse_code(const uint8_t* ctl, const std::vector<uint8_t>& area) {"),
    }
    code = CODE
    for name, text in parts.items():
        code = code.replace(name, text)
    with tempfile.TemporaryDirectory(prefix="capture-past-end-") as tmp:
        src, exe = Path(tmp) / "fixture.cpp", Path(tmp) / ("fixture.exe" if sys.platform == "win32" else "fixture")
        src.write_text(code, encoding="utf-8")
        subprocess.run([a.cxx, "-std=c++20", "-O1", "-Wno-everything" if "clang" in a.cxx else "-w",
                        "-I" + str(root / "gpu" / "vk" / "eden"), "-I" + str(root / "gpu" / "vk" / "compat"),
                        str(src), "-o", str(exe)], check=True, timeout=300)
        run = subprocess.run([str(exe)], timeout=120)
    bad = callers(root)
    for b in bad:
        print("FAIL: " + b)
    if run.returncode or bad:
        raise SystemExit("FAIL: a word past the program's end that reads as a branch outside it")
    print("PASS: every capture loop ends before such a word")


if __name__ == "__main__":
    main()
