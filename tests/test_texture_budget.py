"""Compile and run the texture cache's budget rule (gpu/vk/texture_budget.h; no game/GPU required), and check that the renderer
uses it alone: vk_texture.cpp's texture_frame takes RX_VK_VRAM_MB or the rule, with no Quality preset or menu row over it.

The menu's VRAM budget row is gone (a player choosing 6 GB on an 8 GB card was working around the presets' sizes, and the
row's steps were read as a quality setting): no row, no options for it, and an old options file's vram_budget= line is dropped
when the options are saved rather than kept for nothing.

python -I -B tests/test_texture_budget.py [--cxx g++]
"""
import argparse
import re
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "g++"]

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu/vk"


def block(text, marker):
    if marker not in text:
        raise SystemExit("no longer there: " + marker)
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def check_source():
    fail = []
    tex = (VK / "vk_texture.cpp").read_text(encoding="utf-8")
    if '#include "texture_budget.h"' not in tex:
        fail.append("vk_texture.cpp no longer includes texture_budget.h")
    frame = block(tex, "void texture_frame(uint64_t completed)")
    for needle in ['getenv("RX_VK_VRAM_MB")', "texture_rule::integrated_bytes(", "texture_rule::dedicated_bytes(",
                   "uint64_t budget = own;"]:
        if needle not in frame:
            fail.append("texture_frame no longer has: " + needle)
    if "opts.vram_mb" in tex or "preset_texture_budget" in tex or "preset_caps_memory" in tex:
        fail.append("vk_texture.cpp: a preset's texture budget again")
    menu = (VK / "vk_menu.cpp").read_text(encoding="utf-8")
    header = (VK / "vk_menu.h").read_text(encoding="utf-8")
    options = re.search(r"struct Options \{.*?\n\};", header, re.S).group()
    for name in ("vram_mb", "mirror_mb", "vram_budget"):
        if re.search(r"\bint %s\b" % name, options):
            fail.append("vk_menu.h: Options has %s again (no preset or row sets the VRAM budgets)" % name)
    if '"VRAM budget"' in menu or "&opts.vram_budget" in menu:
        fail.append("vk_menu.cpp: a VRAM budget row again")
    if "preset_caps_memory" in header or "preset_caps_memory" in menu:
        fail.append("preset_caps_memory again")
    if 'mine |= key == "vram_budget";' not in block(menu, "void save() {"):
        fail.append("save() keeps an old file's vram_budget= line (it is read by nothing)")
    if fail:
        raise SystemExit("\n".join(fail))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    check_source()
    with tempfile.TemporaryDirectory(prefix="texture-budget-") as tmp:
        exe = Path(tmp) / "texture-budget"
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", str(ROOT / "tests/test_texture_budget.cpp"), "-o",
                        str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
