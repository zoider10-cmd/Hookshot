// CPU upload of complete 64-byte by 8-row Switch 2 GOBs (Longshot 09a20cd6, #1603): 1.7-2.6x the reference decoder.
#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <span>

namespace mkwvk::texture_tiles {
inline bool unswizzle(std::span<uint8_t> dest, std::span<const uint8_t> src,
                      uint64_t pitch, uint32_t height, uint32_t tile_height) {
    if (!pitch || pitch % 64 || !height || height % 8 || tile_height > 5 || pitch > dest.size() / height)
        return false;
    const std::size_t columns = std::size_t(pitch / 64);
    const std::size_t rows = height / 8;
    const std::size_t rows_per_block = std::size_t{1} << tile_height;
    const std::size_t padded_rows = (rows + rows_per_block - 1) / rows_per_block * rows_per_block;
    if (columns > src.size() / padded_rows / 512) return false;

    // Finish eight destination rows before moving down. A taller strip repeatedly
    // evicts its own destination cache lines when the pitch is a power of two.
    for (std::size_t y = 0; y < rows; ++y) {
        const std::size_t top = y & ~(rows_per_block - 1);
        for (std::size_t x = 0; x < columns; ++x) {
            const uint8_t* in = src.data() + (top * columns + x * rows_per_block + (y - top)) * 512;
            uint8_t* out = dest.data() + y * 8 * pitch + x * 64;
            for (std::size_t line = 0; line < 8; ++line) {
                const uint8_t* row = in + (line & 3) * 16 + (line >> 2) * 128;
                auto* d = out + line * pitch;
                std::memcpy(d, row, 16);
                std::memcpy(d + 16, row + 64, 16);
                std::memcpy(d + 32, row + 256, 16);
                std::memcpy(d + 48, row + 320, 16);
            }
        }
    }
    return true;
}
} // namespace mkwvk::texture_tiles
