// (hookshot) The overlays' three fonts (vk_imgui.cpp loads them for the renderer's menu, vk_crash_window.cpp for the crash
// window), apart from the renderer's headers: vk_ui.h's drawing needs only these, so a window with no Vulkan draws with it too.
#pragma once

struct ImFont;

namespace mkwvk::ui {

struct Fonts {
    ImFont* body = nullptr;      // (rows, help, prompts)
    ImFont* strong = nullptr;    // (the selected row, values, buttons)
    ImFont* heading = nullptr;   // (tabs, titles, the wordmark)
};

} // namespace mkwvk::ui
