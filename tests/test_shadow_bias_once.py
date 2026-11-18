"""RX_VK_SHADOW_BIAS is read once, safely across the threads that record draws.

dynamic_state() kept the shadow bias in two function statics, initialised by hand: `units < 0` meant "not read yet",
then units was set to the default before getenv/sscanf filled both. Parallel recording threads (RX_VK_PARALLEL) reach it
at once, so one thread could read units and slope while another was still writing them: a data race, and a draw could
take the 250000 default with a slope not read yet, or a half-written pair. Now both start at their defaults and the
variable is parsed in a function-local static's initializer, which C++ runs exactly once and makes visible to every
thread before they go on.

python -I -B tests/test_shadow_bias_once.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    src = (ROOT / "gpu" / "vk" / "vk_draw.cpp").read_text(encoding="utf-8")
    at = src.find('getenv("RX_VK_SHADOW_BIAS")')
    if at < 0:
        raise SystemExit("RX_VK_SHADOW_BIAS is no longer read in vk_draw.cpp: this test needs updating")
    block = src[src.rfind("{", 0, src.rfind("static float units", 0, at)):at]
    if "static float units" not in block:
        raise SystemExit("the shadow bias statics moved: this test needs updating")
    if "if (units < 0)" in block:
        raise SystemExit("RX_VK_SHADOW_BIAS is read under a plain `units < 0` check: threads race on units and slope")
    if "static const bool" not in block or "= [] {" not in block:
        raise SystemExit("RX_VK_SHADOW_BIAS is not read in a static initializer (once, thread-safely)")
    print("RX_VK_SHADOW_BIAS read once, in a static initializer")


if __name__ == "__main__":
    main()
