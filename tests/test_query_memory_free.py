"""svcQueryMemory answers free memory as the whole gap and past the address space as Inaccessible
(host/hos_svc.c query_memory).

The kernel answers the memory block that holds the address, and free blocks are merged, so a free address is answered
with the whole free range around it, from the end of the mapping before it to the start of the one after it. Past the
address space it answers one Inaccessible block (state 0x10) from the space's end to 2^64 (Atmosphere's mesosphere,
KPageTableBase::QueryInfo). Longshot answered a free address with its one page, so a walk over the address space
region by region (base + size each step, as code that lists the mappings does) needed a step per free page and never
got far past the system region. query_memory is cut from the source and compiled with stubs for the layout, then:

- each free gap (below the system region, between it and the image, between the image and the heap, between the heap
  and a stack above it, after the last mapping) is answered whole, from any address inside it, state Free, perm none;
- from 1 << 39 up, Inaccessible to the end of the 64-bit space;
- the mapped regions answer as before (system region, image, heap, the thread's stack);
- a walk from 0 meets every mapping and ends at the Inaccessible block in a few steps;
- a stack inside the heap and an empty heap keep the gaps right.

python -I -B tests/test_query_memory_free.py [--cc gcc]
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

FIXTURE = r'''#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define HOS_SYSTEM_BASE 0x01000000ULL
#define HOS_SYSTEM_END 0x07000000ULL
#define HOS_HEAP_BASE 0x1000000000ULL
#define HOS_GUEST_SPACE (1ULL << 39)
typedef struct HosThread HosThread;
static uint8_t outbuf[0x28];
#define GP(a) ((void *)(outbuf + (a)))
#define G64(a) (*(uint64_t *)GP(a))
#define G32(a) (*(uint32_t *)GP(a))
static uint64_t hos_image_base, hos_image_end, hos_heap_size, t_stack, t_stack_size;
static HosThread *hos_self(void) { return 0; }
static void hos_thread_stack(HosThread *t, uint64_t *addr, uint64_t *size) { (void)t; *addr = t_stack; *size = t_stack_size; }
@QUERY@
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); return 1; } } while (0)
static uint64_t qb, qs; static uint32_t qst, qp;
static void q(uint64_t addr) { memset(outbuf, 0xa5, sizeof outbuf); query_memory(0, addr); qb = G64(0); qs = G64(8); qst = G32(16); qp = G32(24); }
#define FREE(addr, b, e) do { q(addr); CHECK(qb == (b) && qs == (e) - (b) && qst == 0 && qp == 0); } while (0)
static int walk(int want_regions) {
    uint64_t a = 0; int steps = 0, mapped = 0;
    for (;;) {
        q(a);
        if (qst != 0 && qst != 0x10) mapped++;
        steps++;
        if (qst == 0x10 || steps > 64) break;
        CHECK(qb <= a && qs > 0 && qb + qs > a);
        a = qb + qs;
    }
    CHECK(qst == 0x10 && qb == HOS_GUEST_SPACE && qb + qs == 0);
    CHECK(mapped == want_regions);
    CHECK(steps <= 2 * want_regions + 2);
    return 0;
}
int main(void) {
    const uint64_t img = 0x08000000, img_end = 0x0C000000, heap = 0x40000000, stk = 0x2000000000ULL, stk_n = 0x100000;
    hos_image_base = img; hos_image_end = img_end; hos_heap_size = heap; t_stack = stk; t_stack_size = stk_n;
    FREE(0, 0, HOS_SYSTEM_BASE);
    FREE(0xFFF000, 0, HOS_SYSTEM_BASE);
    FREE(HOS_SYSTEM_END, HOS_SYSTEM_END, img);
    FREE(0x07654321, HOS_SYSTEM_END, img);
    FREE(img_end, img_end, HOS_HEAP_BASE);
    FREE(0x800000000ULL, img_end, HOS_HEAP_BASE);
    FREE(HOS_HEAP_BASE + heap, HOS_HEAP_BASE + heap, stk);
    FREE(stk + stk_n, stk + stk_n, HOS_GUEST_SPACE);
    FREE(HOS_GUEST_SPACE - 1, stk + stk_n, HOS_GUEST_SPACE);
    q(HOS_GUEST_SPACE); CHECK(qb == HOS_GUEST_SPACE && qs == 0 - HOS_GUEST_SPACE && qst == 0x10 && qp == 0);
    q(~0ULL); CHECK(qb == HOS_GUEST_SPACE && qst == 0x10);
    q(HOS_SYSTEM_BASE + 5); CHECK(qb == HOS_SYSTEM_BASE && qs == HOS_SYSTEM_END - HOS_SYSTEM_BASE && qst == 0x05 && qp == 3);
    q(img + 0x1234); CHECK(qb == img && qs == img_end - img && qst == 0x03 && qp == 5);
    q(HOS_HEAP_BASE); CHECK(qb == HOS_HEAP_BASE && qs == heap && qst == 0x05 && qp == 3);
    q(stk + 8); CHECK(qb == stk && qs == stk_n && qst == 0x0B && qp == 3);
    if (walk(4)) return 1;
    t_stack = HOS_HEAP_BASE + 0x1000; t_stack_size = 0x10000;   /* a stack inside the heap */
    FREE(img_end, img_end, HOS_HEAP_BASE);
    FREE(HOS_HEAP_BASE + heap, HOS_HEAP_BASE + heap, HOS_GUEST_SPACE);
    if (walk(3)) return 1;   /* (the heap is answered whole from its base: the walk steps over the stack in it) */
    hos_heap_size = 0;   /* no heap yet */
    FREE(img_end, img_end, t_stack);   /* (the stack is still mapped: the gap ends there) */
    FREE(HOS_HEAP_BASE, img_end, t_stack);
    printf("PASS: svcQueryMemory answers free memory as the whole gap, Inaccessible past the address space\n");
    return 0;
}
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="gcc")
    a = p.parse_args()
    svc = (ROOT / "host/hos_svc.c").read_text(encoding="utf-8")
    fixture = FIXTURE.replace("@QUERY@", block(svc, "static void query_memory(uint64_t out, uint64_t addr)"))
    with tempfile.TemporaryDirectory(prefix="query-memory-free-") as tmp:
        c = Path(tmp) / "fixture.c"
        exe = Path(tmp) / "fixture.exe"
        c.write_text(fixture, encoding="utf-8")
        subprocess.run([a.cc, "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", str(c), "-o", str(exe)],
                       check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
        print(r.stdout, end="")
        if r.returncode:
            print(r.stderr, end="")
            raise SystemExit("test_query_memory_free: failed")


if __name__ == "__main__":
    main()
