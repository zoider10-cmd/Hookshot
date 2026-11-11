// (hookshot) How the overlays look (vk_menu.cpp draws the Insert menu, the FPS counter and the start-up screen with these): in
// the style of the game's own pause and options screens, so they sit naturally over it. Our own drawing on ImGui's draw lists
// (no texture, icon or ornament of the game's); the font is the game's own menu font from the player's files, else Libertinus
// (vk_imgui.cpp). Sizes are points of a 720-line window times the unit (unit()). Every text sits on its own background at a
// contrast of 4.5:1 or more (WCAG), a white game pixel behind at worst: gold only for the selected value, with dark text on it.
#pragma once

#define IMGUI_DEFINE_MATH_OPERATORS
#include <algorithm>
#include <cfloat>
#include <cmath>
#include <cstring>

#include "imgui.h"
#include "vk_imgui.h"

namespace mkwvk::ui {

constexpr ImU32 rgba(int r, int g, int b, int a = 255) { return IM_COL32(r, g, b, a); }
inline ImU32 alpha(ImU32 c, float k) {
    const int a = (int)((c >> IM_COL32_A_SHIFT & 0xFF) * k);
    return (c & ~IM_COL32_A_MASK) | ((ImU32)std::clamp(a, 0, 255) << IM_COL32_A_SHIFT);
}

// ---- the palette ----
// (Mako) Its own look, the launcher's: deep navy panels, an electric blue selection with white text on it, cyan accents, rounded
// corners. Every text keeps 4.5:1 or more on its own background (WCAG AA); the selection's blue is dark enough for white text.
constexpr ImU32 kInk = rgba(232, 240, 250), kInkBright = rgba(255, 255, 255), kSoft = rgba(186, 202, 224), kDim = rgba(138, 156, 184),
                kGold = rgba(22, 92, 206), kGoldHi = rgba(96, 200, 255), kGoldInk = rgba(255, 255, 255), kAccent = rgba(88, 196, 255),
                kSelTop = rgba(40, 122, 236), kSelBot = rgba(22, 92, 206),
                kEdge = rgba(72, 96, 136, 150), kCellDark = rgba(10, 16, 28, 246), kCellName = rgba(20, 30, 50, 240),
                kCellNameSel = rgba(30, 50, 86, 248), kBronze = rgba(34, 50, 80), kColumn = rgba(8, 13, 24, 228),
                kBannerTop = rgba(18, 28, 48, 250), kBanner = rgba(10, 17, 32, 250), kBannerInk = rgba(214, 226, 244),
                kBannerEdge = rgba(88, 196, 255), kTabInset = rgba(34, 58, 100, 250), kChip = rgba(36, 52, 84), kBox = rgba(12, 19, 34, 248),
                kBoxEdge = rgba(64, 90, 132, 220), kBar = rgba(6, 10, 20, 236), kListen = rgba(30, 100, 200);
constexpr float kRound = 6;   // (corner radius in points: cells, boxes, buttons)
constexpr int kDimAlpha = 185;   // (the game behind the menu)

/// The unit: pixels per point. By the window's height and the Menu size (0 Auto, 1 Small, 2 Medium, 3 Large; Auto is Large
/// in fullscreen at 1080 lines and up while a controller is in use); *margin: the edge kept clear (5% at Large, the TV size)
inline float unit(float h, int size, bool fullscreen, bool pad, float* margin) {
    if (size <= 0 || size > 3) size = fullscreen && h >= 1080 && pad ? 3 : 2;
    const float k = size == 1 ? 0.85f : size == 3 ? 1.3f : 1.0f;
    *margin = h * (size == 3 ? 0.05f : 0.025f);
    return h / 720.0f * k;
}

struct Ctx {
    ImDrawList* d;
    Fonts f;
    float s;      // (pixels per point)
    float w, h;   // (the window)
    float safe;   // (the margin kept clear at each edge, pixels)
    bool pad;     // (a controller was the last input: its buttons in the prompts)
    int confirm_dot = 3, back_dot = 1;   // (the face buttons that confirm and go back: vk_menu_keys.h dot, 3 the bottom, 1 the right)
};

inline ImVec2 size_of(ImFont* font, float px, const char* t, float wrap = 0) { return font->CalcTextSizeA(px, FLT_MAX, wrap, t); }
inline float text(Ctx& c, ImFont* font, float px, ImVec2 p, ImU32 col, const char* t, float wrap = 0) {
    c.d->AddText(font, px, p, col, t, nullptr, wrap);
    return size_of(font, px, t, wrap).x;
}
/// Text wrapped at wrap pixels, its lines 1.3 em apart (ImGui's own wrap sets them 1 em apart: too tight for reading); its
/// height. draw false: measured only
inline float para(Ctx& c, ImFont* font, float px, ImVec2 p, ImU32 col, const char* t, float wrap, bool draw = true) {
    const char* end = t + strlen(t);
    float y = 0;
    while (t < end) {
        const char* cut = font->CalcWordWrapPosition(px, t, end, wrap);
        if (cut == t) cut = t + 1;   // (a word wider than the line: a letter at least)
        if (draw) c.d->AddText(font, px, ImVec2(p.x, p.y + y), col, t, cut);
        y += px * 1.3f;
        t = cut;
        while (t < end && (*t == ' ' || *t == '\n')) t++;
    }
    return y > 0 ? y - px * 0.3f : 0;
}
/// The top to draw at for capitals centred on y: from the font's own ascent (fonts differ), a cap height of 0.7 em
inline float mid_top(ImFont* font, float px, float y) { return y - font->GetFontBaked(px)->Ascent + 0.35f * px; }
inline float text_mid(Ctx& c, ImFont* font, float px, float x, float y, ImU32 col, const char* t) {
    return text(c, font, px, ImVec2(x, mid_top(font, px, y)), col, t);
}
inline void text_mid_centre(Ctx& c, ImFont* font, float px, float cx, float y, ImU32 col, const char* t) {
    text_mid(c, font, px, cx - size_of(font, px, t).x * 0.5f, y, col, t);
}
inline void text_mid_right(Ctx& c, ImFont* font, float px, float x, float y, ImU32 col, const char* t) {
    text_mid(c, font, px, x - size_of(font, px, t).x, y, col, t);
}
inline void text_centre(Ctx& c, ImFont* font, float px, ImVec2 p, ImU32 col, const char* t) {
    text(c, font, px, ImVec2(p.x - size_of(font, px, t).x * 0.5f, p.y), col, t);
}
/// Capitals with extra space between the letters (gap in pixels), centred on x
inline void spaced(Ctx& c, ImFont* font, float px, ImVec2 p, ImU32 col, const char* t, float gap) {
    char one[2] = {0, 0};
    float total = 0;
    for (const char* q = t; *q; q++) one[0] = *q, total += size_of(font, px, one).x + gap;
    float x = p.x - (total - gap) * 0.5f;
    for (const char* q = t; *q; q++) {
        one[0] = *q;
        c.d->AddText(font, px, ImVec2(x, p.y), col, one);
        x += size_of(font, px, one).x + gap;
    }
}
/// A soft shadow under a rectangle: layers growing outwards, fading
inline void shadow(Ctx& c, ImVec2 a, ImVec2 b, float spread, float strength, float dy) {
    const int n = 16;
    for (int i = n; i >= 1; i--) {
        const float k = (float)i / n, e = spread * k;
        c.d->AddRectFilled(a - ImVec2(e, e) + ImVec2(0, dy), b + ImVec2(e, e) + ImVec2(0, dy),
                           rgba(0, 0, 0, (int)(255 * strength * (1 - k) * (1 - k) / 3.5f)), e);
    }
}
inline void triangle(Ctx& c, ImVec2 m, float size, int dir, ImU32 col) {   // (dir: 0 left, 1 right, 2 up, 3 down)
    const float a = size * 0.5f, b = size * 0.42f;
    switch (dir) {
    case 0: c.d->AddTriangleFilled(m + ImVec2(b, -a), m + ImVec2(-b, 0), m + ImVec2(b, a), col); break;
    case 1: c.d->AddTriangleFilled(m + ImVec2(-b, -a), m + ImVec2(b, 0), m + ImVec2(-b, a), col); break;
    case 2: c.d->AddTriangleFilled(m + ImVec2(-a, b), m + ImVec2(0, -b), m + ImVec2(a, b), col); break;
    default: c.d->AddTriangleFilled(m + ImVec2(-a, -b), m + ImVec2(a, -b), m + ImVec2(0, b), col); break;
    }
}
inline void diamond(Ctx& c, ImVec2 m, float r, ImU32 col) {
    c.d->AddQuadFilled(m + ImVec2(0, -r), m + ImVec2(r, 0), m + ImVec2(0, r), m + ImVec2(-r, 0), col);
}
/// A divider: a fine faint line with a small flourish of two mirrored curls at its middle
inline void flourish(Ctx& c, float x0, float x1, float y, ImU32 col) {
    const float s = c.s, m = (x0 + x1) * 0.5f, t = std::max(1.0f, 0.8f * s);
    c.d->AddLine(ImVec2(x0, y), ImVec2(m - 30 * s, y), alpha(col, 0.35f), t);
    c.d->AddLine(ImVec2(m + 30 * s, y), ImVec2(x1, y), alpha(col, 0.35f), t);
    for (int side = -1; side <= 1; side += 2) {
        const float k = (float)side;
        c.d->AddBezierCubic(ImVec2(m + k * 4 * s, y), ImVec2(m + k * 11 * s, y - 7 * s), ImVec2(m + k * 21 * s, y - 6 * s),
                            ImVec2(m + k * 19 * s, y), alpha(col, 0.8f), 1.3f * s);
        c.d->AddBezierCubic(ImVec2(m + k * 19 * s, y), ImVec2(m + k * 17 * s, y + 5 * s), ImVec2(m + k * 11 * s, y + 4 * s),
                            ImVec2(m + k * 12 * s, y + 1 * s), alpha(col, 0.8f), 1.3f * s);
    }
    diamond(c, ImVec2(m, y), 2.2f * s, alpha(col, 0.8f));
}
/// The selection: a bright outline with a soft warm-white glow around it
inline void glow(Ctx& c, ImVec2 a0, ImVec2 b0) {
    const float s = c.s;
    for (int i = 6; i >= 1; i--)
        c.d->AddRect(a0 - ImVec2(i * 1.5f * s, i * 1.5f * s), b0 + ImVec2(i * 1.5f * s, i * 1.5f * s), rgba(120, 200, 255, 12 + 5 * (6 - i)),
                     (kRound + i * 1.5f) * s, 0, 2.2f * s);
    c.d->AddRect(a0 - ImVec2(1.5f * s, 1.5f * s), b0 + ImVec2(1.5f * s, 1.5f * s), kInkBright, (kRound + 1.5f) * s, 0, 2.5f * s);
}
/// The selection's fill: electric blue, lighter at its top, rounded (the flat colours in the rounded corners, the gradient
/// between them)
inline void gold(Ctx& c, ImVec2 a0, ImVec2 b0) {
    const float r = std::min(kRound * c.s, (b0.y - a0.y) * 0.5f);
    c.d->AddRectFilled(a0, b0, kSelBot, r);
    c.d->AddRectFilled(a0, ImVec2(b0.x, a0.y + 2 * r), kSelTop, r, ImDrawFlags_RoundCornersTop);
    if (b0.y - a0.y > 2 * r) c.d->AddRectFilledMultiColor(ImVec2(a0.x, a0.y + r), ImVec2(b0.x, b0.y - r), kSelTop, kSelTop, kSelBot, kSelBot);
}

// ---- the button prompts: the keys, or a controller's buttons by position (any layout: the dot lit) ----
enum Glyph { kUpDown, kLeftRight, kTabs, kConfirm, kBack, kKey };
struct Prompt {
    Glyph g;
    const char* what;
    const char* key = nullptr;   // (kKey: a key's name, shown with the keys and with a controller alike)
};
/// One glyph at p (its top left; the line px + 10 points high); its width. draw false: measured only
inline float glyph(Ctx& c, float px, ImVec2 p, const Prompt& pr, bool draw) {
    const float s = c.s, hh = px + 10 * s, my = p.y + hh * 0.5f, kpx = px * 0.84f;
    const ImU32 cap = kInk, ink = rgba(12, 20, 36), dim = rgba(128, 142, 164);
    auto key = [&](float x, const char* label) {   // (a key's cap, its label in it)
        const float w = label ? std::max(hh, size_of(c.f.strong, kpx, label).x + 14 * s) : hh;
        if (draw) {
            c.d->AddRectFilled(ImVec2(x, p.y), ImVec2(x + w, p.y + hh), cap, 4 * s);
            if (label) text_mid_centre(c, c.f.strong, kpx, x + w * 0.5f, my, ink, label);
        }
        return w;
    };
    if (pr.g == kKey) return key(p.x, pr.key);
    if (!c.pad) {
        switch (pr.g) {
        case kUpDown:
        case kLeftRight: {
            const bool v = pr.g == kUpDown;
            const float w = key(p.x, nullptr);
            key(p.x + w + 3 * s, nullptr);
            if (draw) triangle(c, ImVec2(p.x + w * 0.5f, my), 8 * s, v ? 2 : 0, ink), triangle(c, ImVec2(p.x + w * 1.5f + 3 * s, my), 8 * s, v ? 3 : 1, ink);
            return 2 * w + 3 * s;
        }
        case kTabs: {
            const float w = key(p.x, "Q");
            return w + 3 * s + key(p.x + w + 3 * s, "E");
        }
        case kConfirm: return key(p.x, "Enter");
        default: return key(p.x, "Esc");
        }
    }
    const float r = hh * 0.5f;
    const ImVec2 m(p.x + r, my);
    if (pr.g == kTabs) {   // (the shoulder buttons)
        float x = p.x;
        for (const char* l : {"L", "R"}) {
            const float w = hh * 1.25f;
            if (draw) {
                c.d->AddRectFilled(ImVec2(x, p.y + 2 * s), ImVec2(x + w, p.y + hh - 2 * s), cap, (hh - 4 * s) * 0.5f);
                text_mid_centre(c, c.f.strong, px * 0.8f, x + w * 0.5f, my, ink, l);
            }
            x += w + 3 * s;
        }
        return x - p.x - 3 * s;
    }
    if (!draw) return 2 * r;
    c.d->AddCircleFilled(m, r, cap);
    if (pr.g == kUpDown || pr.g == kLeftRight) {   // (the D-pad: a cross, the arms in use dark)
        const float arm = r * 0.26f, len = r * 0.68f;
        const bool v = pr.g == kUpDown;
        c.d->AddRectFilled(m - ImVec2(arm, len), m + ImVec2(arm, len), v ? ink : dim, arm * 0.5f);
        c.d->AddRectFilled(m - ImVec2(len, arm), m + ImVec2(len, arm), v ? dim : ink, arm * 0.5f);
        c.d->AddRectFilled(m - ImVec2(arm, arm), m + ImVec2(arm, arm), ink);
    } else {   // (the face buttons, four dots: the bottom one confirms, the right one goes back)
        const int lit = pr.g == kConfirm ? c.confirm_dot : c.back_dot;   // (0 top, 1 right, 2 left, 3 bottom)
        const ImVec2 at[4] = {m + ImVec2(0, -r * 0.5f), m + ImVec2(r * 0.5f, 0), m + ImVec2(-r * 0.5f, 0), m + ImVec2(0, r * 0.5f)};
        for (int i = 0; i < 4; i++) {
            if (i == lit) c.d->AddCircleFilled(at[i], r * 0.27f, ink);
            else c.d->AddCircle(at[i], r * 0.22f, dim, 0, std::max(1.0f, s));
        }
    }
    return 2 * r;
}
/// The prompts, the label before its button as the game's own: their width (draw false: measured only)
inline float prompts(Ctx& c, ImVec2 p, const Prompt* list, int n, bool draw) {
    const float s = c.s, px = 17 * s, hh = px + 10 * s, x0 = p.x;
    for (int i = 0; i < n; i++) {
        if (draw) text_mid(c, c.f.body, px, p.x, p.y + hh * 0.5f, kInk, list[i].what);
        p.x += size_of(c.f.body, px, list[i].what).x + 8 * s;
        p.x += glyph(c, px, p, list[i], draw) + 26 * s;
    }
    return n ? p.x - x0 - 26 * s : 0;
}
/// The prompt strip's top: the same at any prompts (the menu lays out above it before it draws the strip, last, on top)
inline float prompt_bar_top(const Ctx& c) { return c.h - c.safe - (17 * c.s + 10 * c.s) - 12 * c.s; }
/// The prompts at the bottom right on a solid strip, drawn over whatever is under it; its top (prompt_bar_top). Prompts wider
/// than the window between its margins take the whole width, and smaller ones still if they must
inline float prompt_bar(Ctx& c, const Prompt* list, int n) {
    const float s = c.s, px = 17 * s, ph = px + 10 * s, py = c.h - c.safe - ph;
    Ctx k = c;   // (the prompts' own scale: smaller only when they do not fit the width)
    const float room = c.w - 2 * c.safe - 20 * s, full = prompts(c, ImVec2(0, 0), list, n, false);
    if (full > room) k.s = s * room / full;
    const float pw = prompts(k, ImVec2(0, 0), list, n, false);
    const float x0 = std::max(0.0f, c.w - c.safe - pw - 34 * s);
    if (x0 > 0) c.d->AddRectFilledMultiColor(ImVec2(std::max(0.0f, x0 - 80 * s), py - 12 * s), ImVec2(x0, c.h), alpha(kBar, 0), kBar, kBar,
                                             alpha(kBar, 0));
    c.d->AddRectFilled(ImVec2(x0, py - 12 * s), ImVec2(c.w, c.h), kBar);
    c.d->AddLine(ImVec2(x0, py - 12 * s), ImVec2(c.w, py - 12 * s), alpha(kEdge, 0.8f), std::max(1.0f, s));
    const float kh = 17 * k.s + 10 * k.s;   // (smaller prompts: centred in the strip's height)
    prompts(k, ImVec2(c.w - c.safe - pw - 10 * s, py + (ph - kh) * 0.5f), list, n, true);
    return py - 12 * s;
}
/// The navy banner across the top, hh pixels high, a thin cyan line at its foot fading at both ends
inline void banner(Ctx& c, float hh) {
    const float s = c.s, t = std::max(1.0f, 1.5f * s);
    c.d->AddRectFilledMultiColor(ImVec2(0, 0), ImVec2(c.w, hh), kBannerTop, kBannerTop, kBanner, kBanner);
    const ImU32 clear = alpha(kBannerEdge, 0);
    c.d->AddRectFilledMultiColor(ImVec2(0, hh - t), ImVec2(c.w * 0.5f, hh), clear, kBannerEdge, kBannerEdge, clear);
    c.d->AddRectFilledMultiColor(ImVec2(c.w * 0.5f, hh - t), ImVec2(c.w, hh), kBannerEdge, clear, clear, kBannerEdge);
}
/// A box (the help, the restart question): opaque, a fine edge, a soft shadow
inline void box(Ctx& c, ImVec2 a, ImVec2 b) {
    const float r = kRound * 1.5f * c.s;
    shadow(c, a, b, 18 * c.s, 0.8f, 4 * c.s);
    c.d->AddRectFilled(a, b, kBox, r);
    c.d->AddRect(a, b, kBoxEdge, r, 0, 1.5f * c.s);
}
/// A button as the game's pause menu draws its own: a warm cell with a fine inner frame; selected, gold with the outline
inline void button(Ctx& c, ImVec2 a0, ImVec2 b0, const char* label, bool sel) {
    const float s = c.s;
    if (sel) gold(c, a0, b0);
    else c.d->AddRectFilled(a0, b0, kCellName, kRound * s);
    c.d->AddRect(a0, b0, sel ? alpha(kInkBright, 0.5f) : kEdge, kRound * s, 0, std::max(1.0f, s));
    ImFont* f = sel ? c.f.strong : c.f.body;
    text_mid_centre(c, f, 20 * s, (a0.x + b0.x) * 0.5f, (a0.y + b0.y) * 0.5f, sel ? kGoldInk : kInk, label);
    if (sel) glow(c, a0, b0);
}

} // namespace mkwvk::ui
