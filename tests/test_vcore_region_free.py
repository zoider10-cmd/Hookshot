"""A freed address region's discard runs with the calling thread's virtual core given up.

nn::os::FreeAddressRegion (host/hos_mem.c hos_region_free) discards the freed region's pages with a kernel call
(DiscardVirtualMemory, MADV_REMOVE on Linux). For the regions a change of area frees it runs for milliseconds at a time, and
OoT's Resource_Memory thread made it holding a virtual core: 14% of the 11.6 s after arriving on Death Mountain Trail, while
the workers that run on that core only waited (ModuleSystemWorker1: 2.5 ms a frame). The call touches no guest state, so the
core is given up for it, as for a file read (tests/test_vcore_fs_open.py); the region is out of the list, and the list's
lock let go, before that.

python -I -B tests/test_vcore_region_free.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    src = (ROOT / "host" / "hos_mem.c").read_text(encoding="utf-8")
    body = src[src.index("void hos_region_free(uint64_t addr) {"):]
    body = body[:body.index("\n}\n")]
    order = ["LOCK();", "UNLOCK();", "hos_vcore_away()", "discard_pages(freed, freed_size);", "if (away) hos_vcore_back();"]
    at = []
    for needle in order:
        if body.count(needle) != (2 if needle == "LOCK();" else 1):   # ("UNLOCK();" holds "LOCK();" too)
            raise SystemExit("hos_region_free: %r is there %d times" % (needle, body.count(needle)))
        at.append(body.index(needle))
    if at != sorted(at):
        raise SystemExit("hos_region_free: the discard is not made with the core given up, after the regions' lock is let go")
    if 'env_on("HOS_DISCARD_HOLDS_CORE")' not in body or "const int away = holds ? 0 : hos_vcore_away();" not in body:
        raise SystemExit("hos_region_free: no HOS_DISCARD_HOLDS_CORE to keep the core, as before")
    print("a freed region's pages are discarded with the virtual core given up")


if __name__ == "__main__":
    main()
