// (hookshot) The pipeline cache written before the title after a start that compiled its noted pipelines (vk_draw.cpp
// precompile_run), and what a forced save did, in words (pipeline_cache_save). In play the cache is written only once it has
// grown 64 MB (RX_VK_PLAY_SAVE_START_MB). A start that compiled every noted pipeline under new keys grew it far less on RADV:
// 4.3 MB for 32,438 pipelines on a Steam Deck, because Mesa keeps a pipeline as its key and the hashes of its shaders, and the
// shaders' code was already in the cache. Unwritten, the next start had to find them all again in the driver's own folder.
// RX_VK_PRECOMPILE_SAVE_S=<s>: the precompile's build time that writes it (30; 0: never). Standard library only:
// tests/precompile_save_test.cpp.
#pragma once
#include <cstddef>
#include <cstdio>
#include <cstdlib>
#include <string>

namespace precompile_save {
constexpr int kDefaultS = 30;
/// RX_VK_PRECOMPILE_SAVE_S's value: unset or not a whole number of seconds, the default; 0 never
inline int after_s(const char* value) {
    if (!value || !*value) return kDefaultS;
    char* end = nullptr;
    const long s = strtol(value, &end, 10);
    if (*end || s < 0) return kDefaultS;
    return s > 86400 ? 86400 : (int)s;
}
/// Whether the precompile writes the cache before the title: it got to its end (not left behind in the driver, not stopped),
/// in a game start (the preparation writes it anyway), and its pipelines took the time
inline bool due(double build_s, int save_s, bool gone_on, bool stopped, bool prepare_only) {
    return save_s > 0 && build_s >= save_s && !gone_on && !stopped && !prepare_only;
}
/// What a forced save did
struct Outcome {
    enum What { kNotRun, kWritten, kSame, kOff, kNoCache, kFetchFailed, kWriteFailed, kError } what = kNotRun;
    size_t bytes = 0;     // (the cache's size: written, or as it was)
    std::string detail;   // (kWriteFailed: the file; kError: the exception's words)
};
inline std::string mb(size_t bytes) {
    char b[32];
    snprintf(b, sizeof b, "%.1f MB", bytes / 1048576.0);
    return b;
}
inline std::string said(const Outcome& o) {
    switch (o.what) {
    case Outcome::kWritten: return "written, " + mb(o.bytes);
    case Outcome::kSame: return "not written: nothing new since it was read or last written (" + mb(o.bytes) + ")";
    case Outcome::kOff: return "not written: saving is off (RX_VK_PCACHE_LOAD=0)";
    case Outcome::kNoCache: return "not written: there is no pipeline cache";
    case Outcome::kFetchFailed: return "not written: the driver did not give its data";
    case Outcome::kWriteFailed: return "not written: " + o.detail + " could not be written";
    case Outcome::kError: return "not written: " + o.detail;
    default: return "not written: the save did not run";
    }
}
}  // namespace precompile_save
