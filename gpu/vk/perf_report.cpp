// (hookshot) The performance summary (perf_report.h): on only when the launcher's "Send performance statistics" tick wrote
// send=1 to the game folder's hookshot_perf.ini. Then the FPS counter's Breakdown measures every frame whatever level the
// counter shows (vk_fps.h fps_breakdown_on), and each frame is added here, on the thread that presents, to its map's totals:
// a bucket, a few sums and the renderer's counters read since the frame before. No allocation, no file and no lookup a
// frame: the map is asked of the host about once a second, the memory once a summary, and a summary's JSON is made and
// written on a thread of its own every `period` seconds (RX_VK_PERF_INTERVAL) and at exit. Off, the only cost is fps_presented's look at perf_measure.
#include "perf_report.h"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <thread>

#include "vk_bug_report.h"
#include "vk_draw.h"
#include "vk_fps.h"
#include "vk_internal.h"
#include "vk_menu.h"
#include "vk_paths.h"
#include "vk_shader.h"
#include "vk_texture.h"
#include "upscaler_rows.h"

#ifdef _WIN32
#include <psapi.h>
#else
#include <unistd.h>
#endif

namespace mkwvk {

std::atomic<bool> perf_measure{false};
double menu_target_ms();   // (vk_menu.cpp fps_target_ms: the frame time the game aims for, 0 uncapped)
int menu_fps_cap();        // (vk_menu.cpp fps_cap_now: the cap in effect, the same rule)
bool shaders_preparing();  // (vk_main.cpp: the start-up screen's shader preparation)

namespace {

namespace pr = perf_report;
namespace fs = fps_stats;

double period = pr::kPeriodDefault;   // (seconds of play between summaries: RX_VK_PERF_INTERVAL, perf_report_init)
constexpr double kMapEvery = 1;      // (seconds between asking the host where Link is)
constexpr int kMaxPending = 48;      // (summaries waiting in perf_pending at most, about four hours of play: a player who never
                                     // starts the launcher, or is offline, doesn't fill the disk; the newest go unwritten)

std::mutex mu;   // (the presenting thread's frames, against the exit's and a lost device's last summary)
std::map<std::string, pr::MapTotals> maps;
std::map<std::string, bool> seen_maps;   // (maps this session has sent: the relay counts a session on a map once)
pr::MapTotals* current = nullptr;
std::string current_map;
pr::Machine machine;
std::filesystem::path folder;   // (the game folder: vk_paths.h, wide on Windows)
std::atomic<int64_t> events[pr::kEvents];
int64_t started_ns = 0, last_movie[5] = {};
double since_map = 0, since_summary = 0, avg_ms = 0, last_ms = 0;
bool first = true;
int seq = 0;
int64_t l_failed = 0;   // (the renderer's counts at the summary before: at the start, perf_report_init)
uint64_t l_swap = 0;

bool ticked(const std::filesystem::path& dir) {
    std::ifstream f(dir / "hookshot_perf.ini");
    bool on = false;
    for (std::string line; std::getline(f, line);)
        if (!line.compare(0, 5, "send=")) on = atoi(line.c_str() + 5) == 1;
    return on;
}

double ram_used_gb() {
#ifdef _WIN32
    PROCESS_MEMORY_COUNTERS_EX pm{};
    pm.cb = sizeof pm;
    if (K32GetProcessMemoryInfo(GetCurrentProcess(), (PROCESS_MEMORY_COUNTERS*)&pm, sizeof pm)) return pm.PrivateUsage / 1073741824.0;
#else
    FILE* f = fopen("/proc/self/statm", "r");
    long pages = 0, resident = 0;
    if (f) {
        if (fscanf(f, "%ld %ld", &pages, &resident) != 2) resident = 0;
        fclose(f);
        return resident * (double)sysconf(_SC_PAGE_SIZE) / 1073741824.0;
    }
#endif
    return 0;
}

double vram_total_gb() {
    if (!dev.physical) return 0;
    VkPhysicalDeviceMemoryProperties mp{};
    vkGetPhysicalDeviceMemoryProperties(dev.physical, &mp);
    uint64_t most = 0;
    for (uint32_t i = 0; i < mp.memoryHeapCount; i++)
        if (mp.memoryHeaps[i].flags & VK_MEMORY_HEAP_DEVICE_LOCAL_BIT) most = std::max<uint64_t>(most, mp.memoryHeaps[i].size);
    return most / 1073741824.0;
}

const char* upscaler_name(int v) {
    // (upscaler_rows.h's order: GAME .. XESS_AA)
    static const char* const t[] = {"Game network", "DLSS", "DLAA", "FSR 3.1", "FSR 4", "FSR 4 AA", "Off", "XeSS", "XeSS AA"};
    static_assert(sizeof t / sizeof t[0] == upscaler_rows::kUpscalers, "a name for each upscaler");
    return v >= 0 && v < upscaler_rows::kUpscalers ? t[v] : "other";
}
const char* preset_name(int v) {
    static const char* const t[] = {"Custom", "Minimum", "Low", "Balanced", "High", "Ultra"};
    return v >= 0 && v < 6 ? t[v] : "Auto";
}

/// The machine, once: the GPU and its driver from Vulkan, the rest from the Bug report's system line (vk_bug_report.cpp
/// system_text: "<cpu> (<n> threads), <ram> GB, <os> (<kernel>)...")
void read_machine(const char* version) {
    machine.version = version ? version : "";
    machine.version = machine.version.substr(0, machine.version.find(" ("));   // ("<version> (source <hash>)": the version)
    machine.gpu = dev.props.deviceName;
    machine.driver = driver_text();
    machine.vram_gb = vram_total_gb();
    const std::string sys = bug_report::system_text();
    const size_t threads = sys.find(" ("), gb = sys.find(" GB, ");
    machine.cpu = sys.substr(0, threads);
    if (gb != std::string::npos) {
        const size_t from = sys.rfind(", ", gb);
        machine.ram_gb = atof(sys.c_str() + (from == std::string::npos ? 0 : from + 2));
        const std::string os = sys.substr(gb + 5);
        machine.os = os.substr(0, os.find(" ("));
        machine.kernel = pr::kernel_of(os);
    }
}

/// The settings a summary says: read at each one (the player may change them in play)
void read_settings() {
    machine.upscaler = upscaler_name(opts.dlss);
    machine.preset = preset_name(opts.preset);
    machine.fps_cap = menu_fps_cap();
}

/// The map from the host, and the movies' totals since the last ask, onto the map they played on. True when Link is on a map
/// the summary has no room for (pr::kMaxMaps): it stays on the one before, for a summary to make room
bool where_now() {
    char map[120] = "";
    int64_t movie[5] = {};
    const char* version = host->perf_info ? host->perf_info(map, sizeof map, movie) : nullptr;
    if (machine.gpu.empty()) read_machine(version);
    // (before a map: the start-up screen while the shaders are prepared, then the intro, the title and the file select)
    const std::string name = map[0] ? map : shaders_preparing() ? pr::kPreparingShaders : pr::kTitleAndIntro;
    const bool full = current && name != current_map && !maps.count(name) && maps.size() >= (size_t)pr::kMaxMaps;
    if (!full && (!current || name != current_map)) {
        current_map = name;
        current = &maps[name];
        current->fresh = !seen_maps.count(name);
    }
    current->movie_shown += movie[0] - last_movie[0];
    current->movie_dropped += movie[1] - last_movie[1];
    current->movie_late += movie[2] - last_movie[2];
    current->movie_decode_ms += (movie[3] - last_movie[3]) / 1e6;
    current->movie_fallbacks += movie[4] - last_movie[4];
    memcpy(last_movie, movie, sizeof last_movie);
    return full;
}

void write_summary(const std::filesystem::path& dir, const std::string& name, const std::string& json) {
    namespace fsys = std::filesystem;
    const fsys::path pending = dir / "perf_pending";
    std::error_code ec;
    {
        int waiting = 0;
        for (fsys::directory_iterator it(pending, ec), end; !ec && it != end; it.increment(ec))
            waiting += it->path().extension() == ".json";
        if (waiting >= kMaxPending) return;
    }
    fsys::create_directory(pending, ec);
    const fsys::path tmp = pending / (name + ".tmp"), path = pending / (name + ".json");
    bool ok;
    {
        std::ofstream f(tmp, std::ios::binary);
        ok = f && f.write(json.data(), (std::streamsize)json.size()) && f.flush();
    }
    if (ok) fsys::rename(tmp, path, ec);
    if (!ok || ec) fsys::remove(tmp, ec);   // (whole or nothing: the launcher never reads half)
}

/// The summary of what came in since the one before (under mu), written on a thread of its own unless `now` (the exit, a
/// lost device: the process ends next)
void summarize(bool now) {
    if (!current) return;
    if (!ticked(folder)) {   // (unticked in the launcher while the game ran: nothing more measured or written)
        perf_measure.store(false, std::memory_order_relaxed);
        maps.clear(), current = nullptr;
        logf("vk: performance statistics off (unticked in the launcher): nothing more is written");
        return;
    }
    where_now();
    read_settings();
    {   // (the renderer's events, onto the map they ended on: there are few)
        int64_t translated = 0, failed = 0;
        shader_stats(&translated, &failed);
        current->event[pr::kProgramFailed] += failed - l_failed, l_failed = failed;
        const uint64_t swap = dev.swapchain_generation;
        current->event[pr::kSwapchainRecreated] += (int64_t)(swap - l_swap);
        l_swap = swap;
        for (int e = 0; e < pr::kEvents; e++) current->event[e] += events[e].exchange(0);
    }
    bool any = false;
    for (const auto& [n, t] : maps) any = any || t.any();
    if (!any) return;   // (nothing since the last: the exit right after a lost device's summary)
    pr::Memory mem;
    uint64_t used = 0, allowed = 0;
    if (vram_usage_now(&used, &allowed)) mem.vram_used_gb = used / 1073741824.0, mem.vram_allowed_gb = allowed / 1073741824.0;
    mem.ram_used_gb = ram_used_gb();
    const double session_s = (fps_clock() - started_ns) / 1e9;
    std::string json = pr::summary_json(machine, first, session_s, current_map, &mem, maps);
    char name[48];
    snprintf(name, sizeof name, "%lld-%d", (long long)std::time(nullptr), seq++);
    for (auto& [n, t] : maps)
        if (t.any()) seen_maps[n] = true;
    maps.clear();
    current = &maps[current_map];
    current->fresh = !seen_maps.count(current_map);   // (a map entered just before this summary, with nothing yet: still new)
    first = false;
    if (now) return write_summary(folder, name, json);
    std::thread([dir = folder, n = std::string(name), j = std::move(json)] { write_summary(dir, n, j); }).detach();
}

// (an exit that runs atexit: Windows' ExitProcess, exit(). The window's close writes it first, mkwvk_close_asked; then
// this finds nothing new. Only tried: ExitProcess has already ended the other threads, and one may have held mu)
void at_exit() {
    std::unique_lock lk(mu, std::try_to_lock);
    if (lk) summarize(true);
}

}   // namespace

bool perf_report_init() {
    folder = game_dir_path();
    if (!ticked(folder)) return false;
    {   // (a summary cut short by an exit before: its .tmp, never sent and never counted)
        std::error_code ec;
        for (std::filesystem::directory_iterator it(folder / "perf_pending", ec), end; !ec && it != end; it.increment(ec))
            if (it->path().extension() == ".tmp") std::filesystem::remove(it->path(), ec);
    }
    period = pr::summary_period(getenv("RX_VK_PERF_INTERVAL"));
    started_ns = fps_clock();
    int64_t translated = 0;
    shader_stats(&translated, &l_failed);   // (the renderer's counts so far: only what comes after is counted)
    l_swap = dev.swapchain_generation;
    std::atexit(at_exit);
    logf("vk: performance statistics on (the launcher's Send performance statistics): a summary every %.0f s into perf_pending",
         period);
    perf_measure.store(true, std::memory_order_relaxed);
    return true;
}

void perf_event(int e) {
    if (e >= 0 && e < pr::kEvents && perf_measure.load(std::memory_order_relaxed)) events[e].fetch_add(1, std::memory_order_relaxed);
}

void perf_frame(const fs::Frame& f, double wait_ms) {
    // (the renderer's counters since the frame before: what the slow frames waited on. wait_ms: draw_stats3's, read by
    // fps_presented, which calls this only while perf_measure holds)
    static int64_t l_prof[PROF_COUNT], l_readback;
    static double l_wait_ms, l_translate;
    static bool primed = false;   // (the first frame only takes the counters: they hold everything since the game started)
    const double translate = shader_translate_wait_ms();   // (only what a draw waited for: the jobs' run behind the game)
    const int64_t readback = texture_readback_wait_ns();
    const auto dp = [](int i) { return (prof_ns[i] - l_prof[i]) / 1e6; };
    pr::Waits w;
    // (draw_stats3's waits are draws waiting for a program's translation; program_pick's own translation, in place, is
    // timed inside PROF_PROGRAM too: each counted once, as a translation)
    const double in_place = translate - l_translate;
    w.translate = wait_ms - l_wait_ms + in_place;
    w.pipeline = std::max(0.0, dp(PROF_PIPE) + dp(PROF_PROGRAM) - in_place);
    w.upload = dp(PROF_UPLOAD);
    w.memsync = dp(PROF_MEMSYNC);
    w.readback = (readback - l_readback) / 1e6;
    memcpy(l_prof, prof_ns, sizeof l_prof);
    l_wait_ms = wait_ms, l_translate = translate, l_readback = readback;
    if (!primed) w = pr::Waits{}, primed = true;

    std::lock_guard lk(mu);
    if (!current || since_map >= kMapEvery) {
        // (a 17th map in one period: that summary now, with the 16 it has, then the new map in the next)
        if (where_now()) summarize(false), since_summary = 0, where_now();
        since_map = 0;
    }
    // (the target: the cap's, else uncapped the recent average. A hitch is twice the longer of the target and the recent
    // average, before this frame: a frame twice the usual, never every frame of a game the GPU holds under its cap)
    const double usual = avg_ms ? avg_ms : f.ms;
    avg_ms = usual * 0.98 + f.ms * 0.02;
    const double cap_ms = menu_target_ms();
    const double target = cap_ms > 0 ? cap_ms : usual;
    pr::add_frame(*current, f, w, target, last_ms, usual);
    last_ms = f.ms;
    since_map += f.ms / 1000.0, since_summary += f.ms / 1000.0;
    if (since_summary >= period) summarize(false), since_summary = 0;
}

void perf_report_final(int event) {
    if (!perf_measure.load(std::memory_order_relaxed)) return;
    perf_event(event);
    std::lock_guard lk(mu);
    summarize(true);
}

}   // namespace mkwvk
