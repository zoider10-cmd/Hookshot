"""The uniform snapshot (gpu/vk/vk_draw.cpp ub_snapshot_wanted, RX_VK_UB_SNAPSHOT) is on by default on every Intel GPU,
its discrete Arc cards with VRAM mirrors included, and off elsewhere; uniform_range asks it. The decision compiled alone
against a table; no game or GPU required.

Bound where the game keeps them, a frame's uniforms are read by the GPU after the game has written the next frame's over
them: on an Arc B580 (101.9154, mirrors on) the Kokiri Forest floor and the treehouses went to sky, with white glowing
blocks and pots that came and went, as on the Intel iGPUs the snapshot was first made for.

python -I -B tests/test_ub_snapshot_default.py [--cxx g++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"


def block(text, marker):
    """From marker to the brace closing its first one"""
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


# RX_VK_UB_SNAPSHOT's value (None: unset), the GPU's vendor, and whether the uniforms are snapshotted
VENDORS = {"intel": 0x8086, "amd": 0x1002, "nvidia": 0x10DE}
CASES = ([(None, "intel", 1), (None, "amd", 0), (None, "nvidia", 0)] +
         [(v, g, 1) for v in ("1", "on", "yes") for g in VENDORS] +
         [(v, g, 0) for v in ("0", "off", "false", "no", "") for g in VENDORS])
FIXTURE = r"""
#include <cstdio>
#include <cstdlib>
#include <cstring>
struct { struct { unsigned vendorID; } props; } dev;
static const char* the_value;   // (the switch's value, nullptr: unset; read in place of the environment)
static const char* fake_getenv(const char* name) { return strcmp(name, "RX_VK_UB_SNAPSHOT") ? nullptr : the_value; }
@@DECISION@@
int main(int argc, char** argv) {
    // (argv: value or -unset, the vendor, 1 snapshotted or 0)
    for (int i = 1; i + 2 < argc; i += 3) {
        the_value = strcmp(argv[i], "-unset") ? argv[i] : nullptr;
        dev.props.vendorID = (unsigned)strtoul(argv[i + 1], nullptr, 0);
        const bool got = ub_snapshot_wanted();
        if (got != (atoi(argv[i + 2]) != 0)) {
            printf("FAIL: RX_VK_UB_SNAPSHOT=[%s], vendor 0x%04x: %s\n", the_value ? the_value : "(unset)",
                   dev.props.vendorID, got ? "snapshotted" : "bound in place");
            return 1;
        }
    }
    return 0;
}
"""


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="g++")
    args = p.parse_args()
    src = (VK / "vk_draw.cpp").read_text(encoding="utf-8")

    ranges = block(src, "VkDescriptorBufferInfo uniform_range(const NvnState& s, const Stage& st, uint32_t index) {")
    code = "\n".join(line.split("//")[0] for line in ranges.splitlines())
    if "static const bool snapshot = ub_snapshot_wanted();" not in code:
        raise SystemExit("FAIL: uniform_range no longer asks ub_snapshot_wanted whether to snapshot the uniforms")
    if "snapshot && !gpu_written ? BufferRef{} : gpu_buffer_bind(" not in code:
        raise SystemExit("FAIL: uniform_range binds a uniform buffer in place although the snapshot is on (and the GPU did "
                         "not write it earlier in the submission: tests/test_ub_snapshot_gpu_writes.py)")
    print("source: uniform_range copies the uniforms into the stream when ub_snapshot_wanted says so")

    decision = block(src, "bool ub_snapshot_wanted() {")
    with tempfile.TemporaryDirectory(prefix="ub-snapshot-") as tmp:
        tmp = Path(tmp)
        cpp, exe = tmp / "t.cpp", tmp / "t.exe"
        cpp.write_text(FIXTURE.replace("@@DECISION@@", decision.replace("getenv(", "fake_getenv(")), encoding="utf-8")
        r = subprocess.run([args.cxx, "-std=c++20", "-include", str(VK / "compat" / "hookshot_env.h"), "-Wall",
                            "-Wextra", "-Werror", str(cpp), "-o", str(exe)], capture_output=True, text=True, timeout=120)
        if r.returncode:
            print(r.stdout + r.stderr)
            raise SystemExit("FAIL: ub_snapshot_wanted did not build alone")
        argv = []
        for value, gpu, want in CASES:
            argv += ["-unset" if value is None else value, hex(VENDORS[gpu]), str(want)]
        r = subprocess.run([str(exe), *argv], capture_output=True, text=True, timeout=30)
        if r.returncode:
            print(r.stdout + r.stderr)
            raise SystemExit("FAIL: the uniform snapshot's default is wrong (on for every Intel GPU, mirrors or not; off "
                             "elsewhere; RX_VK_UB_SNAPSHOT by the switches' rule)")
    print("decision: %d cases: unset, on for Intel (discrete Arc included), off for AMD and NVIDIA; RX_VK_UB_SNAPSHOT by "
          "the switches' rule" % len(CASES))
    print("PASS")


if __name__ == "__main__":
    main()
