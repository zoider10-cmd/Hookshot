// guest_holes::data_extents (gpu/vk/guest_holes.h): the parts of the guest window's memfd that hold pages, found without
// reading the holes (a read of one makes the kernel give it a page); guest_holes::share: the threads' parts of them.
// tests/test_guest_holes.py
#include "../gpu/vk/guest_holes.h"

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <utility>
#include <vector>
#if defined(__linux__)
#include <cstring>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>
#endif

static int failures = 0;
static void expect(bool ok, const char* what) {
    if (!ok) {
        std::printf("FAIL: %s\n", what);
        failures++;
    }
}

#if defined(__linux__)
// (shmem transparent huge pages: "always", "within_size" or "force" give a memfd 2 MB pages, so a byte written backs 2 MB)
static bool shmem_huge_pages() {
    FILE* f = std::fopen("/sys/kernel/mm/transparent_hugepage/shmem_enabled", "r");
    if (!f) return false;
    char buf[128] = {};
    const size_t n = std::fread(buf, 1, sizeof buf - 1, f);
    std::fclose(f);
    buf[n] = 0;
    return std::strstr(buf, "[always]") || std::strstr(buf, "[within_size]") || std::strstr(buf, "[force]");
}
#endif

// A file as lseek sees it: its data extents (sorted, apart), the rest holes up to its size, which counts as a hole too
struct Model {
    std::vector<std::pair<uint64_t, uint64_t>> data;
    uint64_t size = 0;
    bool fail = false;
    int calls = 0;
    int64_t operator()(uint64_t pos, bool want_data) {
        calls++;
        if (fail) return guest_holes::kFailed;
        if (pos >= size) return want_data ? guest_holes::kNoData : guest_holes::kFailed;   // (ENXIO for both, as lseek)
        for (const auto& [a, b] : data) {
            if (want_data && b > pos) return (int64_t)std::max(a, pos);
            if (!want_data && a > pos) return (int64_t)pos;
            if (!want_data && b > pos) return (int64_t)b;
        }
        return want_data ? guest_holes::kNoData : (int64_t)pos;
    }
};

using guest_holes::Extents;

// The n threads' parts end to end, joined where one ends where the next starts: the extents again when they cover each byte once
static Extents shares_joined(const Extents& scan, uint32_t n, uint64_t* largest) {
    Extents all;
    *largest = 0;
    for (uint32_t t = 0; t < n; t++) {
        uint64_t mine = 0;
        for (const auto& e : guest_holes::share(scan, t, n)) {
            mine += e.second - e.first;
            if (!all.empty() && all.back().second == e.first) all.back().second = e.second;
            else all.push_back(e);
        }
        *largest = std::max(*largest, mine);
    }
    return all;
}

int main() {
    const uint64_t MB = 1ull << 20, K = 4096;
    {
        Model m{{}, 512 * MB};
        Extents e;
        expect(guest_holes::data_extents(m, 8 * MB, 288 * MB, e) && e.empty(), "all holes: no data, nothing to read");
    }
    {
        Model m{{{16 * MB, 20 * MB}, {40 * MB, 40 * MB + K}}, 512 * MB};
        Extents e;
        expect(guest_holes::data_extents(m, 8 * MB, 48 * MB, e) && e == Extents{{8 * MB, 12 * MB}, {32 * MB, 32 * MB + K}},
               "two extents, relative to the range's start");
    }
    {
        Model m{{{0, 10 * MB}, {50 * MB, 60 * MB}}, 512 * MB};
        Extents e;
        expect(guest_holes::data_extents(m, 4 * MB, 50 * MB, e) && e == Extents{{0, 6 * MB}, {46 * MB, 50 * MB}},
               "extents across both ends clipped to the range");
    }
    {
        Model m{{{100 * MB, 101 * MB}}, 512 * MB};
        Extents e;
        expect(guest_holes::data_extents(m, 0, 64 * MB, e) && e.empty(), "data past the range's end: none in it");
    }
    {
        Model m{{{0, 64 * MB}}, 512 * MB};
        Extents e;
        expect(guest_holes::data_extents(m, 0, 64 * MB, e) && e == Extents{{0, 64 * MB}}, "all data: the whole range");
    }
    {
        Model m{{{0, K}}, 512 * MB};
        m.fail = true;
        Extents e;
        expect(!guest_holes::data_extents(m, 0, 64 * MB, e), "lseek failing: not known, so the caller reads it all");
    }
    {
        Model m{{}, 512 * MB};
        for (uint64_t i = 0; i < 64; i++) m.data.push_back({i * 2 * K, i * 2 * K + K});
        Extents e;
        expect(guest_holes::data_extents(m, 0, 128 * K, e, 3) && e == Extents{{0, K}, {2 * K, 3 * K}, {4 * K, 128 * K}},
               "past the cap of extents the rest is read whole");
        expect(m.calls <= 8, "past the cap no more lseeks");
    }
    {
        uint64_t largest = 0;
        const Extents one{{0, 4 * MB + 3}};
        expect(shares_joined(one, 4, &largest) == one, "shares: a size the threads don't divide evenly, its last bytes too");
        const Extents end{{272 * MB, 288 * MB}};
        expect(shares_joined(end, 8, &largest) == end && largest == 2 * MB,
               "shares: data at one end of the storage, the same 2 MB to each of 8 threads");
        const Extents several{{0, K}, {10 * K, 13 * K}, {100 * K, 101 * K + 5}};
        for (uint32_t n = 1; n <= 9; n++)
            expect(shares_joined(several, n, &largest) == several, "shares: several extents, each byte once, any thread count");
        expect(shares_joined(Extents{}, 8, &largest).empty() && largest == 0, "shares: no data, nothing to read");
        expect(guest_holes::share(one, 0, 0) == one, "shares: no thread count is one thread");
    }
#if defined(__linux__)
    {   // (the kernel's own: a memfd, as the guest window's, MAP_SHARED and MAP_NORESERVE)
        const int fd = (int)syscall(SYS_memfd_create, "guest-holes-test", 1u /* MFD_CLOEXEC */);
        expect(fd >= 0, "memfd_create");
        if (fd >= 0 && ftruncate(fd, (off_t)(1ull << 33)) == 0) {
            void* m = mmap(nullptr, 64 * MB, PROT_READ | PROT_WRITE, MAP_SHARED | MAP_NORESERVE, fd, 0);
            expect(m != MAP_FAILED, "mmap");
            if (m != MAP_FAILED) {
                uint8_t* p = (uint8_t*)m;
                std::memset(p + 16 * MB, 7, 4 * MB);
                p[40 * MB] = 1;
                struct stat s0{}, s1{};
                fstat(fd, &s0);
                Extents e;
                const bool ok = guest_holes::fd_data_extents(fd, 8 * MB, 48 * MB, e);
                fstat(fd, &s1);
                expect(ok, "memfd: the extents found");
                // (with shmem transparent huge pages a byte written is a 2 MB page: what was written lies in the extents,
                // the rest of them is a few huge pages at most)
                auto inside = [&](uint64_t at) {
                    for (const auto& [a, b] : e)
                        if (a <= at && at < b) return true;
                    return false;
                };
                expect(inside(8 * MB) && inside(12 * MB - 1) && inside(32 * MB), "memfd: the pages written are data");
                expect(!inside(0) && !inside(20 * MB) && !inside(39 * MB), "memfd: pages far from them are holes");
                uint64_t data = 0;
                for (const auto& [a, b] : e) data += b - a;
                expect(data >= 4 * MB + K && data <= 8 * MB, "memfd: about as much data as was written");
                expect(s0.st_blocks == s1.st_blocks, "memfd: finding them gave no hole a page");
                if (!shmem_huge_pages()) {
                    expect(e == Extents{{8 * MB, 12 * MB}, {32 * MB, 32 * MB + K}}, "memfd: the pages written, nothing else");
                    expect((uint64_t)s1.st_blocks * 512 == 4 * MB + K, "memfd: no page but those written");
                }
                Extents none;
                expect(guest_holes::fd_data_extents(fd, 1ull << 32, 288 * MB, none) && none.empty(),
                       "memfd: a range never written has no data");
                struct stat s2{};
                fstat(fd, &s2);
                expect(s2.st_blocks == s1.st_blocks, "memfd: nor did finding none");
                munmap(m, 64 * MB);
            }
        }
        if (fd >= 0) close(fd);
        Extents e;
        expect(!guest_holes::fd_data_extents(-1, 0, MB, e), "no memfd: not known");
        int pipefd[2];
        if (pipe(pipefd) == 0) {   // (lseek fails on a pipe: ESPIPE)
            Extents pe;
            expect(!guest_holes::fd_data_extents(pipefd[0], 0, MB, pe), "a seek failing: not known");
            close(pipefd[0]);
            close(pipefd[1]);
        }
    }
#endif
    if (failures) return EXIT_FAILURE;
    std::printf("guest holes: all checks passed\n");
    return EXIT_SUCCESS;
}
