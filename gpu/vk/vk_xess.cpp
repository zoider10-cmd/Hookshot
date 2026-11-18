// (hookshot) Intel XeSS Super Resolution, one of the temporal upscaler's engines (vk_xess.h). The frame chain it draws with is
// vk_temporal.cpp's, the same as NVIDIA DLSS's and AMD FSR 4's: the colour as the game's network samples it, the depth, the
// motion (the camera's and the skinned draws' own) and the camera jitter. Here are Intel's library, the XeSS context and its
// execution. The host side follows Intel's XeSS-SR developer guide (doc/xess_sr_developer_guide_english.md of
// https://github.com/intel/xess, the commit third_party/xess names): the instance's and the device's extensions and features
// asked of the library before they are made, inputs read in SHADER_READ_ONLY_OPTIMAL, the output written in GENERAL.
//
// Intel's libxess.dll is looked for in RX_VK_XESS_DIR=<folder> when set, the executable's folder (bin\ beside the launcher),
// then the game folder (xess_rules.h library_dirs), and loaded with LoadLibraryExA: its own folder first in the search, for
// the libraries it loads beside it. Its functions are taken by name (GetProcAddress) with the types of Intel's headers; the
// import library is not linked, so a PC without the DLL runs as before. RX_VK_XESS=0: XeSS out for this run (not even
// loaded); 1 / 2: Intel XeSS / its Native AA over the Upscaler row. Windows only: Intel ships no XeSS library for Linux.
//
// The inputs as XeSS takes them, from the chain's (vk_temporal.h TemporalFrame):
//  - colour: RGBA16F, tonemapped and square-root encoded (LDR): XESS_INIT_FLAG_LDR_INPUT_COLOR, exposure 1 (the guide: "If the
//    application provides LDR input color ... set the exposure value to 1.0 and avoid using auto-exposure"). With the game's
//    native HDR (present_native_pq) the chain gives linear light past 1 (hdr()): no LDR flag, XeSS's own exposure
//    (XESS_INIT_FLAG_ENABLE_AUTOEXPOSURE), as AMD FSR 4's HDR context does
//  - depth: R32F, 0 near ... 1 far, not reversed: XeSS's default ("smaller depth values are closer to the camera"), no
//    XESS_INIT_FLAG_INVERTED_DEPTH
//  - motion: RG16F at the render size (XeSS's default low-res motion vectors, so depth is required), in render pixels, from this
//    frame to the frame before, the jitter taken off. The guide: "Motion vectors specify the screen-space motion in pixels from
//    the current frame to the previous frame" and "do not include motion induced by the camera jitter": the same direction
//    and units, so the velocity scale is 1, 1 (xessSetVelocityScale), no XESS_INIT_FLAG_USE_NDC_VELOCITY nor _JITTERED_MV
//  - jitter: the chain's, in render pixels, x right and y down, each in [-0.5, 0.5). XeSS's (Jx, Jy) are the offset the
//    projection is sheared by, ProjectionMatrix[2][0] += Jx * 2 / InputWidth, ProjectionMatrix[2][1] -= Jy * 2 / InputHeight:
//    +Jx moves the picture right and +Jy down, in input pixels. That is the convention AMD FSR's jitterOffset has too
//    (its projection: +2 Jx / width, -2 Jy / height), which vk_fsr4.cpp hands the chain's jitter as it is: the jitter scale
//    is 1, 1 (xessSetJitterScale), the values passed as they come
#include "vk_xess.h"

#include <atomic>
#include <cstdlib>

#include "vk_internal.h"
#include "vk_temporal.h"
#include "xess_rules.h"

#if defined(_WIN32) && defined(HOOKSHOT_XESS)
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

#include "vk_gprof.h"
#include "vk_paths.h"
#include "vk_texture.h"

// (XESS_SHARED_LIB not defined: XESS_API is empty, the prototypes only declared, for their types; nothing calls them by name)
#include "xess/xess.h"
#include "xess/xess_vk.h"
#endif
#include "vk_work.h"   // (after the others: the barriers here count as work for full_barrier)

namespace mkwvk {

extern std::atomic<bool> present_native_pq;   // (vk_replay.cpp do_present: the game presents its own HDR10 picture, Native)

namespace {
// (what is known of XeSS on this device: -1 not yet, else an XessWhy. Set when Intel's library has been asked)
std::atomic<int> g_why{-1};
}  // namespace

XessWhy xess_why() {
    if (!xess_built()) return XESS_NOT_BUILT;
    static const bool env_off = xess_rules::env_mode(getenv("RX_VK_XESS")) == 0;
    if (env_off) return XESS_ENV_OFF;
    const int w = g_why.load(std::memory_order_relaxed);
    return w < 0 ? XESS_OK : (XessWhy)w;
}

#if defined(_WIN32) && defined(HOOKSHOT_XESS)

namespace {

constexpr const char* kLibrary = "libxess.dll";

/// Intel's library, loaded once (at the instance's making: its extensions are asked before it), its functions, and how far
/// the instance and the device took what it asked for
struct Library {
    std::mutex mu;
    bool tried = false, ok = false;
    HMODULE lib = nullptr;
    decltype(&xessGetVersion) get_version = nullptr;
    decltype(&xessVKGetRequiredInstanceExtensions) instance_extensions = nullptr;
    decltype(&xessVKGetRequiredDeviceExtensions) device_extensions = nullptr;
    decltype(&xessVKGetRequiredDeviceFeatures) device_features = nullptr;
    decltype(&xessVKCreateContext) create = nullptr;
    decltype(&xessVKInit) init = nullptr;
    decltype(&xessVKExecute) execute = nullptr;
    decltype(&xessDestroyContext) destroy = nullptr;
    decltype(&xessGetOptimalInputResolution) optimal_input = nullptr;
    decltype(&xessGetProperties) properties = nullptr;
    decltype(&xessSetVelocityScale) velocity_scale = nullptr;
    decltype(&xessSetJitterScale) jitter_scale = nullptr;
    decltype(&xessSetLoggingCallback) logging = nullptr;   // (optional, as the ones below)
    decltype(&xessIsOptimalDriver) optimal_driver = nullptr;
    decltype(&xessGetIntelXeFXVersion) xefx_version = nullptr;
    bool instance_ok = false;   // (the instance has every extension the library asked for)
    bool device_extensions_ok = false, device_ok = false;   // (the device: its extensions, then its features too)
    bool probed = false;
    xess_context_handle_t query = nullptr;   // (a context never initialised: the presets' input ranges are asked of it)
};
// (lib() and st() are never destroyed: Hookshot leaves through ExitProcess / exit() with the device alive, and a destructor
// then would call into Intel's library after its DLL_PROCESS_DETACH)
Library& lib() {
    static Library& l = *new Library;
    return l;
}

/// An XeSS context and what it was made for: destroyed a few frames after it is let go (temporal_later), as recorded
/// executions may still use it
struct Context {
    xess_context_handle_t context = nullptr;
    uint32_t width = 0, height = 0;   // (its output)
    int preset = -1;                  // (xess_rules::Preset)
    uint32_t min_w = 0, min_h = 0;    // (the smallest render size the preset takes for this output)
    bool hdr = false;                 // (made for the game's native HDR: linear light past 1, XeSS's own exposure)
    uint64_t memory = 0;              // (the temporary storage XeSS says it needs; its history is not counted)
    ~Context() {
        if (context) lib().destroy(context);
    }
};

struct State {
    std::shared_ptr<Context> context;
    uint32_t in_w = 0, in_h = 0;   // (the inputs' size under this context: the largest render size it has had)
    uint64_t evals = 0;
    int told_resets = 0;
};
State& st() {
    static State& s = *new State;   // (never destroyed: lib()'s note)
    return s;
}

const char* result_name(xess_result_t r) {
    switch (r) {
    case XESS_RESULT_SUCCESS: return "success";
    case XESS_RESULT_WARNING_NONEXISTING_FOLDER: return "warning: no such folder";
    case XESS_RESULT_WARNING_OLD_DRIVER: return "warning: an old driver";
    case XESS_RESULT_ERROR_UNSUPPORTED_DEVICE: return "unsupported device";
    case XESS_RESULT_ERROR_UNSUPPORTED_DRIVER: return "unsupported driver";
    case XESS_RESULT_ERROR_UNINITIALIZED: return "not initialised";
    case XESS_RESULT_ERROR_INVALID_ARGUMENT: return "invalid argument";
    case XESS_RESULT_ERROR_DEVICE_OUT_OF_MEMORY: return "out of video memory";
    case XESS_RESULT_ERROR_DEVICE: return "device error";
    case XESS_RESULT_ERROR_NOT_IMPLEMENTED: return "not implemented";
    case XESS_RESULT_ERROR_INVALID_CONTEXT: return "invalid context";
    case XESS_RESULT_ERROR_OPERATION_IN_PROGRESS: return "operation in progress";
    case XESS_RESULT_ERROR_UNSUPPORTED: return "unsupported";
    case XESS_RESULT_ERROR_CANT_LOAD_LIBRARY: return "cannot load a library";
    case XESS_RESULT_ERROR_WRONG_CALL_ORDER: return "wrong call order";
    default: return "unknown error";
    }
}

void on_message(const char* message, xess_logging_level_t level) {   // (any thread: logf is)
    logf("vk: Intel XeSS: Intel's %s: %s", level >= XESS_LOGGING_LEVEL_ERROR ? "error" : "warning", message ? message : "");
}

void* symbol(const char* name) { return (void*)GetProcAddress(lib().lib, name); }

bool no(XessWhy why) {
    g_why = why;
    return false;
}

/// Intel's library, once: false when XeSS cannot run here (g_why says why, the log too). Under l.mu
bool load_locked() {
    Library& l = lib();
    if (l.tried) return l.ok;
    l.tried = true;
    std::string exe_dir, game_dir;
    char exe[MAX_PATH];
    DWORD n = GetModuleFileNameA(nullptr, exe, MAX_PATH);
    if (n && n < MAX_PATH) exe_dir = std::string(exe, n).substr(0, std::string(exe, n).find_last_of("\\/"));
    n = game_module_path(exe, MAX_PATH);
    if (n && n < MAX_PATH) game_dir = std::string(exe, n).substr(0, std::string(exe, n).find_last_of("\\/"));
    std::string where;
    for (const std::string& dir : xess_rules::library_dirs(getenv("RX_VK_XESS_DIR"), exe_dir, game_dir)) {
        where += (where.empty() ? "" : ", ") + dir;
        const std::string path = dir + "\\" + kLibrary;
        if (GetFileAttributesA(path.c_str()) == INVALID_FILE_ATTRIBUTES) continue;
        // (the libraries it loads lie beside it: its folder first in the search. A relative RX_VK_XESS_DIR the flags refuse)
        l.lib = LoadLibraryExA(path.c_str(), nullptr, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
        if (!l.lib) {
            logf("vk: Intel XeSS: %s not loaded (Windows error %lu)", path.c_str(), (unsigned long)GetLastError());
            continue;
        }
        logf("vk: Intel XeSS: %s", path.c_str());
        break;
    }
    if (!l.lib) {
        logf("vk: Intel XeSS: no %s in %s (the readme says where Intel's file comes from)", kLibrary, where.c_str());
        return no(XESS_NO_LIBRARY);
    }
    l.get_version = (decltype(l.get_version))symbol("xessGetVersion");
    l.instance_extensions = (decltype(l.instance_extensions))symbol("xessVKGetRequiredInstanceExtensions");
    l.device_extensions = (decltype(l.device_extensions))symbol("xessVKGetRequiredDeviceExtensions");
    l.device_features = (decltype(l.device_features))symbol("xessVKGetRequiredDeviceFeatures");
    l.create = (decltype(l.create))symbol("xessVKCreateContext");
    l.init = (decltype(l.init))symbol("xessVKInit");
    l.execute = (decltype(l.execute))symbol("xessVKExecute");
    l.destroy = (decltype(l.destroy))symbol("xessDestroyContext");
    l.optimal_input = (decltype(l.optimal_input))symbol("xessGetOptimalInputResolution");
    l.properties = (decltype(l.properties))symbol("xessGetProperties");
    l.velocity_scale = (decltype(l.velocity_scale))symbol("xessSetVelocityScale");
    l.jitter_scale = (decltype(l.jitter_scale))symbol("xessSetJitterScale");
    l.logging = (decltype(l.logging))symbol("xessSetLoggingCallback");
    l.optimal_driver = (decltype(l.optimal_driver))symbol("xessIsOptimalDriver");
    l.xefx_version = (decltype(l.xefx_version))symbol("xessGetIntelXeFXVersion");
    if (!l.get_version || !l.instance_extensions || !l.device_extensions || !l.device_features || !l.create || !l.init ||
        !l.execute || !l.destroy || !l.optimal_input || !l.properties || !l.velocity_scale || !l.jitter_scale) {
        logf("vk: Intel XeSS: %s lacks XeSS's Vulkan entry points (an old or a D3D-only XeSS: 1.3 or newer has them)", kLibrary);
        return no(XESS_NO_LIBRARY);
    }
    xess_version_t v{};
    if (l.get_version(&v) == XESS_RESULT_SUCCESS) logf("vk: Intel XeSS: XeSS %u.%u.%u", v.major, v.minor, v.patch);
    l.ok = true;
    return true;
}

/// The context that answers the presets' ranges, made once on this device (the first ask: the menu's probe or the first
/// upscale). Under l.mu. false: XeSS cannot run here (g_why)
bool probe_locked() {
    Library& l = lib();
    if (l.probed) return l.query != nullptr;
    if (!dev.device || !load_locked()) return false;
    l.probed = true;
    if (!l.instance_ok || !l.device_ok) return no(XESS_NO_VULKAN);   // (said when it was found: xess_*_extensions)
    xess_context_handle_t c = nullptr;
    const xess_result_t r = l.create(dev.instance, dev.physical, dev.device, &c);
    if (r != XESS_RESULT_SUCCESS || !c) {
        logf("vk: Intel XeSS: no XeSS context on this GPU (%d, %s)", (int)r, result_name(r));
        return no(XESS_UNSUPPORTED);
    }
    if (l.logging) l.logging(c, XESS_LOGGING_LEVEL_WARNING, &on_message);
    if (l.optimal_driver && l.optimal_driver(c) == XESS_RESULT_WARNING_OLD_DRIVER)
        logf("vk: Intel XeSS: Intel's library says this driver may give a slower or worse picture (a newer one is better)");
    xess_version_t fx{};
    if (l.xefx_version && l.xefx_version(c, &fx) == XESS_RESULT_SUCCESS && (fx.major || fx.minor || fx.patch))
        logf("vk: Intel XeSS: Intel's XeFX library %u.%u.%u (Intel's GPU path)", fx.major, fx.minor, fx.patch);
    l.query = c;
    g_why = XESS_OK;
    return true;
}

/// The input range of each scaled preset for an output, as Intel's library gives it (xessGetOptimalInputResolution's
/// minimum; the guide's ratios rounded up where it has no answer)
void ranges_for(uint32_t ow, uint32_t oh, xess_rules::Range* out) {
    Library& l = lib();
    for (int p = 0; p < xess_rules::kPresets; p++) {
        out[p] = {xess_rules::min_input(ow, p), xess_rules::min_input(oh, p)};
        if (p == xess_rules::NATIVE_AA || !l.query) continue;
        const xess_2d_t o{ow, oh};
        xess_2d_t opt{}, mn{}, mx{};
        if (l.optimal_input(l.query, &o, (xess_quality_settings_t)xess_rules::kQuality[p], &opt, &mn, &mx) ==
                XESS_RESULT_SUCCESS && mn.x && mn.y)
            out[p] = {mn.x, mn.y};
    }
}

std::shared_ptr<Context> make_context(uint32_t ow, uint32_t oh, int preset, const xess_rules::Range& range, bool hdr) {
    Library& l = lib();
    auto c = std::make_shared<Context>();
    const auto t0 = std::chrono::steady_clock::now();
    xess_result_t r = l.create(dev.instance, dev.physical, dev.device, &c->context);
    if (r != XESS_RESULT_SUCCESS || !c->context) {
        logf("vk: Intel XeSS: no context (%d, %s)", (int)r, result_name(r));
        c->context = nullptr;
        return nullptr;
    }
    if (l.logging) l.logging(c->context, XESS_LOGGING_LEVEL_WARNING, &on_message);
    xess_vk_init_params_t ip{};
    ip.outputResolution = {ow, oh};
    ip.qualitySetting = (xess_quality_settings_t)xess_rules::kQuality[preset];
    // (LDR: the chain's colour is tonemapped and square-root encoded, exposure 1. HDR: linear light past 1, XeSS's exposure.
    // Depth not inverted, motion at the render size in pixels, the jitter taken off it: the defaults. The file's head says why)
    ip.initFlags = hdr ? (uint32_t)XESS_INIT_FLAG_ENABLE_AUTOEXPOSURE : (uint32_t)XESS_INIT_FLAG_LDR_INPUT_COLOR;
    ip.tempBufferHeap = VK_NULL_HANDLE, ip.tempTextureHeap = VK_NULL_HANDLE;   // (XeSS's own)
    ip.pipelineCache = VK_NULL_HANDLE;
    r = l.init(c->context, &ip);
    if (r != XESS_RESULT_SUCCESS) {
        logf("vk: Intel XeSS: not initialised for %ux%u, %s (%d, %s)", ow, oh, xess_rules::kName[preset], (int)r, result_name(r));
        return nullptr;   // (the context destroyed with it)
    }
    l.velocity_scale(c->context, 1.0f, 1.0f);   // (render pixels, towards the frame before: XeSS's own units and direction)
    l.jitter_scale(c->context, 1.0f, 1.0f);     // (render pixels, the projection's offset as XeSS's guide writes it)
    const double made_ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
    c->width = ow, c->height = oh, c->preset = preset, c->hdr = hdr;
    c->min_w = preset == xess_rules::NATIVE_AA ? ow : range.min_w, c->min_h = preset == xess_rules::NATIVE_AA ? oh : range.min_h;
    xess_properties_t props{};
    const xess_2d_t o{ow, oh};
    if (l.properties(c->context, &o, &props) == XESS_RESULT_SUCCESS)
        c->memory = props.tempBufferHeapSize + props.tempTextureHeapSize;
    logf("vk: Intel XeSS: %s made for outputs of %ux%u, render sizes from %ux%u (frame %llu, %.1f ms of CPU; its temporary "
         "storage %llu MB)%s", xess_rules::kName[preset], ow, oh, c->min_w, c->min_h, (unsigned long long)texture_frame_no(),
         made_ms, (unsigned long long)(c->memory >> 20), hdr ? ", HDR colour, linear (the game's native HDR)" : "");
    return c;
}

VkImageMemoryBarrier2 barrier(VkImage image, VkAccessFlags2 src, VkAccessFlags2 dst, VkImageLayout from, VkImageLayout to) {
    VkImageMemoryBarrier2 b{VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER_2};
    b.srcStageMask = b.dstStageMask = VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT;
    b.srcAccessMask = src, b.dstAccessMask = dst, b.oldLayout = from, b.newLayout = to;
    b.srcQueueFamilyIndex = b.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    b.image = image, b.subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
    return b;
}
void barriers(VkCommandBuffer cmd, const VkImageMemoryBarrier2* b, uint32_t n) {
    VkDependencyInfo di{VK_STRUCTURE_TYPE_DEPENDENCY_INFO};
    di.imageMemoryBarrierCount = n, di.pImageMemoryBarriers = b;
    vkCmdPipelineBarrier2(cmd, &di);
}

xess_vk_image_view_info view_info(const TemporalImage& im) {
    xess_vk_image_view_info v{};
    v.imageView = im.view, v.image = im.image, v.subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
    v.format = im.format, v.width = im.width, v.height = im.height;
    return v;
}

// ---- the engine (vk_temporal.h TemporalEngine) ----

bool start() {
    Library& l = lib();
    std::lock_guard lk(l.mu);
    return probe_locked();
}

void release() {
    State& s = st();
    if (!s.context) return;
    std::shared_ptr<Context> old = std::move(s.context);
    temporal_later([old] {});   // (destroyed with the last copy, a few frames on: recorded executions may still use it)
    s.context.reset();
}

int prepare(VkCommandBuffer, uint32_t rw, uint32_t rh, uint32_t ow, uint32_t oh, bool native_aa, uint32_t* in_w,
            uint32_t* in_h, const char** why) {
    State& s = st();
    // (the game's native HDR: Context::hdr. What the game presents, as FSR 4's. RX_VK_XESS_HDR=0: the LDR context and the
    // clamped colour with Native too)
    static const bool hdr_allowed = xess_rules::env_mode(getenv("RX_VK_XESS_HDR")) != 0;
    const bool hdr = hdr_allowed && present_native_pq.load(std::memory_order_relaxed);
    const bool native = native_aa;
    Context* c = s.context.get();
    const bool fits = c && c->width == ow && c->height == oh && c->hdr == hdr &&
                      (c->preset == xess_rules::NATIVE_AA) == native && rw <= ow && rh <= oh && rw >= c->min_w && rh >= c->min_h;
    int made = 1;
    if (!fits) {
        xess_rules::Range ranges[xess_rules::kPresets];
        {
            std::lock_guard lk(lib().mu);
            ranges_for(ow, oh, ranges);
        }
        const int preset = xess_rules::preset_for(rw, rh, ow, oh, native, ranges);
        if (preset < 0) return *why = native ? "XeSS's Native AA takes only the output's own size"
                                             : "no XeSS preset takes this render size (3x smaller at the most)", 0;
        if (c) {
            if (c->hdr != hdr) logf("vk: Intel XeSS: made again: the game's native HDR turned %s", hdr ? "on" : "off");
            else if (c->width != ow || c->height != oh) logf("vk: Intel XeSS: made again: the output is %ux%u", ow, oh);
            else logf("vk: Intel XeSS: made again: the render size %ux%u needs %s", rw, rh, xess_rules::kName[preset]);
        }
        release();
        s.context = make_context(ow, oh, preset, ranges[preset], hdr);
        if (!s.context) return *why = "its context was not made", -1;
        s.in_w = s.in_h = 0;
        made = 2;
    }
    // (the inputs as large as the largest render size this context has had, never past the output: the game's dynamic
    // resolution makes them again only when it goes past them; XeSS reads the frame's part at the top left, inputWidth x
    // inputHeight)
    s.in_w = std::min(std::max(s.in_w, rw), ow), s.in_h = std::min(std::max(s.in_h, rh), oh);
    *in_w = s.in_w, *in_h = s.in_h;
    return made;
}

bool evaluate(VkCommandBuffer cmd, const TemporalFrame& f) {
    State& s = st();
    Library& l = lib();
    constexpr VkImageLayout G = VK_IMAGE_LAYOUT_GENERAL, R = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
    constexpr VkAccessFlags2 any = VK_ACCESS_2_MEMORY_READ_BIT | VK_ACCESS_2_MEMORY_WRITE_BIT;
    const VkImageMemoryBarrier2 in[4] = {barrier(f.color.image, VK_ACCESS_2_MEMORY_WRITE_BIT, VK_ACCESS_2_SHADER_READ_BIT, G, R),
                                         barrier(f.depth.image, VK_ACCESS_2_MEMORY_WRITE_BIT, VK_ACCESS_2_SHADER_READ_BIT, G, R),
                                         barrier(f.motion.image, VK_ACCESS_2_MEMORY_WRITE_BIT, VK_ACCESS_2_SHADER_READ_BIT, G, R),
                                         barrier(f.output.image, any, any, G, G)};
    barriers(cmd, in, 4);

    xess_vk_execute_params_t p{};
    p.colorTexture = view_info(f.color);
    p.velocityTexture = view_info(f.motion);
    p.depthTexture = view_info(f.depth);
    p.outputTexture = view_info(f.output);   // (exposure and responsive mask: none, VK_NULL_HANDLE)
    p.jitterOffsetX = f.jitter[0], p.jitterOffsetY = f.jitter[1];   // (render pixels, x right and y down: the file's head)
    p.exposureScale = 1.0f;
    p.resetHistory = f.reset ? 1u : 0u;
    p.inputWidth = f.render_w, p.inputHeight = f.render_h;
    xess_result_t r;
    {
        GprofSpan timed(cmd, "xess xessVKExecute (Intel's passes)");   // (RX_VK_PASS_TIMING=1: Intel's own GPU time, named)
        ::mkwvk::rec::boundary(::mkwvk::rec::B_DIRECT);   // (xessVKExecute records into cmd itself: what this thread recorded through vk_work.h reaches cmd first)
        r = l.execute(s.context->context, cmd, &p);
        note_work();   // (Intel's dispatches: full_barrier must not take the next barrier for a repeat of the one before them)
    }

    const VkImageMemoryBarrier2 out[4] = {barrier(f.color.image, VK_ACCESS_2_SHADER_READ_BIT, any, R, G),
                                          barrier(f.depth.image, VK_ACCESS_2_SHADER_READ_BIT, any, R, G),
                                          barrier(f.motion.image, VK_ACCESS_2_SHADER_READ_BIT, any, R, G),
                                          barrier(f.output.image, any, any, G, G)};
    barriers(cmd, out, 4);
    if (r != XESS_RESULT_SUCCESS) {
        logf("vk: Intel XeSS: its execution failed (%d, %s)", (int)r, result_name(r));
        return false;
    }
    // (the first evaluation, and the first resets: a camera cut each)
    if (s.evals++ == 0 || (f.reset && s.told_resets < 40))
        s.told_resets++, logf("vk: Intel XeSS: %ux%u -> %ux%u (%s), jitter %+.3f %+.3f px%s", f.render_w, f.render_h,
                              f.output.width, f.output.height, xess_rules::kName[s.context->preset], f.jitter[0], f.jitter[1],
                              f.reset ? " (history reset)" : "");
    return true;
}

uint64_t memory() {
    State& s = st();
    return s.context ? s.context->memory : 0;
}

/// Its context takes HDR colour (made for the game's native HDR): the chain gives it linear light, unclamped
bool hdr() {
    State& s = st();
    return s.context && s.context->hdr;
}

const TemporalEngine kEngine{"Intel XeSS", "XeSS", start, prepare, evaluate, release, memory, hdr};

}  // namespace

bool xess_built() { return true; }
const TemporalEngine* xess_engine() { return &kEngine; }

bool xess_library_loaded() {
    if (xess_why() == XESS_ENV_OFF) return false;
    Library& l = lib();
    std::lock_guard lk(l.mu);
    return l.ok;
}

void xess_probe() {
    if (xess_why() != XESS_OK || g_why.load(std::memory_order_relaxed) >= 0 || !dev.device) return;
    Library& l = lib();
    std::lock_guard lk(l.mu);
    probe_locked();
}

void xess_instance_extensions(std::vector<const char*>& want, const std::vector<VkExtensionProperties>& all, uint32_t api) {
    if (xess_why() != XESS_OK) return;
    Library& l = lib();
    std::lock_guard lk(l.mu);
    if (!load_locked()) return;
    uint32_t n = 0, min_api = 0;
    const char* const* names = nullptr;
    const xess_result_t r = l.instance_extensions(&n, &names, &min_api);
    if (r != XESS_RESULT_SUCCESS) {
        logf("vk: Intel XeSS: no instance extensions from Intel's library (%d, %s): XeSS is off", (int)r, result_name(r));
        no(XESS_NO_VULKAN);
        return;
    }
    if (min_api > api) {
        logf("vk: Intel XeSS: it needs Vulkan %u.%u, the instance is %u.%u: XeSS is off", VK_API_VERSION_MAJOR(min_api),
             VK_API_VERSION_MINOR(min_api), VK_API_VERSION_MAJOR(api), VK_API_VERSION_MINOR(api));
        no(XESS_NO_VULKAN);
        return;
    }
    std::vector<const char*> add;
    std::string listed;
    for (uint32_t i = 0; i < n && names; i++) {
        if (!names[i]) continue;
        listed += (listed.empty() ? "" : ", ") + std::string(names[i]);
        bool has = false, wanted = false;
        for (const auto& e : all) has |= !std::strcmp(e.extensionName, names[i]);
        for (const char* w : want) wanted |= !std::strcmp(w, names[i]);
        if (!has) {
            logf("vk: Intel XeSS: the Vulkan loader has no %s, which XeSS needs: XeSS is off", names[i]);
            no(XESS_NO_VULKAN);
            return;
        }
        if (!wanted) add.push_back(names[i]);   // (the library's memory, kept as long as it is loaded: for good)
    }
    want.insert(want.end(), add.begin(), add.end());
    l.instance_ok = true;
    logf("vk: Intel XeSS: instance extensions %s", listed.empty() ? "none" : listed.c_str());
}

void xess_device_extensions(std::vector<const char*>& want, const std::vector<VkExtensionProperties>& all) {
    if (xess_why() != XESS_OK) return;
    Library& l = lib();
    std::lock_guard lk(l.mu);
    if (!l.ok || !l.instance_ok || !dev.instance || !dev.physical) return;
    uint32_t n = 0;
    const char* const* names = nullptr;
    const xess_result_t r = l.device_extensions(dev.instance, dev.physical, &n, &names);
    if (r != XESS_RESULT_SUCCESS) {
        logf("vk: Intel XeSS: no device extensions from Intel's library for this GPU (%d, %s): XeSS is off", (int)r,
             result_name(r));
        no(r == XESS_RESULT_ERROR_UNSUPPORTED_DEVICE ? XESS_UNSUPPORTED : XESS_NO_VULKAN);
        return;
    }
    std::vector<const char*> add;
    std::string listed;
    for (uint32_t i = 0; i < n && names; i++) {
        if (!names[i]) continue;
        listed += (listed.empty() ? "" : ", ") + std::string(names[i]);
        bool has = false, wanted = false;
        for (const auto& e : all) has |= !std::strcmp(e.extensionName, names[i]);
        for (const char* w : want) wanted |= !std::strcmp(w, names[i]);
        if (!has) {
            logf("vk: Intel XeSS: the GPU has no %s, which XeSS needs: XeSS is off", names[i]);
            no(XESS_NO_VULKAN);
            return;
        }
        if (!wanted) add.push_back(names[i]);
    }
    want.insert(want.end(), add.begin(), add.end());
    l.device_extensions_ok = true;
    logf("vk: Intel XeSS: device extensions %s", listed.empty() ? "none" : listed.c_str());
}

/// The Vulkan version whose VkPhysicalDeviceVulkan1NFeatures holds a feature structure's features (1, 2, 3), 0 for another
static int promoted_to(VkStructureType t) {
    switch (t) {
    case VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_16BIT_STORAGE_FEATURES:
    case VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_MULTIVIEW_FEATURES:
    case VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VARIABLE_POINTERS_FEATURES:
    case VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROTECTED_MEMORY_FEATURES:
    case VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SAMPLER_YCBCR_CONVERSION_FEATURES:
    case VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SHADER_DRAW_PARAMETERS_FEATURES: return 1;
    case VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_8BIT_STORAGE_FEATURES:
    case VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SHADER_ATOMIC_INT64_FEATURES:
    case VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SHADER_FLOAT16_INT8_FEATURES:
    case VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DESCRIPTOR_INDEXING_FEATURES:
    case VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SCALAR_BLOCK_LAYOUT_FEATURES:
    case VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_IMAGELESS_FRAMEBUFFER_FEATURES:
    case VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_UNIFORM_BUFFER_STANDARD_LAYOUT_FEATURES:
    case VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SHADER_SUBGROUP_EXTENDED_TYPES_FEATURES:
    case VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SEPARATE_DEPTH_STENCIL_LAYOUTS_FEATURES:
    case VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_HOST_QUERY_RESET_FEATURES:
    case VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_TIMELINE_SEMAPHORE_FEATURES:
    case VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_BUFFER_DEVICE_ADDRESS_FEATURES:
    case VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_MEMORY_MODEL_FEATURES: return 2;
    case VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_IMAGE_ROBUSTNESS_FEATURES:
    case VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_INLINE_UNIFORM_BLOCK_FEATURES:
    case VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PIPELINE_CREATION_CACHE_CONTROL_FEATURES:
    case VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PRIVATE_DATA_FEATURES:
    case VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SHADER_DEMOTE_TO_HELPER_INVOCATION_FEATURES:
    case VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SHADER_TERMINATE_INVOCATION_FEATURES:
    case VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SUBGROUP_SIZE_CONTROL_FEATURES:
    case VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SYNCHRONIZATION_2_FEATURES:
    case VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_TEXTURE_COMPRESSION_ASTC_HDR_FEATURES:
    case VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_ZERO_INITIALIZE_WORKGROUP_MEMORY_FEATURES:
    case VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DYNAMIC_RENDERING_FEATURES:
    case VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SHADER_INTEGER_DOT_PRODUCT_FEATURES:
    case VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_MAINTENANCE_4_FEATURES: return 3;
    default: return 0;
    }
}

void xess_device_features(void** first, void** tail) {
    if (xess_why() != XESS_OK) return;
    Library& l = lib();
    std::lock_guard lk(l.mu);
    if (!l.device_extensions_ok) return;
    void* const was = *first;
    void* chain = *first;
    const xess_result_t r = l.device_features(dev.instance, dev.physical, &chain);
    if (r != XESS_RESULT_SUCCESS || !chain) {
        logf("vk: Intel XeSS: the device features it needs were not given (%d, %s): XeSS is off", (int)r, result_name(r));
        *first = was, *tail = nullptr;   // (anything it added cut off: the chain as the renderer made it)
        no(XESS_NO_VULKAN);
        return;
    }
    // (no structure twice in the chain, and none beside the Vulkan 1.1 / 1.2 / 1.3 one that holds the same features
    // (VUID-VkDeviceCreateInfo-pNext-02829/02830/06532): such a structure the library added is taken out again, what it asked
    // for of shaderInt8 and shaderIntegerDotProduct (the two the guide names) set in the renderer's. The renderer's chain was
    // filled with every feature the GPU has (vkGetPhysicalDeviceFeatures2), and the library asks only for features the GPU
    // has, so the others are on already)
    bool core[4] = {};   // (the renderer's chain has VkPhysicalDeviceVulkan1NFeatures, N = 1, 2, 3)
    VkPhysicalDeviceVulkan12Features* v12 = nullptr;
    VkPhysicalDeviceVulkan13Features* v13 = nullptr;
    for (auto* b = (VkBaseOutStructure*)chain; b; b = b->pNext) {
        if (b->sType == VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_1_FEATURES) core[1] = true;
        if (b->sType == VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_2_FEATURES && !v12) v12 = (VkPhysicalDeviceVulkan12Features*)b;
        if (b->sType == VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_3_FEATURES && !v13) v13 = (VkPhysicalDeviceVulkan13Features*)b;
    }
    core[2] = v12 != nullptr, core[3] = v13 != nullptr;
    std::vector<VkStructureType> seen;
    int dropped = 0;
    VkBaseOutStructure* prev = nullptr;
    for (auto* b = (VkBaseOutStructure*)chain; b;) {
        VkBaseOutStructure* const next = b->pNext;
        bool drop = std::find(seen.begin(), seen.end(), b->sType) != seen.end() || core[promoted_to(b->sType)];
        if (b->sType == VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SHADER_FLOAT16_INT8_FEATURES && v12) {
            const auto* x = (const VkPhysicalDeviceShaderFloat16Int8Features*)b;
            v12->shaderFloat16 |= x->shaderFloat16, v12->shaderInt8 |= x->shaderInt8;
        }
        if (b->sType == VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SHADER_INTEGER_DOT_PRODUCT_FEATURES && v13)
            v13->shaderIntegerDotProduct |= ((const VkPhysicalDeviceShaderIntegerDotProductFeatures*)b)->shaderIntegerDotProduct;
        if (drop) {
            dropped++;
            if (prev) prev->pNext = next;   // (the library's memory: left as it is)
            else chain = next;
        } else {
            seen.push_back(b->sType), prev = b;
        }
        b = next;
    }
    *first = chain;
    l.device_ok = true;
    logf("vk: Intel XeSS: device features asked for (%zu structures in the chain, %d of the library's merged into the "
         "renderer's)", seen.size(), dropped);
}

#else  // (not Windows: Intel makes no XeSS library for Linux. XeSS is not there)

bool xess_built() { return false; }
const TemporalEngine* xess_engine() { return nullptr; }
bool xess_library_loaded() { return false; }
void xess_probe() {}
void xess_instance_extensions(std::vector<const char*>&, const std::vector<VkExtensionProperties>&, uint32_t) {}
void xess_device_extensions(std::vector<const char*>&, const std::vector<VkExtensionProperties>&) {}
void xess_device_features(void**, void**) {}

#endif

}  // namespace mkwvk
