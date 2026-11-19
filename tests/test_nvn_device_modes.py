"""nvnDeviceGetWindowOriginMode and nvnDeviceGetDepthMode answer what the game set (host/nvn_native.c).

Neither was in the proc table, so a caller got the "not implemented" stub's 0: lower left and near = -w whatever the
game had set. The game sets upper left, so code that asks the origin to lay its own drawing over the picture (a mod's
overlay, reading rows bottom up for lower left) drew it upside down. The device functions are compiled from the source
and checked:

- a new device answers NVN's defaults (lower left, near = -w), and after the game sets them, what it set;
- both names are in the proc table, so nvnDeviceGetProcAddress hands out these and not the stub.

python -I -B tests/test_nvn_device_modes.py [--cc clang]
"""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

RUN_ALL_ARGS = ["--cc", "gcc"]
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))   # (python -I leaves the check's own folder off the path)
from srccut import block  # noqa: E402


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="gcc", help="C compiler (gcc or clang)")
    a = p.parse_args()
    src = (ROOT / "host/nvn_native.c").read_text(encoding="utf-8")
    for name in ("nvnDeviceGetWindowOriginMode", "nvnDeviceGetDepthMode"):
        if '{"%s", n_%s},' % (name, name) not in src:
            raise SystemExit("test_nvn_device_modes: %s is not in the proc table" % name)
    parts = [block(src, m) for m in ("NV(nvnDeviceInitialize)", "NV(nvnDeviceSetWindowOriginMode)",
                                             "NV(nvnDeviceGetWindowOriginMode)", "NV(nvnDeviceGetDepthMode)",
                                             "NV(nvnDeviceSetDepthMode)")]
    fixture = r'''#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef long LONG;
static LONG InterlockedExchange(volatile LONG *p, LONG v) { LONG o = *p; *p = v; return o; }
static void hos_log(const char *f, ...) { (void)f; }
typedef struct { uint64_t x[32]; } Ctx;
#define NVN_MAGIC(a, b, c, d) ((uint32_t)(a) | (uint32_t)(b) << 8 | (uint32_t)(c) << 16 | (uint32_t)(d) << 24)
#define NVN_DEPTH_MODE_NEAR_IS_MINUS_W 0
typedef struct { uint32_t magic, flags, origin, depth_mode; } nvn_dev;
typedef struct { uint32_t flags; } nvn_dev_builder;
static volatile LONG depth_minus_w;
static uint8_t mem[256];
#define P(i) ((void *)(mem + c->x[i]))
#define U32(i) ((uint32_t)c->x[i])
#define U64(i) (c->x[i])
#define RET(v) (c->x[0] = (uint64_t)(v))
#define NV(name) static void n_##name(Ctx *c)
''' + "\n".join(parts) + r'''
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); return 1; } } while (0)
int main(void) {
    memset(mem, 0xa5, sizeof mem);
    Ctx c = {{0x10, 0x80}};
    ((nvn_dev_builder *)(mem + 0x80))->flags = 0;
    n_nvnDeviceInitialize(&c);
    c = (Ctx){{0x10}}; n_nvnDeviceGetWindowOriginMode(&c); CHECK(c.x[0] == 0);
    c = (Ctx){{0x10}}; n_nvnDeviceGetDepthMode(&c); CHECK(c.x[0] == 0);
    c = (Ctx){{0x10, 1}}; n_nvnDeviceSetWindowOriginMode(&c);   /* upper left, as the game sets it */
    c = (Ctx){{0x10, 1}}; n_nvnDeviceSetDepthMode(&c);          /* near = 0 */
    c = (Ctx){{0x10}}; n_nvnDeviceGetWindowOriginMode(&c); CHECK(c.x[0] == 1);
    c = (Ctx){{0x10}}; n_nvnDeviceGetDepthMode(&c); CHECK(c.x[0] == 1);
    c = (Ctx){{0x10, 0}}; n_nvnDeviceSetDepthMode(&c);
    c = (Ctx){{0x10}}; n_nvnDeviceGetDepthMode(&c); CHECK(c.x[0] == 0);
    printf("PASS: the device's window origin and depth mode answer what the game set, NVN's defaults before\n");
    return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix="nvn-device-modes-") as tmp:
        c = Path(tmp) / "fixture.c"
        exe = Path(tmp) / "fixture.exe"
        c.write_text(fixture, encoding="utf-8")
        subprocess.run([a.cc, "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", "-Wno-unused-parameter",
                        str(c), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
        print(r.stdout, end="")
        if r.returncode:
            print(r.stderr, end="")
            raise SystemExit("test_nvn_device_modes: failed")


if __name__ == "__main__":
    main()
