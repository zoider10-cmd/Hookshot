"""The write-back diff pass has a checkpoint of its own (gpu/vk/vk_memory.cpp), named in the device-lost report
(gpu/vk/vk_draw.cpp checkpoint_kind): without it a fault in the pass read as the last pool's copy (issues 899, 1008). No game/GPU."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    mem = (ROOT / "gpu/vk/vk_memory.cpp").read_text(encoding="utf-8")
    dispatch = "vkCmdDispatch(cmd, std::min<uint32_t>(n, 65535u), (n + 65534u) / 65535u, 1);"
    at = mem.find(dispatch)
    if at < 0:
        raise SystemExit("vk_memory.cpp: the write-back diff's dispatch is not found")
    if mem.rfind("checkpoint_mark(cmd, n, 'w');", 0, at) < mem.rfind("vkCmdPushConstants(cmd, wbd_pipe.layout", 0, at):
        raise SystemExit("vk_memory.cpp: the write-back diff's dispatch has no checkpoint of its own between its push and it")
    draw = (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")
    kinds = draw[draw.index("const char* checkpoint_kind(char c) {"):]
    if "c == 'w' ? \"write-back diff pass" not in kinds[:800]:
        raise SystemExit("vk_draw.cpp: checkpoint_kind does not name the write-back diff pass ('w')")


if __name__ == "__main__":
    main()
