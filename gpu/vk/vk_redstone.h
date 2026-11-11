// (Mako) AMD FSR Redstone frame generation (the ML frame generation of FidelityFX SDK 2.4, amd_fidelityfx_framegeneration_vk.dll
// 4.x, RX 9000 only), in place of the renderer's own made frame at 2x. Built in vk_fsr4.cpp (it shares AMD's loader with
// FSR 4, and only a build with HOOKSHOT_FSR has AMD's headers); without them every call here does nothing.
//
// Dispatched by hand (the FSR API's FFX_FRAMEGENERATION_FLAG_NO_SWAPCHAIN_CONTEXT_NOTIFY): no AMD swapchain, the renderer
// paces and shows the frames as it does its own (vk_framegen.cpp). Its inputs:
//  - the depth and the motion: the temporal upscaler's chain (vk_temporal.h), so it runs while FSR 4 (or DLSS) upscales;
//  - the HUD-less picture: OoT upscales its scene into the picture, then draws its HUD over that same picture. The picture as
//    it is when the first pass draws into it after the upscale is copied (as the game's own last blit encodes it, sRGB) and
//    given as HUDLessColor, so AMD keeps the HUD where it is instead of moving it with the scene.
// RX_VK_REDSTONE=1 (the launcher's switch) turns it on; without it, never (the renderer's own, or FSR 3.1's with RX_VK_FSR_FG). A frame it cannot make (no inputs this
// present, a failure) goes to the renderer's own interpolation, as before.
#pragma once
#include <cstdint>

#include "vk_internal.h"

namespace mkwvk {

struct Texture;
struct TemporalFrame;

/// The temporal upscaler drew this frame (f: its inputs) into the game's picture out (ow x oh)
void redstone_note_frame(const TemporalFrame& f, Texture* out, uint32_t ow, uint32_t oh);
/// A pass begins (vk_draw.cpp begin_pass, no pass open): the HUD-less copy when its colour target 0 is this frame's picture
void redstone_hudless(VkCommandBuffer cmd, Texture* color0);
/// Whether Redstone is to make the frame at 2x (asked each present: the Frame generation row changes while the game runs)
bool redstone_wanted();
/// The frame between the last presented one and color (w x h, R8G8B8A8_UNORM, GENERAL) into made (the same): 1 when made,
/// 0 when not (the caller makes it). sequence: the presents' count (a gap: a reset), reset: the caller's own
int redstone_frame(VkCommandBuffer cmd, VkImage color, VkImage made, uint32_t w, uint32_t h, uint64_t sequence, bool reset);

}  // namespace mkwvk
