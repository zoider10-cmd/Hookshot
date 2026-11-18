/* (hookshot) The performance summary (perf_report.cpp gathers it, the launcher sends it: nx2/perf_report.py): what a
   player who ticked "Send performance statistics" in the launcher sends about their frames, split by the map they were
   on. Every few minutes and at the end the game writes one summary, the counts since the one before, into the game folder's
   perf_pending folder; the launcher sends them to the perf relay (Hookshot-api's telemetry, /telemetry/perf: telemetry/perf there, whose
   format this is) at its next start, and deletes them.

   Plain functions and a summary's data: tests/test_perf_report.cpp checks them. The bucket lists are the relay's
   (FRAME_BUCKETS_MS, GPU_BUCKETS_MS): change both together. */
#pragma once

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <map>
#include <string>

#include "fps_stats.h"

namespace mkwvk::perf_report {

/// Frame times around the usual refresh rates (240, 144, 120, 90, 60, 50, 40, 30, 20 fps) and the stutters past them, ms
constexpr double kFrameBuckets[] = {4.17, 6.94, 8.33, 11.1, 16.7, 20, 25, 33.3, 50, 100, 250, 1000};
constexpr int kFrameBucketCount = sizeof kFrameBuckets / sizeof kFrameBuckets[0] + 1;   // (+Inf last)
/// The GPU's own time a frame, ms
constexpr double kGpuBuckets[] = {2, 4, 6, 8.33, 11.1, 16.7, 25, 33.3, 50, 100};
constexpr int kGpuBucketCount = sizeof kGpuBuckets / sizeof kGpuBuckets[0] + 1;

template <size_t N>
inline int bucket_of(double ms, const double (&bounds)[N]) {
    for (size_t i = 0; i < N; i++)
        if (ms <= bounds[i]) return (int)i;
    return (int)N;
}

/// What a slow frame waited on most (the relay's CAUSES, in its order)
enum Cause { kPipelineWait, kShaderTranslate, kTextureUpload, kMemsync, kGpuBound, kReadback, kGameCpu, kPacing, kOther, kCauses };
inline const char* cause_name(int c) {
    static const char* const t[] = {"pipeline_wait", "shader_translate", "texture_upload", "memsync", "gpu_bound", "readback",
                                    "game_cpu", "pace", "other"};
    return c >= 0 && c < kCauses ? t[c] : "other";
}

/// The "map" before the game is in one: the start-up screen preparing the shaders, then the intro, title and file select
/// (the crash report names them the same: host/hos_crash_dialog.h)
constexpr const char* kPreparingShaders = "Preparing shaders";
constexpr const char* kTitleAndIntro = "Title and intro";

/// The renderer's events (the relay's EVENTS)
enum Event { kProgramFailed, kDeviceLost, kSwapchainRecreated, kMovieUpscalerDropped, kDlssRecreated, kVramOverBudget, kEvents };
inline const char* event_name(int e) {
    static const char* const t[] = {"program_failed", "device_lost", "swapchain_recreated", "movie_upscaler_dropped",
                                    "dlss_recreated", "vram_over_budget"};
    return e >= 0 && e < kEvents ? t[e] : "";
}

/// A frame's times beyond the FPS counter's parts, ms: from the renderer's counters, since the frame before
struct Waits {
    double pipeline = 0;    // (building pipelines and picking programs on the drawing threads)
    double translate = 0;   // (draws waiting for a shader translation, or translating one in place)
    double upload = 0;      // (texture uploads and their CPU unswizzle)
    double memsync = 0;     // (the guest memory's sync to the GPU)
    double readback = 0;    // (read-backs' waits for the GPU)
};

/// Seconds of play between summaries: RX_VK_PERF_INTERVAL's whole seconds, 60 to 840, else 300. A summary ends on the frame
/// past it, and the relay takes a map's seconds up to 900: 840 leaves a minute for that frame
constexpr int kPeriodDefault = 300, kPeriodMin = 60, kPeriodMax = 840;
/// The maps a summary holds at most: the relay refuses one with more (400), and the sender then deletes it. A map past them
/// ends the summary early (perf_report.cpp where_now)
constexpr int kMaxMaps = 16;
inline int summary_period(const char* env) {
    char* end = nullptr;
    const long s = env ? strtol(env, &end, 10) : 0;
    if (!env || end == env || *end) return kPeriodDefault;   // (unset, empty or not a number: the default)
    return (int)std::clamp<long>(s, kPeriodMin, kPeriodMax);
}

/// A hitch: a frame over twice its target, and at least 25 ms (a 240 fps frame twice as long is not a stutter anyone sees)
inline bool is_hitch(double ms, double target_ms) { return ms > std::max(2.0 * target_ms, 25.0); }

/// What the hitch waited on most: the renderer's own waits first, then the FPS counter's parts (the GPU's, the pacing's, the
/// game's); "other" when nothing measured is a quarter of the frame
inline Cause cause_of(const fps_stats::Frame& f, const Waits& w) {
    const double c[kCauses] = {w.pipeline, w.translate, w.upload, w.memsync, f.part[fps_stats::kGpuWait], w.readback,
                               f.part[fps_stats::kGame], f.part[fps_stats::kPace], 0};
    int best = kOther;
    double most = f.ms * 0.25;
    for (int i = 0; i < kOther; i++)
        if (c[i] > most) best = i, most = c[i];
    return (Cause)best;
}

/// A frame off its slot: more than a quarter of the target away from the frame before (uneven pacing, even at a good
/// average). Hitches are counted apart
inline bool is_pacing_miss(double ms, double last_ms, double target_ms) {
    return last_ms > 0 && std::abs(ms - last_ms) > 0.25 * target_ms;
}

/// The totals of one map since the summary before
struct MapTotals {
    bool fresh = true;   // (the first summary of this session with this map: the relay counts it as a session on it)
    double seconds = 0;
    int64_t frame[kFrameBucketCount] = {};
    double frame_sum = 0;
    int64_t gpu[kGpuBucketCount] = {};
    double gpu_sum = 0;
    double part[fps_stats::kParts] = {};
    int64_t hitch[kCauses] = {};
    int64_t pacing_misses = 0, left_out = 0;
    int64_t event[kEvents] = {};
    int64_t movie_shown = 0, movie_dropped = 0, movie_late = 0, movie_fallbacks = 0;
    double movie_decode_ms = 0;
    bool any() const {
        return seconds > 0 || movie_shown || movie_dropped || movie_late || movie_fallbacks || movie_decode_ms > 0 ||
               std::any_of(event, event + kEvents, [](int64_t v) { return v > 0; });
    }
};

/// usual_ms: the recent average frame. A hitch is measured against the longer of it and the target: a game the GPU holds
/// at 20 fps under a 60 cap has slow frames, not stutters (its fps says so), and each of its frames would be one otherwise
inline void add_frame(MapTotals& m, const fps_stats::Frame& f, const Waits& w, double target_ms, double last_ms,
                      double usual_ms = 0) {
    m.seconds += f.ms / 1000.0;
    m.frame[bucket_of(f.ms, kFrameBuckets)]++;
    m.frame_sum += f.ms;
    if (f.gpu_ms > 0) m.gpu[bucket_of(f.gpu_ms, kGpuBuckets)]++, m.gpu_sum += f.gpu_ms;
    for (int p = 0; p < fps_stats::kParts; p++) m.part[p] += f.part[p];
    if (is_hitch(f.ms, std::max(target_ms, usual_ms))) m.hitch[cause_of(f, w)]++;
    else if (is_pacing_miss(f.ms, last_ms, target_ms)) m.pacing_misses++;
    m.left_out += f.left_out;
}

/// What the summary says of the machine and the settings (the relay derives the classes itself)
struct Machine {
    std::string version, os, kernel, renderer = "Vulkan", gpu, driver, cpu, upscaler, preset;
    bool release = false;
    double vram_gb = 0, ram_gb = 0;
    int fps_cap = 0;   // (0: uncapped)
};

struct Memory {
    double vram_used_gb = 0, vram_allowed_gb = 0, ram_used_gb = 0;
};

/// A string as JSON: quotes, backslashes and control characters escaped, cut at `limit` bytes (the relay's limits), never
/// inside a UTF-8 character (half of one would make the whole file unreadable)
inline std::string json_text(const std::string& s, size_t limit = 120) {
    size_t n = std::min(s.size(), limit);
    while (n > 0 && n < s.size() && ((unsigned char)s[n] & 0xC0) == 0x80) n--;
    std::string out = "\"";
    for (size_t i = 0; i < n; i++) {
        const unsigned char ch = (unsigned char)s[i];
        if (ch == '"' || ch == '\\') out += '\\', out += (char)ch;
        else if (ch < 0x20) out += ' ';
        else out += (char)ch;
    }
    return out + "\"";
}

inline std::string json_num(double v) {
    char b[32];
    snprintf(b, sizeof b, "%.3f", std::max(v, 0.0));
    std::string s = b;
    s.erase(s.find_last_not_of('0') + 1);
    if (s.back() == '.') s.pop_back();
    return s;
}

template <class T, size_t N>
std::string json_list(const T (&v)[N]) {
    std::string out = "[";
    for (size_t i = 0; i < N; i++) out += (i ? "," : "") + json_num((double)v[i]);
    return out + "]";
}

/// The summary, as the relay takes it (version 1)
inline std::string summary_json(const Machine& m, bool first, double session_s, const std::string& map, const Memory* mem,
                                const std::map<std::string, MapTotals>& maps) {
    std::string o = "{\"v\":1,\"version\":" + json_text(m.version, 40) + ",\"release\":" + (m.release ? "true" : "false") +
                    ",\"first\":" + (first ? "true" : "false") + ",\"session_s\":" + json_num(session_s) +
                    ",\"os\":" + json_text(m.os, 60) + ",\"kernel\":" + json_text(m.kernel, 60) +
                    ",\"renderer\":" + json_text(m.renderer, 40) + ",\"gpu\":" + json_text(m.gpu) +
                    ",\"driver\":" + json_text(m.driver, 60) + ",\"vram_gb\":" + json_num(m.vram_gb) +
                    ",\"cpu\":" + json_text(m.cpu) + ",\"ram_gb\":" + json_num(m.ram_gb) +
                    ",\"upscaler\":" + json_text(m.upscaler, 40) + ",\"preset\":" + json_text(m.preset, 40) +
                    ",\"fps_cap\":" + std::to_string(m.fps_cap) + ",\"map\":" + json_text(map);
    if (mem)
        o += ",\"memory\":{\"vram_used_gb\":" + json_num(mem->vram_used_gb) + ",\"vram_allowed_gb\":" +
             json_num(mem->vram_allowed_gb) + ",\"ram_used_gb\":" + json_num(mem->ram_used_gb) + "}";
    o += ",\"maps\":{";
    bool comma = false;
    for (const auto& [name, t] : maps) {
        if (!t.any()) continue;
        o += std::string(comma ? "," : "") + json_text(name) + ":{\"new\":" + (t.fresh ? "true" : "false") +
             ",\"seconds\":" + json_num(t.seconds) + ",\"frame_ms\":" + json_list(t.frame) + ",\"frame_ms_sum\":" +
             json_num(t.frame_sum) + ",\"gpu_ms\":" + json_list(t.gpu) + ",\"gpu_ms_sum\":" + json_num(t.gpu_sum) +
             ",\"parts_ms\":{\"game\":" + json_num(t.part[fps_stats::kGame]) + ",\"render\":" +
             json_num(t.part[fps_stats::kRender]) + ",\"gpu_wait\":" + json_num(t.part[fps_stats::kGpuWait]) + ",\"pace\":" +
             json_num(t.part[fps_stats::kPace]) + "},\"hitches\":{";
        for (int c = 0; c < kCauses; c++) o += std::string(c ? "," : "") + "\"" + cause_name(c) + "\":" + std::to_string(t.hitch[c]);
        o += "},\"pacing_misses\":" + std::to_string(t.pacing_misses) + ",\"draws_left_out\":" + std::to_string(t.left_out) +
             ",\"events\":{";
        for (int e = 0; e < kEvents; e++) o += std::string(e ? "," : "") + "\"" + event_name(e) + "\":" + std::to_string(t.event[e]);
        o += "},\"movie\":{\"shown\":" + std::to_string(t.movie_shown) + ",\"dropped\":" + std::to_string(t.movie_dropped) +
             ",\"late\":" + std::to_string(t.movie_late) + ",\"decode_ms\":" + json_num(t.movie_decode_ms) +
             ",\"fallbacks\":" + std::to_string(t.movie_fallbacks) + "}}";
        comma = true;
    }
    return o + "}}";
}

/// "6.12.3-arch1-1" out of uname's release, "10.0.26100" out of Windows' version: the relay cuts them to major.minor
inline std::string kernel_of(const std::string& os_text) {
    const size_t at = os_text.find("(Linux ");
    if (at != std::string::npos) return os_text.substr(at + 7, os_text.find(')', at) - at - 7);
    const size_t b = os_text.find("(build ");
    if (b != std::string::npos) return "10.0." + os_text.substr(b + 7, os_text.find(')', b) - b - 7);
    return "";
}

}   // namespace mkwvk::perf_report
