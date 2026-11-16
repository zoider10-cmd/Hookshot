// When the dead transient render targets are looked for between the eviction's passes (vk_texture.cpp texture_frame and
// dead_targets_sweep). tests/test_dead_targets_sweep.py
//
// OoT makes a frame's render targets one after another in a scratch heap, so their addresses shift from frame to frame and each
// is a new image here; one whose storage another target has been drawn over from another start since its last use holds nothing
// any more (target_overlap.h) and its image goes back to the target pool. RX_VK_DEAD_EVERY has said "every present" since the
// pool's bound grew, but the pass that reads it sits behind texture_frame's `frame_no % 10` and ran every tenth present only:
// a frame's dead targets waited up to nine more presents. In Castle Town's market with the camera turning, 160-290 of them
// (700-830 MB) were alive at a time, every one already drawn over, and ten frames' worth came back to the pool at once.
#pragma once

#include <algorithm>
#include <cstdint>

namespace mkwvk::dead_targets {

/// The eviction's pass (budget, hold, sweep) runs at every tenth present: texture_frame's own gate
inline constexpr uint64_t kPassEvery = 10;

/// Whether the eviction's pass runs at this present
inline bool pass_due(uint64_t frame_no) { return frame_no % kPassEvery == 0; }

/// Whether the dead targets are looked for at this present, between the passes: every `every` presents (RX_VK_DEAD_EVERY;
/// 10 or more leaves them to the pass alone, as before), unless they are not looked for at all (RX_VK_DEAD_TARGETS=0) or
/// nothing is evicted (RX_VK_NO_EVICT)
inline bool sweep_due(uint64_t frame_no, uint64_t every, bool on) {
    return on && !pass_due(frame_no) && frame_no % std::max<uint64_t>(every, 1) == 0;
}

/// Whether a render target may go as a dead one at present `frame_no`: of one level and layer, unused for `need` presents
/// (RX_VK_DEAD_MIN_UNUSED) and the GPU past its last use. Whether another target was drawn over it is target_overlap.h's
inline bool candidate(uint64_t frame_no, uint64_t last_frame, uint64_t need, uint64_t last_value, uint64_t completed, bool single) {
    return single && frame_no - last_frame >= need && last_value <= completed;
}

}  // namespace mkwvk::dead_targets
