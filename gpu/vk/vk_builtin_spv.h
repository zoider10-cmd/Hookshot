// The renderer's built-in shaders, from disk when asked (the dev-loop proposal's B2, #2636).
//
// RX_VK_SHADER_DIR=<folder>: each built-in shader is taken from <folder>/<name>.spv when that file is SPIR-V, and the log
// names it; otherwise the words compiled in from gpu/vk/shaders/*_spv.h. <name> is the header's: clear_vert.spv for
// CLEAR_VERT_SPV, as its header is clear_vert_spv.h. For trying a shader edit without a renderer build: glslangValidator -V
// <source> -o <folder>/<name>.spv, with the target and defines the shader's header or test names, then start the game again.
// The shipped headers are still generated from the sources.
#pragma once

#include <cstddef>
#include <cstdint>

namespace mkwvk {

struct BuiltinSpv {
    const uint32_t* code;
    size_t size;   ///< in bytes, as VkShaderModuleCreateInfo::codeSize
};

/// A built-in shader's SPIR-V: `words` (`size` bytes, the compiled-in array named `name`), or its file under
/// RX_VK_SHADER_DIR. A file is read once and kept for the process, as the compiled-in words are
BuiltinSpv builtin_spv(const char* name, const uint32_t* words, size_t size);

} // namespace mkwvk

/// builtin_spv for a compiled-in array, by its name: BUILTIN_SPV(CLEAR_VERT_SPV)
#define BUILTIN_SPV(words) ::mkwvk::builtin_spv(#words, words, sizeof words)
/// The same as the two arguments (words, bytes) the pipeline helpers take. Both calls give the same: the first decides, and
/// what it decided is kept
#define BUILTIN_SPV_ARGS(words) BUILTIN_SPV(words).code, BUILTIN_SPV(words).size
