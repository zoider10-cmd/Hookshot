/* (hookshot) The FPS counter's levels and its numbers (vk_fps.cpp measures, vk_menu.cpp draws): the row's values, the frames
   of the last seconds in a ring, their averages, the 1% low, the graph's columns and its scale. Plain functions:
   tests/test_fps_stats.cpp checks them. */
#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <vector>

namespace mkwvk::fps_stats {

/// The FPS counter row (opts.show_fps, saved as fps_counter=): an options file from before the levels has 0 Off or 1 On,
/// and 1 is the counter as it was, the number alone. Dev: the Breakdown and the renderer's own numbers under it (dev_line)
enum Level { kOff, kFps, kFrameTime, kGraph, kBreakdown, kDev, kLevels };
inline int level_of(int saved) { return std::clamp(saved, (int)kOff, (int)kLevels - 1); }
inline const char* level_name(int v) {
    static const char* const t[] = {"Off", "FPS", "Frame time", "Graph", "Breakdown", "Dev"};
    return t[level_of(v)];
}

/// The Dev level's lines, under the Breakdown's: their names, and their values from the renderer's counters (vk_menu.cpp
/// fps_texts, every half second: the counts a frame over that half second, the uploads a second)
/// (hookshot) and the renderer's pressure: its waits for a recording slot (the GPU behind), its queue submits (the driver's
/// and the kernel's time) and the GPU's results written back to the game's memory, a frame each
enum DevLine { kVram, kTextures, kDraws, kDispatches, kPasses, kSkipped, kUploads, kPipelines, kSlotWait, kQueueSubmit,
               kWriteBack, kDevLines };
inline const char* dev_name(int i) {
    static const char* const t[] = {"VRAM", "Textures", "Draws / frame", "Dispatches / frame", "Render passes / frame",
                                    "Draws skipped / frame", "Texture uploads", "Pipelines built", "GPU slot waits / frame",
                                    "Queue submits / frame", "Write-backs / frame"};
    return i >= 0 && i < kDevLines ? t[i] : "";
}
/// (hookshot) the names in the Dev level's grid, two to a row: short, the details page's rows have the full ones
inline const char* dev_short(int i) {
    static const char* const t[] = {"VRAM", "Textures", "Draws", "Dispatches", "Passes", "Skipped", "Uploads", "Pipelines",
                                    "Slot waits", "Submits", "Write-backs"};
    return i >= 0 && i < kDevLines ? t[i] : "";
}
/// The grid's order after VRAM (which has a row of its own, its value is long): pairs that read together
constexpr int kDevGrid[kDevLines - 1] = {kTextures, kUploads, kDraws, kDispatches, kPasses, kSkipped, kSlotWait, kQueueSubmit,
                                         kWriteBack, kPipelines};
inline double dev_gb(uint64_t bytes) { return bytes / (1024.0 * 1024.0 * 1024.0); }
/// "5.2 of 7.8 GB": what the game uses of what the driver allows it (VK_EXT_memory_budget); without a budget, its own "5.2 GB"
inline int vram_line(char* b, size_t n, uint64_t used, uint64_t allowed, bool known) {
    if (known && allowed) return snprintf(b, n, "%.1f of %.1f GB", dev_gb(used), dev_gb(allowed));
    return snprintf(b, n, "%.1f GB", dev_gb(used));
}
/// "1843, 2.1 GB": the textures the renderer holds and their memory
inline int textures_line(char* b, size_t n, uint64_t count, uint64_t bytes) {
    return snprintf(b, n, "%llu, %.1f GB", (unsigned long long)count, dev_gb(bytes));
}
/// A count a frame: what a counter moved over the window, by the frames in it ("2481"; "-" without a frame)
inline int per_frame_line(char* b, size_t n, int64_t moved, int frames) {
    if (frames <= 0) return snprintf(b, n, "-");
    return snprintf(b, n, "%lld", (long long)((std::max<int64_t>(moved, 0) + frames / 2) / frames));
}
/// "12.3 MB/s": bytes over the window's seconds
inline int rate_line(char* b, size_t n, int64_t bytes, double seconds) {
    if (seconds <= 0) return snprintf(b, n, "-");
    return snprintf(b, n, "%.1f MB/s", std::max<int64_t>(bytes, 0) / (1024.0 * 1024.0) / seconds);
}

/// The FPS counter position row (opts.fps_corner): bit 0 the left side, bit 1 the bottom
inline const char* corner_name(int v) {
    static const char* const t[] = {"Top right", "Top left", "Bottom right", "Bottom left"};
    return t[std::clamp(v, 0, 3)];
}

/// Where a frame's time went, on the thread that presents (the parts add up to the frame's time): the game's code (what
/// is left), the renderer's recording and submitting, waits for the GPU (a recording slot, OoT's own poll for its frame's
/// GPU work), and the wait for the frame's turn (the frame pacing, the game's own sleeps, vsync). (hookshot) And the game's
/// waits for its fences, on any of its threads (OoT's main thread makes most): for work the renderer had not recorded yet
/// (kWaitRender), or had and the GPU had not run yet (kWaitGpu). On another thread they are carved out of the game's part:
/// the presenting thread waited for that thread meanwhile. kWaitRender also takes the present's wait for room (the render
/// thread a frame behind). kWaitMain: with the render thread, the present's wait for the main thread's signal that the frame
/// is written (the game's own time, until then in the renderer's part)
enum Part { kGame, kRender, kGpuWait, kPace, kWaitRender, kWaitGpu, kWaitMain, kParts };
/// (hookshot) The render thread's frame (threaded rendering): its recording and submitting (what is left), its waits for the
/// parallel replay's workers, for the GPU (a recording slot), and for work (idle). Over the same present-to-present span
enum RenderPart { kRtWork, kRtWorkers, kRtGpu, kRtIdle, kRtParts };

struct Frame {
    int64_t at_ns = 0;          // (its present)
    float ms = 0;               // (present to present)
    float part[kParts] = {};    // (ms)
    float gpu_ms = 0;           // (the GPU's own time for the recordings timed since the frame before: a few frames late)
    float rt[kRtParts] = {};    // (the render thread's, ms; all 0 without a render thread)
    uint16_t pipelines = 0;     // (pipelines made since the frame before: shaders built in play)
    uint16_t left_out = 0;      // (draws left out because their pipeline was not ready)
};

/// The parts of a frame of `ms`: what was measured on the presenting thread, scaled down if it is more than the frame (a wait
/// that began before the frame did), and the game's the rest; then the fence waits of the game's other threads taken out of
/// the game's part, as far as it goes
inline void split(Frame& f, double ms, double render, double gpu_wait, double pace, double wait_render = 0, double wait_gpu = 0,
                  double other_render = 0, double other_gpu = 0, double wait_main = 0) {
    f.ms = (float)ms;
    render = std::max(render, 0.0), gpu_wait = std::max(gpu_wait, 0.0), pace = std::max(pace, 0.0);
    wait_render = std::max(wait_render, 0.0), wait_gpu = std::max(wait_gpu, 0.0), wait_main = std::max(wait_main, 0.0);
    const double sum = render + gpu_wait + pace + wait_render + wait_gpu + wait_main;
    const double k = sum > ms && sum > 0 ? std::max(ms, 0.0) / sum : 1.0;
    f.part[kRender] = (float)(render * k), f.part[kGpuWait] = (float)(gpu_wait * k), f.part[kPace] = (float)(pace * k);
    double game = std::max(0.0, ms - sum * k);
    const double other_r = std::min(std::max(other_render, 0.0), game);
    game -= other_r;
    const double other_g = std::min(std::max(other_gpu, 0.0), game);
    game -= other_g;
    f.part[kWaitRender] = (float)(wait_render * k + other_r), f.part[kWaitGpu] = (float)(wait_gpu * k + other_g);
    f.part[kWaitMain] = (float)(wait_main * k);
    f.part[kGame] = (float)game;
}

/// The last N frames (N a power of two): back(0) the newest
template <int N>
struct Ring {
    static_assert((N & (N - 1)) == 0, "a power of two");
    Frame f[N];
    uint64_t pushed = 0;
    void push(const Frame& x) { f[pushed++ & (N - 1)] = x; }
    int size() const { return (int)std::min<uint64_t>(pushed, N); }
    const Frame& back(int i) const { return f[(pushed - 1 - (uint64_t)i) & (N - 1)]; }
    void clear() { pushed = 0; }
};
constexpr int kRing = 16384;              // (10 s at 1600 fps: the 1% low's window whole with the cap Uncapped (1000))
constexpr int64_t kSecond = 1000000000;
constexpr int64_t kGraphWindow = 4 * kSecond;   // (the graph's span)
constexpr int64_t kLowWindow = 10 * kSecond;    // (the 1% low's)

/// The 1% low: the frame rate of the slowest 1% of these frames (at least one), as 1000 over their mean time. ms is
/// reordered. 0 for no frames
inline double one_percent_low(float* ms, int n) {
    if (n <= 0) return 0;
    const int k = std::max(1, (n + 99) / 100);
    std::nth_element(ms, ms + (n - k), ms + n);
    double sum = 0;
    for (int i = n - k; i < n; i++) sum += ms[i];
    return sum > 0 ? 1000.0 * k / sum : 0;
}

struct Summary {
    int frames = 0;            // (in the window)
    double avg_ms = 0;         // (the mean frame time over the window)
    double part[kParts] = {};  // (each part's mean)
    double gpu_ms = 0;         // (the GPU's mean time a frame)
    double rt[kRtParts] = {};  // (the render thread's parts' means)
    int pipelines = 0, left_out = 0;   // (summed over the window)
    double low_fps = 0;        // (the 1% low over the low window)
};

/// The frames presented in (now - window, now], and the 1% low over (now - low_window, now]
template <int N>
Summary summarize(const Ring<N>& r, int64_t now, int64_t window, int64_t low_window) {
    Summary s;
    static thread_local std::vector<float> low;
    low.clear();
    for (int i = 0; i < r.size(); i++) {
        const Frame& f = r.back(i);
        const int64_t age = now - f.at_ns;
        if (age >= std::max(window, low_window)) break;
        if (age < low_window) low.push_back(f.ms);
        if (age >= window) continue;
        s.frames++;
        s.avg_ms += f.ms;
        for (int p = 0; p < kParts; p++) s.part[p] += f.part[p];
        s.gpu_ms += f.gpu_ms;
        for (int p = 0; p < kRtParts; p++) s.rt[p] += f.rt[p];
        s.pipelines += f.pipelines, s.left_out += f.left_out;
    }
    if (s.frames) {
        s.avg_ms /= s.frames, s.gpu_ms /= s.frames;
        for (double& p : s.part) p /= s.frames;
        for (double& p : s.rt) p /= s.frames;
    }
    s.low_fps = one_percent_low(low.data(), (int)low.size());
    return s;
}

/// The graph's columns, oldest left: column c holds the frames presented in its share of (now - window, now]; out[c] is
/// the back() index of its slowest frame, -1 for none; marks[c] whether one of its frames built pipelines or left draws out
/// (hookshot) A column is a fixed slot of time (window / count), not a share of the window back from now: a frame stays in its
/// column while the graph scrolls, and the columns do not change between two draws (the line jumped as the shares slid over
/// the frames). The newest column is the one now is in; *scroll, if asked, how far into its slot now is (0 to 1), for a
/// smooth scroll
template <int N>
void columns(const Ring<N>& r, int64_t now, int64_t window, int count, int* out, bool* marks, double* scroll = nullptr) {
    for (int c = 0; c < count; c++) out[c] = -1, marks[c] = false;
    if (scroll) *scroll = 0;
    if (count <= 0 || window <= 0) return;
    const int64_t span = std::max<int64_t>(1, window / count), slot_now = now / span;
    if (scroll) *scroll = (double)(now - slot_now * span) / (double)span;
    for (int i = 0; i < r.size(); i++) {
        const Frame& f = r.back(i);
        const int64_t back = slot_now - f.at_ns / span;
        if (back >= count) break;
        if (back < 0) continue;
        const int c = count - 1 - (int)back;
        if (out[c] < 0 || f.ms > r.back(out[c]).ms) out[c] = i;
        if (f.pipelines || f.left_out) marks[c] = true;
    }
}

/// The Game frame rate cap row's rate (-1 30, 0 60, then 90, 120, 144, 165, 240; 6 Uncapped: 0, no rate); HOS_FPS_MAX over it
/// (env_max, 0 when not set: host/nn_vi.c fps_max's rules, 1000 and over is uncapped)
inline int cap_rate(int fps_cap, int env_max = 0) {
    if (env_max == 30 || (fps_cap == -1 && env_max <= 0)) return 30;
    static const int rates[] = {60, 90, 120, 144, 165, 240, 0};
    if (env_max > 0) return env_max >= 1000 ? 0 : std::max(env_max, 60);
    return fps_cap >= 0 && fps_cap <= 6 ? rates[fps_cap] : 60;   // (a value this build does not know: 60, as the host)
}
/// The frame time the game aims for, in ms: the cap's, or with V-Sync On (FIFO, no frame generation) the display's refresh
/// when that is slower; 0 when there is none (Uncapped, without V-Sync)
inline double target_ms_for(int cap, bool vsync_on, int refresh_hz) {
    int rate = cap;
    if (vsync_on && refresh_hz > 0) rate = rate ? std::min(rate, refresh_hz) : refresh_hz;
    return rate > 0 ? 1000.0 / rate : 0;
}
inline double target_ms(int fps_cap) { return target_ms_for(cap_rate(fps_cap), false, 0); }
/// The graph's top, in ms: twice the target, doubled until the usual frame fits (typical: a high percentile of the columns,
/// not the slowest, so one spike does not flatten the rest), four times the target at most. With no target (Uncapped):
/// from 4 ms, doubled until half again the usual frame fits, 100 at most. A frame past the top is drawn at it, and marked
inline double graph_top(double target, double typical) {
    if (target <= 0) {
        double top = 4;
        while (top < typical * 1.5 && top < 100) top *= 2;
        return std::min(top, 100.0);
    }
    double top = 2 * target;
    while (top < typical * 1.1 && top < 4 * target) top *= 2;
    return std::min(top, 4 * target);
}
/// The graph's typical frame: the 90th percentile of the columns' frame times (0 for none). ms is reordered
inline double typical_ms(float* ms, int n) {
    if (n <= 0) return 0;
    const int k = std::min(n - 1, n * 9 / 10);
    std::nth_element(ms, ms + k, ms + n);
    return ms[k];
}
/// The counter's colour for a frame rate against the cap's: 0 at it (5% under counts), 1 under it, 2 at under two thirds.
/// No target (Uncapped): against the console's 60
inline int rate_grade(double fps, double target_ms) {
    const double want = target_ms > 0 ? 1000.0 / target_ms : 60.0;
    return fps >= want * 0.95 ? 0 : fps >= want * 2 / 3 ? 1 : 2;
}

/// The frame time's text: "16.7 ms"
inline int frame_time_text(char* b, size_t n, double ms) { return snprintf(b, n, ms >= 100 ? "%.0f ms" : "%.1f ms", ms); }
/// (hookshot) the 1% low as a frame time, beside the frame time: the slowest 1% of frames' mean time ("1% low 40.0 ms"), from
/// its rate; "1% low -" with none
inline int low_text(char* b, size_t n, double fps) {
    if (fps <= 0) return snprintf(b, n, "1%% low -");
    const double ms = 1000.0 / fps;
    return snprintf(b, n, ms >= 100 ? "1%% low %.0f ms" : "1%% low %.1f ms", ms);
}

} // namespace mkwvk::fps_stats
