// SPDX-FileCopyrightText: Copyright 2026 Eden Emulator Project
// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <optional>
#include <span>
#include <vector>
#include "common/common_types.h"

namespace Shader::Ampere {
constexpr u64 NativeAddressMapMagic = 0x50414d4e4544454eULL;
// (hookshot) The most native instructions a program may have, for the capture, the lowering and this map: as many as fit
// in the largest code area the renderer reads (a control section whose area ends past 16 MiB is refused: control_end,
// gpu/vk/vk_shader.cpp), 16 bytes each. The GPU has no instruction count of its own: Maxwell and Ampere address a program
// by a 32-bit offset in its program region, and an Ampere BRA's offset has 50 bits. (65,536, 1 MiB, refused compute
// program 79116b290d46542f, 0x104680 bytes of code, on every platform)
constexpr u32 MaximumNativeInstructions = (16u << 20) / 16;
inline bool HasNativeAddressMap(std::span<const u64> code) {
    return code.size() >= 2 && code.back() == NativeAddressMapMagic;
}
inline void AppendNativeAddressMap(std::vector<u64>& code, std::span<const u32> offsets) {
    if (offsets.empty()) return;
    for (u32 index : offsets) code.push_back(0x50U + index * 8 + ((index + 1) / 3) * 8);
    code.push_back(offsets.size());
    code.push_back(NativeAddressMapMagic);
}
inline std::optional<u32> NativeProgramAddress(std::span<const u64> code, u32 address) {
    if (!HasNativeAddressMap(code) || address % 16) return {};
    const u64 count = code[code.size() - 2];
    if (!count || count > MaximumNativeInstructions || count + 2 > code.size() || address / 16 >= count) return {};
    const size_t start = code.size() - static_cast<size_t>(count) - 2;
    const u64 target = code[start + address / 16];
    if (target < 0x50 || target >= start * 8 || target % 8 || target % 32 == 0) return {};
    return static_cast<u32>(target);
}
} // namespace Shader::Ampere
