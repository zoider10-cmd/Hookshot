// (hookshot) The steps of a start that a crash in the driver would repeat at every start, each with a file beside the notes that
// says it began and has not ended: the stage libraries' (hookshot_prepared.bin.warming), the predicted pipelines'
// (hookshot_pipelines.bin.predicting), the warm into the pipeline cache's (hookshot_pipelines.bin.built.warming) and the
// precompile's (hookshot_pipelines.bin.running), vk_draw.cpp. The next start reads it and, after one or two starts that ended
// inside, goes on without that step. Only a crash (or a kill) may count. A close does not: the window's close, the Insert
// menu's Quit and Restart now and the control socket's quit all end the process at once (ExitProcess: no destructor runs, no
// thread is joined), so the step's file was left as if the start had crashed there, and two quits in the precompile dropped
// its notes. The close (mkwvk_close_asked, which each of them calls first) puts every step still open back as its start found
// it. tests/test_quit_not_crash.py.
#pragma once

#include <cstddef>
#include <cstdio>
#include <mutex>
#include <string>
#include <vector>

namespace crash_markers {

/// A count for no file at all
constexpr int none = -1;

namespace detail {
struct Open {
    std::string path;
    int closed;   // (what a close leaves in the file)
};
struct State {
    std::mutex mu;
    std::vector<Open> open;
    bool closing = false;
};
/// (never freed: the close's ExitProcess can come while a step's thread is still in begin() or end())
inline State& state() {
    static State* s = new State;
    return *s;
}
/// The file holds `count` (none: there is no file)
inline void put(const std::string& path, int count) {
    if (count == none) std::remove(path.c_str());
    else if (FILE* f = std::fopen(path.c_str(), "wb")) std::fprintf(f, "%d\n", count), std::fclose(f);
}
inline void forget(State& s, const std::string& path) {
    for (std::size_t i = 0; i < s.open.size(); i++)
        if (s.open[i].path == path) {
            s.open.erase(s.open.begin() + (std::ptrdiff_t)i);
            return;
        }
}
} // namespace detail

/// A step begins: its file holds `count` from now on. A close before end() leaves `closed` there instead (none: no file), as the
/// start found it, so that a start the player closed counts neither as one that crashed in the step nor as one that got through
inline void begin(const std::string& path, int count, int closed) {
    detail::State& s = detail::state();
    std::lock_guard lk(s.mu);
    if (s.closing) return;
    detail::forget(s, path);
    detail::put(path, count);
    s.open.push_back({path, closed});
}

/// The step got through (or its file is no longer wanted): the file goes
inline void end(const std::string& path) {
    detail::State& s = detail::state();
    std::lock_guard lk(s.mu);
    if (s.closing) return;
    detail::forget(s, path);
    std::remove(path.c_str());
}

/// The player is closing the game: every step still open has its file put back as its start found it, whether its workers
/// stopped in time or are still at work. From then on begin() and end() do nothing: the files stay as the start found them
/// until the process ends a moment later, whatever a worker still running does (a restart's new process may already read them)
inline void close() {
    detail::State& s = detail::state();
    std::lock_guard lk(s.mu);
    s.closing = true;
    for (const detail::Open& o : s.open) detail::put(o.path, o.closed);
    s.open.clear();
}

} // namespace crash_markers
