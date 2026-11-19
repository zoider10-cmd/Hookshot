"""Compare the CPU texture upload path to the reference decoder (Longshot 09a20cd6; gpu/vk/texture_tiles.h, vk_texture.cpp
unswizzle_upload). Here the reference keeps its stride alignment of 1, as the renderer always called it: the fast path's bytes
must be the reference's, so no texture changes. Run with --cxx clang++ or g++."""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from srccut import block

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

HARNESS = r"""
#include "texture_tiles.h"
#include <cstdlib>
#include "video_core/textures/decoders.h"
#include <cassert>
#include <random>
#include <vector>
namespace texture_tiles = mkwvk::texture_tiles;
using texture_tiles::unswizzle;
namespace Tegra::Texture {
unsigned fallback_calls;
template<class... Args>
void counted_unswizzle(Args... args) {
    ++fallback_calls;
    UnswizzleTexture(args...);
}
}
#define UnswizzleTexture counted_unswizzle
@UPLOAD@
#undef UnswizzleTexture
int main() {
    std::mt19937 random(817);
    for (unsigned bpb : {1u, 2u, 3u, 4u, 6u, 8u, 12u, 16u})
        for (unsigned width : {8u, 17u, 21u, 32u, 64u, 85u, 128u})
            for (unsigned height : {3u, 8u, 16u, 24u, 72u})
                for (unsigned tile : {0u, 1u, 3u, 5u})
                    for (unsigned depth : {1u, 2u}) {
                        const unsigned tile_d = depth == 2 ? 1 : 0;
                        const size_t pitch = width * bpb;
                        // Allocate both possible padding layouts. Compare their pixel contents safely.
                        const size_t cols = (((width+1u)&~1u)*bpb+63u)/64u;
                        const size_t rows_per_block = 8u << tile;
                        const size_t size = cols * 64 * rows_per_block *
                            ((height+rows_per_block-1)/rows_per_block) * depth;
                        std::vector<uint8_t> input(size+5);
                        for (auto& value : input) value = uint8_t(random());
                        const auto src = std::span(input).subspan(5);
                        std::vector<uint8_t> result(pitch*height*depth+32, 0x7f), ref=result;
                        auto output = std::span(result).subspan(7, pitch*height*depth);
                        Tegra::Texture::UnswizzleTexture(std::span(ref).subspan(7,output.size()), src,
                                                        bpb,width,height,depth,tile,tile_d,1);
                        const unsigned before = Tegra::Texture::fallback_calls;
                        unswizzle_upload(output,src,bpb,width,height,depth,tile,tile_d);
                        assert(ref == result);
                        const bool complete = pitch % 64 == 0 && height % 8 == 0;
                        assert(Tegra::Texture::fallback_calls == before + (depth != 1 || !complete));
                        if (depth != 1) continue;
                        assert(unswizzle(output,src,pitch,height,tile) == complete);
                        if (complete) {
                            assert(!unswizzle(output.first(output.size()-1),src,pitch,height,tile));
                            assert(!unswizzle(output,src.first(src.size()-1),pitch,height,tile));
                        }
                    }
    uint8_t a[512]{};
    assert(!unswizzle(a,a,UINT64_MAX-63,8,0));
    assert(!unswizzle(a,a,64,8,32));
    assert(!unswizzle(a,a,0,8,0));
    assert(!unswizzle(a,a,64,0,0));
}
"""

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="c++")
    args = parser.parse_args()
    gpu = ROOT / 'gpu'
    suyu = gpu / 'third_party' / 'suyu'
    upload = block((gpu/'vk/vk_texture.cpp').read_text(), 'void unswizzle_upload(')
    with tempfile.TemporaryDirectory() as folder:
        cpp = Path(folder)/'tiles.cpp'
        exe = Path(folder)/'tiles.exe'
        cpp.write_text(HARNESS.replace('@UPLOAD@',upload))
        # C++23 is needed for the vendor reference. Older Clang releases use its draft spelling.
        flags = [args.cxx, '-std=c++2b', '-O2', '-I', gpu/'vk', '-isystem', suyu]
        decoder = Path(folder)/'reference.o'
        subprocess.run([*flags, '-c', suyu/'video_core/textures/decoders.cpp', '-o', decoder], check=True)
        subprocess.run([*flags, '-Wall', '-Wextra', '-Werror', cpp, decoder, '-o', exe], check=True)
        subprocess.run([exe],check=True)

if __name__ == '__main__':
    main()
