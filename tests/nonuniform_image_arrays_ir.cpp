// SPDX-License-Identifier: GPL-3.0-or-later
// The renderer's profile (make_profile, gpu/vk/vk_shader.cpp) on GPUs with and without nonuniform indexing of storage image,
// uniform texel buffer and storage texel buffer arrays, and synthetic compute programs with descriptor arrays of each kind
// through the real texture pass and SPIR-V back end: no game or GPU (tests/test_nonuniform_image_arrays.py cuts make_profile,
// storage_binding_align and translator_stamp's nonuniform word out of the tree into nonuniform_profile.inc, builds this and
// validates its modules).
//
// A handle read from a constant buffer at a dynamic offset (base + element * 8) is a descriptor array: the texture pass sizes it
// by the words left after the base (DynamicDescriptorCount) and indexes it with the element, here each invocation's own. The
// same programs with the handle at a constant offset are single descriptors.
//
//     nonuniform_image_arrays_ir <output folder>
// writes <device>.<program>.spv for each GPU and program and prints one line each:
//     <device>.<program> <words>             (a module)
//     <device>.<program> refused: <what>     (what the translation threw)
//     stamp <device> <words>                 (what translator_stamp's nonuniform word adds, in hex, comma separated; - for
//                                             nothing; "missing" when the tree's translator_stamp has no such word)
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <exception>
#include <filesystem>
#include <fstream>
#include <string>
#include <utility>
#include <vector>

#include "shader_recompiler/backend/spirv/emit_spirv.h"
#include "shader_recompiler/backend/spirv/mma_layout.h"
#include "shader_recompiler/environment.h"
#include "shader_recompiler/frontend/ir/ir_emitter.h"
#include "shader_recompiler/host_translate_info.h"
#include "shader_recompiler/ir_opt/passes.h"
#include "shader_recompiler/object_pool.h"
#include "shader_recompiler/profile.h"

// What make_profile and storage_binding_align read of the renderer (vk_internal.h's dev): a GPU with 32 lanes, no float add of
// its own, NVIDIA's gather, 16-byte storage buffer offsets, f16 shaders; the nonuniform indexing features set per device below
constexpr uint32_t VK_SHADER_STAGE_ALL = 0x7fffffff;
constexpr uint32_t VK_DRIVER_ID_AMD_PROPRIETARY = 1;
struct {
    uint32_t subgroup_max = 32, driver_id = 0;
    bool float_atomic_add = false;
    struct {
        bool shaderFloat16 = true;
        bool shaderStorageImageArrayNonUniformIndexing = false, shaderUniformTexelBufferArrayNonUniformIndexing = false,
             shaderStorageTexelBufferArrayNonUniformIndexing = false;
    } vk12;
    struct { struct { uint64_t minStorageBufferOffsetAlignment = 16; } limits; } props;
    struct { bool gather_offset = false; } fixes;
} dev;

#include "nonuniform_profile.inc"   // (storage_binding_align, make_profile, profile(), stamp_section and STAMP_SECTION)

using namespace Shader;

struct TestEnvironment final : Environment {
    TestEnvironment() { stage = Stage::Compute; }
    u64 ReadInstruction(u32) override { return 0; }
    u32 ReadCbufValue(u32, u32) override { return 1; }
    TextureType ReadTextureType(u32) override { return TextureType::Color2D; }
    TexturePixelFormat ReadTexturePixelFormat(u32) override { return {}; }
    bool IsTexturePixelFormatInteger(u32) override { return false; }
    u32 ReadViewportTransformState() override { return 1; }
    u32 TextureBoundBuffer() const override { return 0; }
    u32 LocalMemorySize() const override { return 0; }
    u32 SharedMemorySize() const override { return 0; }
    std::array<u32, 3> WorkgroupSize() const override { return {64, 1, 1}; }
    bool HasHLEMacroState() const override { return false; }
    std::optional<ReplaceConstant> GetReplaceConstBuffer(u32, u32) override { return std::nullopt; }
    void Dump(u64, u64) override {}
};

enum class Kind { TextureBuffer, ImageBuffer, Texture, Image, ImageBufferAtomic, ImageAtomic };

struct Array {
    Kind kind;
    u32 count;   // (1: a handle at a constant offset, a single descriptor)
};

// The GPUs: which of the three kinds of array they index nonuniformly (Vulkan 1.2's features of those names)
struct Device {
    const char* name;
    bool storage_image, uniform_texel_buffer, storage_texel_buffer;
};

// The texture pass's limit with no device limits (HostTranslateInfo::DEFAULT_DESCRIPTOR_LIMIT) reads 16 bytes a descriptor:
// a base 8 * count bytes before that end leaves room for count descriptors of 8 bytes
constexpr u32 kCbufEnd = 16 * HostTranslateInfo::DEFAULT_DESCRIPTOR_LIMIT;

IR::U32 Handle(IR::IREmitter& ir, u32 cbuf, u32 count, const IR::U32& element) {
    if (count == 1) {
        return ir.GetCbuf(ir.Imm32(cbuf), ir.Imm32(0x40));
    }
    const IR::U32 offset{ir.IAdd(ir.Imm32(kCbufEnd - 8 * count), IR::U32{ir.ShiftLeftLogical(element, ir.Imm32(3))})};
    return ir.GetCbuf(ir.Imm32(cbuf), offset);
}

IR::Value AsU32x4(IR::IREmitter& ir, const IR::Value& color) {
    std::array<IR::U32, 4> parts;
    for (size_t i = 0; i < parts.size(); ++i) {
        parts[i] = ir.BitCast<IR::U32, IR::F32>(IR::F32{ir.CompositeExtract(color, i)});
    }
    return ir.CompositeConstruct(parts[0], parts[1], parts[2], parts[3]);
}

std::vector<u32> Emit(const std::vector<Array>& arrays, const Profile& device_profile) {
    ObjectPool<IR::Inst> inst_pool;
    IR::Block block{inst_pool};
    IR::Program program;
    program.stage = Stage::Compute;
    program.workgroup_size = {64, 1, 1};
    program.blocks.push_back(&block);
    program.post_order_blocks.push_back(&block);
    IR::AbstractSyntaxNode node{};
    node.type = IR::AbstractSyntaxNode::Type::Block;
    node.data.block = &block;
    program.syntax_list.push_back(node);
    IR::AbstractSyntaxNode ret{};
    ret.type = IR::AbstractSyntaxNode::Type::Return;
    program.syntax_list.push_back(ret);

    IR::IREmitter ir{block};
    const IR::U32 lane{ir.LocalInvocationIdX()};   // (each invocation its own element: nonuniform)
    const IR::U32 next{ir.IAdd(lane, ir.Imm32(1))};
    IR::TextureInstInfo out{};   // (where sampled reads are stored: a single image buffer bound at c0[0x100])
    out.type.Assign(TextureType::Buffer);
    out.image_format.Assign(ImageFormat::R32_UINT);
    u32 cbuf{2};
    for (const Array& array : arrays) {
        const IR::U32 handle{Handle(ir, cbuf++, array.count, lane)};
        IR::TextureInstInfo info{};
        info.image_format.Assign(ImageFormat::R32_UINT);
        switch (array.kind) {
        case Kind::ImageBuffer: {
            info.type.Assign(TextureType::Buffer);
            const IR::Value texel{ir.ImageRead(handle, lane, info)};
            ir.ImageWrite(handle, next, texel, info);
            break;
        }
        case Kind::Image: {
            info.type.Assign(TextureType::Color2D);
            const IR::Value texel{ir.ImageRead(handle, ir.CompositeConstruct(lane, ir.Imm32(0)), info)};
            ir.ImageWrite(handle, ir.CompositeConstruct(next, ir.Imm32(1)), texel, info);
            break;
        }
        case Kind::TextureBuffer: {
            info.type.Assign(TextureType::Buffer);
            const IR::Value texel{ir.ImageFetch(handle, lane, {}, {}, {}, info)};
            ir.ImageWrite(ir.Imm32(0x100), lane, AsU32x4(ir, texel), out);
            break;
        }
        case Kind::Texture: {
            info.type.Assign(TextureType::Color2D);
            const IR::Value texel{
                ir.ImageFetch(handle, ir.CompositeConstruct(lane, ir.Imm32(0)), {}, ir.Imm32(0), {}, info)};
            ir.ImageWrite(ir.Imm32(0x100), next, AsU32x4(ir, texel), out);
            break;
        }
        case Kind::ImageBufferAtomic: {
            info.type.Assign(TextureType::Buffer);
            const IR::U32 old{ir.ImageAtomicIAdd(handle, lane, ir.Imm32(1), info)};
            ir.ImageWrite(ir.Imm32(0x100), lane, ir.CompositeConstruct(old, old, old, old), out);
            break;
        }
        case Kind::ImageAtomic: {
            info.type.Assign(TextureType::Color2D);
            const IR::U32 old{ir.ImageAtomicIAdd(handle, ir.CompositeConstruct(lane, ir.Imm32(0)), ir.Imm32(1), info)};
            ir.ImageWrite(ir.Imm32(0x100), lane, ir.CompositeConstruct(old, old, old, old), out);
            break;
        }
        }
    }
    ir.Epilogue();

    TestEnvironment env;
    HostTranslateInfo host_info{};
    host_info.support_snorm_render_buffer = true;
    host_info.ApplyDescriptorLimitPolicy();   // (as TranslateProgram: no device limits, the defaults)
    Optimization::TexturePass(env, program, host_info);
    Optimization::DeadCodeEliminationPass(program);
    Optimization::CollectShaderInfoPass(env, program);
    return Backend::SPIRV::EmitSPIRV(device_profile, program);
}

int main(int argc, char** argv) {
    if (argc != 2) {
        std::fprintf(stderr, "usage: nonuniform_image_arrays_ir <output folder>\n");
        return 2;
    }
    const std::filesystem::path folder{argv[1]};
    std::filesystem::create_directories(folder);
    const std::array<Device, 5> devices{{
        {"none", false, false, false},
        {"storage-image", true, false, false},
        {"uniform-texel-buffer", false, true, false},
        {"storage-texel-buffer", false, false, true},
        {"all", true, true, true},
    }};
    const std::array<std::pair<const char*, std::vector<Array>>, 13> programs{{
        {"imgbuf-1", {{Kind::ImageBuffer, 1}}},
        {"img-1", {{Kind::Image, 1}}},
        {"texbuf-1", {{Kind::TextureBuffer, 1}}},
        {"imgbuf-atomic-1", {{Kind::ImageBufferAtomic, 1}}},
        {"img-atomic-1", {{Kind::ImageAtomic, 1}}},
        {"mixed-1", {{Kind::TextureBuffer, 1}, {Kind::ImageBuffer, 1}, {Kind::Texture, 1}, {Kind::Image, 1}}},
        {"tex-2", {{Kind::Texture, 2}}},
        {"imgbuf-2", {{Kind::ImageBuffer, 2}}},
        {"img-3", {{Kind::Image, 3}}},
        {"texbuf-2", {{Kind::TextureBuffer, 2}}},
        {"imgbuf-atomic-2", {{Kind::ImageBufferAtomic, 2}}},
        {"img-atomic-3", {{Kind::ImageAtomic, 3}}},
        {"mixed", {{Kind::TextureBuffer, 2}, {Kind::ImageBuffer, 2}, {Kind::Texture, 2}, {Kind::Image, 3}}},
    }};
    Backend::SPIRV::fetch_bounds = Backend::SPIRV::fetch_bounds_buffers = false;   // (NVIDIA's: vk_vendor.h)
    for (const Device& device : devices) {
        dev.vk12.shaderStorageImageArrayNonUniformIndexing = device.storage_image;
        dev.vk12.shaderUniformTexelBufferArrayNonUniformIndexing = device.uniform_texel_buffer;
        dev.vk12.shaderStorageTexelBufferArrayNonUniformIndexing = device.storage_texel_buffer;
        const Profile device_profile{make_profile()};
        current_profile = &device_profile;
        std::string words;
        stamp_section([&words](const void* data, size_t bytes) {
            for (size_t i = 0; i < bytes / 4; ++i) {
                char hex[16];
                std::snprintf(hex, sizeof hex, "%s%08x", words.empty() ? "" : ",", static_cast<const uint32_t*>(data)[i]);
                words += hex;
            }
        });
        std::printf("stamp %s %s\n", device.name, STAMP_SECTION ? (words.empty() ? "-" : words.c_str()) : "missing");
        for (const auto& [name, arrays] : programs) {
            const std::string id{std::string{device.name} + "." + name};
            std::vector<u32> module;
            try {
                module = Emit(arrays, device_profile);
            } catch (const std::exception& e) {
                std::printf("%s refused: %s\n", id.c_str(), e.what());
                continue;
            }
            std::ofstream file(folder / (id + ".spv"), std::ios::binary);
            file.write(reinterpret_cast<const char*>(module.data()), static_cast<std::streamsize>(module.size() * 4));
            if (!file) {
                std::fprintf(stderr, "%s: not written\n", id.c_str());
                return 3;
            }
            std::printf("%s %zu\n", id.c_str(), module.size());
        }
    }
    return 0;
}
