"""Compile the real NGX feature preparation with a recording SDK stand-in.

Creation uses each mode's recommended input size, independently of the larger
dynamic input-resource range and the current render subrect. No GPU/SDK/game.
API sizing reference: NVIDIA-RTX/Streamline source/plugins/sl.dlss/dlssEntry.cpp.
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]
ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    parser.add_argument("--source-file", type=Path, default=ROOT / "gpu/vk/vk_dlss.cpp")
    args = parser.parse_args()
    source = args.source_file.read_text(encoding="utf-8")
    begin = source.index("int prepare(VkCommandBuffer cmd")
    end = source.index("\nbool start()", begin)
    fixture = (ROOT / "tests/dlss_feature_size_test.cpp").read_text(encoding="utf-8")
    fixture = fixture.replace("/* PREPARE */", source[begin:end])
    with tempfile.TemporaryDirectory(prefix="dlss-feature-size-") as tmp:
        cpp = Path(tmp) / "test.cpp"
        exe = Path(tmp) / "test"
        cpp.write_text(fixture, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "gpu/vk"),
                        str(cpp), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
