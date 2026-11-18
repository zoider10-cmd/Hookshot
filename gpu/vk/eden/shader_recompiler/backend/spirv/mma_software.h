// (hookshot) HMMA.16816.F16 in software: D(16x8) = A(16x16) * B(16x8) + C on the subgroup's lanes, for GPUs without
// cooperative matrices (AMD before RDNA 3, the Steam Deck among them; GTX 10 and 16; Intel's integrated GPUs). The 32 lanes'
// fragments (PTX mma.m16n8k16's layout: lane t, g = t/4, i = t%4) are exchanged through subgroup operations; the products are
// accumulated with FMA in f32 and rounded to f16 after every 8 columns of K, as HMMA.F16 does. One function, called for each
// HMMA_nx2 (emit_spirv_warp.cpp EmitMatrixMulAddF16), and built the same way by the device's self-test (vk_coopmat.cpp), which
// is why it takes a plain Sirit module and the types it needs rather than the translator's EmitContext.
//
// Two forms compute the same words:
// - Loop: Lichii's (zortos293/Lichii, emit_spirv_tensor.cpp, GPL-3.0). The 8 steps (4 K-pairs in each half of K) in a loop the
//   driver is asked not to unroll; A and B from other lanes through shuffles, the f16 rounding in integer operations.
// - Unrolled: the steps written out (in a loop that runs once: see below). A lane's rows of A are in its own quad (lanes 4g..4g+3), so A comes through quad broadcasts
//   (DPP on AMD, not the LDS crossbar a shuffle takes), and A's lane indices are constants (B's are still the lane's
//   warp_base + col_base + c). The rounding to f16 is either the same
//   integer operations or the GPU's own f32 -> f16 -> f32 conversion (round to nearest even, f16 subnormals kept). A conversion
//   applied to an FMA's result may be folded into it by the driver (RADV: v_fma_mixlo_f16), which rounds the exact sum once
//   instead of rounding it to f32 first: a tie in f32 then goes the other way (1 word in about 17,000 of random data). The value
//   is passed through a shuffle with lane xor 0 (the same lane) before the conversion, which keeps them apart; RADV folds that
//   shuffle into the conversion as a DPP identity, so it costs nothing. vk_coopmat.cpp runs both forms on the device and uses the
//   unrolled one only where its words are the loop's. The shuffle keeps them apart only while the driver keeps a shuffle by
//   xor 0: one that folds it away rounds once again, and the tie inputs then make the self-test keep the loop (slower, said
//   only in the log).
//
// On the Steam Deck (RADV), one multiply a lane over a 1280x800 dispatch: 0.469 ms looped, 0.363 ms unrolled with the integer
// rounding, 0.177 ms unrolled with the conversion (a fully fused conversion, not the same words, 0.153 ms). OoT's gameplay network
// at Resolution 100% (9dc98871, Kokiri Forest): 8.61 ms a frame looped, 3.82 ms unrolled with the conversion.
#pragma once

#include <array>
#include <cstdint>

#include <sirit/sirit.h>

namespace Shader::Backend::SPIRV {

enum class SoftwareMmaForm : uint32_t {
    Loop = 0,          // (Lichii's: the steps in a loop, shuffles, integer rounding)
    Unrolled = 1,      // (written out, A through quad broadcasts, integer rounding)
    UnrolledF16 = 2,   // (written out, A through quad broadcasts, the GPU's f16 conversion rounds)
};

struct SoftwareMmaTypes {
    Sirit::Id u32, u32x2, u32x4, f32, f32x2, f16, boolean;
};

/// The function (A: 4 words, B: 2, C: 2) -> D: 2 words, as the console's fragments hold them, two f16 a word. lane_variable is the
/// SubgroupLocalInvocationId input; quad: OpGroupNonUniformQuadBroadcast may be used (the caller adds GroupNonUniformQuad), else
/// A's lanes are shuffled to. The caller adds GroupNonUniform and GroupNonUniformShuffle.
inline Sirit::Id DefineSoftwareMma(Sirit::Module& m, const SoftwareMmaTypes& t, Sirit::Id lane_variable, SoftwareMmaForm form,
                                   bool quad) {
    using Sirit::Id;
    const Id u32ty = t.u32, f32ty = t.f32;
    const auto imm = [&](uint32_t v) { return m.Constant(u32ty, v); };
    const auto add = [&](Id a, Id b) { return m.OpIAdd(u32ty, a, b); };
    const auto and_ = [&](Id a, uint32_t b) { return m.OpBitwiseAnd(u32ty, a, imm(b)); };
    const auto unpack = [&](Id v) { return m.OpUnpackHalf2x16(t.f32x2, v); };
    const auto round_half = [&](Id value) {
        // Do not express the intermediate rounding as unpack(pack(value)): drivers may
        // eliminate that round trip. Round normal significands explicitly, ties to even;
        // half subnormals lie on the exactly representable 2^-24 grid.
        const Id bits = m.OpBitcast(u32ty, value);
        const Id magnitude = and_(bits, 0x7fffffffU);
        const Id tie = and_(m.OpShiftRightLogical(u32ty, magnitude, imm(13)), 1);
        const Id rounded = and_(add(add(magnitude, imm(0xfff)), tie), ~0x1fffU);
        const Id normal = m.OpSelect(u32ty, m.OpUGreaterThanEqual(t.boolean, rounded, imm(0x47800000)), imm(0x7f800000), rounded);
        const Id scaled = m.OpFMul(f32ty, m.OpBitcast(f32ty, magnitude), m.Constant(f32ty, 16777216.0f));
        const Id subnormal = m.OpBitcast(u32ty, m.OpFMul(f32ty, m.OpRoundEven(f32ty, scaled), m.Constant(f32ty, 0x1p-24f)));
        const Id finite = m.OpSelect(u32ty, m.OpUGreaterThanEqual(t.boolean, magnitude, imm(0x38800000)), normal, subnormal);
        const Id result = m.OpSelect(u32ty, m.OpUGreaterThanEqual(t.boolean, magnitude, imm(0x7f800000)), magnitude, finite);
        return m.OpBitcast(f32ty, m.OpBitwiseOr(u32ty, result, and_(bits, 0x80000000)));
    };
    const auto round_half_f16 = [&](Id value) {
        // (through the same lane first: the conversion is then not folded into the FMA that made the value, see above)
        const Id same = m.OpBitcast(f32ty, m.OpGroupNonUniformShuffleXor(u32ty, imm(3), m.OpBitcast(u32ty, value), imm(0)));
        const Id half = m.OpFConvert(t.f16, same);
        m.Decorate(half, spv::Decoration::NoContraction);
        const Id back = m.OpFConvert(f32ty, half);
        m.Decorate(back, spv::Decoration::NoContraction);
        return back;
    };

    const Id type = m.TypeFunction(t.u32x2, t.u32x4, t.u32x2, t.u32x2);
    const Id fn = m.OpFunction(t.u32x2, spv::FunctionControlMask::DontInline, type);
    const Id matrix_a = m.OpFunctionParameter(t.u32x4);
    const Id matrix_b = m.OpFunctionParameter(t.u32x2);
    const Id matrix_c = m.OpFunctionParameter(t.u32x2);
    m.AddLabel();
    const bool loop = form == SoftwareMmaForm::Loop;
    // (a function's variables come first in its first block; the counter first in either form, as in Lichii's)
    const Id counter = m.AddLocalVariable(m.TypePointer(spv::StorageClass::Function, u32ty), spv::StorageClass::Function);
    Id result{};
    std::array<Id, 4> accumulators{};
    if (!loop)
        result = m.AddLocalVariable(m.TypePointer(spv::StorageClass::Function, t.u32x2), spv::StorageClass::Function);
    else
        for (auto& acc : accumulators)
            acc = m.AddLocalVariable(m.TypePointer(spv::StorageClass::Function, f32ty), spv::StorageClass::Function);
    std::array<Id, 8> inputs;
    for (uint32_t i = 0; i < 4; ++i) inputs[i] = m.OpCompositeExtract(u32ty, matrix_a, i);
    for (uint32_t i = 0; i < 2; ++i) {
        inputs[4 + i] = m.OpCompositeExtract(u32ty, matrix_b, i);
        inputs[6 + i] = m.OpCompositeExtract(u32ty, matrix_c, i);
    }
    // (the lane's warp, its quad and its B lanes' base; read where Lichii's function reads them, so that the loop's SPIR-V is
    // the same as before word for word)
    Id warp_base{}, row_base{}, col_base{};
    const auto read_lane = [&] {
        const Id lane = m.OpLoad(u32ty, lane_variable);
        warp_base = and_(lane, ~31U);
        row_base = and_(lane, 28);
        col_base = m.OpShiftLeftLogical(u32ty, and_(lane, 3), imm(3));
    };
    const auto subgroup = [&] { return imm(3); };   // (spv::Scope::Subgroup)
    // acc[row * 2 + col] += A[row's register].half * B[col's lane].half, each half of the pair in turn (NoContraction: each FMA
    // rounds to f32 as the CPU's would)
    const auto multiply_add = [&](Id value, Id as, Id bs) {
        for (uint32_t half = 0; half < 2; ++half) {
            value = m.OpFma(f32ty, m.OpCompositeExtract(f32ty, as, half), m.OpCompositeExtract(f32ty, bs, half), value);
            m.Decorate(value, spv::Decoration::NoContraction);
        }
        return value;
    };

    if (!loop) {
        read_lane();
        std::array<Id, 4> acc;
        for (uint32_t row = 0; row < 2; ++row) {
            const Id c = unpack(inputs[6 + row]);
            for (uint32_t col = 0; col < 2; ++col) acc[row * 2 + col] = m.OpCompositeExtract(f32ty, c, col);
        }
        // (the body in a loop that runs once, which the driver is asked not to unroll. Mesa inlines every call, and with the bodies
        // side by side its CSE shares the shuffles of an operand that several multiplies take: fewer of them, but each held until
        // its last use. OoT's gameplay network then took 256 VGPRs (4 waves a SIMD on the Steam Deck, not 8) and the 3/4 one spilled
        // 181 to scratch; in a loop of their own they keep the loop form's 128. On the Deck, at 1280x800: 3.82 ms a frame in a loop,
        // 4.60 ms without)
        m.OpStore(counter, imm(0));
        const Id header = m.OpLabel(), body = m.OpLabel(), next = m.OpLabel(), end = m.OpLabel();
        m.OpBranch(header);
        m.AddLabel(header);
        const Id trip = m.OpLoad(u32ty, counter);
        const Id more = m.OpULessThan(t.boolean, trip, imm(1));
        m.OpLoopMerge(end, next, spv::LoopControlMask::DontUnroll);
        m.OpBranchConditional(more, body, end);
        m.AddLabel(body);
        for (uint32_t upper = 0; upper < 2; ++upper) {   // (K 0-7, then 8-15: B's word and A's two of that half)
            for (uint32_t component = 0; component < 4; ++component) {   // (the K pair 2 * component of that half)
                std::array<Id, 2> bs;   // (B's column 2i + col, from lane 8i + component + 4 col)
                for (uint32_t col = 0; col < 2; ++col)
                    bs[col] = unpack(m.OpGroupNonUniformShuffle(u32ty, subgroup(), inputs[4 + upper],
                                                                add(warp_base, add(col_base, imm(component + col * 4)))));
                for (uint32_t row = 0; row < 2; ++row) {   // (A's row g + 8 row, from lane 4g + component: this lane's quad)
                    const Id a = inputs[upper * 2 + row];
                    const Id as = unpack(quad ? m.OpGroupNonUniformQuadBroadcast(u32ty, subgroup(), a, imm(component))
                                              : m.OpGroupNonUniformShuffle(u32ty, subgroup(), a, add(warp_base, add(row_base, imm(component)))));
                    for (uint32_t col = 0; col < 2; ++col) acc[row * 2 + col] = multiply_add(acc[row * 2 + col], as, bs[col]);
                }
            }
            // HMMA.F16 rounds after each K=8 group, including the midpoint of K=16.
            for (auto& v : acc) v = form == SoftwareMmaForm::UnrolledF16 ? round_half_f16(v) : round_half(v);
        }
        std::array<Id, 2> packed;
        for (uint32_t row = 0; row < 2; ++row)
            packed[row] = m.OpPackHalf2x16(u32ty, m.OpCompositeConstruct(t.f32x2, acc[row * 2], acc[row * 2 + 1]));
        m.OpStore(result, m.OpCompositeConstruct(t.u32x2, packed[0], packed[1]));
        m.OpBranch(next);
        m.AddLabel(next);
        m.OpStore(counter, add(trip, imm(1)));
        m.OpBranch(header);
        m.AddLabel(end);
        m.OpReturnValue(m.OpLoad(t.u32x2, result));
        m.OpFunctionEnd();
        return fn;
    }

    for (uint32_t row = 0; row < 2; ++row) {
        const Id c = unpack(inputs[6 + row]);
        for (uint32_t col = 0; col < 2; ++col) m.OpStore(accumulators[row * 2 + col], m.OpCompositeExtract(f32ty, c, col));
    }
    m.OpStore(counter, imm(0));
    read_lane();
    const Id header = m.OpLabel(), body = m.OpLabel(), next = m.OpLabel(), end = m.OpLabel();
    m.OpBranch(header);
    m.AddLabel(header);
    const Id pair = m.OpLoad(u32ty, counter);
    const Id more = m.OpULessThan(t.boolean, pair, imm(8));
    m.OpLoopMerge(end, next, spv::LoopControlMask::DontUnroll);
    m.OpBranchConditional(more, body, end);
    m.AddLabel(body);
    const Id upper = m.OpUGreaterThanEqual(t.boolean, pair, imm(4));
    const Id component = and_(pair, 3);
    const Id a_lane = add(warp_base, add(row_base, component));
    const Id b_lane = add(warp_base, add(col_base, component));
    const Id b = m.OpSelect(u32ty, upper, inputs[5], inputs[4]);
    std::array<Id, 2> bs;
    for (uint32_t col = 0; col < 2; ++col)
        bs[col] = unpack(m.OpGroupNonUniformShuffle(u32ty, subgroup(), b, add(b_lane, imm(col * 4))));
    const Id round_now = m.OpIEqual(t.boolean, component, imm(3));
    for (uint32_t row = 0; row < 2; ++row) {
        const Id a = m.OpSelect(u32ty, upper, inputs[row + 2], inputs[row]);
        const Id as = unpack(m.OpGroupNonUniformShuffle(u32ty, subgroup(), a, a_lane));
        for (uint32_t col = 0; col < 2; ++col)
            m.OpStore(accumulators[row * 2 + col], multiply_add(m.OpLoad(f32ty, accumulators[row * 2 + col]), as, bs[col]));
    }
    // HMMA.F16 rounds after each K=8 group, including the midpoint of K=16.
    // OpSelect evaluates both operands: keep the expensive half conversion in
    // a branch so the other three pairs do no rounding work. The counter is
    // identical in every participating lane and all shuffles precede this branch.
    const Id round_block = m.OpLabel(), round_merge = m.OpLabel();
    m.OpSelectionMerge(round_merge, spv::SelectionControlMask::DontFlatten);
    m.OpBranchConditional(round_now, round_block, round_merge);
    m.AddLabel(round_block);
    for (const Id accumulator : accumulators) m.OpStore(accumulator, round_half(m.OpLoad(f32ty, accumulator)));
    m.OpBranch(round_merge);
    m.AddLabel(round_merge);
    m.OpBranch(next);
    m.AddLabel(next);
    m.OpStore(counter, add(pair, imm(1)));
    m.OpBranch(header);
    m.AddLabel(end);
    std::array<Id, 2> packed;
    for (uint32_t row = 0; row < 2; ++row)
        packed[row] = m.OpPackHalf2x16(u32ty, m.OpCompositeConstruct(t.f32x2, m.OpLoad(f32ty, accumulators[row * 2]),
                                                                     m.OpLoad(f32ty, accumulators[row * 2 + 1])));
    m.OpReturnValue(m.OpCompositeConstruct(t.u32x2, packed[0], packed[1]));
    m.OpFunctionEnd();
    return fn;
}

} // namespace Shader::Backend::SPIRV
