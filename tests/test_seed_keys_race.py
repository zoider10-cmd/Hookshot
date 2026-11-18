"""Game-free: a seed opened in play does not fill seed_keys under miss_note's reads (gpu/vk/vk_shader.cpp seed_open).

seed_keys (a std::unordered_set) is read by miss_note on the replay's program picks, the first 1500 misses in play. With
RX_VK_PREPARE_BACKGROUND the seed is opened in play, and seed_open() inserted every stage's key while those reads ran: a
rehash under a reader, which can walk freed buckets. seed_keys only serves RX_VK_SEED_CHECK's marks, so seed_open fills
it only then. Checked on the source:
  - every seed_keys.insert in seed_open is under `if (seed_check)`;
  - seed_check is RX_VK_SEED_CHECK, read once.

python -I -B tests/test_seed_keys_race.py
"""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "gpu" / "vk" / "vk_shader.cpp"


def body(text, head):
    """The braces-balanced body of the function whose definition starts with head"""
    i = text.index(head)
    j = text.index("{", i)
    depth = 0
    for k in range(j, len(text)):
        depth += {"{": 1, "}": -1}.get(text[k], 0)
        if depth == 0:
            return text[j:k + 1]
    raise AssertionError("unbalanced braces after " + head)


def main():
    seed_open = body(SRC.read_text(encoding="utf-8"), "size_t seed_open()")
    inserts = [l.strip() for l in seed_open.splitlines() if "seed_keys.insert" in l]
    if not inserts:
        sys.exit("FAIL: seed_open no longer fills seed_keys at all: update this check with what does")
    bare = [l for l in inserts if not l.startswith("if (seed_check)")]
    if bare:
        sys.exit("FAIL: seed_open fills seed_keys outside RX_VK_SEED_CHECK (a rehash under miss_note's reads in play): %s"
                 % "; ".join(bare))
    if not re.search(r'static\s+const\s+bool\s+seed_check\s*=\s*env_on\("RX_VK_SEED_CHECK"\)', seed_open):
        sys.exit("FAIL: seed_check in seed_open is not RX_VK_SEED_CHECK read once")
    print("ok: seed_open fills seed_keys only for RX_VK_SEED_CHECK (%d insert)" % len(inserts))


if __name__ == "__main__":
    main()
