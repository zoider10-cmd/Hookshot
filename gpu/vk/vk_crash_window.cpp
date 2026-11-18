// (hookshot) The crash window (crash_window_api.h): the crash helper's pages (host/hos_crash_dialog.c), drawn as the Insert
// menu is (vk_ui.h: its banner, its box, its buttons, its fonts), in one window that goes from page to page. Through the SDL
// the helper loaded, by name (SDL3 or SDL2, whichever it is), and SDL's software renderer: no Vulkan and not even the GPU's
// driver, as the crash may have been the GPU's. Dear ImGui lays the text out and makes the triangles; SDL_RenderGeometryRaw
// draws them (ImGui's own SDL_Renderer back ends link SDL, which this module does not). Keys: Tab and the arrows pick a
// button, Enter presses it, Escape the last; the wheel, Page Up and Page Down scroll a page longer than the window. A press
// is the player's choice, not input left over (Input): no key repeats, nothing in a page's first kQuiet, and a key that went
// down then only once it has been let go.
#include <algorithm>
#include <bitset>
#include <chrono>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

#include "vk_ui.h"
#include "crash_window_api.h"

extern const unsigned hookshot_font_body_size, hookshot_font_strong_size, hookshot_font_heading_size;
extern const unsigned char hookshot_font_body[], hookshot_font_strong[], hookshot_font_heading[];

namespace {

using namespace mkwvk;

// ---- SDL, by name: the calls the window makes, as SDL3 and SDL2 each have them ----
struct Sdl {
    int v = 0;
    void* (*sym)(const char*) = nullptr;
    template <class F>
    bool get(F& f, const char* three, const char* two) {
        f = (F)sym(v == 3 ? three : two);
        return f != nullptr;
    }
    void* InitSubSystem = nullptr; void* CreateWindow = nullptr; void* CreateRenderer = nullptr; void* OutputSize = nullptr;
    void* WindowSize = nullptr; void* CreateTexture = nullptr; void* UpdateTexture = nullptr; void* BlendMode = nullptr;
    void* ScaleMode = nullptr; void* Geometry = nullptr; void* ClipRect = nullptr; void* DrawColor = nullptr;
    void* Clear = nullptr; void* Present = nullptr; void* WaitEvent = nullptr; void* DestroyTexture = nullptr;
    void* DestroyRenderer = nullptr; void* DestroyWindow = nullptr; void* SetTitle = nullptr; void* Raise = nullptr;
    void* MinSize = nullptr; void* Hint = nullptr;
    bool load(const MkwCrashSdl* s) {
        v = s->version, sym = s->sym;
        if ((v != 2 && v != 3) || !sym) return false;
        bool ok = get(InitSubSystem, "SDL_InitSubSystem", "SDL_InitSubSystem") && get(CreateWindow, "SDL_CreateWindow", "SDL_CreateWindow") &&
                  get(CreateRenderer, "SDL_CreateRenderer", "SDL_CreateRenderer") &&
                  get(OutputSize, "SDL_GetRenderOutputSize", "SDL_GetRendererOutputSize") &&
                  get(WindowSize, "SDL_GetWindowSize", "SDL_GetWindowSize") && get(CreateTexture, "SDL_CreateTexture", "SDL_CreateTexture") &&
                  get(UpdateTexture, "SDL_UpdateTexture", "SDL_UpdateTexture") &&
                  get(BlendMode, "SDL_SetTextureBlendMode", "SDL_SetTextureBlendMode") &&
                  get(Geometry, "SDL_RenderGeometryRaw", "SDL_RenderGeometryRaw") &&   // (SDL 2.0.18 on)
                  get(ClipRect, "SDL_SetRenderClipRect", "SDL_RenderSetClipRect") &&
                  get(DrawColor, "SDL_SetRenderDrawColor", "SDL_SetRenderDrawColor") && get(Clear, "SDL_RenderClear", "SDL_RenderClear") &&
                  get(Present, "SDL_RenderPresent", "SDL_RenderPresent") && get(WaitEvent, "SDL_WaitEventTimeout", "SDL_WaitEventTimeout") &&
                  get(DestroyTexture, "SDL_DestroyTexture", "SDL_DestroyTexture") &&
                  get(DestroyRenderer, "SDL_DestroyRenderer", "SDL_DestroyRenderer") &&
                  get(DestroyWindow, "SDL_DestroyWindow", "SDL_DestroyWindow") && get(SetTitle, "SDL_SetWindowTitle", "SDL_SetWindowTitle");
        get(ScaleMode, "SDL_SetTextureScaleMode", "SDL_SetTextureScaleMode");   // (optional: SDL 2.0.12 on)
        get(Raise, "SDL_RaiseWindow", "SDL_RaiseWindow");
        get(MinSize, "SDL_SetWindowMinimumSize", "SDL_SetWindowMinimumSize");
        get(Hint, "SDL_SetHint", "SDL_SetHint");
        return ok;
    }
#define SDL_CALL(type, f) ((type)f)
    bool init_video() {
        return v == 3 ? SDL_CALL(bool (*)(uint32_t), InitSubSystem)(0x20) : SDL_CALL(int (*)(uint32_t), InitSubSystem)(0x20) == 0;
    }
    void* window(const char* title, int w, int h) {
        if (v == 3) return SDL_CALL(void* (*)(const char*, int, int, uint64_t), CreateWindow)(title, w, h, 0x20 | 0x2000);
        return SDL_CALL(void* (*)(const char*, int, int, int, int, uint32_t), CreateWindow)(title, 0x2FFF0000, 0x2FFF0000, w, h,
                                                                                           0x4 | 0x20 | 0x2000);
    }
    // (SDL's software renderer: the GPU's driver is never touched, as the crash may have been in it. A page is still, and
    // small: drawn again only on an event)
    void* renderer(void* win) {
        if (v == 3) return SDL_CALL(void* (*)(void*, const char*), CreateRenderer)(win, "software");
        return SDL_CALL(void* (*)(void*, int, uint32_t), CreateRenderer)(win, -1, 0x1 /* SDL_RENDERER_SOFTWARE */);
    }
    void output_size(void* r, int* w, int* h) {
        *w = *h = 0;
        if (v == 3) SDL_CALL(bool (*)(void*, int*, int*), OutputSize)(r, w, h);
        else SDL_CALL(int (*)(void*, int*, int*), OutputSize)(r, w, h);
    }
    void window_size(void* win, int* w, int* h) {
        *w = *h = 0;
        if (v == 3) SDL_CALL(bool (*)(void*, int*, int*), WindowSize)(win, w, h);
        else SDL_CALL(void (*)(void*, int*, int*), WindowSize)(win, w, h);
    }
    void* texture(void* r, int w, int h, const void* pixels) {
        void* t = SDL_CALL(void* (*)(void*, uint32_t, int, int, int), CreateTexture)(r, 0x16762004 /* ABGR8888: RGBA bytes */, 0, w, h);
        if (!t) return nullptr;
        SDL_CALL(int (*)(void*, int), BlendMode)(t, 1);   // (blend; SDL3's bool is returned the same way, unread)
        if (ScaleMode) SDL_CALL(int (*)(void*, int), ScaleMode)(t, 1);   // (linear: the glyphs drawn between pixels stay smooth)
        upload(t, w, pixels);
        return t;
    }
    void upload(void* t, int w, const void* pixels) { SDL_CALL(int (*)(void*, const void*, const void*, int), UpdateTexture)(t, nullptr, pixels, w * 4); }
    void clip(void* r, int x, int y, int w, int h) {
        const int rect[4] = {x, y, w, h};
        SDL_CALL(int (*)(void*, const int*), ClipRect)(r, rect);
    }
    void clear(void* r, ImU32 c) {
        SDL_CALL(int (*)(void*, uint8_t, uint8_t, uint8_t, uint8_t), DrawColor)(r, c & 255, c >> 8 & 255, c >> 16 & 255, 255);
        SDL_CALL(int (*)(void*), Clear)(r);
    }
    void present(void* r) { SDL_CALL(int (*)(void*), Present)(r); }
    bool wait(uint8_t* raw, int ms) {
        return v == 3 ? SDL_CALL(bool (*)(void*, int32_t), WaitEvent)(raw, ms) : SDL_CALL(int (*)(void*, int), WaitEvent)(raw, ms) != 0;
    }
    void geometry(void* r, void* tex, const ImDrawVert* vtx, int nv, const ImDrawIdx* idx, int ni, std::vector<float>& colors) {
        const int st = (int)sizeof(ImDrawVert);
        const float* xy = (const float*)((const char*)vtx + offsetof(ImDrawVert, pos));
        const float* uv = (const float*)((const char*)vtx + offsetof(ImDrawVert, uv));
        if (v == 3) {   // (SDL3 takes the colours as floats)
            colors.resize((size_t)nv * 4);
            for (int i = 0; i < nv; i++)
                for (int k = 0; k < 4; k++) colors[(size_t)i * 4 + k] = (float)(vtx[i].col >> (8 * k) & 255) / 255.0f;
            SDL_CALL(bool (*)(void*, void*, const float*, int, const float*, int, const float*, int, int, const void*, int, int), Geometry)(
                r, tex, xy, st, colors.data(), 16, uv, st, nv, idx, ni, (int)sizeof(ImDrawIdx));
        } else {        // (SDL2 as bytes: ImGui's own order, R first)
            const uint8_t* col = (const uint8_t*)vtx + offsetof(ImDrawVert, col);
            SDL_CALL(int (*)(void*, void*, const float*, int, const uint8_t*, int, const float*, int, int, const void*, int, int), Geometry)(
                r, tex, xy, st, col, st, uv, st, nv, idx, ni, (int)sizeof(ImDrawIdx));
        }
    }
#undef SDL_CALL
};

// ---- the input a page takes, read from SDL's events at their offsets (host/hos_sdl.c reads the same) ----
// (a page's first moments take no press: a key held or mashed as the game died, a key or click queued while the page before
// was sending, never presses a button the player has not read. The window raises itself, so it gets those keys)
constexpr auto kQuiet = std::chrono::milliseconds(400);
struct Input {
    bool quit = false, resized = false, left = false;
    bool moved = false, down = false, up = false;
    float x = 0, y = 0, wheel = 0;
    int scancode = 0;   // (a key pressed: its USB HID usage; 0 none)
    bool shift = false;
    bool quiet = false;               // (in the page's first kQuiet: presses are not taken)
    std::bitset<512>* held = nullptr;   // (the page's keys that went down unheard and are not yet let go)
};
// A key going down (not a repeat) or up, in the order SDL had them
void key_event(Input& in, int code, bool down, uint16_t mods) {
    if (code <= 0 || code >= 512) return;
    if (!down) {
        in.held->reset((size_t)code);
        return;
    }
    if (in.quiet) in.held->set((size_t)code);
    if (in.held->test((size_t)code)) return;
    in.scancode = code, in.shift = mods & 3;
}
void read_event(int v, const uint8_t* raw, Input& in) {
    uint32_t type;
    memcpy(&type, raw, 4);
    float f[2];
    int32_t i[2];
    if (type == 0x100) in.quit = true;
    if (v == 3) {
        switch (type) {
        case 0x210: in.quit = true; break;                         // (close requested)
        case 0x206: case 0x207: case 0x204: in.resized = true; break;   // (resized, pixel size changed, exposed)
        case 0x20d: in.left = true; break;
        case 0x300: case 0x301:   // (key down, up: SDL_KeyboardEvent's scancode at 24, mod at 32, repeat at 37)
            if (type == 0x300 && raw[37]) break;
            memcpy(i, raw + 24, 4), key_event(in, i[0], type == 0x300, (uint16_t)(raw[32] | raw[33] << 8));
            break;
        case 0x400: memcpy(f, raw + 28, 8), in.x = f[0], in.y = f[1], in.moved = true, in.left = false; break;
        case 0x401: case 0x402:
            if (raw[24] != 1) break;
            memcpy(f, raw + 28, 8), in.x = f[0], in.y = f[1], in.moved = true;
            if (type == 0x401 && in.quiet) break;
            (type == 0x401 ? in.down : in.up) = true;
            break;
        case 0x403: {
            uint32_t dir;
            memcpy(f, raw + 28, 4), memcpy(&dir, raw + 32, 4);
            in.wheel += dir == 1 ? -f[0] : f[0];
            break;
        }
        }
        return;
    }
    switch (type) {
    case 0x200:
        if (raw[12] == 14) in.quit = true;
        else if (raw[12] == 11) in.left = true;
        else if (raw[12] == 3 || raw[12] == 5 || raw[12] == 6) in.resized = true;
        break;
    case 0x300: case 0x301:   // (key down, up: SDL_KeyboardEvent's repeat at 13, keysym's scancode at 16, mod at 24)
        if (type == 0x300 && raw[13]) break;
        memcpy(i, raw + 16, 4), key_event(in, i[0], type == 0x300, (uint16_t)(raw[24] | raw[25] << 8));
        break;
    case 0x400: memcpy(i, raw + 20, 8), in.x = (float)i[0], in.y = (float)i[1], in.moved = true, in.left = false; break;
    case 0x401: case 0x402:
        if (raw[16] != 1) break;
        memcpy(i, raw + 20, 8), in.x = (float)i[0], in.y = (float)i[1], in.moved = true;
        if (type == 0x401 && in.quiet) break;
        (type == 0x401 ? in.down : in.up) = true;
        break;
    case 0x403: {
        uint32_t dir;
        memcpy(i, raw + 20, 8), dir = (uint32_t)i[1];
        in.wheel += (float)(dir == 1 ? -i[0] : i[0]);
        break;
    }
    }
}

// ---- the window: made at the first page, kept for the next ----
struct Window {
    Sdl sdl;
    void* win = nullptr;
    void* ren = nullptr;
    ImGuiContext* ctx = nullptr;
    ui::Fonts fonts;
    std::vector<float> colors;
    std::chrono::steady_clock::time_point last;
};
Window* g_window = nullptr;

void textures(Window& w, ImDrawData* dd) {
    if (!dd->Textures) return;
    for (ImTextureData* t : *dd->Textures) {
        if (t->Status == ImTextureStatus_WantCreate) {
            void* st = w.sdl.texture(w.ren, t->Width, t->Height, t->GetPixels());
            t->SetTexID((ImTextureID)(intptr_t)st);
            t->SetStatus(st ? ImTextureStatus_OK : ImTextureStatus_Destroyed);
        } else if (t->Status == ImTextureStatus_WantUpdates) {   // (new glyphs: the whole atlas again, small at this size)
            w.sdl.upload((void*)(intptr_t)t->GetTexID(), t->Width, t->GetPixels());
            t->SetStatus(ImTextureStatus_OK);
        } else if (t->Status == ImTextureStatus_WantDestroy && t->UnusedFrames > 0) {
            if (t->GetTexID()) ((void (*)(void*))w.sdl.DestroyTexture)((void*)(intptr_t)t->GetTexID());
            t->SetTexID(ImTextureID_Invalid);
            t->SetStatus(ImTextureStatus_Destroyed);
        }
    }
}
void render(Window& w, ImDrawData* dd) {
    textures(w, dd);
    w.sdl.clear(w.ren, ui::rgba(22, 17, 11));
    for (ImDrawList* list : dd->CmdLists) {
        for (const ImDrawCmd& cmd : list->CmdBuffer) {
            if (cmd.UserCallback || cmd.ElemCount == 0) continue;
            const ImVec4 r = cmd.ClipRect;
            if (r.z <= r.x || r.w <= r.y) continue;
            w.sdl.clip(w.ren, (int)r.x, (int)r.y, (int)(r.z - r.x), (int)(r.w - r.y));
            w.sdl.geometry(w.ren, (void*)(intptr_t)cmd.GetTexID(), list->VtxBuffer.Data + cmd.VtxOffset,
                           list->VtxBuffer.Size - (int)cmd.VtxOffset, list->IdxBuffer.Data + cmd.IdxOffset, (int)cmd.ElemCount, w.colors);
        }
    }
    w.sdl.present(w.ren);
}

Window* open_window(const MkwCrashSdl* s, const char* title) {
    if (g_window) return g_window;
    auto* w = new Window;
    if (!w->sdl.load(s)) return delete w, nullptr;
    auto hint = (int (*)(const char*, const char*))w->sdl.Hint;
    // (X11 where there is one, XWayland on a Wayland desktop: SDL's Wayland driver has no window framebuffer of its own, so no
    // software renderer without the GPU ("Window framebuffer support not available"); X11's has. Wayland when X11 can't be had.
    // SDL_VIDEO_DRIVER (SDL_VIDEODRIVER) in the environment still wins over the hint)
    const char* x11 = getenv("DISPLAY");
    const char* driver = w->sdl.v == 3 ? "SDL_VIDEO_DRIVER" : "SDL_VIDEODRIVER";
    bool video = false;
    if (hint && x11 && *x11) {
        hint(driver, "x11");
        video = w->sdl.init_video();
        if (!video) hint(driver, nullptr);
    }
    if (!video && !w->sdl.init_video()) return delete w, nullptr;
    if (hint) {
        hint("SDL_RENDER_SCALE_QUALITY", "1");        // (SDL2: linear)
        hint("SDL_FRAMEBUFFER_ACCELERATION", "0");   // (the window's pixels in memory: not a GPU texture, as SDL makes by default)
    }
    w->win = w->sdl.window(title, 860, 560);
    w->ren = w->win ? w->sdl.renderer(w->win) : nullptr;
    if (!w->ren) {
        if (w->win) ((void (*)(void*))w->sdl.DestroyWindow)(w->win);
        delete w;
        return nullptr;
    }
    if (w->sdl.MinSize) ((void (*)(void*, int, int))w->sdl.MinSize)(w->win, 560, 380);
    if (w->sdl.Raise) ((void (*)(void*))w->sdl.Raise)(w->win);
    IMGUI_CHECKVERSION();
    w->ctx = ImGui::CreateContext();
    ImGuiIO& io = ImGui::GetIO();
    io.IniFilename = nullptr, io.LogFilename = nullptr;
    io.BackendFlags |= ImGuiBackendFlags_RendererHasTextures | ImGuiBackendFlags_RendererHasVtxOffset;
    io.Fonts->TexDesiredFormat = ImTextureFormat_RGBA32;
    auto font = [](const unsigned char* data, unsigned size, const char* name) {
        ImFontConfig cfg;
        cfg.FontDataOwnedByAtlas = false;   // (the compiled-in bytes)
        snprintf(cfg.Name, sizeof cfg.Name, "%s", name);
        return ImGui::GetIO().Fonts->AddFontFromMemoryTTF((void*)data, (int)size, 18.0f, &cfg);
    };
    w->fonts.body = font(hookshot_font_body, hookshot_font_body_size, "Libertinus Sans");
    w->fonts.strong = font(hookshot_font_strong, hookshot_font_strong_size, "Libertinus Sans Bold");
    w->fonts.heading = font(hookshot_font_heading, hookshot_font_heading_size, "Libertinus Serif Semibold");
    w->last = std::chrono::steady_clock::now();
    return g_window = w;
}

// ---- a page's layout: the text's lines wrapped, the buttons in rows, everything in pixels from the unit s ----
struct Layout {
    float s, w, h, banner, pad, top, bottom;   // (top, bottom: the scrolled part's)
    std::vector<ImVec4> buttons;              // (x0, y0, x1, y1)
};
Layout lay_out(ui::Ctx& c, const MkwCrashPage& p) {
    Layout l;
    l.s = c.s, l.w = c.w, l.h = c.h, l.banner = 64 * c.s, l.pad = 28 * c.s;
    const float bh = 44 * c.s, gap = 12 * c.s, room = c.w - 2 * l.pad;
    std::vector<float> widths;
    for (int i = 0; i < p.nbuttons; i++)
        widths.push_back(std::max(140 * c.s, ui::size_of(c.f.strong, 20 * c.s, p.buttons[i]).x + 44 * c.s));
    // (rows from the last button up, so the first ones sit together on the bottom row's left when they must wrap)
    std::vector<std::pair<int, int>> rows;   // (first, count)
    for (int i = 0; i < p.nbuttons;) {
        int n = 0;
        float used = 0;
        while (i + n < p.nbuttons && (n == 0 || used + gap + widths[i + n] <= room)) used += (n ? gap : 0) + widths[i + n], n++;
        rows.push_back({i, n});
        i += n;
    }
    float y = c.h - l.pad - bh * rows.size() - gap * (rows.size() - 1);
    l.bottom = y - 22 * c.s;
    for (auto [first, n] : rows) {
        float used = 0;
        for (int k = 0; k < n; k++) used += (k ? gap : 0) + widths[first + k];
        float x = c.w - l.pad - used;   // (right-aligned, as the launcher's own window has them)
        for (int k = 0; k < n; k++) {
            l.buttons.push_back(ImVec4(x, y, x + widths[first + k], y + bh));
            x += widths[first + k] + gap;
        }
        y += bh + gap;
    }
    l.top = l.banner + 20 * c.s;
    return l;
}
/// The page's scrolled part from y (scroll already taken off); its height. draw false: measured only
float body(ui::Ctx& c, const Layout& l, const MkwCrashPage& p, float y, bool draw) {
    const float px = 19 * c.s, wrap = c.w - 2 * l.pad;
    const float y0 = y;
    for (const char* t = p.text ? p.text : ""; *t;) {
        const char* nl = strchr(t, '\n');
        const std::string line(t, nl ? (size_t)(nl - t) : strlen(t));
        if (line.empty()) y += px * 0.6f;
        else y += ui::para(c, c.f.body, px, ImVec2(l.pad, y), ui::kInk, line.c_str(), wrap, draw) + px * 0.45f;
        t = nl ? nl + 1 : t + strlen(t);
    }
    if (p.block && *p.block) {
        const float bpx = 15.5f * c.s, inner = 14 * c.s;
        y += 8 * c.s;
        float th = 0;
        std::vector<std::string> lines;
        for (const char* t = p.block; *t;) {
            const char* nl = strchr(t, '\n');
            lines.emplace_back(t, nl ? (size_t)(nl - t) : strlen(t));
            t = nl ? nl + 1 : t + strlen(t);
        }
        for (const std::string& ln : lines)
            th += ln.empty() ? bpx * 0.7f : ui::para(c, c.f.body, bpx, ImVec2(0, 0), 0, ln.c_str(), wrap - 2 * inner, false) + bpx * 0.3f;
        if (draw) {
            ui::box(c, ImVec2(l.pad, y), ImVec2(c.w - l.pad, y + th + 2 * inner));
            float by = y + inner;
            for (const std::string& ln : lines)
                by += ln.empty() ? bpx * 0.7f
                                 : ui::para(c, c.f.body, bpx, ImVec2(l.pad + inner, by), ui::kSoft, ln.c_str(), wrap - 2 * inner) + bpx * 0.3f;
        }
        y += th + 2 * inner;
    }
    return y - y0;
}

int page(Window& w, const MkwCrashPage& p) {
    ((void (*)(void*, const char*))w.sdl.SetTitle)(w.win, p.title ? p.title : "Hookshot");
    int sel = 0, pressed = -1, result = -3;   // (pressed: the button the mouse went down on, on this page only)
    float scroll = 0, mx = -1, my = -1;
    bool dirty = true;
    const auto shown = std::chrono::steady_clock::now();
    std::bitset<512> held;
    while (result == -3) {
        Input in;
        in.held = &held;
        alignas(8) uint8_t raw[128];
        if (w.sdl.wait(raw, dirty ? 0 : 500)) {
            in.quiet = std::chrono::steady_clock::now() - shown < kQuiet;
            read_event(w.sdl.v, raw, in);
            while (w.sdl.wait(raw, 0)) read_event(w.sdl.v, raw, in);
            dirty = true;
        }
        if (in.quit) return -1;
        if (!dirty) continue;
        dirty = false;
        int pw, ph, ww, wh;
        w.sdl.output_size(w.ren, &pw, &ph);
        w.sdl.window_size(w.win, &ww, &wh);
        if (pw <= 0 || ph <= 0) continue;
        const float density = ww > 0 ? (float)pw / ww : 1.0f;
        if (in.moved) mx = in.x * density, my = in.y * density;
        if (in.left) mx = my = -1;

        ImGuiIO& io = ImGui::GetIO();
        io.DisplaySize = ImVec2((float)pw, (float)ph);
        const auto now = std::chrono::steady_clock::now();
        io.DeltaTime = std::max(1e-4f, std::chrono::duration<float>(now - w.last).count());
        w.last = now;
        ImGui::NewFrame();
        // (the unit: the window's density, a little smaller in a small window, so the page's lines fit it)
        const float s = density * std::clamp(std::min(pw / density / 860.0f, ph / density / 560.0f) * 0.25f + 0.75f, 0.8f, 1.15f);
        ui::Ctx c{ImGui::GetBackgroundDrawList(), w.fonts, s, (float)pw, (float)ph, 0, false};
        const Layout l = lay_out(c, p);

        // (the scrolled part: how far it may go, the wheel and the keys)
        const float total = body(c, l, p, 0, false), view = std::max(1.0f, l.bottom - l.top);
        const float most = std::max(0.0f, total - view);
        scroll -= in.wheel * 60 * s;
        if (in.scancode == 75) scroll -= view * 0.9f;   // (Page Up)
        if (in.scancode == 78) scroll += view * 0.9f;   // (Page Down)
        if (in.scancode == 74) scroll = 0;              // (Home)
        if (in.scancode == 77) scroll = most;           // (End)
        scroll = std::clamp(scroll, 0.0f, most);

        // (the buttons: under the mouse, or picked with the keys)
        int hover = -1;
        for (int i = 0; i < (int)l.buttons.size(); i++) {
            const ImVec4& b = l.buttons[i];
            if (mx >= b.x && mx < b.z && my >= b.y && my < b.w) hover = i;
        }
        if (in.moved && hover >= 0) sel = hover;
        const int n = p.nbuttons;
        if (in.scancode == 43) sel = (sel + (in.shift ? n - 1 : 1)) % n;   // (Tab, Shift+Tab)
        if (in.scancode == 79 || in.scancode == 81) sel = std::min(n - 1, sel + 1);   // (right, down)
        if (in.scancode == 80 || in.scancode == 82) sel = std::max(0, sel - 1);       // (left, up)
        if (in.scancode == 40 || in.scancode == 88 || in.scancode == 44) result = sel;  // (Enter, the keypad's, Space)
        if (in.scancode == 41) result = n - 1;                                          // (Escape)
        if (in.down) pressed = hover;
        if (in.up) {
            if (pressed >= 0 && pressed == hover) result = hover;
            pressed = -1;
        }

        // (the page, as the Insert menu's: its banner and title, the text, a fine flourish above the buttons)
        c.d->AddRectFilledMultiColor(ImVec2(0, 0), ImVec2(c.w, c.h), ui::rgba(40, 31, 21), ui::rgba(40, 31, 21), ui::rgba(22, 17, 11),
                                     ui::rgba(22, 17, 11));
        c.d->PushClipRect(ImVec2(0, l.top - 8 * s), ImVec2(c.w, l.bottom), true);
        body(c, l, p, l.top - scroll, true);
        c.d->PopClipRect();
        if (most > 0) {   // (where in the page it is: a thin gold bar at the right)
            const float x = c.w - 10 * s, len = view * view / total, at = l.top + (view - len) * scroll / most;
            c.d->AddRectFilled(ImVec2(x, l.top), ImVec2(x + 3 * s, l.bottom), ui::alpha(ui::kEdge, 0.6f), 2 * s);
            c.d->AddRectFilled(ImVec2(x, at), ImVec2(x + 3 * s, at + len), ui::kGold, 2 * s);
        }
        ui::banner(c, l.banner);
        ui::text_mid(c, c.f.heading, 30 * s, l.pad, l.banner * 0.5f - 2 * s, ui::kBannerInk, p.heading ? p.heading : "");
        ui::flourish(c, l.pad, c.w - l.pad, l.bottom + 10 * s, ui::kAccent);
        for (int i = 0; i < (int)l.buttons.size(); i++) {
            const ImVec4& b = l.buttons[i];
            ui::button(c, ImVec2(b.x, b.y), ImVec2(b.z, b.w), p.buttons[i], i == sel);
        }
        ImGui::Render();
        render(w, ImGui::GetDrawData());
        // (new glyphs baked this frame: drawn again with them)
        if (ImGui::GetDrawData()->Textures)
            for (ImTextureData* t : *ImGui::GetDrawData()->Textures)
                if (t->Status != ImTextureStatus_OK && t->Status != ImTextureStatus_Destroyed) dirty = true;
        if (in.resized) dirty = true;
    }
    return result;
}

} // namespace

extern "C"
#ifdef _WIN32
__declspec(dllexport)
#else
__attribute__((visibility("default")))
#endif
int mkwvk_crash_page(const MkwCrashSdl* sdl, const MkwCrashPage* p) {
    if (!sdl || !p || p->nbuttons < 1 || p->nbuttons > 4) return -2;
    Window* w = open_window(sdl, p->title ? p->title : "Hookshot");
    if (!w) return -2;
    ImGui::SetCurrentContext(w->ctx);
    return page(*w, *p);
}

extern "C"
#ifdef _WIN32
__declspec(dllexport)
#else
__attribute__((visibility("default")))
#endif
void mkwvk_crash_close(void) {
    Window* w = g_window;
    if (!w) return;
    ImGui::SetCurrentContext(w->ctx);
    for (ImTextureData* t : ImGui::GetPlatformIO().Textures)
        if (t->GetTexID()) ((void (*)(void*))w->sdl.DestroyTexture)((void*)(intptr_t)t->GetTexID());
    ImGui::DestroyContext(w->ctx);
    ((void (*)(void*))w->sdl.DestroyRenderer)(w->ren);
    ((void (*)(void*))w->sdl.DestroyWindow)(w->win);
    delete w;
    g_window = nullptr;
}
