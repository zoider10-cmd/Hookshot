"""Compile and run decoded ASTC's reuse rules (gpu/vk/astc_reuse.h: the blocks' hash, the shape, the list; no game/GPU), and
check that vk_texture.cpp still lists finalized textures, copies from them and retires them."""
import argparse
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "g++"]

ROOT = Path(__file__).resolve().parents[1]


def check_source():
    src = (ROOT / "gpu/vk/vk_texture.cpp").read_text(encoding="utf-8")
    for needle in ('#include "astc_reuse.h"',
                   'getenv("RX_VK_ASTC_REUSE")',
                   "if (!dirty && !tex.uploaded && reuse_on() && reuse_upload(tex, total)) return up_route = UP_ASTC, true;",
                   "freed.list(x->blocks_hash, x);",
                   "if (tex->freed_listed || tex->reuse_retire) reuse_drop(*tex);",
                   "if (tex->freed_listed || tex->reuse_retire) return false;",
                   "vkCmdCopyImage(cmd, from->image, VK_IMAGE_LAYOUT_GENERAL, tex.image, VK_IMAGE_LAYOUT_GENERAL",
                   "from->last_value = std::max(from->last_value, rec_value);",
                   "went.swap(reuse_gone);"):
        if needle not in src:
            raise SystemExit("vk_texture.cpp no longer has: " + needle)
    forget = src[src.index("void forget_gpu(Texture* tex) {"):]
    if "reuse_drop(*tex);" not in forget[:200]:
        raise SystemExit("forget_gpu no longer takes a destroyed texture out of the reuse list")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    check_source()
    with tempfile.TemporaryDirectory(prefix="astc-reuse-") as tmp:
        exe = Path(tmp) / "astc-reuse"
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror",
                        str(ROOT / "tests/test_astc_reuse.cpp"), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
