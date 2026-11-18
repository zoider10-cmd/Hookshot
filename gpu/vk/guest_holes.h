// (hookshot) The parts of the guest window's memfd (host/hos_main.c) that hold pages, by lseek's SEEK_DATA and SEEK_HOLE. A hole
// reads as zero, but a read of it through the window's shared mapping makes the kernel give it a page, zeroed: what checks a
// storage for zeros (vk_texture.cpp upload_all_zero) would make guest memory of every page it looks at. A page in swap counts as
// data. tests/test_guest_holes.py
#pragma once
#include <algorithm>
#include <cstdint>
#include <utility>
#include <vector>
#if defined(__linux__)
#include <cerrno>
#include <unistd.h>
#endif

namespace guest_holes {

/// {start, end} offsets from the start of the range asked about
using Extents = std::vector<std::pair<uint64_t, uint64_t>>;

constexpr int64_t kNoData = -1;   // (a seek for data: none at or after the offset; ENXIO)
constexpr int64_t kFailed = -2;   // (anything else)

/// The extents of [off, off + len) that hold data, appended to out: seek(pos, true) is the first offset at or after pos that holds
/// data (kNoData: none), seek(pos, false) the first that is a hole (the file's end counts as one). Past max_extents the rest of the
/// range is one extent, read whole. False when a seek failed: what holds data is not known, and all of it is to be read
template <class Seek>
bool data_extents(Seek&& seek, uint64_t off, uint64_t len, Extents& out, size_t max_extents = 1024) {
    const uint64_t end = off + len;
    for (uint64_t pos = off; pos < end;) {
        const int64_t d = seek(pos, true);
        if (d == kNoData) break;
        if (d < 0) return false;
        if ((uint64_t)d >= end) break;
        const uint64_t from = (uint64_t)d < pos ? pos : (uint64_t)d;
        if (out.size() + 1 >= max_extents) {
            out.push_back({from - off, len});
            return true;
        }
        const int64_t h = seek(from, false);
        if (h < 0 || (uint64_t)h <= from) return false;
        const uint64_t to = (uint64_t)h < end ? (uint64_t)h : end;
        out.push_back({from - off, to - off});
        pos = to;
    }
    return true;
}

/// Thread t of n's part of the extents' bytes, taken end to end: bytes t * per .. (t + 1) * per of the data, per the ceiling
/// of the data over n rounded up to a page. The n parts cover all of it once, however it lies in the range: split by the
/// range instead, data at one end (the shadow map's 16 MB of its 288) was one thread's to read while the others found none.
/// Offsets as in the extents
inline Extents share(const Extents& scan, uint32_t t, uint32_t n) {
    uint64_t data = 0;
    for (const auto& [a, b] : scan) data += b - a;
    n = n ? n : 1;
    const uint64_t per = (((data + n - 1) / n) + 4095) & ~4095ull;
    uint64_t skip = (uint64_t)t * per, left = per;
    Extents out;
    for (const auto& [a, b] : scan) {
        if (!left) break;
        if (skip >= b - a) {
            skip -= b - a;
            continue;
        }
        const uint64_t from = a + skip, to = std::min(b, from + left);
        out.push_back({from, to});
        skip = 0, left -= to - from;
    }
    return out;
}

#if defined(__linux__)
inline int64_t fd_seek(int fd, uint64_t pos, bool data) {
    errno = 0;
    const off_t r = lseek(fd, (off_t)pos, data ? SEEK_DATA : SEEK_HOLE);
    if (r >= 0) return (int64_t)r;
    return data && errno == ENXIO ? kNoData : kFailed;
}

inline bool fd_data_extents(int fd, uint64_t off, uint64_t len, Extents& out, size_t max_extents = 1024) {
    if (fd < 0) return false;
    return data_extents([fd](uint64_t pos, bool data) { return fd_seek(fd, pos, data); }, off, len, out, max_extents);
}
#endif

} // namespace guest_holes
