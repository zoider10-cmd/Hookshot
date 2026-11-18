"""The Frame generation by row: DLSS FG, FSR 3.1 FG or Built-in FG, no Auto (gpu/vk/vk_menu.cpp, vk_dlss.cpp), game-free.

Its Auto named who made the last frames ("Auto: Built-in FG"), and the game's own menus (the title screen, the file select)
give DLSS Frame Generation no Upscaler picture to make frames from, so the built-in one made theirs: a player who opened the
Insert menu there read that Auto had picked the built-in one, with DLSS FG nowhere in the row's choices. Now the row names
the choice itself: DLSS FG, offered only where it runs (NGX asked once a run, before a present needs it: dlss_fg_probe),
and Built-in FG; then (#1103) FSR 3.1 FG, AMD FSR 3.1's frame interpolation, as 2 so an options file's 1 stays Built-in
FG. Where DLSS FG cannot run, the row has FSR 3.1 FG (0, the default; a 2 the same) and Built-in FG, and its line at FSR
3.1 FG says why not DLSS FG. At DLSS FG on a temporal
Upscaler, a set with no picture from it (the game's own menus, movies, loading screens) is the game's frame alone, not the
built-in one's (dlss_fg_holds; tests/present_source_crop_test.cpp runs framegen_record so), and the row's line and the FPS
counter say DLSS FG is paused.

Checked here, with the menu's own functions compiled (tx_framegen_by, hn_framegen_by, framegen_skip_text, dlss_why_text,
framegen_maker_name, the options file's loading loop and ini_key) and vk_dlss.cpp's fg_asked and dlss_fg_holds:
- the row has three choices, DLSS FG (0, the default), Built-in FG (1) and FSR 3.1 FG (2), and no value reads Auto;
- an options file's frame_generation_by=0 from before (Auto) loads as the default: DLSS FG, DLSS-G asked for, where it
  runs; FSR 3.1 FG where it does not; 1 stays Built-in FG, 2 FSR 3.1 FG; a hand-edited value out of range is clamped;
- where DLSS FG cannot run, its line at FSR 3.1 FG says why, DLSS's own reason when DLSS does not run, and at Built-in FG
  is Built-in FG's own; with RX_VK_DLSS_FG=1 it is fixed at DLSS FG (row_fixed) and says the switch chooses;
- at DLSS FG: the line says why another makes the frames, and that DLSS FG is paused where the sets are the game's alone;
- the sets are the game's alone only at DLSS FG, on a temporal Upscaler, for a set without its picture;
- every line the row can show is among the variants measure_help makes room for;
- NGX is asked at the start-up screen and when the menu opens, and fg_start tells the menu's thread once it has answered;
- every translation table has the new texts.

    python -I -B tests/test_framegen_by_row.py --cxx clang++
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # (python -I leaves the check's own folder off the path)
from srccut import block  # noqa: E402

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"


def fail(why):
    raise SystemExit("FAIL: " + why)


def found(pattern, text, why, flags=re.S):
    m = re.search(pattern, text, flags)
    if not m:
        fail(why)
    return m.group(0)


FIXTURE = r"""
#include <algorithm>
#include <atomic>
#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <set>
#include <string>
/* OPTIONS */
Options opts;
/* FGSKIP */
/* DLSSWHY */
/* FGMAKER */
int unavailable = FG_SKIP_NONE;   // (vk_dlss.cpp dlss_fg_unavailable's answer for this "run")
DlssWhy why_dlss = DLSS_OK;       // (dlss_why: DLSS's own reason)
bool forced = false;              // (dlss_fg_forced: RX_VK_DLSS_FG=1)
FgMaker maker = FgMaker::None;    // (who made the last frames: vk_framegen.cpp framegen_maker)
int skip_now = FG_SKIP_NONE;      // (why DLSS-G did not make the last set: dlss_fg_skip)
bool temporal_on = true;          // (vk_temporal.cpp temporal_wanted: a temporal Upscaler runs)
bool scene_now = false;           // (vk_temporal.cpp temporal_scene_now: the game asked for its gameplay upscale just now)
std::atomic<int> fg_skip{FG_SKIP_NONE};
int dlss_fg_unavailable() { return unavailable; }
DlssWhy dlss_why() { return why_dlss; }
bool dlss_fg_forced() { return forced; }
FgMaker framegen_maker() { return maker; }
bool temporal_wanted() { return temporal_on; }
bool temporal_scene_now() { return scene_now; }
int dlss_fg_skip(unsigned* most) {
    if (most) *most = 1;
    return skip_now;
}
/* ENV */
/* POSSIBLE */
/* ASKED */
/* HOLDS */
/* TABS */
/* ROW */
/* OFFERED */
/* FIXED */
/* WHYTEXT */
/* SKIPTEXT */
/* MAKERNAME */
/* TEXT */
/* HINT */
Row rows[] = {
/* ROWLINE */
};
int monitor_pick; // Fullscreen selection is not exercised by this frame-generation fixture.
/* INIKEY */
int parse_output(const char*) { return 0; }
void load(const char* text) {   // (one line of hookshot_options.ini, through the menu's own loop)
    char line[80];
    std::snprintf(line, sizeof line, "%s", text);
    char* eq = std::strchr(line, '=');
    *eq = 0;
/* LOOP */
}
int failures = 0;
#define CHECK(x, why) do { if (!(x)) { ++failures; std::fprintf(stderr, "FAIL %d: %s (%s)\n", __LINE__, why, #x); } } while (0)
bool starts(const char* s, const char* with) { return s && !std::strncmp(s, with, std::strlen(with)); }
void reset_run() { unavailable = FG_SKIP_NONE, why_dlss = DLSS_OK, forced = false, maker = FgMaker::None, skip_now = FG_SKIP_NONE; }
int main() {
    const Row& r = rows[0];
    CHECK(std::strcmp(ini_key(r), "frame_generation_by") == 0, "the row's key in hookshot_options.ini changed");
    CHECK(r.lo == 0 && r.hi == 2 && r.step == 1, "the row is not three choices, DLSS FG, Built-in FG and FSR 3.1 FG");
    CHECK(Options{}.framegen_by == 0, "the default is not DLSS FG (0, the old Auto's number)");
    // (no value reads Auto, wherever DLSS FG runs or not and whoever made the last frames)
    for (int u : {(int)FG_SKIP_NONE, (int)FG_SKIP_DEVICE, (int)FG_SKIP_START})
        for (FgMaker m : {FgMaker::None, FgMaker::BuiltIn, FgMaker::Dlss, FgMaker::DlssPaused, FgMaker::Fsr3}) {
            unavailable = u, maker = m, opts.framegen = 3;
            for (int v = r.lo; v <= r.hi; v++) CHECK(!std::strstr(r.text(v), "Auto"), "a value of the row reads Auto");
        }
    reset_run();
    // (an options file from before: 0 was Auto, the default)
    struct Load { const char* line; int unavailable; int value; const char* text; bool asked; } loads[] = {
        {"frame_generation_by=0", FG_SKIP_NONE, 0, "DLSS FG", true},              // (Auto from before: DLSS FG where it runs)
        {"frame_generation_by=0", FG_SKIP_DEVICE, 0, "FSR 3.1 FG", true},         // (an AMD or Intel GPU: FSR 3.1 FG; kept)
        {"frame_generation_by=0", FG_SKIP_START, 0, "FSR 3.1 FG", true},          // (an RTX 30, no runtime: the same)
        {"frame_generation_by=0", FG_SKIP_NOT_BUILT, 0, "FSR 3.1 FG", true},      // (a build without NVIDIA's SDK)
        {"frame_generation_by=1", FG_SKIP_NONE, 1, "Built-in FG", false},         // (Built-in FG chosen: kept)
        {"frame_generation_by=1", FG_SKIP_DEVICE, 1, "Built-in FG", false},
        {"frame_generation_by=2", FG_SKIP_NONE, 2, "FSR 3.1 FG", false},          // (FSR 3.1 FG chosen: no DLSS-G)
        {"frame_generation_by=2", FG_SKIP_DEVICE, 2, "FSR 3.1 FG", false},
        {"frame_generation_by=3", FG_SKIP_NONE, 2, "FSR 3.1 FG", false},          // (hand-edited past the last: clamped)
        {"frame_generation_by=-1", FG_SKIP_NONE, 0, "DLSS FG", true},
    };
    for (const Load& l : loads) {
        opts = Options{};
        opts.framegen_by = 7;   // (whatever was there: the line sets it)
        unavailable = l.unavailable;
        load(l.line);
        CHECK(opts.framegen_by == l.value, l.line);
        CHECK(std::strcmp(r.text(opts.framegen_by), l.text) == 0, l.line);
        CHECK(fg_asked() == l.asked, l.line);   // (vk_dlss.cpp: DLSS-G asked for at DLSS FG)
    }
    reset_run();
    // (its line, and every one it can show among the variants measure_help makes room for)
    std::set<std::string> variants;
    for (int v = r.lo; v <= r.hi; v++)
        for (int k = 0; const char* t = r.hint(v, k); k++) variants.insert(t);
    auto line = [&](int v) {
        const char* t = r.hint(v, -1);
        CHECK(t && variants.count(t), "a line of the row's is not among its variants (the menu's height)");
        return t ? t : "";
    };
    opts = Options{};
    opts.framegen = 3;   // (3x)
    maker = FgMaker::Dlss;
    CHECK(starts(line(0), "NVIDIA DLSS Frame Generation (RTX 40 and newer)"), "DLSS FG making the frames: not its own line");
    CHECK(starts(line(1), "The renderer's own"), "Built-in FG: not its own line");
    CHECK(starts(line(2), "AMD FSR 3.1 frame interpolation"), "FSR 3.1 FG: not its own line");
    CHECK(std::strcmp(r.text(2), "FSR 3.1 FG") == 0, "FSR 3.1 FG is not named so where DLSS FG runs");
    CHECK(std::strcmp(framegen_maker_name(), "DLSS FG") == 0, "the FPS counter does not name DLSS FG");
    maker = FgMaker::DlssPaused, skip_now = FG_SKIP_INPUTS;   // (the game's own menus, on a temporal Upscaler)
    CHECK(starts(line(0), "DLSS FG paused: the game's own menus"), "DLSS FG paused (the game's frames alone) is not said");
    CHECK(std::strcmp(framegen_maker_name(), "DLSS FG paused") == 0, "the FPS counter does not say DLSS FG is paused");
    CHECK(std::strcmp(r.text(0), "DLSS FG") == 0, "the row does not name the choice while DLSS FG is paused");
    maker = FgMaker::BuiltIn, skip_now = FG_SKIP_INPUTS;   // (an Upscaler that gives DLSS-G no picture: the built-in one)
    CHECK(starts(line(0), "Not DLSS FG now: No picture from a temporal Upscaler"), "the built-in one making the frames at "
          "DLSS FG is not said");
    CHECK(starts(line(1), "The renderer's own"), "Built-in FG chosen: a reason for DLSS FG shown");
    maker = FgMaker::BuiltIn, skip_now = FG_SKIP_TOO_MANY;
    CHECK(starts(line(0), "Not DLSS FG now: Its runtime makes 1 made frames at most"), "a multiplier its runtime does not "
          "make is not said");
    maker = FgMaker::BuiltIn, skip_now = FG_SKIP_NONE;   // (nothing known: the choice's own line, not the switch's)
    CHECK(starts(line(0), "NVIDIA DLSS Frame Generation (RTX 40"), "no reason known: not the choice's own line");
    opts.framegen = 1, skip_now = FG_SKIP_NONE;   // (Frame generation's Auto: the renderer's own always)
    CHECK(starts(line(0), "Not DLSS FG now: DLSS Frame Generation makes a fixed 2x"), "Frame generation's Auto not said");
    opts.framegen = 3;
    // (RX_VK_DLSS_FG=1: DLSS FG for the run, whatever the row says)
    reset_run();
    forced = true;
    for (int v = r.lo; v <= r.hi; v++) {
        CHECK(std::strcmp(r.text(v), "DLSS FG") == 0, "RX_VK_DLSS_FG=1: the row does not read DLSS FG");
        CHECK(starts(line(v), "RX_VK_DLSS_FG=1 is set: it chooses for this run."), "RX_VK_DLSS_FG=1 is not said");
    }
    // (DLSS FG cannot run: FSR 3.1 FG (0 or 2) says why, DLSS's own reason for DLSS; Built-in FG chosen its own line)
    struct Cannot { int why; DlssWhy dlss; const char* text; } cannot[] = {
        {FG_SKIP_OFF, DLSS_OK, "DLSS FG cannot run: DLSS Frame Generation is turned off for this run (RX_VK_DLSS_FG=0)."},
        {FG_SKIP_DEVICE, DLSS_ENV_OFF, "DLSS FG cannot run: DLSS and DLAA: off for this run (RX_VK_DLSS=0)."},
        {FG_SKIP_DEVICE, DLSS_NEEDS_RTX, "DLSS FG cannot run: DLSS and DLAA: need an NVIDIA RTX GPU."},
        {FG_SKIP_DEVICE, DLSS_NEEDS_DRIVER, "DLSS FG cannot run: DLSS and DLAA: need a newer NVIDIA driver."},
        {FG_SKIP_DEVICE, DLSS_NO_RUNTIME, "DLSS FG cannot run: DLSS and DLAA: DLSS's runtime was not found"},
        {FG_SKIP_DEVICE, DLSS_RUNTIME_NOT_ASCII, "DLSS FG cannot run: DLSS and DLAA: NVIDIA's NGX on Linux"},
        {FG_SKIP_START, DLSS_OK, "DLSS FG cannot run: NVIDIA's runtime did not start DLSS Frame Generation"},
        {FG_SKIP_REFUSED, DLSS_OK, "DLSS FG cannot run: NGX refused its frames."},
        {FG_SKIP_NOT_BUILT, DLSS_NOT_BUILT, "DLSS FG cannot run: This build has no NVIDIA DLSS"},
    };
    for (const Cannot& c : cannot)
        for (bool f : {false, true})
            for (int v = r.lo; v <= r.hi; v++) {
                reset_run();
                unavailable = c.why, why_dlss = c.dlss, forced = f, maker = FgMaker::BuiltIn;
                CHECK(starts(line(v), v == 1 && !f ? "The renderer's own" : c.text), c.text);
                CHECK(std::strcmp(r.text(v), v == 1 ? "Built-in FG" : "FSR 3.1 FG") == 0, c.text);
            }
    // (the sets are the game's alone: at DLSS FG, on a temporal Upscaler, for a set without its picture)
    reset_run();
    struct Hold { int by; bool temporal; bool scene; int skip; bool held; } holds[] = {
        {0, true, false, FG_SKIP_INPUTS, true},      // (the game's own menus: no 3D scene asked for)
        {0, false, false, FG_SKIP_INPUTS, false},    // (the game's own upscaler or Off: the built-in one, as before)
        {0, true, true, FG_SKIP_INPUTS, false},      // (in play, the Upscaler drew nothing: failed, refused; the built-in one)
        {1, true, false, FG_SKIP_INPUTS, false},     // (Built-in FG chosen)
        {2, true, false, FG_SKIP_INPUTS, false},     // (FSR 3.1 FG chosen)
        {0, true, false, FG_SKIP_TOO_MANY, false},   // (more frames than its runtime makes: the built-in one)
        {0, true, false, FG_SKIP_REFUSED, false},
        {0, true, false, FG_SKIP_DEVICE, false},
        {0, true, false, FG_SKIP_NONE, false},
    };
    for (const Hold& h : holds) {
        opts.framegen_by = h.by, temporal_on = h.temporal, scene_now = h.scene, fg_skip = h.skip;
        CHECK(dlss_fg_holds() == h.held, "dlss_fg_holds: the game's frames alone in the wrong case");
    }
    scene_now = false;
    if (failures) return 1;
    std::puts("PASS: Frame generation by: DLSS FG, FSR 3.1 FG or Built-in FG, an old Auto as the default, DLSS FG paused in the "
              "game's menus, why when not DLSS FG");
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    menu = (VK / "vk_menu.cpp").read_text(encoding="utf-8")
    header = (VK / "vk_menu.h").read_text(encoding="utf-8")
    dlss = (VK / "vk_dlss.cpp").read_text(encoding="utf-8")
    dlss_h = (VK / "vk_dlss.h").read_text(encoding="utf-8")
    framegen = (VK / "vk_framegen.cpp").read_text(encoding="utf-8")
    framegen_h = (VK / "vk_framegen.h").read_text(encoding="utf-8")
    i18n = (VK / "menu_i18n.h").read_text(encoding="utf-8")

    rowline = found(r'    \{TAB_GRAPHICS, "Frame generation by", &opts\.framegen_by, [^}]*\},', menu,
                    "no Frame generation by row on the Graphics tab")
    found(r"&opts\.framegen_by, 0, 2, 1, tx_framegen_by,.*hn_framegen_by, false, true\}", rowline,
          "the row is not DLSS FG, Built-in FG and FSR 3.1 FG (0 to 2), at once, outside the Quality preset")
    # (with nothing to choose: no arrows, the saved value left alone)
    found(r"value == &opts\.framegen_by && framegen_by_fixed\(\)", block(menu, "bool row_fixed(const int* value) {"),
          "row_fixed: the row is not fixed where RX_VK_DLSS_FG=1 chooses")
    # (NGX asked before a present needs it: the start-up screen's background questions, and the menu's open)
    found(r"dlss_probe\(\);\s*dlss_fg_probe\(\);", block(menu, "static void probe_upscalers_soon() {"),
          "probe_upscalers_soon: NGX is not asked about frame generation at the start-up screen")
    found(r"if \(open_now\.load\(\)\)\s*dlss_probe\(\),\s*dlss_fg_probe\(\)", menu,
          "the menu's open does not ask NGX about frame generation")
    found(r"std::lock_guard\s*lk\(g\.mu\);[^\n]*\n\s*if \(!g\.closed\)\s*fg_start\(g\);", block(dlss, "void dlss_fg_probe() {\n"),
          "dlss_fg_probe: NGX is not asked under the Fg lock (as dlss_fg_frames)")
    found(r"g\.answered\.store\(true", block(dlss, "bool fg_start(Fg& g) {"),
          "fg_start: the menu's thread is not told that NGX has answered")
    unavailable_fn = block(dlss, "int dlss_fg_unavailable() {\n")
    for want in ("FG_SKIP_OFF", "FG_SKIP_DEVICE", "g.answered.load(", "FG_SKIP_REFUSED", "FG_SKIP_START"):
        if want not in unavailable_fn:
            fail("dlss_fg_unavailable: no %s" % want)
    found(r"int dlss_fg_unavailable\(\)\s*\{\s*return FG_SKIP_NOT_BUILT;\s*\}", dlss,
          "a build without NVIDIA's SDK does not say so to the row")
    found(r"held = [^;]*dlss_fg_holds\(\)", block(framegen, "bool framegen_record("),
          "framegen_record: a set DLSS FG has no picture for is not the game's frame alone")
    for table, body in re.findall(r'inline constexpr Entry (k\w+)\[\] = \{\n(.*?)\n\};', i18n, re.S):
        for text in ("DLSS FG cannot run: %s", "DLSS FG paused",
                     "NVIDIA DLSS Frame Generation (RTX 40 and newer), made from the Upscaler's depth and motion.",
                     "AMD FSR 3.1 frame interpolation, made from the scene's depth and motion: any GPU.",
                     "DLSS FG paused: the game's own menus, movies and loading screens draw no 3D to make frames from, so "
                     "only the game's own frames show."):
            if '    {"%s", ' % text not in body:
                fail("%s: %r is not translated" % (table, text))

    loop = found(r"\n +for \(Row& r : rows\) \{\n +if \(!r\.value \|\| r\.value == &opts\.game_lang \|\| strcmp\(line, "
                 r"ini_key\(r\)\)\) continue;.*?\n +\}\n", menu, "the options file's loading loop over the rows is not where it was")
    parts = {
        "/* OPTIONS */": found(r"struct Options \{.*?\n\};", header, "no struct Options"),
        "/* FGSKIP */": found(r"enum FgSkip \{.*?\};", dlss_h, "no enum FgSkip"),
        "/* DLSSWHY */": found(r"enum DlssWhy \{.*?\};", dlss_h, "no enum DlssWhy"),
        "/* FGMAKER */": found(r"enum class FgMaker \{[^}]*\};", framegen_h, "no enum class FgMaker"),
        "/* ENV */": block(dlss, "int env_switch(const char* name) {"),
        "/* POSSIBLE */": block(dlss, "bool fg_possible() {"),
        "/* ASKED */": block(dlss, "bool fg_asked() {"),
        "/* HOLDS */": block(dlss, "bool dlss_fg_holds() {\n"),
        "/* TABS */": found(r"enum MenuTab \{.*?\};", menu, "no enum MenuTab"),
        "/* ROW */": found(r"struct Row \{.*?\n\};", menu, "no struct Row"),
        "/* OFFERED */": block(menu, "bool framegen_by_dlss_offered() {"),
        "/* FIXED */": block(menu, "bool framegen_by_fixed() {"),
        "/* WHYTEXT */": block(menu, "const char* dlss_why_text(int why) {"),
        "/* SKIPTEXT */": block(menu, "const char* framegen_skip_text(int why, unsigned most) {"),
        "/* MAKERNAME */": block(menu, "const char* framegen_maker_name() {"),
        "/* TEXT */": block(menu, "const char* tx_framegen_by(int v) {"),
        "/* HINT */": block(menu, "const char* hn_framegen_by(int v, int variant) {"),
        "/* ROWLINE */": rowline,
        "/* INIKEY */": block(menu, "const char* ini_key(const Row& r) {"),
        "/* LOOP */": loop,
    }
    src_text = FIXTURE
    for key, value in parts.items():
        src_text = src_text.replace(key, value)
    # (the switches fg_possible and fg_asked read are the run's: none from the shell this runs in)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("RX_", "HOS_", "HOOKSHOT_"))}
    with tempfile.TemporaryDirectory(prefix="framegen-by-") as tmp:
        src = Path(tmp) / "row.cpp"
        exe = Path(tmp) / ("row.exe" if os.name == "nt" else "row")
        src.write_text(src_text, encoding="utf-8")
        if Path(args.cxx).name.lower() in ("cl", "cl.exe", "clang-cl", "clang-cl.exe"):
            command = [args.cxx, "/nologo", "/std:c++20", "/EHsc", "/D_CRT_SECURE_NO_WARNINGS", str(src),
                       "/Fo" + str(Path(tmp) / "row.obj"), "/Fe" + str(exe)]
        else:
            command = [args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-D_CRT_SECURE_NO_WARNINGS", str(src), "-o",
                       str(exe)]
        subprocess.run(command, cwd=tmp, check=True)
        subprocess.run([str(exe)], cwd=tmp, env=env, check=True, timeout=60)


if __name__ == "__main__":
    main()
