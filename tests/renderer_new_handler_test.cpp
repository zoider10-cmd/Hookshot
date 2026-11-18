// The renderer's C++ allocations at the commit limit (gpu/vk/vk_main.cpp new_refused, issue 1280), around the real new_handler
// and its constants cut out by tests/test_renderer_new_handler.py: a clock that the sleep moves, a log that is kept, and a host
// whose out_of_memory throws GaveUp here (in the game it does not return). The refusals are real: 1 PB, more than any PC's
// address space, asked of the C++ library's own operator new, which calls the handler each time malloc says no and tries again
// when it returns. No game, window or GPU. Each case in its own process (the handler's state is per thread).
#include <atomic>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <new>
#include <string>

#include "gpu/vk/vk_api.h"
#include "gpu/vk/vk_new.h"

static const char* scenario = "";
#define CHECK(x)                                                                                    \
    do {                                                                                            \
        if (!(x)) {                                                                                 \
            std::fprintf(stderr, "FAIL %s:%d: %s\n", scenario, __LINE__, #x);                       \
            std::exit(1);                                                                           \
        }                                                                                           \
    } while (0)

// (a std::bad_alloc, as the C++ libraries' nothrow new turn only that into their null: libstdc++ catches bad_alloc alone)
struct GaveUp : std::bad_alloc {};

namespace mkwvk {
static int64_t now_ms = 1000000, slept_ms;
static int sleeps, oom_calls, logs;
static std::string oom_what, last_log;
const MkwVkHost* host;
int64_t steady_ms() { return now_ms; }
void logf(const char* fmt, ...) {
    char b[512];
    va_list a;
    va_start(a, fmt);
    std::vsnprintf(b, sizeof b, fmt, a);
    va_end(a);
    last_log = b, logs++;
}
#include "renderer_new_handler_head.inc"
static void new_sleep_ms(int ms) { sleeps++, slept_ms += ms, now_ms += ms; }
#include "renderer_new_handler_body.inc"
}   // namespace mkwvk

static void fake_out_of_memory(const char* what) {
    mkwvk::oom_calls++, mkwvk::oom_what = what;
    throw GaveUp();
}
static MkwVkHost host_v28, host_v27;
static volatile size_t big = size_t(1) << 50;   // (1 PB: refused on any PC)
static void* volatile kept;

// run stmt: 1 if the host's out_of_memory ran (GaveUp), 2 if std::bad_alloc came out instead, 0 if it returned
template <class F>
static int ends(F stmt) {
    try {
        stmt();
    } catch (const GaveUp&) {
        return 1;
    } catch (const std::bad_alloc&) {
        return 2;
    }
    return 0;
}

static bool gave_up_after_5s() {
    using namespace mkwvk;
    return oom_calls == 1 && oom_what == "the renderer's C++ allocations" && sleeps == 100 && slept_ms == 5000 && logs == 1 &&
           last_log.find("tried again for up to 5 s") != std::string::npos;
}

int main(int argc, char** argv) {
    using namespace mkwvk;
    scenario = argc > 1 ? argv[1] : "";
    host_v28.version = 28, host_v28.out_of_memory = fake_out_of_memory;
    host_v27.version = 27, host_v27.out_of_memory = fake_out_of_memory;   // (an older host: the slot is not its)
    host = &host_v28;
    std::set_new_handler(new_refused);
    if (!std::strcmp(scenario, "limit")) {   // (operator new: 5 s of tries, then the host's out-of-memory stop)
        CHECK(ends([] { kept = ::operator new(big); }) == 1);
        CHECK(gave_up_after_5s());
    } else if (!std::strcmp(scenario, "aligned")) {   // (operator new with an alignment: the same)
        CHECK(ends([] { kept = ::operator new(big, std::align_val_t(64)); }) == 1);
        CHECK(gave_up_after_5s());
    } else if (!std::strcmp(scenario, "array")) {   // (new[]: the same)
        CHECK(ends([] { kept = new uint8_t[big]; }) == 1);
        CHECK(gave_up_after_5s());
    } else if (!std::strcmp(scenario, "continues")) {   // (one refusal's tries, each right after the last: one 5 s in all)
        for (int i = 0; i < 100; i++) CHECK(ends([] { new_refused(); }) == 0);
        CHECK(sleeps == 100 && slept_ms == 5000 && oom_calls == 0 && logs == 1);
        CHECK(ends([] { new_refused(); }) == 1);
        CHECK(gave_up_after_5s());
    } else if (!std::strcmp(scenario, "apart")) {   // (a refusal a second after the last try: a new one, with a whole wait)
        for (int i = 0; i < 60; i++) CHECK(ends([] { new_refused(); }) == 0);
        now_ms += 1000;
        for (int i = 0; i < 100; i++) CHECK(ends([] { new_refused(); }) == 0);
        CHECK(sleeps == 160 && oom_calls == 0 && logs == 2);
        CHECK(ends([] { new_refused(); }) == 1);
        CHECK(oom_calls == 1 && sleeps == 160);
    } else if (!std::strcmp(scenario, "nothrow")) {   // (in a NewNothrow scope: the null at once, no wait, no stop)
        const NewNothrow scope;
        CHECK(::operator new(big, std::nothrow) == nullptr);
        CHECK(::operator new(big, std::align_val_t(64), std::nothrow) == nullptr);   // (the recorder's ring and arena)
        kept = new (std::nothrow) uint8_t[big];   // (a capture's staging block; kept: clang may fold a new compared with null alone)
        CHECK(kept == nullptr);
        CHECK(sleeps == 0 && oom_calls == 0 && logs == 0);
    } else if (!std::strcmp(scenario, "nothrow-unscoped")) {   // (why the scope: without it a nothrow new waits and stops too)
        CHECK(::operator new(big, std::align_val_t(64), std::nothrow) == nullptr);
        CHECK(gave_up_after_5s());
    } else if (!std::strcmp(scenario, "old-host")) {   // (a version-27 host has no out_of_memory: thrown, as before)
        host = &host_v27;
        CHECK(ends([] { kept = ::operator new(big); }) == 2);
        CHECK(sleeps == 100 && oom_calls == 0);
    } else if (!std::strcmp(scenario, "no-host")) {   // (before mkwvk_init: thrown, as before)
        host = nullptr;
        CHECK(ends([] { kept = ::operator new(big); }) == 2);
        CHECK(sleeps == 100 && oom_calls == 0);
    } else if (!std::strcmp(scenario, "small")) {   // (what is given is given: the handler never runs)
        kept = ::operator new(64);
        ::operator delete(kept);
        CHECK(sleeps == 0 && oom_calls == 0 && logs == 0);
    } else {
        std::fprintf(stderr, "unknown scenario %s\n", scenario);
        return 2;
    }
    std::printf("PASS %s\n", scenario);
    return 0;
}
