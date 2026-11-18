// Game-free documentation capture. Compile the maintained menu in this translation unit;
// never initialize the game, the Vulkan renderer, menu persistence or game-provided fonts.
#include "gpu/vk/vk_menu.cpp"
#include <SDL.h>
#include <png.h>
#include <stdexcept>

// Any accidental attempt to resolve a game directory fails closed.
extern "C" DWORD GetModuleFileNameA(HMODULE, LPSTR, DWORD) { std::abort(); }
extern "C" DWORD GetFileAttributesA(LPCSTR) { std::abort(); }

// Explicit fixture capabilities: no GPU-specific upscaler or latency SDK. These are
// display inputs, not probes of the capture machine or claims about supported hardware.
namespace mkwvk {
const MkwVkHost* host = nullptr;
Device dev{}; // No physical device: hide hardware-specific Debug actions in this UI-only fixture.
std::atomic<bool> present_native_pq{false}; // Synthetic SDR presentation, never a live HDR surface.
void logf(const char*, ...) {}
std::vector<std::string> gpu_device_names;
std::vector<gpu_choice::Card> gpu_device_cards;
std::string options_path() { std::abort(); } // Capture never reads or writes player settings.
bool dlss_built() { return false; }
DlssWhy dlss_why() { return DLSS_NOT_BUILT; }
uint64_t device_vram_bytes() { return 0; } // No physical device: the DLSS model row as on an unknown card (K).
int dlss_fg_skip(unsigned* most) { if (most) *most = 0; return FG_SKIP_NOT_BUILT; }
int dlss_fg_unavailable() { return FG_SKIP_NOT_BUILT; }
bool dlss_fg_forced() { return false; }
bool fsr4_built() { return false; }
FsrWhy fsr4_why() { return FSR_NOT_BUILT; }
bool xess_built() { return false; }
XessWhy xess_why() { return XESS_NOT_BUILT; }
bool fsr3_wanted() { return false; }
namespace fsr3 { bool supported() { return false; } }
namespace fsr3fi { uint32_t frames_wanted() { return 0; } }
bool reflex_available() { return false; }
bool antilag_available() { return false; }
int temporal_mode() { return 0; }
bool temporal_off() { return false; }
FgMaker framegen_maker() { return static_cast<FgMaker>(0); }
namespace bug_report {
State state() { return kIdle; }
std::string shown() { return {}; }
}
}

static void check(bool ok, const char* what) {
    if (!ok) throw std::runtime_error(std::string(what) + ": " + SDL_GetError());
}

// SDL's software renderer consumes the real ImGui triangles, clip rectangles and
// dynamic font atlas. No recreation of menu labels, rows or layout lives here.
static void render(SDL_Renderer* renderer, ImDrawData* data) {
    for (ImTextureData* t : *data->Textures) {
        if (t->Status == ImTextureStatus_WantDestroy) {
            SDL_DestroyTexture(reinterpret_cast<SDL_Texture*>(t->GetTexID()));
            t->SetTexID(ImTextureID_Invalid);
            t->SetStatus(ImTextureStatus_Destroyed);
            continue;
        }
        if (t->Status != ImTextureStatus_WantCreate && t->Status != ImTextureStatus_WantUpdates) continue;
        check(t->Format == ImTextureFormat_RGBA32, "RGBA font atlas required");
        auto* texture = reinterpret_cast<SDL_Texture*>(t->GetTexID());
        if (t->Status == ImTextureStatus_WantCreate) {
            texture = SDL_CreateTexture(renderer, SDL_PIXELFORMAT_RGBA32, SDL_TEXTUREACCESS_STATIC, t->Width, t->Height);
            check(texture != nullptr, "create atlas texture");
            check(SDL_SetTextureBlendMode(texture, SDL_BLENDMODE_BLEND) == 0, "atlas blending");
            check(SDL_SetTextureScaleMode(texture, SDL_ScaleModeLinear) == 0, "atlas filtering");
            t->SetTexID(reinterpret_cast<ImTextureID>(texture));
        }
        check(SDL_UpdateTexture(texture, nullptr, t->GetPixels(), t->GetPitch()) == 0, "upload atlas");
        t->SetStatus(ImTextureStatus_OK);
    }
    for (const ImDrawList* list : data->CmdLists) {
        for (const ImDrawCmd& cmd : list->CmdBuffer) {
            check(cmd.UserCallback == nullptr, "unexpected drawing callback");
            SDL_Rect clip{std::max(0, int(cmd.ClipRect.x)), std::max(0, int(cmd.ClipRect.y)),
                          int(std::min(data->DisplaySize.x, cmd.ClipRect.z)) - std::max(0, int(cmd.ClipRect.x)),
                          int(std::min(data->DisplaySize.y, cmd.ClipRect.w)) - std::max(0, int(cmd.ClipRect.y))};
            if (clip.w <= 0 || clip.h <= 0) continue;
            check(SDL_RenderSetClipRect(renderer, &clip) == 0, "clip rectangle");
            const ImDrawVert* v = list->VtxBuffer.Data + cmd.VtxOffset;
            check(SDL_RenderGeometryRaw(renderer, reinterpret_cast<SDL_Texture*>(cmd.GetTexID()),
                &v->pos.x, sizeof(ImDrawVert), reinterpret_cast<const SDL_Color*>(&v->col), sizeof(ImDrawVert),
                &v->uv.x, sizeof(ImDrawVert), list->VtxBuffer.Size - cmd.VtxOffset,
                list->IdxBuffer.Data + cmd.IdxOffset, cmd.ElemCount, sizeof(ImDrawIdx)) == 0, "menu geometry");
        }
    }
    SDL_RenderSetClipRect(renderer, nullptr);
    SDL_RenderPresent(renderer);
}

int main(int argc, char** argv) {
    if (argc != 4) { fprintf(stderr, "usage: menu-capture FONT_DIRECTORY graphics|graphics-screen|audio|controls OUTPUT.png\n"); return 2; }
    try {
        const std::string tab = argv[2];
        if (tab != "graphics" && tab != "graphics-screen" && tab != "audio" && tab != "controls") throw std::runtime_error("unsupported view");
        constexpr int width = 1280, height = 720;
        check(SDL_Init(0) == 0, "SDL initialization");
        SDL_Surface* surface = SDL_CreateRGBSurfaceWithFormat(0, width, height, 32, SDL_PIXELFORMAT_RGBA32);
        check(surface != nullptr, "capture surface");
        SDL_Renderer* renderer = SDL_CreateSoftwareRenderer(surface);
        check(renderer != nullptr, "software renderer");
        ImGui::CreateContext();
        auto& io = ImGui::GetIO();
        io.IniFilename = nullptr;
        io.LogFilename = nullptr;
        io.DisplaySize = ImVec2(width, height);
        io.DeltaTime = 1.f / 60;
        io.BackendFlags |= ImGuiBackendFlags_RendererHasTextures | ImGuiBackendFlags_RendererHasVtxOffset;
        auto font = [&](const char* name) {
            std::string path = std::string(argv[1]) + "/" + name;
            ImFont* f = io.Fonts->AddFontFromFileTTF(path.c_str(), 18);
            if (!f) throw std::runtime_error("missing bundled font: " + path);
            return f;
        };
        mkwvk::ui::Fonts fonts{font("LibertinusSans-Regular.ttf"), font("LibertinusSans-Bold.ttf"), font("LibertinusSerif-Semibold.ttf")};
        mkwvk::opts.menu_lang = 1; // English; do not read language.txt or environment-selected game language.
        mkwvk::cur_tab = tab == "audio" ? mkwvk::TAB_AUDIO : tab == "controls" ? mkwvk::TAB_CONTROLS : mkwvk::TAB_GRAPHICS;
        mkwvk::opts.ultrawide = 0; // Explicit 16:9, independent of any real monitor.
        mkwvk::outputs_sync();
        // Snapshot these fixture values as the starting state, without restart_init's language-file read.
        for (int i = 0; i < mkwvk::kRows; ++i) {
            auto& row = mkwvk::rows[i];
            int slot = row.restart && row.value ? mkwvk::restart_state.add(mkwvk::row_restart_value(row)) : -1;
            mkwvk::restart_slot[i] = slot;
            if (slot >= 0) mkwvk::restart_names[slot] = row.name;
        }
        while (mkwvk::rows[mkwvk::tab_row_to_global(mkwvk::cur_tab, mkwvk::tab_selected[mkwvk::cur_tab])].heading)
            ++mkwvk::tab_selected[mkwvk::cur_tab];
        if (tab == "graphics-screen") {
            bool found = false;
            for (int i = 0; i < mkwvk::tab_row_count(mkwvk::cur_tab); ++i) {
                const auto& row = mkwvk::rows[mkwvk::tab_row_to_global(mkwvk::cur_tab, i)];
                if (!row.heading && std::string(row.name) == "Fullscreen") {
                    mkwvk::tab_selected[mkwvk::cur_tab] = i;
                    // A settled Screen view, rather than an off-screen selection or scroll animation.
                    mkwvk::scroll_at[mkwvk::cur_tab] = mkwvk::scroll_want[mkwvk::cur_tab] = (float)std::max(0, i - 1);
                    mkwvk::ease_step = 1.f;
                    found = true;
                    break;
                }
            }
            if (!found) throw std::runtime_error("Fullscreen row missing from Graphics capture source");
        }
        // Match the renderer's first unscrolled menu view; no real options file is opened.
        float safe = 0;
        float scale = mkwvk::ui::unit(height, mkwvk::opts.menu_size, &safe);
        for (int frame = 0; frame < 3; ++frame) {
            SDL_SetRenderDrawColor(renderer, 16, 18, 21, 255);
            SDL_RenderClear(renderer);
            ImGui::NewFrame();
            mkwvk::ui::Ctx c{ImGui::GetBackgroundDrawList(), fonts, scale, width, height, safe, false};
            mkwvk::draw_menu(c);
            ImGui::Render();
            render(renderer, ImGui::GetDrawData());
        }
        std::vector<unsigned char> rgba(width * height * 4);
        check(SDL_RenderReadPixels(renderer, nullptr, SDL_PIXELFORMAT_RGBA32, rgba.data(), width * 4) == 0, "capture pixels");
        png_image png{};
        png.version = PNG_IMAGE_VERSION; png.width = width; png.height = height; png.format = PNG_FORMAT_RGBA;
        if (!png_image_write_to_file(&png, argv[3], 0, rgba.data(), width * 4, nullptr)) throw std::runtime_error(png.message);
        for (auto* t : ImGui::GetPlatformIO().Textures) {
            if (t->GetTexID() != ImTextureID_Invalid) SDL_DestroyTexture(reinterpret_cast<SDL_Texture*>(t->GetTexID()));
            t->SetTexID(ImTextureID_Invalid); t->SetStatus(ImTextureStatus_Destroyed);
        }
        ImGui::DestroyContext(); SDL_DestroyRenderer(renderer); SDL_FreeSurface(surface); SDL_Quit();
        return 0;
    } catch (const std::exception& e) { fprintf(stderr, "%s\n", e.what()); return 1; }
}
