// (hookshot) The compute fallback's mesh epilogue and its generated vertex stage through the real SPIR-V back end, in each record
// layout (RX_VK_MESH_FB_LAYOUT: aos, soa) for the shapes its programs take: the position first or not, per-primitive lines
// or none, triangles, lines and points, a wide record, with a task stage before it or none. Each mesh program writes its stage
// buffer as a game's does: its primitive count, its index bytes and its vertex and primitive lines, all from its workgroup and
// thread, so a device that runs the modules gets records to compare. tests/test_mesh_fallback_layout.py runs it.
//
//   mesh_fallback_layout_ir <folder>: writes <shape>-<layout>-mesh.spv and -vertex.spv for every shape and layout, and
//   <shape>-default-*.spv, RuntimeInfo's layout left unset (aos; the switch's own default, soa, is mesh_mode.h's), and
//   prints a line a module: its words and its stores
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <string>
#include <vector>

#include <spirv/unified1/spirv.hpp>
#include "shader_recompiler/backend/spirv/emit_spirv.h"
#include "shader_recompiler/environment.h"
#include "shader_recompiler/frontend/ir/ir_emitter.h"
#include "shader_recompiler/ir_opt/passes.h"
#include "shader_recompiler/object_pool.h"
#include "shader_recompiler/runtime_info.h"

using namespace Shader;
using Shader::Backend::SPIRV::EmitSPIRV;

namespace {
constexpr u32 kThreads = 32;

struct TestEnvironment final : Environment {
    explicit TestEnvironment(Stage s) { stage = s; }
    u64 ReadInstruction(u32) override { return 0; }
    u32 ReadCbufValue(u32, u32) override { return 0; }
    TextureType ReadTextureType(u32) override { return TextureType::Color2D; }
    TexturePixelFormat ReadTexturePixelFormat(u32) override { return TexturePixelFormat::R8_UNORM; }
    bool IsTexturePixelFormatInteger(u32) override { return false; }
    u32 ReadViewportTransformState() override { return 0; }
    u32 TextureBoundBuffer() const override { return 0; }
    u32 LocalMemorySize() const override { return 0; }
    u32 SharedMemorySize() const override { return 0; }
    std::array<u32, 3> WorkgroupSize() const override { return {kThreads, 1, 1}; }
    bool HasHLEMacroState() const override { return false; }
    std::optional<ReplaceConstant> GetReplaceConstBuffer(u32, u32) override { return std::nullopt; }
    void Dump(u64, u64) override {}
};

u32 Position(u32 c) { return u32(IR::Attribute::PositionX) + c; }
u32 Generic(u32 index, u32 c) { return u32(IR::Attribute::Generic0X) + index * 4 + c; }

struct Shape {
    const char* name;
    u32 topology;   // (GL's numbers: 0 points, 1 lines, 4 triangles)
    u32 max_vertices, max_primitives;
    std::vector<u32> vertex_lines, primitive_lines;
    bool task;
};

std::vector<Shape> Shapes() {
    std::vector<Shape> shapes;
    // (the position first, two generics after it: no per-primitive lines, 11 words a record)
    shapes.push_back({"tri-pos-first", 4, 64, 126,
                      {Position(0), Position(1), Position(2), Position(3), Generic(0, 0), Generic(0, 1), Generic(0, 2),
                       Generic(0, 3), Generic(1, 0), Generic(1, 1)},
                      {}, false});
    // (a generic before the position, and a per-primitive generic: per corner in every layout)
    shapes.push_back({"tri-pos-later-prim", 4, 64, 126,
                      {Generic(0, 0), Generic(0, 1), Position(0), Position(1), Position(2), Position(3), Generic(1, 0),
                       Generic(1, 1), Generic(1, 2), Generic(1, 3)},
                      {Generic(2, 0)}, false});
    // (a wide record, 27 words, as the hot programs' 22-27: the position, five generics, a pair; vertices fewer than the
    // threads' indices reach, so the epilogue holds them to the count)
    {
        Shape wide{"tri-wide", 4, 32, 62, {Position(0), Position(1), Position(2), Position(3)}, {}, true};
        for (u32 g = 0; g < 5; g++)
            for (u32 c = 0; c < 4; c++) wide.vertex_lines.push_back(Generic(g, c));
        wide.vertex_lines.push_back(Generic(5, 0));
        wide.vertex_lines.push_back(Generic(5, 1));
        shapes.push_back(wide);
    }
    shapes.push_back({"tri-task", 4, 64, 126, {Position(0), Position(1), Position(2), Position(3), Generic(0, 0)}, {}, true});
    shapes.push_back({"lines", 1, 32, 32, {Position(0), Position(1), Position(2), Position(3), Generic(0, 0)}, {}, false});
    shapes.push_back({"points", 0, 32, 32, {Position(0), Position(1), Position(2), Position(3), Generic(0, 0)}, {}, false});
    return shapes;
}

/// The stage buffer as a game's mesh program writes it, from its workgroup w and thread t only, so a device's run of each
/// layout can be compared: primitive count (w * 37 + 5) & 127 held to max primitives (0 for some workgroups); index bytes
/// of corner c of primitive p a hash's top byte masked to 7 (odd workgroups: few vertices used, repeats, degenerate triangles) or 63
/// (past 32 vertices for a 32-vertex program: the epilogue holds those); the lines small exact floats
struct Body {
    IR::IREmitter& ir;
    IR::U32 w, t;
    IR::U32 Hash(const IR::U32& a, u32 salt) {
        IR::U32 h{ir.BitwiseXor(ir.IMul(w, ir.Imm32(0x9E3779B1u)), ir.IMul(a, ir.Imm32(0x85EBCA77u)))};
        h = ir.BitwiseXor(h, ir.Imm32(salt * 0xC2B2AE3Du));
        h = ir.BitwiseXor(h, ir.ShiftRightLogical(h, ir.Imm32(15u)));
        return ir.IMul(h, ir.Imm32(0x2C1B3C6Du));
    }
    IR::U32 Small(const IR::U32& h, f32 scale, f32 offset) {   // ((h >> 8) & 255) * scale + offset: exact in f32
        const IR::F32 f{ir.ConvertUToF(32, 32, ir.BitwiseAnd(ir.ShiftRightLogical(h, ir.Imm32(8u)), ir.Imm32(255u)))};
        return ir.BitCast<IR::U32>(IR::F32{ir.FPAdd(IR::F32{ir.FPMul(f, ir.Imm32(scale))}, ir.Imm32(offset))});
    }
    void Write(const Shape& s) {
        const u32 corners{s.topology == 0 ? 1U : s.topology == 1 ? 2U : 3U};
        const u32 vertex_lines{static_cast<u32>(s.vertex_lines.size())};
        const u32 primitive_lines{static_cast<u32>(s.primitive_lines.size())};
        const u32 primitive_base{(s.max_vertices + 31) / 32 * vertex_lines * 32};
        // (the count: the map's word at byte 3)
        ir.IsbeWriteMapU32(ir.Imm32(3u), ir.UMin(ir.BitwiseAnd(ir.IAdd(ir.IMul(w, ir.Imm32(37u)), ir.Imm32(5u)), ir.Imm32(127u)),
                                                 ir.Imm32(s.max_primitives)));
        const IR::U32 mask{ir.ShiftRightLogical(ir.Imm32(63u), ir.IMul(ir.BitwiseAnd(w, ir.Imm32(1u)), ir.Imm32(3u)))};
        for (u32 first = 0; first < (s.max_primitives + 31) / 32 * 32; first += kThreads) {
            const IR::U32 p{ir.IAdd(t, ir.Imm32(first))};
            for (u32 c = 0; c < corners; c++) {
                const IR::U32 byte{ir.IAdd(ir.IMul(p, ir.Imm32(corners)), ir.Imm32(4u + c))};
                ir.IsbeWriteMapU8(byte, ir.BitwiseAnd(ir.ShiftRightLogical(Hash(p, 100 + c), ir.Imm32(24u)), mask));
            }
            for (u32 l = 0; l < primitive_lines; l++) {
                const IR::U32 word{ir.IAdd(ir.IAdd(ir.IMul(ir.ShiftRightLogical(p, ir.Imm32(5u)), ir.Imm32(primitive_lines * 32)),
                                                   ir.BitwiseAnd(p, ir.Imm32(31u))),
                                           ir.Imm32(primitive_base + l * 32))};
                ir.IsbeWriteAttribute(ir.IMul(word, ir.Imm32(4u)), Small(Hash(p, 200 + l), 1.0f / 64, 0.0f));
            }
        }
        for (u32 first = 0; first < s.max_vertices; first += kThreads) {
            const IR::U32 v{ir.IAdd(t, ir.Imm32(first))};
            for (u32 l = 0; l < vertex_lines; l++) {
                const u32 a{s.vertex_lines[l]};
                IR::U32 value;
                if (a == Position(0) || a == Position(1)) value = Small(Hash(v, 300 + l), 1.0f / 128, -1.0f);
                else if (a == Position(2)) value = ir.Imm32(0x3F000000u);   // (0.5)
                else if (a == Position(3)) value = ir.Imm32(0x3F800000u);   // (1.0)
                else value = Small(Hash(v, 300 + l), 1.0f / 256, 0.0f);
                const IR::U32 word{ir.IAdd(ir.IAdd(ir.IMul(ir.ShiftRightLogical(v, ir.Imm32(5u)), ir.Imm32(vertex_lines * 32)),
                                                   ir.BitwiseAnd(v, ir.Imm32(31u))),
                                           ir.Imm32(l * 32))};
                ir.IsbeWriteAttribute(ir.IMul(word, ir.Imm32(4u)), value);
            }
        }
    }
};

/// layout: -1 leaves RuntimeInfo's unset
std::vector<u32> Emit(const Shape& s, int layout, bool vertex_stage) {
    ObjectPool<IR::Inst> inst_pool;
    IR::Block block{inst_pool};
    IR::Program program;
    program.stage = Stage::Mesh;
    program.workgroup_size = {kThreads, 1, 1};
    program.output_vertices = s.max_vertices;
    program.mesh.max_vertices = s.max_vertices;
    program.mesh.max_primitives = s.max_primitives;
    program.mesh.topology = s.topology;
    program.mesh.payload_words = 4;
    for (u32 a : s.vertex_lines) program.mesh.vertex_lines.push_back(a);
    for (u32 a : s.primitive_lines) program.mesh.primitive_lines.push_back(a);
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
    ir.Prologue();
    Body body{ir, ir.WorkgroupIdX(), ir.LocalInvocationIdX()};
    body.Write(s);
    ir.Epilogue();
    TestEnvironment env{Stage::Mesh};
    Optimization::CollectShaderInfoPass(env, program);
    program.info.is_mesh = true;
    for (u32 a : program.mesh.vertex_lines) program.info.stores.Set(IR::Attribute(a));
    for (u32 a : program.mesh.primitive_lines) program.info.stores.Set(IR::Attribute(a));
    Profile profile{};
    profile.supported_spirv = 0x00010600;
    profile.support_int64 = true;
    RuntimeInfo rt{};
    rt.mesh_fallback = true;
    rt.mesh_fallback_capacity = Backend::SPIRV::MESH_FALLBACK_CAPACITY;
    rt.mesh_fallback_task = s.task;
    rt.mesh_fallback_task_threads = s.task ? kThreads : 0;
    if (layout >= 0) rt.mesh_fallback_layout = static_cast<u32>(layout);
    Backend::Bindings bindings{};
    if (!vertex_stage) return EmitSPIRV(profile, rt, program, bindings);
    RuntimeInfo vrt{};
    vrt.mesh_fallback = true;
    vrt.mesh_fallback_vertex = true;
    vrt.mesh_fallback_capacity = Backend::SPIRV::MESH_FALLBACK_CAPACITY;
    if (layout >= 0) vrt.mesh_fallback_layout = static_cast<u32>(layout);
    for (u32 a : s.primitive_lines)
        if (IR::IsGeneric(IR::Attribute(a))) vrt.per_primitive_generics.set(IR::GenericAttributeIndex(IR::Attribute(a)));
    Info stores_only{};
    stores_only.stores = program.info.stores;
    program.info = stores_only;
    program.stage = Stage::VertexB;
    return EmitSPIRV(profile, vrt, program, bindings);
}
} // namespace

int main(int argc, char** argv) {
    if (argc < 2) {
        std::fprintf(stderr, "usage: mesh_fallback_layout_ir <folder>\n");
        return 2;
    }
    const std::pair<const char*, int> layouts[] = {{"default", -1}, {"aos", 0}, {"soa", 1}};
    for (const Shape& s : Shapes()) {
        for (const auto& [layout_name, layout] : layouts) {
            for (int v = 0; v < 2; v++) {
                const std::vector<u32> code = Emit(s, layout, v != 0);
                if (code.size() < 5 || code[0] != spv::MagicNumber) {
                    std::fprintf(stderr, "FAIL: %s %s: no module\n", s.name, layout_name);
                    return 1;
                }
                size_t stores = 0;
                for (size_t at = 5; at < code.size();) {
                    const u32 n = code[at] >> 16;
                    if (!n) return 1;
                    stores += (code[at] & 0xffff) == u32(spv::Op::OpStore);
                    at += n;
                }
                const std::string path = std::string(argv[1]) + "/" + s.name + "-" + layout_name + (v ? "-vertex" : "-mesh") + ".spv";
                std::ofstream(path, std::ios::binary).write(reinterpret_cast<const char*>(code.data()), code.size() * 4);
                std::printf("%s-%s-%s: %zu words, %zu stores\n", s.name, layout_name, v ? "vertex" : "mesh", code.size(), stores);
            }
        }
    }
    return 0;
}
