"""The read-back command pool is not kept half made.

When vkAllocateCommandBuffers or vkCreateFence failed, rb_pool stayed set with rb_cmd or rb_fence null: the next call
skipped the creation and began a null command buffer. Now the pool is destroyed and all three made again next time.

python -I -B tests/test_readback_pending.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"


def body_of(src, head):
    b = src[src.index(head):]
    return b[:b.index("\n}\n")]


def main():
    tex = (VK / "vk_texture.cpp").read_text(encoding="utf-8")
    begin = body_of(tex, "bool readback_begin() {")
    reset = begin.find("vkResetCommandPool(")
    if reset < 0:
        raise SystemExit("readback_begin no longer resets its pool")
    made = begin[begin.index("vkAllocateCommandBuffers("):reset]
    if "vkDestroyCommandPool(dev.device, rb_pool, nullptr);" not in made or "rb_pool = VK_NULL_HANDLE" not in made:
        raise SystemExit("a read-back pool whose command buffer or fence failed is kept half made")
    print("the read-back pool is never used half made")


if __name__ == "__main__":
    main()
