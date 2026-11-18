// Real prepare(), fake NGX: observe the creation parameters and returned input range.
#include <atomic>
#include <cassert>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <functional>
#include "dlss_checks.h"
#include "upscaler_rows.h"
namespace dlss_checks = mkwvk::dlss_checks;
namespace upscaler_rows = mkwvk::upscaler_rows;

using VkCommandBuffer = int;
enum NVSDK_NGX_PerfQuality_Value {
    NVSDK_NGX_PerfQuality_Value_MaxPerf, NVSDK_NGX_PerfQuality_Value_Balanced,
    NVSDK_NGX_PerfQuality_Value_MaxQuality, NVSDK_NGX_PerfQuality_Value_UltraPerformance,
    NVSDK_NGX_PerfQuality_Value_DLAA = 5
};
constexpr int NVSDK_NGX_DLSS_Hint_Render_Preset_K = 11, NVSDK_NGX_DLSS_Hint_Render_Preset_L = 12,
              NVSDK_NGX_DLSS_Hint_Render_Preset_M = 13, NVSDK_NGX_DLSS_Hint_Render_Preset_Default = 0;
constexpr int NVSDK_NGX_DLSS_Feature_Flags_MVLowRes = 1, NVSDK_NGX_DLSS_Feature_Flags_IsHDR = 2,
              NVSDK_NGX_DLSS_Feature_Flags_AutoExposure = 4;
constexpr const char* NVSDK_NGX_Parameter_DLSS_Hint_Render_Preset_DLAA = "aa";
constexpr const char* NVSDK_NGX_Parameter_DLSS_Hint_Render_Preset_Quality = "quality";
constexpr const char* NVSDK_NGX_Parameter_DLSS_Hint_Render_Preset_Balanced = "balanced";
constexpr const char* NVSDK_NGX_Parameter_DLSS_Hint_Render_Preset_Performance = "performance";
constexpr const char* NVSDK_NGX_Parameter_DLSS_Hint_Render_Preset_UltraPerformance = "ultra";
constexpr const char* NVSDK_NGX_Parameter_DLSS_Hint_Render_Preset_UltraQuality = "ultra-quality";
struct NVSDK_NGX_Handle {};
using NVSDK_NGX_Result = unsigned;
#define NVSDK_NGX_FAILED(result) ((result) != 0)
struct NVSDK_NGX_DLSS_Create_Params {
    struct {
        unsigned InWidth = 0, InHeight = 0, InTargetWidth = 0, InTargetHeight = 0;
        NVSDK_NGX_PerfQuality_Value InPerfQualityValue{};
    } Feature;
    unsigned InFeatureCreateFlags = 0;
};
struct State {
    dlss_checks::PresetSettle settle;
    NVSDK_NGX_Handle* feature = nullptr;
    unsigned feature_ow = 0, feature_oh = 0, feature_rw = 0, feature_rh = 0, min_rw = 0, min_rh = 0;
    unsigned feature_preset = 0;
    bool feature_hdr = false, feature_aa = false;
    uint64_t features_made = 0, refused = 0;
    void* caps = nullptr;
    void* params = nullptr;
};
State state;
State& st() { return state; }
std::atomic<bool> present_native_pq{false};
uint64_t frame = 0;
uint64_t texture_frame_no() { return frame; }
unsigned preset = 11;
unsigned wanted_preset() { return preset; }
void logf(const char*, ...) {}
void note_work() {}
void temporal_later(std::function<void()> f) { f(); }
void NVSDK_NGX_VULKAN_ReleaseFeature(NVSDK_NGX_Handle*) {}
void NVSDK_NGX_Parameter_SetUI(void*, const char*, unsigned) {}
namespace mkwvk::rec { enum { B_DIRECT }; void boundary(int) {} }
struct Settings { unsigned w, h, min_w, min_h, max_w, max_h; bool fails = false; };
Settings settings[6];
unsigned queries = 0, creations = 0;
bool fail_create = false;
NVSDK_NGX_DLSS_Create_Params captured;
NVSDK_NGX_Result NGX_DLSS_GET_OPTIMAL_SETTINGS(void*, unsigned, unsigned, NVSDK_NGX_PerfQuality_Value mode,
    unsigned* w, unsigned* h, unsigned* max_w, unsigned* max_h, unsigned* min_w, unsigned* min_h, float*) {
    queries++;
    const auto& s = settings[mode];
    *w = s.w; *h = s.h; *max_w = s.max_w; *max_h = s.max_h; *min_w = s.min_w; *min_h = s.min_h;
    return s.fails ? 1 : 0;
}
NVSDK_NGX_Result NGX_VULKAN_CREATE_DLSS_EXT(int, int, int, NVSDK_NGX_Handle** handle, void*,
                                         NVSDK_NGX_DLSS_Create_Params* params) {
    static NVSDK_NGX_Handle feature;
    captured = *params;
    creations++;
    *handle = fail_create ? nullptr : &feature;
    return fail_create ? 1 : 0;
}
const char* test_getenv(const char*) { return nullptr; }
#define getenv test_getenv
/* PREPARE */
#undef getenv

void reset() {
    state = {}; frame = 0; queries = creations = 0; fail_create = false;
    settings[2] = {2293, 960, 1720, 720, 3440, 1440};
    settings[5] = {3440, 1440, 3440, 1440, 3440, 1440};
    settings[1] = {2007, 840, 1720, 720, 3440, 1440};
    settings[0] = {1720, 720, 1720, 720, 3440, 1440};
    settings[3] = {1146, 480, 1146, 480, 1146, 480};
}
int call(unsigned rw, unsigned rh, unsigned& iw, unsigned& ih, bool native = false) {
    const char* why = nullptr;
    return prepare(0, rw, rh, 3440, 1440, native, &iw, &ih, &why);
}
int main() {
    for (unsigned p : {11u, 12u, 13u}) for (bool hdr : {false, true}) {
        reset(); preset = p; present_native_pq = hdr;
        unsigned iw = 0, ih = 0;
        assert(call(2294, 960, iw, ih) == 2);
        assert(captured.Feature.InWidth == 2293 && captured.Feature.InHeight == 960);
        assert(captured.Feature.InTargetWidth == 3440 && captured.Feature.InTargetHeight == 1440);
        assert(captured.Feature.InPerfQualityValue == NVSDK_NGX_PerfQuality_Value_MaxQuality);
        assert(captured.InFeatureCreateFlags == unsigned(1 | (hdr ? 6 : 0)));
        assert(state.feature_preset == p && iw == 3440 && ih == 1440);
        const unsigned before = queries;
        // The full advertised dynamic range remains available without recreating.
        assert(call(2867, 1200, iw, ih) == 1 && creations == 1 && queries == before);
        assert(call(1720, 720, iw, ih) == 1 && creations == 1);
        assert(call(1434, 600, iw, ih) == 0 && creations == 1 && state.feature != nullptr);
        // Native AA retains the full-resolution creation size.
        assert(call(3440, 1440, iw, ih, true) == 2 && creations == 2);
        assert(captured.Feature.InWidth == 3440 && captured.Feature.InHeight == 1440);
        assert(captured.Feature.InPerfQualityValue == NVSDK_NGX_PerfQuality_Value_DLAA);
        assert(iw == 3440 && ih == 1440);
    }
    reset(); preset = 11;
    settings[2].fails = true;  // Skipped entries must not shift the selected optimal dimensions.
    unsigned iw = 0, ih = 0;
    assert(call(2294, 960, iw, ih) == 2);
    assert(captured.Feature.InWidth == 2007 && captured.Feature.InHeight == 840);
    assert(captured.Feature.InPerfQualityValue == NVSDK_NGX_PerfQuality_Value_Balanced);
    reset();
    assert(call(1147, 480, iw, ih) == 2);
    assert(captured.Feature.InWidth == 1146 && captured.Feature.InHeight == 480);
    assert(iw == 1147 && ih == 480);  // Rounded render size still receives sufficient backing storage.
    reset(); fail_create = true;
    assert(call(2294, 960, iw, ih) == 0 && creations == 1);
    assert(call(2294, 960, iw, ih) == 0 && creations == 1);
    preset = 12;
    assert(call(2294, 960, iw, ih) == 0 && creations == 2);
    std::puts("DLSS recommended feature sizes, dynamic ranges, native AA and failure handling pass");
}
