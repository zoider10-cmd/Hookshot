// (hookshot) A model of what the compute fallback's mesh workgroups write in each record layout (RX_VK_MESH_FB_LAYOUT;
// emit_spirv_mesh.cpp MeshFallbackEpilogue, its layouts and the generated vertex stage's reads) and of what the draw then reads,
// with the layout's words from emit_spirv.h. For random meshlets (up to 256 vertices and 256 primitives, counts past the most,
// index bytes past the vertices, repeated corners, workgroups with nothing) the triangles, lines or points each layout's draw
// reconstructs must be the meshlets' own primitives, in order, each corner's vertex and per-primitive words as a record a
// corner gives them: the same provoking vertex and winding. Past the area, each layout draws the first workgroups that fit and
// never a word not written. tests/test_mesh_fallback_layout.py runs it.
//   mesh_fallback_layout_model [seed]
#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <random>
#include <string>
#include <vector>

#include "mesh_mode.h"
#include "shader_recompiler/backend/spirv/emit_spirv.h"

using namespace Shader;
using namespace Shader::Backend::SPIRV;

namespace {
constexpr u32 kUnwritten = 0xDEADBEEFu;

struct Meshlet {
    u32 count;                     // (the primitive count it wrote, maybe past the most)
    std::vector<u32> bytes;        // (index bytes, corners a primitive, maybe past the vertices)
    std::vector<u32> vertex;       // (vertex v's line l at v * vertex_lines + l)
    std::vector<u32> primitive;    // (primitive p's line l at p * primitive_lines + l)
};

struct Program {
    MeshInfo mesh;
    u32 vertex_lines() const { return static_cast<u32>(mesh.vertex_lines.size()); }
    u32 primitive_lines() const { return static_cast<u32>(mesh.primitive_lines.size()); }
    u32 words() const { return 1 + vertex_lines() + primitive_lines(); }   // (FallbackRecordWords)
};

using Corner = std::vector<u32>;   // (a corner's words as the vertex stage outputs them: vertex lines, then primitive lines)
using Primitive = std::vector<Corner>;

u32 Held(u32 index, u32 count) { return std::min(index, count - 1); }   // (Clamped)

/// What the game drew: each workgroup's primitives below its count (held to the most), in workgroup order
std::vector<std::vector<Primitive>> Expected(const Program& p, const std::vector<Meshlet>& ms) {
    std::vector<std::vector<Primitive>> out;
    const u32 corners{p.mesh.Corners()};
    for (const Meshlet& m : ms) {
        std::vector<Primitive> prims;
        for (u32 q = 0; q < std::min(m.count, p.mesh.max_primitives); q++) {
            Primitive prim;
            for (u32 c = 0; c < corners; c++) {
                const u32 v{Held(m.bytes[q * corners + c], p.mesh.max_vertices)};
                Corner corner(m.vertex.begin() + v * p.vertex_lines(), m.vertex.begin() + (v + 1) * p.vertex_lines());
                corner.insert(corner.end(), m.primitive.begin() + q * p.primitive_lines(),
                              m.primitive.begin() + (q + 1) * p.primitive_lines());
                prim.push_back(corner);
            }
            prims.push_back(prim);
        }
        out.push_back(prims);
    }
    return out;
}

/// The records buffer: its header at 0 and the area past it unwritten. One buffer, as a recording thread's: each case puts back
/// only the words it wrote
struct Area {
    struct Words {
        std::vector<u32>& w;
        std::vector<u32>& touched;
        u32& operator[](size_t at) {
            touched.push_back(static_cast<u32>(at));
            return w[at];
        }
        u32 operator[](size_t at) const { return w[at]; }
        size_t size() const { return w.size(); }
    };
    static std::vector<u32>& Storage() {
        static std::vector<u32> storage(MESH_FALLBACK_HEADER_WORDS + MESH_FALLBACK_RECORD_WORDS, kUnwritten);
        return storage;
    }
    std::vector<u32> touched;
    Words w{Storage(), touched};
    explicit Area(u32 header) {
        for (u32 i = 0; i < header; i++) w[i] = 0;
    }
    ~Area() {
        for (u32 at : touched) Storage()[at] = kUnwritten;
    }
};

/// The records layouts, Aos and Soa: a workgroup takes a record a corner
void WriteRecords(const Program& p, u32 layout, const std::vector<Meshlet>& ms, Area& a) {
    const u32 corners{p.mesh.Corners()}, words{p.words()}, fit{MeshFallbackFit(words)};
    for (const Meshlet& m : ms) {
        const u32 count{std::min(m.count, p.mesh.max_primitives)};
        const u32 taken{count * corners};
        if (!taken) continue;
        const u32 base{a.w[MESH_FALLBACK_ALLOC_WORD]};
        a.w[MESH_FALLBACK_ALLOC_WORD] += taken;
        if (!(base <= fit && taken <= fit - base)) continue;
        a.w[MESH_FALLBACK_DRAW_WORD] += taken;
        for (u32 k = 0; k < taken; k++) {
            const u32 q{k / corners}, v{Held(m.bytes[k], p.mesh.max_vertices)}, record{base + k};
            const auto at = [&](u32 line) {
                return layout == static_cast<u32>(MeshFallbackLayout::Aos) ? MESH_FALLBACK_HEADER_WORDS + record * words + line
                                                                           : MESH_FALLBACK_HEADER_WORDS + line * fit + record;
            };
            a.w[at(0)] = 1;
            for (u32 l = 0; l < p.vertex_lines(); l++) a.w[at(1 + l)] = m.vertex[v * p.vertex_lines() + l];
            for (u32 l = 0; l < p.primitive_lines(); l++)
                a.w[at(1 + p.vertex_lines() + l)] = m.primitive[q * p.primitive_lines() + l];
        }
    }
}

/// What the draw reads: the vertex stage's outputs for each vertex the draw reaches, a primitive a corners' run. bad: a word
/// read that was not written this draw, a record not marked valid
std::vector<Primitive> Drawn(const Program& p, u32 layout, const Area& a, bool& bad) {
    const u32 corners{p.mesh.Corners()}, words{p.words()}, fit{MeshFallbackFit(words)};
    std::vector<Primitive> out;
    const auto word = [&](size_t at) {
        if (at >= a.w.size() || a.w[at] == kUnwritten) bad = true;
        return at < a.w.size() ? a.w[at] : 0U;
    };
    const u32 drawn{a.w[MESH_FALLBACK_DRAW_WORD]};
    if (drawn > fit) bad = true;
    for (u32 first = 0; first < drawn; first += corners) {
        Primitive prim;
        for (u32 c = 0; c < corners; c++) {
            const u32 r{first + c};
            const auto at = [&](u32 line) {
                return layout == static_cast<u32>(MeshFallbackLayout::Aos) ? MESH_FALLBACK_HEADER_WORDS + (size_t)r * words + line
                                                                           : MESH_FALLBACK_HEADER_WORDS + (size_t)line * fit + r;
            };
            if (word(at(0)) != 1) bad = true;
            Corner corner;
            for (u32 l = 1; l < words; l++) corner.push_back(word(at(l)));
            prim.push_back(corner);
        }
        out.push_back(prim);
    }
    return out;
}

/// The workgroups' primitives that fit, in order, flattened: the first `fitting` workgroups'
std::vector<Primitive> Flat(const std::vector<std::vector<Primitive>>& e, size_t fitting) {
    std::vector<Primitive> out;
    for (size_t i = 0; i < fitting && i < e.size(); i++) out.insert(out.end(), e[i].begin(), e[i].end());
    return out;
}

/// How many workgroups, in order, fit when each takes `need(i)` from one allocator: taking only grows, so once one does not fit
/// none after it with anything to take does
template <typename Need>
size_t Fitting(size_t n, u32 fit, Need need) {
    u64 taken{0};
    for (size_t i = 0; i < n; i++) {
        const u32 k{need(i)};
        if (!k) continue;
        if (taken + k > fit) return i;
        taken += k;
    }
    return n;
}

int fails = 0;
void Check(bool ok, const std::string& what) {
    if (!ok) {
        std::printf("FAIL: %s\n", what.c_str());
        fails++;
    }
}

Program MakeProgram(std::mt19937& rng, u32 topology, u32 vertex_lines, u32 primitive_lines) {
    Program p;
    p.mesh.topology = topology;
    p.mesh.max_vertices = 1 + rng() % 256;
    p.mesh.max_primitives = 1 + rng() % 256;
    for (u32 l = 0; l < vertex_lines; l++) p.mesh.vertex_lines.push_back(u32(IR::Attribute::PositionX) + l);
    for (u32 l = 0; l < primitive_lines; l++) p.mesh.primitive_lines.push_back(u32(IR::Attribute::Generic0X) + l);
    return p;
}

std::vector<Meshlet> MakeMeshlets(std::mt19937& rng, const Program& p, size_t n, bool full) {
    std::vector<Meshlet> ms(n);
    const u32 corners{p.mesh.Corners()};
    for (Meshlet& m : ms) {
        const u32 mode{static_cast<u32>(rng() % 8)};
        m.count = full ? p.mesh.max_primitives : mode == 0 ? 0 : mode == 1 ? p.mesh.max_primitives + rng() % 9 : rng() % (p.mesh.max_primitives + 1);
        // (indices among few vertices (repeats, degenerate primitives), among all, or past them)
        const u32 span{mode == 2 ? 3U : mode == 3 ? 256U : p.mesh.max_vertices};
        m.bytes.resize(p.mesh.max_primitives * corners);
        for (u32& b : m.bytes) b = static_cast<u32>(rng() % span) & 0xFF;
        m.vertex.resize(p.mesh.max_vertices * p.vertex_lines());
        for (u32& w : m.vertex) w = static_cast<u32>(rng()) & 0x7FFFFFFF;   // (never the unwritten pattern)
        m.primitive.resize(p.mesh.max_primitives * p.primitive_lines());
        for (u32& w : m.primitive) w = static_cast<u32>(rng()) & 0x7FFFFFFF;
    }
    return ms;
}

void RunCase(const char* name, const Program& p, const std::vector<Meshlet>& ms) {
    const auto expected{Expected(p, ms)};
    const u32 corners{p.mesh.Corners()};
    const u32 fit{MeshFallbackFit(p.words())};
    const size_t fit_records{Fitting(ms.size(), fit, [&](size_t i) { return std::min(ms[i].count, p.mesh.max_primitives) * corners; })};
    std::vector<Primitive> records_drawn;
    for (u32 layout : {0U, 1U}) {
        Area a{MESH_FALLBACK_HEADER_WORDS};
        WriteRecords(p, layout, ms, a);
        bool bad{false};
        const auto drawn{Drawn(p, layout, a, bad)};
        const std::string what{std::string(name) + " layout " + std::to_string(layout)};
        Check(!bad, what + ": the draw reads a word not written or a record not valid");
        Check(drawn == Flat(expected, fit_records), what + ": not the workgroups' primitives in order, as a record a corner");
        if (layout == 0) records_drawn = drawn;
        else Check(drawn == records_drawn, what + ": not what the record-after-record layout draws");
    }
}
} // namespace

int main(int argc, char** argv) {
    std::mt19937 rng{argc > 1 ? static_cast<u32>(std::atoi(argv[1])) : 640U};
    int cases = 0;
    // (the switch: aos the records as they were before soa; unset, empty or soa line after line, the default; any case;
    // anything else the default, and says so)
    Check(mesh_rule::fb_layout(nullptr).mode == 1 && mesh_rule::fb_layout("").mode == 1, "RX_VK_MESH_FB_LAYOUT unset is not soa");
    Check(mesh_rule::fb_layout("aos").mode == 0 && mesh_rule::fb_layout("AoS").mode == 0, "aos");
    Check(mesh_rule::fb_layout("soa").mode == 1 && mesh_rule::fb_layout("SOA").mode == 1, "soa");
    for (const char* other : {"1", "2", "lines", "index", "soa ", "indexed"})
        Check(mesh_rule::fb_layout(other).mode == 1 && std::string(mesh_rule::fb_layout(other).why).find("RX_VK_MESH_FB_LAYOUT") !=
                                                            std::string::npos,
              std::string("RX_VK_MESH_FB_LAYOUT=") + other + " is not the default (soa), named");
    Check(MeshFallbackLayout::Aos == MeshFallbackLayout{0}, "aos is RuntimeInfo's 0");
    // (random programs and meshlets: triangles with and without per-primitive lines, lines, points; record widths 2 to 31)
    for (int i = 0; i < 60; i++) {
        const u32 topology{i % 6 == 4 ? 1U : i % 6 == 5 ? 0U : 4U};
        const u32 primitive_lines{i % 3 == 1 ? 1 + static_cast<u32>(rng() % 3) : 0U};
        const Program p{MakeProgram(rng, topology, 1 + static_cast<u32>(rng() % 26), primitive_lines)};
        RunCase(("random " + std::to_string(i)).c_str(), p, MakeMeshlets(rng, p, 1 + rng() % 64, false));
        cases++;
    }
    // (past the area: full meshlets of a wide record, as Kokiri's hot programs, until the area is cut)
    for (u32 vertex_lines : {21U, 26U}) {
        Program p{MakeProgram(rng, 4, vertex_lines, 0)};
        p.mesh.max_vertices = 64, p.mesh.max_primitives = 126;
        RunCase(("past the area " + std::to_string(vertex_lines)).c_str(), p, MakeMeshlets(rng, p, 2400, true));
        cases++;
    }
    std::printf("mesh fallback layouts: %d cases, %d failed\n", cases, fails);
    return fails ? 1 : 0;
}
