// tests/test_perf_report.py: gpu/vk/perf_report.h, the performance summary: its interval, its buckets, what a hitch is and what it waited on,
// the pacing misses, the JSON the relay takes, and what a frame costs to add
#include "../gpu/vk/perf_report.h"

#include <chrono>
#include <cstdio>
#include <cstring>

#define CHECK(name, condition) do { if (!(condition)) { std::fprintf(stderr, "FAIL %s at line %d\n", name, __LINE__); return 1; } } while (0)

namespace pr = mkwvk::perf_report;
namespace fs = mkwvk::fps_stats;

static fs::Frame frame(float ms, float game, float render, float gpu_wait, float pace) {
    fs::Frame f;
    f.ms = ms;
    f.part[fs::kGame] = game, f.part[fs::kRender] = render, f.part[fs::kGpuWait] = gpu_wait, f.part[fs::kPace] = pace;
    return f;
}

int main() {
    // the buckets: the relay's lists, an upper bound each, +Inf last
    CHECK("counts", pr::kFrameBucketCount == 13 && pr::kGpuBucketCount == 11);
    CHECK("a cut never splits a character", pr::json_text("ab\xc3\xa9", 3) == "\"ab\"" && pr::json_text("ab\xc3\xa9", 4) == "\"ab\xc3\xa9\"");
    CHECK("a 60 fps frame", pr::bucket_of(16.6, pr::kFrameBuckets) == 4);
    CHECK("on the bound", pr::bucket_of(16.7, pr::kFrameBuckets) == 4);
    CHECK("past every bound", pr::bucket_of(5000, pr::kFrameBuckets) == pr::kFrameBucketCount - 1);

    // the interval between summaries: RX_VK_PERF_INTERVAL, 60 to 840 s (the relay's 900 s, a minute left for the last frame)
    CHECK("unset: 5 minutes", pr::summary_period(nullptr) == 300 && pr::summary_period("") == 300);
    CHECK("10 minutes", pr::summary_period("600") == 600);
    CHECK("at least a minute", pr::summary_period("10") == 60 && pr::summary_period("-5") == 60);
    CHECK("at most 14 minutes", pr::summary_period("900") == 840 && pr::summary_period("99999999999") == 840);
    CHECK("not a number: the default", pr::summary_period("soon") == 300 && pr::summary_period("600s") == 300);

    // a hitch: over twice the target and at least 25 ms
    CHECK("60 fps, 40 ms", pr::is_hitch(40, 16.7));
    CHECK("60 fps, 30 ms", !pr::is_hitch(30, 16.7));
    CHECK("240 fps, 12 ms is no stutter", !pr::is_hitch(12, 4.17));
    CHECK("30 fps, 70 ms", pr::is_hitch(70, 33.3));
    {   // (a 60 cap the GPU holds at 20 fps: its 50 ms frames are slow, not hitches; a 120 ms one among them is)
        pr::MapTotals m;
        for (int i = 0; i < 50; i++) pr::add_frame(m, frame(50, 10, 35, 3, 2), pr::Waits{}, 16.7, 50, 50);
        int64_t hitches = 0;
        for (int64_t h : m.hitch) hitches += h;
        CHECK("held at 20 fps under a 60 cap: no hitch", hitches == 0);
        pr::add_frame(m, frame(120, 10, 100, 3, 2), pr::Waits{}, 16.7, 50, 50);
        for (int64_t h : m.hitch) hitches += h;
        CHECK("a 120 ms frame among them: one", hitches == 1);
    }

    // what it waited on: the biggest of the renderer's waits and the parts, "other" under a quarter of the frame
    {
        pr::Waits w;
        w.pipeline = 30;
        CHECK("pipelines", pr::cause_of(frame(50, 10, 35, 2, 3), w) == pr::kPipelineWait);
        CHECK("the GPU", pr::cause_of(frame(50, 5, 5, 38, 2), pr::Waits{}) == pr::kGpuBound);
        CHECK("the game", pr::cause_of(frame(50, 40, 5, 3, 2), pr::Waits{}) == pr::kGameCpu);
        w = {};
        w.upload = 20;
        CHECK("uploads", pr::cause_of(frame(60, 10, 25, 10, 5), w) == pr::kTextureUpload);
        CHECK("nothing stands out", pr::cause_of(frame(100, 20, 20, 20, 20), pr::Waits{}) == pr::kOther);
        CHECK("names", !std::strcmp(pr::cause_name(pr::kGpuBound), "gpu_bound") && !std::strcmp(pr::cause_name(pr::kPacing), "pace") &&
                           !std::strcmp(pr::event_name(pr::kDeviceLost), "device_lost"));
    }

    // pacing: a quarter of the target from the frame before; never the first frame
    CHECK("even", !pr::is_pacing_miss(16.9, 16.5, 16.7));
    CHECK("uneven", pr::is_pacing_miss(22, 16.5, 16.7));
    CHECK("first", !pr::is_pacing_miss(22, 0, 16.7));

    // a map's totals, and the summary as the relay takes it
    {
        std::map<std::string, pr::MapTotals> maps;
        auto& m = maps["Kokiri Forest (child)"];
        double last = 0;
        for (int i = 0; i < 100; i++) pr::add_frame(m, frame(16.6f, 10, 4, 2, 0.6f), pr::Waits{}, 16.7, last), last = 16.6;
        pr::Waits w;
        w.pipeline = 40;
        pr::add_frame(m, frame(60, 10, 45, 3, 2), w, 16.7, last);
        CHECK("frames", m.frame[4] == 100 && m.frame[9] == 1);
        CHECK("seconds", m.seconds > 1.71 && m.seconds < 1.73);
        CHECK("the hitch", m.hitch[pr::kPipelineWait] == 1 && m.pacing_misses == 0);
        CHECK("an empty map is left out", !maps["Hyrule Field (adult)"].any());
        pr::Machine mc;
        mc.version = "2.4.1 (source 1234abcd)", mc.os = "Arch Linux", mc.kernel = "6.12.3-arch1-1", mc.gpu = "AMD \"Radeon\" RX 7800 XT";
        mc.driver = "radv Mesa 25.2.4", mc.cpu = "AMD Ryzen 7 7800X3D", mc.upscaler = "FSR 3.1", mc.preset = "High";
        mc.vram_gb = 16, mc.ram_gb = 32, mc.fps_cap = 60;
        pr::Memory mem{5.25, 15.5, 7.75};
        const std::string j = pr::summary_json(mc, true, 312.5, "Kokiri Forest (child)", &mem, maps);
        CHECK("version 1", j.rfind("{\"v\":1,", 0) == 0);
        CHECK("quotes escaped", j.find("\"AMD \\\"Radeon\\\" RX 7800 XT\"") != std::string::npos);
        CHECK("the map", j.find("\"Kokiri Forest (child)\":{\"new\":true,") != std::string::npos);
        CHECK("not the empty one", j.find("Hyrule Field") == std::string::npos);
        CHECK("buckets", j.find("\"frame_ms\":[0,0,0,0,100,0,0,0,0,1,0,0,0]") != std::string::npos);
        CHECK("hitches", j.find("\"hitches\":{\"pipeline_wait\":1,") != std::string::npos);
        CHECK("memory", j.find("\"memory\":{\"vram_used_gb\":5.25,\"vram_allowed_gb\":15.5,\"ram_used_gb\":7.75}") != std::string::npos);
        CHECK("numbers", j.find("\"session_s\":312.5,") != std::string::npos && j.find("\"fps_cap\":60,") != std::string::npos);
        CHECK("closed", j.back() == '}' && std::count(j.begin(), j.end(), '{') == std::count(j.begin(), j.end(), '}'));
    }

    // the kernel out of the Bug report's system line
    CHECK("linux", pr::kernel_of("Arch Linux (Linux 6.12.3-arch1-1), KDE (wayland)") == "6.12.3-arch1-1");
    CHECK("windows", pr::kernel_of("Windows 11 (build 26100)") == "10.0.26100");
    CHECK("unknown", pr::kernel_of("Linux").empty());

    // what a frame costs (a player's): well under a microsecond, against a 16.7 ms frame
    {
        pr::MapTotals m;
        const auto f = frame(16.6f, 10, 4, 2, 0.6f);
        const auto t0 = std::chrono::steady_clock::now();
        const int n = 1000000;
        for (int i = 0; i < n; i++) pr::add_frame(m, f, pr::Waits{}, 16.7, 16.5);
        const double ns = std::chrono::duration<double, std::nano>(std::chrono::steady_clock::now() - t0).count() / n;
        std::printf("add_frame: %.1f ns a frame\n", ns);
        CHECK("cheap", ns < 1000 && m.frame[4] == n);
    }
    return 0;
}
