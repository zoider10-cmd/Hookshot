"""The render target pool's default bound (gpu/vk/target_pool.h): a twelfth of the driver's allowance, from 256 to 768 MB.

Compiles the header with a small fixture and checks the bound at the allowances it is meant for: unknown (0) and small cards stay
at the old 256 MB, an 8 GB card's allowance gets about a twelfth, a 12 GB card's and anything larger 768 MB.

python tests/test_target_pool_cap.py [--cxx clang++]
"""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "clang++"]

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r'''#include <cstdio>
#include "target_pool.h"
using mkwvk::target_pool::default_mb;
static int fails;
static void expect(unsigned long long allowed_mb, unsigned long long want) {
    const unsigned long long got = default_mb(allowed_mb << 20);
    if (got != want) { std::printf("FAIL: allowance %llu MB: %llu MB, expected %llu\n", allowed_mb, got, want); fails++; }
}
int main() {
    if (default_mb(0) != 256) { std::printf("FAIL: an unknown allowance: %llu MB\n", (unsigned long long)default_mb(0)); fails++; }
    expect(2048, 256);    // (a 4 GB laptop card's allowance and less: the old bound)
    expect(3300, 275);
    expect(7000, 583);    // (an 8 GB card)
    expect(9500, 768);    // (a 12 GB card with other programs open)
    expect(11229, 768);
    expect(23000, 768);   // (a 24 GB card: no more than 768)
    if (!fails) std::puts("PASS: the render target pool's default bound is a twelfth of the allowance, 256 to 768 MB");
    return fails ? 1 : 0;
}
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="clang++", help="C++ compiler")
    a = p.parse_args()
    cxx = shutil.which(a.cxx)
    if not cxx:
        raise SystemExit("test_target_pool_cap: no C++ compiler %r (pass --cxx)" % a.cxx)
    with tempfile.TemporaryDirectory(prefix="target-pool-cap-") as temp:
        d = Path(temp)
        src, exe = d / "fixture.cpp", d / "fixture.exe"
        src.write_text(FIXTURE, encoding="utf-8")
        subprocess.run([cxx, "-std=c++17", "-O2", "-I", str(ROOT / "gpu" / "vk"), str(src), "-o", str(exe)], check=True)
        result = subprocess.run([str(exe)], capture_output=True, text=True)
        print(result.stdout, end="")
        if result.returncode:
            raise SystemExit("test_target_pool_cap: failed")


if __name__ == "__main__":
    main()
