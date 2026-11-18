// (hookshot, issue 1280) A nothrow new that keeps its null at the commit limit. The renderer's new_handler (vk_main.cpp,
// new_refused) waits for memory when an allocation is refused, and stops the game with the out-of-memory notice when none comes
// back: a throwing new can do nothing else with a refusal. A nothrow new has a fallback of its own for a null (the recorder's
// ring, an arena's chunk, a capture's staging block), and libc++'s and libstdc++'s nothrow new call the throwing one and turn
// its std::bad_alloc into that null. Inside a NewNothrow scope the handler throws at once, so such a caller gets its null at
// once, as before the handler. The shader translation is in one too (vk_shader.cpp): a bad shader can ask for a size no PC has,
// and it fails that program, as before.
// Not in one, on purpose: the C++ library's own nothrow buffers (std::stable_sort's, std::inplace_merge's: get_temporary_buffer)
// and the renderer's catch blocks around allocations (vk_jobs.cpp run_guarded, the caches' inserts, thread starts). At the
// commit limit those wait for memory with every other allocation, then stop the game with the notice; before the handler the
// unwind to them often failed there anyway (0xc00000ff after the throw in the player reports).
#pragma once

namespace mkwvk {

inline constinit thread_local int t_new_nothrow = 0;   // (> 0: this thread is in a nothrow new that has a fallback)

struct NewNothrow {
    NewNothrow() { t_new_nothrow++; }
    ~NewNothrow() { t_new_nothrow--; }
    NewNothrow(const NewNothrow&) = delete;
    NewNothrow& operator=(const NewNothrow&) = delete;
};

}   // namespace mkwvk
