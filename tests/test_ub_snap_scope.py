"""The uniform copies' sharing and batched reads (#952) are the uniform snapshot's alone (no game, no GPU): with the snapshot
off (RX_VK_UB_SNAPSHOT=0, every GPU but Intel's by default), a uniform range that can't be bound in place, unaligned or
outside the pools, is read and copied at its own binding as before, never given another draw's copy and never read later,
and bind_descriptors keeps its delta push, whose re-push of every uniform write is tied to the sharing.

python -I -B tests/test_ub_snap_scope.py
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from srccut import block  # noqa: E402


def need(ok, what):
    if not ok:
        raise SystemExit("ub snap scope: " + what)


def main():
    src = (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")
    ur = block(src, "VkDescriptorBufferInfo uniform_range(const NvnState& s, const Stage& st, uint32_t index)")
    need("static const bool snapshot = ub_snapshot_wanted();" in ur, "uniform_range no longer asks whether the snapshot is on")
    need("static const int dedup = snapshot ? ub_snap_dedup_mode() : 0;" in ur,
         "the sharing (RX_VK_UB_SNAP_DEDUP) runs with the snapshot off: the fallback copies would be shared")
    need("static const int batch = snapshot ? ub_read_batch_mode() : 0;" in ur,
         "the batched reads (RX_VK_UB_READ_BATCH) run with the snapshot off: the fallback copies would be read late")
    # (with batch 0 the copy is read at its binding, and none is queued for the build's end)
    need("if (batch != 1) memory_read_as_submitted(u.addr, cur->mapped + at, n);" in ur, "a copy is not read at its binding")
    need("if (batch != 0) ub_reads_pending().push_back(" in ur, "the batched reads are not gated by their mode")
    need("if (hit && dedup == 1) return {memo->buf, memo->at, n};" in ur, "the sharing is not gated by its mode")
    # (the re-push of every uniform write is the sharing's: off with the snapshot, so the delta push is main's)
    need("static const bool ub_every = ub_snapshot_wanted() && ub_snap_dedup_mode() == 1;" in src,
         "bind_descriptors' re-push is no longer tied to the snapshot's sharing")
    print("ub snap scope: ok")


if __name__ == "__main__":
    main()
