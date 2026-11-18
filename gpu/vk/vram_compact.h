// (hookshot) The compaction's rules (on unless RX_VK_COMPACT=0; vk_texture.cpp's compact_step and the texture budget), apart from Vulkan so
// that tests/test_vram_compact.py can run them.
//
// The driver counts VMA's blocks whole. An evicted texture's memory stays inside its 128 MB block, so the count keeps what the
// cache gave up: at DLAA 2560 x 1440 on a 12 GB card the count sat at 10.0 of the 10.9 GB the driver allows with 1.4-1.7 GB of it
// free inside the blocks. There the GPU's frame went from ~10 ms to 13-20 ms (the driver itself short, and the write-back
// shadows given back at 95%): 34-49 frames over 33 ms in a five-minute walk across Hyrule Field, a 1% low of 26-29 fps.
// Compacted, the textures' free space goes back to the driver, and the budget can hold the count below that.
#pragma once

#include <algorithm>
#include <cstdint>
#include <cstdlib>

namespace vram_compact {

/// Global minimum graphics memory requirement for the game (~8 GB, matching Switch 2 UMA footprint).
inline constexpr uint64_t GLOBAL_MIN_GRAPHICS_REQ = 8192ull << 20;

/// Whether the textures are compacted, by RX_VK_COMPACT as the environment has it: on when it is not set, off for 0 (or empty).
/// It was opt-in (RX_VK_COMPACT=1) while its hold could let go of textures in use; that is what hold_keeps and hold_met are for
inline bool enabled(const char* env) { return !env || atoi(env) != 0; }

/// The driver's count over 90% of what it allows: a run starts for less free space, and the next one sooner
inline bool pressed(uint64_t used, uint64_t allowed) { return allowed && used > allowed / 10 * 9; }

/// The free space in the textures' pool from which a run starts: proportional to `allowed` (allowed / 16, clamped to 64-512 MB)
/// unless overridden by RX_VK_COMPACT_MB, and 192 MB while pressed.
inline uint64_t default_min_free(uint64_t allowed) {
    return allowed ? std::clamp<uint64_t>(allowed / 16, 64ull << 20, 512ull << 20) : (512ull << 20);}
inline uint64_t run_from(uint64_t min_free, bool is_pressed) { return is_pressed ? std::min<uint64_t>(min_free, 192ull << 20) : min_free; }

/// The blocks a pool starts with (#2438: each block made in play is a vkAllocateMemory on the replay thread, ~170 ms on AMD's
/// Windows driver): 15% of the card's memory, 2 to 24, in the pool the sampled textures are made in (holds_textures) and in no
/// other. They were the images' pool's, where the textures went when #2438 was measured; compacted, the textures have a pool of
/// their own, and the images' pool is left DLSS's, the frame interpolation's and the scratch images. There the blocks stayed
/// empty: the driver counted them (1152 MB on an 8 GB card), no texture could take them, so reclaimable() rightly left them in
/// the count and the hold cut the texture budget by as much (#2690: an RTX 3070 in Castle Town Market, 31-36 fps against 54-56
/// without them), and the textures' blocks were made in play as before. In the textures' pool the scene's textures fill them,
/// and what they hold free is that pool's free space, which the budget takes off the count already.
/// None on an integrated GPU: its heap is the PC's RAM, which the game needs too, and VMA keeps those blocks for the whole run.
/// On a UHD Graphics with 16 GB (i3-1115G4) nine blocks (1152 MB) stayed while the textures' budget fell to 720 MB; the pool
/// down to them (kept_only) kept the 97% rule waiting, and at 6.6 GB of the 6.5 the driver allowed a 1119 x 1119 depth image
/// was not made and the device was lost (the Deku Tree's last cutscene)
inline uint64_t blocks_at_start(uint64_t heap, uint64_t block, bool holds_textures, bool integrated) {
    if (!holds_textures || !block || integrated) return 0;
    if (heap < GLOBAL_MIN_GRAPHICS_REQ) return std::clamp<uint64_t>(heap / 100 * 8 / block, 2, 12);
    return std::clamp<uint64_t>(heap / 100 * 15 / block, 2, 24);
}

/// The free space of the textures' pool a run can give back: not what the blocks made at the start hold (kept), which VMA
/// keeps whatever is in them. Counted, a scene with fewer textures than those blocks hold started a run every time one was due
inline uint64_t returnable(uint64_t block_bytes, uint64_t free_bytes, uint64_t kept) {
    return std::min(free_bytes, block_bytes - std::min(block_bytes, kept));
}

/// Whether the textures' pool is down to its blocks made at the start. VMA keeps those, so nothing an eviction frees comes off
/// the driver's count: the rule that squeezes by the count alone (97% of the allowance) waits, as it does for room in the blocks
inline bool kept_only(uint64_t block_bytes, uint64_t kept) { return kept && block_bytes <= kept; }

/// The driver's count, in percent of its allowance, above which the textures give up the excess. 97 on a dedicated card, whose
/// driver pages what is past the allowance out to system memory. 90 on an integrated GPU: its heap is the PC's RAM, with nowhere
/// to page to, so past the allowance the driver's own allocations fail. A UHD Graphics (i3-1115G4, 7.0 GB allowed) at 6.7 GB
/// entered Hyrule Castle, its imports grew by 560 MB, and at 7.5 of 7.0 GB graphics pipelines were not made (-2) and the next
/// vkCmdDispatchIndirect faulted inside igvk64.dll; 3% of the allowance is 215 MB of room, 10% is 717
inline uint64_t count_line_pct(bool integrated) { return integrated ? 90 : 97; }

/// Whether VMA's blocks hold room enough (an eighth of the allowance free) that the count line's squeeze waits: new images take
/// that space and the count does not grow. Not past the allowance, where a dedicated card's driver pages (#2156), and not on an
/// integrated GPU: what grows there near the line is the driver's own (pipelines, command memory) and the staging arenas, which
/// no block's free space takes. The UHD Graphics above sat at 6,709 of 7,172 MB with 1,121 MB of it free in the blocks, so the
/// squeeze waited; Hyrule Castle's load then took the count to 7.5 GB
inline bool room_in_blocks(uint64_t used, uint64_t allowed, uint64_t block_free, bool integrated) {
    return !integrated && used <= allowed && block_free >= allowed / 8;
}

/// What the textures give up once the driver has refused a pipeline for want of memory (VK_ERROR_OUT_OF_DEVICE_MEMORY or
/// _HOST_MEMORY): the count's excess over its line, and kShortGive at least, whatever the blocks hold free. The count is read
/// every 10 frames (3 s at the UHD Graphics' 3.5 fps); the refusals say it sooner, and the UHD Graphics' next indirect dispatch
/// after six of them faulted inside igvk64.dll
inline constexpr uint64_t kShortGive = 256ull << 20;
inline uint64_t short_excess(uint64_t used, uint64_t count_line) {
    return std::max<uint64_t>(used > count_line ? used - count_line : 0, kShortGive);
}

/// The allowance as the rules take it, from the driver's count (used) and allowance: one the driver gives as the count itself,
/// within kAtCount, is past: AMD's Windows driver reports a process over what it allows as allowed what it uses (an RX 6600 at
/// 5940 of 5940 MB, another at 6.6 of 6.6 GB after 5.3 of 6.5: #933, #1025). Taken as it is, every rule saw the count within it
/// while the driver paged. Then a tenth under the count (kPastShare), so the rules give back until the driver says again how
/// much it allows. An allowance under the count is past already and stays as it is; 0 (unknown) too
inline constexpr uint64_t kAtCount = 16ull << 20;
inline constexpr uint64_t kPastShare = 10;
inline uint64_t past_allowance(uint64_t used, uint64_t allowed) {
    if (!allowed || allowed + kAtCount < used || allowed > used + kAtCount) return allowed;
    return used - used / kPastShare;
}

/// The presents between the end of a run and the next look
inline uint64_t rest(bool is_pressed) { return is_pressed ? 120 : 600; }

/// The free space the texture budget takes off the driver's count: the textures' pool's alone, which a run gives back. What the
/// other blocks hold free (the render targets', the buffers') stays in the count and no texture can take it; taken off as well,
/// it let the cache grow until the count was at the limit (99% eight times in five minutes, 850 MB free where no texture goes)
inline uint64_t reclaimable(uint64_t block_free, uint64_t pool_free) { return std::min(block_free, pool_free); }

/// The texture budget that holds the count, as it will be once a run has given `reclaim` back, at pct% of the allowance:
/// what the textures hold (total) less the excess, and never more than the budget was
/// Sane texture working set floor to prevent thrashing and downward budget ratcheting.
/// Preserves a 1800 MB baseline on < 8 GB cards for complex open-world scenes (e.g. Kokiri Forest, Hyrule Field).
inline uint64_t texture_min_floor(uint64_t allowed) {
    if (!allowed) return 0;
    if (allowed < GLOBAL_MIN_GRAPHICS_REQ) return 1800ull << 20;
    return std::max<uint64_t>(1800ull << 20, allowed / 4);
}

/// Dynamic texture floor with hysteresis targeting the 86%-92% VRAM sweet spot on constrained GPUs.
inline uint64_t update_dynamic_floor(uint64_t current_floor, uint64_t total_bytes, uint64_t used, uint64_t pressure, uint64_t allowed) {
    const uint64_t min_floor = texture_min_floor(allowed);
    if (!allowed || allowed >= GLOBAL_MIN_GRAPHICS_REQ) return min_floor;

    const uint64_t max_floor = std::max(min_floor, allowed / 2);
    uint64_t floor = current_floor ? std::clamp(current_floor, min_floor, max_floor) : min_floor;

    const uint64_t sweet_low = allowed / 100 * 86;
    const uint64_t sweet_high = allowed / 100 * 92;
    const uint64_t hard_high = allowed / 100 * 95;
    const uint64_t emergency_high = allowed / 100 * 97;
    constexpr uint64_t kStep = 32ull << 20;

    if (used > emergency_high) {
        floor = min_floor;
    } else if (pressure > sweet_high || used > hard_high) {
        floor = floor > min_floor + kStep ? floor - kStep : min_floor;
    } else if (pressure < sweet_low && used < sweet_high && total_bytes >= floor / 10 * 9) {
        const uint64_t demand_cap = std::min<uint64_t>(max_floor, total_bytes + (64ull << 20));
        if (floor < demand_cap) {
            floor = std::min(demand_cap, floor + kStep);
        }
    }
    return std::clamp(floor, min_floor, max_floor);
}

/// The texture budget that holds the count at pct% of `allowed`, with damped contraction on constrained GPUs.
inline uint64_t held_budget(uint64_t budget, uint64_t total, uint64_t used, uint64_t reclaim, uint64_t allowed, uint64_t pct, uint64_t floor_override = 0) {
    const uint64_t line = allowed / 100 * pct;
    const uint64_t pressure = used - std::min(used, reclaim);
    if (!allowed || pressure <= line) return budget;
    const uint64_t over = pressure - line;
    // Damped contraction (alpha = 0.25) on < 8 GB GPUs to smoothly absorb transient frame spikes without thrashing.
    const uint64_t damped_over = (allowed < GLOBAL_MIN_GRAPHICS_REQ) ? (over / 4) : over;
    uint64_t target = total > damped_over ? total - damped_over : 0;
    const uint64_t floor = floor_override ? floor_override : texture_min_floor(allowed);
    if (floor && target < floor) {
        target = floor;
    }
    uint64_t res = std::min(budget, target);
    if (floor && res < floor) res = floor;
    return res;
}

/// What the hold lets go of has gone unused for this many presents (ten seconds at 60 fps). The eviction's own 60 is right for a
/// budget that is a size: over it, something has to go. The hold's line is crossed for as long as the rest of the game's VRAM
/// leaves the scene's textures no room under it, and then every texture out of view for a second went and came back when the
/// camera turned: with the count held under a 7 GB allowance, a turning camera in Hyrule Field at DLAA let go of 2.3-2.6 GB of live
/// textures every 600 presents and uploaded 6.8 GB in 50 seconds, against 1.4 GB with the compaction off
inline constexpr uint64_t kHoldUnused = 180;

/// Whether the hold's pass keeps a texture no render target has drawn over: one used in the last kHoldUnused presents
inline bool hold_keeps(uint64_t unused) { return unused < kHoldUnused; }

/// The reserve: a second line, kReservePoints points of the allowance under the hold's own (80 for 85). Over it the hold lets go
/// of textures unused for kReserveUnused presents (30 seconds at 60 fps), down to that line. With one line the cache sat at it,
/// and whatever came in next went over: in a walk across Hyrule Field at DLAA with 768 MB of the card held by something else the
/// count was over 85% of the allowance for 47-68% of the time and over 87% for 7-26% (peaks of 91-93%), and in play with a
/// recorder running the GPU's frame went from 11 to 15-23 ms for ten seconds each time it reached 87-90%. With the reserve:
/// over 85% for 5%, over 87% for 0-1%, peaks of 87-88%, no more uploads
inline constexpr uint64_t kReservePoints = 5;
inline constexpr uint64_t kReserveUnused = 600;

/// A texture's presents unused, as many as they would have been at 60 fps (fps: the presents a second lately), for the hold's and
/// the reserve's waits above (kHoldUnused, kReserveUnused), which are seconds at 60 fps. Counted as presents they stretch with the frame rate: at
/// 3.5 fps (a UHD Graphics laptop, i3-1115G4) three and nine minutes, and the hold let go of next to nothing (1,776 MB of textures
/// against a budget of 1,299 MB, 0 to 13 of them retired a pass). At 60 fps or more, or with no rate known, as counted; under
/// kMinFps as at kMinFps, so that a load's stall does not age every texture at once. The eviction's own wait stays in presents,
/// and the rendered textures' keep has a floor in presents (keep_rendered::at_rate): the game samples some of those every so
/// many of its frames, whatever the frame rate
inline constexpr double kMinFps = 2.0;
inline uint64_t age_at_60(uint64_t unused, double fps) {
    if (!(fps > 0) || fps >= 60) return unused;
    return (uint64_t)((double)unused * 60.0 / std::max(fps, kMinFps));
}
inline uint64_t reserve_pct(uint64_t pct) { return pct > kReservePoints ? pct - kReservePoints : 0; }

/// What the rules that are not the hold's (the budget's size, the 90% rule, the driver's limit at 97%) ask an eviction to go down
/// to on their own: 7/8 of their budget once the textures hold more than it, as a pass over the budget cuts with the compaction
/// off; UINT64_MAX: nothing
inline uint64_t rule_target(uint64_t total, uint64_t rule_budget) { return total > rule_budget ? rule_budget / 8 * 7 : UINT64_MAX; }

/// The same, with the budget's size (size_budget) told from what the 90% rule and the driver's limit made of it (rule_budget,
/// never more). Those two are not sizes: each is "what the textures hold less the excess over a line", as the hold's is, and is
/// crossed again whenever anything grows. Cut to 7/8 of it, a few MB over the line took an eighth of the cache: Castle Town
/// Market entered from Hyrule Field on an 8 GB card sat 60 MB over the 90% line and lost ~400 MB of textures unused for a
/// second, all on screen again within the camera's turn, made again, over the line again: 2.5 <-> 2.95 GB every few seconds,
/// 8-9 uploads a frame and 16-25 frames over 50 ms in 30 s, where the same scene loaded from a save (just under the line) had
/// none. So for them what goes is the excess and kExcessSlack more, so that not every pass is one; the budget's size still asks
/// for its 7/8
inline constexpr uint64_t kExcessSlack = 64ull << 20;
inline uint64_t rule_target(uint64_t total, uint64_t size_budget, uint64_t rule_budget) {
    uint64_t to = rule_target(total, size_budget);
    if (rule_budget < size_budget && total > rule_budget) to = std::min(to, rule_budget - std::min(rule_budget, kExcessSlack));
    return to;
}

/// What a live texture unused for that many presents may be let go down to in the hold's pass, the lowest of the lines that
/// apply to it; UINT64_MAX: it stays. Three tiers:
/// - unused for need_unused (the eviction's own 60 presents): what the other rules ask for (rule_to). Over 90% of the allowance
///   or over the budget's size something has to go now, and the hold's patience is not theirs: with the hold's two thresholds
///   alone, a pass the 90% rule asked for took nothing used in the last ten seconds, and the reserve's lower budget made every
///   such pass a hold's pass, on the cards whose count sits past 90%
/// - unused for kHoldUnused: the hold's own line too (hold_to, 0 while it is not crossed)
/// - unused for kReserveUnused: and the reserve's (reserve_to)
inline uint64_t hold_target(uint64_t unused, uint64_t need_unused, uint64_t rule_to, uint64_t hold_to, uint64_t reserve_to) {
    uint64_t to = unused >= need_unused ? rule_to : UINT64_MAX;
    if (!hold_keeps(unused) && hold_to) to = std::min(to, hold_to);
    if (unused >= kReserveUnused) to = std::min(to, reserve_to);
    return to;
}

/// Whether the hold's pass is done with live textures: those it has chosen (live) and the dead render targets it lets go in any
/// case (dead) bring what the textures hold (total) down to evict_to. The dead ones count first: they are the youngest of the
/// textures, and a pass that stopped at the first texture past the excess, oldest first, never reached them, so while the hold
/// was on, live textures went in their place and the dead targets piled up (0.9 to 3.5 GB of them in 120 presents as a new
/// stretch of Hyrule Field came in, the count over what the driver allows, frames of 60-128 ms for three seconds)
inline bool hold_met(uint64_t total, uint64_t live, uint64_t dead, uint64_t evict_to) {
    const uint64_t going = live + dead;
    return going >= total || total - going <= evict_to;
}

}   // namespace vram_compact
