// (hookshot) What the order's watch thread (vk_replay.cpp sync_watch) does with queues stopped at a wait for longer than
// hold_ms: let them be, hold them on, or make them go past their waits (drain). Kept apart so the rule is checked without
// the renderer (tests/test_hold_gpu.py).
//
// hold_ms exists for a game that polls for the stopped work itself: nothing else would ever let it on. But the game's
// threads also wait for the GPU on recorded work of a queue with nothing stopped (OoT's main thread once a frame,
// nvnSyncWait on the last fence of the frame before), and the signal the stopped queues wait for is made after that wait.
// When the GPU took longer than hold_ms over that work (a load's uploads: ~100 ms), the watch thread made the stopped
// queues go, and the frame was drawn with what the game had not written yet: the lit scene and Link dark for a frame
// (issue 366; once or twice a run at Castle Town's gate, the dark frames left with the met-wait capture). They are held
// on while such a wait is under way and for hold_ms after it (the signal follows the wait: it is not made in it), most_ms
// at most since they stopped, so a wait that never ends cannot hold them for good.
#pragma once

namespace mkwvk::hold_gpu {
enum class Choice { Wait, Hold, Force };

/// on: the rule (RX_VK_HOLD_GPU_WAIT; off: Force as soon as hold_ms is past, as before)
/// gpu_wait: a thread of the game's is waiting for the GPU now
/// held_ms: since the queues stopped
/// since_gpu_wait_ms: since such a wait was last seen, or since the queues stopped, whichever is later
constexpr Choice choose(bool on, bool gpu_wait, double held_ms, double since_gpu_wait_ms, double hold_ms, double most_ms) {
    if (held_ms <= hold_ms) return Choice::Wait;
    if (!on || held_ms >= most_ms) return Choice::Force;
    if (gpu_wait || since_gpu_wait_ms <= hold_ms) return Choice::Hold;
    return Choice::Force;
}
}   // namespace mkwvk::hold_gpu
