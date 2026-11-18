"""The cucco lady's game wants one cucco (tools/rando/rando_seed.py CUCCO_LOGIC, CUCCO_FLOW): no game data.

- the pen's logic: its one fixed 7 (an unlinked Int_A) is made 1, nothing else; a file with none or two refuses;
- the script writes it every seed, and her flow's count of cuccos left, with the fixes' version raised.

    python -I -B tests/test_rando_cucco.py
"""
import importlib.util
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("rando_seed", ROOT / "tools" / "rando" / "rando_seed.py")
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)


def check(ok, why):
    if not ok:
        print("FAIL: %s" % why)
        sys.exit(1)


def ainb(values):
    """an AI file of the pen's kind: inputs (name Int_A, unlinked, value) from 0x100, its strings at 0x200"""
    pool = 0x200
    strings = b"\0Int_A\0MiniGame_CatchCucco_InFenceCount\0"
    d = bytearray(pool + len(strings))
    d[0:4] = b"AIB "
    struct.pack_into("<I", d, 4, 0x408)
    struct.pack_into("<I", d, 0x24, pool)
    for k, v in enumerate(values):
        struct.pack_into("<IIIi", d, 0x100 + 16 * k, 1, 0xFFFF, 0x01800000, v)
    d[pool:] = strings
    return bytes(d)


def main():
    S = seed
    before = ainb([3, 7])
    after = S.cucco_logic_one(before)
    check(len(after) == len(before) and struct.unpack_from("<i", after, 0x11C)[0] == 1 and
          [i for i in range(len(before)) if before[i] != after[i]] == [0x11C],
          "the pen's fixed 7 is not made 1 alone")
    for bad in ([3, 4], [7, 7]):
        try:
            S.cucco_logic_one(ainb(bad))
            check(False, "a file with %r was changed" % bad)
        except ValueError:
            pass
    script = (ROOT / "tools" / "rando" / "rando_seed.py").read_text(encoding="utf-8")
    check("flag_files[CUCCO_LOGIC] = cucco_logic_one(" in script and "gift_files[CUCCO_FLOW] = cucco_flow_one(was)" in script and
          "gift_sizes[CUCCO_FLOW[:-3]] = len(gift_files[CUCCO_FLOW])" in script and S.CUCCOS == 1 and S.FIXES_VERSION >= 43,
          "the script does not write the pen's logic and her flow every seed, or the fixes' version was not raised")
    # (her flow's size goes to the size table, which is made before the logic's place in the script)
    check(script.index("gift_sizes[CUCCO_FLOW[:-3]]") < script.index("gift_sizes, FLOW_EXTRA))"),
          "her flow is changed after the size table is made")
    print("PASS: the cucco lady wants one cucco")


if __name__ == "__main__":
    main()
