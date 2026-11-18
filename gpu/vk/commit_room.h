// (hookshot) The commit Windows still has room for, apart from Windows so that tests/test_commit_room.py can run it.
//
// The textures' budget gives commit back below a reserve under Windows' commit limit (vk_texture.cpp's commit rule). That limit
// is RAM plus the page files as they are now, and a page file Windows manages grows when the commit nears it: the limit read
// at one moment is not the one a commit fails at. A 32 GB PC whose page file was 2 GB at the start played 90 minutes with
// 0.3 to 2.5 GB left under the limit of the moment while Windows raised that limit by more than 12 GB and refused no commit;
// the rule took 292,526 textures out of the cache in that time, down to a budget of 0, and the player saw the textures go
// black and come back. What the page files can still grow by counts as room.
#pragma once

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstring>

namespace commit_room {

/// One page file, in bytes: its size now, the most Windows lets it reach, and its drive's letter ('C'; 0: not known)
struct PageFile {
    uint64_t size, max_size;
    char drive;
};

/// What the page files can still grow by: each up to its maximum, and those of one drive together no further than the drive
/// has free (drive_free: bytes free on a drive by its letter; 0 where it cannot be read). A file of an unknown drive counts
/// for nothing, as a file at its maximum does: with only such files the room is what is left under the limit now
template <typename DriveFree>
inline uint64_t growth(const PageFile* files, size_t n, DriveFree drive_free) {
    uint64_t left[26];
    bool read[26] = {};
    uint64_t sum = 0;
    for (size_t i = 0; i < n; i++) {
        const PageFile& f = files[i];
        if (f.drive < 'A' || f.drive > 'Z' || f.max_size <= f.size) continue;
        const int d = f.drive - 'A';
        if (!read[d]) read[d] = true, left[d] = drive_free(f.drive);
        const uint64_t g = std::min(f.max_size - f.size, left[d]);
        left[d] -= g;
        sum = sum > UINT64_MAX - g ? UINT64_MAX : sum + g;
    }
    return sum;
}

/// The commit left before the limit Windows can reach: what is left under the limit now, and what the page files can grow by
inline uint64_t headroom(uint64_t avail, uint64_t grow) { return avail > UINT64_MAX - grow ? UINT64_MAX : avail + grow; }

/// Whether the growth is worth reading: only below the reserve, where the commit rule would act. Above it the answer is the same
inline bool wants_growth(uint64_t avail, uint64_t reserve, bool counted) { return counted && reserve && avail < reserve; }

/// A record of NtQuerySystemInformation's SystemPageFileInformationEx (0x90) on 64-bit Windows: the sizes in pages, the name
/// a UNICODE_STRING (bytes, then the address of its UTF-16 text). 0x28 bytes
struct Record {
    uint32_t next, total, in_use, peak;
    uint16_t name_bytes, name_room;
    uint32_t pad;
    uint64_t name;
    uint32_t min_size, max_size;
};
static_assert(sizeof(Record) == 0x28 && offsetof(Record, name) == 0x18 && offsetof(Record, max_size) == 0x24);

/// The drive letter in a page file's name ("\??\C:\pagefile.sys": the first letter with a colon after it), upper case; 0: none
inline char drive_of(const char16_t* name, size_t chars) {
    for (size_t i = 0; i + 1 < chars; i++) {
        const char16_t c = name[i];
        if (name[i + 1] != u':') continue;
        if (c >= u'A' && c <= u'Z') return (char)c;
        if (c >= u'a' && c <= u'z') return (char)(c - u'a' + u'A');
    }
    return 0;
}

/// The page files in what that query wrote (len bytes at buf, which stays at the address the query wrote it to: the names are
/// addresses into it), at most cap of them. A record or a name that does not lie inside buf ends the list or loses its drive
inline size_t page_files(const unsigned char* buf, size_t len, uint64_t page, PageFile* out, size_t cap) {
    size_t n = 0, at = 0;
    while (n < cap && at <= len && len - at >= sizeof(Record)) {
        Record r;
        std::memcpy(&r, buf + at, sizeof r);
        PageFile f{(uint64_t)r.total * page, (uint64_t)r.max_size * page, 0};
        const uint64_t lo = (uint64_t)(uintptr_t)buf, hi = lo + len;
        if (r.name >= lo && r.name <= hi && r.name_bytes <= hi - r.name && r.name % alignof(char16_t) == 0)
            f.drive = drive_of((const char16_t*)(uintptr_t)r.name, r.name_bytes / sizeof(char16_t));
        out[n++] = f;
        if (!r.next || r.next < sizeof(Record) || r.next > len - at) break;
        at += r.next;
    }
    return n;
}

}  // namespace commit_room
