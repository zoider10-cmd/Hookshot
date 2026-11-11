// (Mako) The incomplete game dump (~23.3 GB; a complete one is ~23.8 GB) has three romfs textures that do not decode:
// Rock_WaterTemple_Gate_M_01_Nrm, CmnTex_Map_Soil_FairyFountain_Floor_D_Nrm and RBake_Scene_GanonStage_G_2_1_d0_t0
// (upstream #1002). Some copies start with zeros, others with a zstd header and garbage after it. The game then leaves
// out every model using one: the Water Temple's walls and floors, the Great Fairy Fountain all black, Ganon's stage.
// Upstream's builder (#1308) puts a whole texture of the same kind in each one's place when it unpacks the game; this
// does the same at start for game folders already built, so a graphics patch repairs them without a rebuild: the
// damaged file is kept beside it as <name>.damaged, and a stand-in (the same last name part, the longest common name
// start, then the nearest size, one that decodes) takes its name. A file that decodes is never touched.
// MAKO_NO_STAND_IN=1: off.
#pragma once
#include <cstdint>
#include <cstdio>
#include <filesystem>
#include <string>
#include <system_error>
#include <vector>

namespace mkwvk::damaged {

struct Fix {
    std::string name, stand_in;   // (stand_in empty: nothing similar found, left as it is)
};

inline bool read_file(const std::filesystem::path& p, std::vector<uint8_t>& out) {
    FILE* f = nullptr;
    if (_wfopen_s(&f, p.c_str(), L"rb") || !f) return false;
    out.clear();
    uint8_t buf[1 << 16];
    for (size_t n; (n = fread(buf, 1, sizeof buf, f)) > 0;) out.insert(out.end(), buf, buf + n);
    fclose(f);
    return true;
}

/// Whether a .zs file's first zstd frame header is sane and its first block's header is a known block type with a size
/// that fits the file: the damaged ones fail here (zeros, or a frame header whose next bytes are not a block). A cheap
/// check, not a decode; the three names are the only ones looked at.
inline bool frame_looks_whole(const std::vector<uint8_t>& d) {
    if (d.size() < 8 || !(d[0] == 0x28 && d[1] == 0xb5 && d[2] == 0x2f && d[3] == 0xfd)) return false;
    const uint8_t fhd = d[4];
    if (fhd & 0x08) return false;   // (reserved bit)
    const int fcs_flag = fhd >> 6, single = (fhd >> 5) & 1, dict_flag = fhd & 3;
    size_t at = 5;
    if (!single) {
        const uint8_t wd = d[at++];
        if ((wd >> 3) + 10 > 31) return false;   // (window past 2 GB: not a real frame)
    }
    static const int dict_size[4] = {0, 1, 2, 4};
    at += dict_size[dict_flag];
    static const int fcs_size[4] = {0, 2, 4, 8};
    at += fcs_flag == 0 && single ? 1 : fcs_size[fcs_flag];
    // blocks: 3 bytes each (last, type, size); walk them all, as far as the file goes
    for (;;) {
        if (at + 3 > d.size()) return false;
        const uint32_t h = d[at] | d[at + 1] << 8 | d[at + 2] << 16;
        at += 3;
        const int last = h & 1, type = (h >> 1) & 3;
        const uint32_t size = h >> 3;
        if (type == 3) return false;   // (reserved block type)
        if (size > (128u << 10)) return false;
        at += type == 1 ? 1 : size;   // (RLE: one byte)
        if (at > d.size()) return false;
        if (last) break;
    }
    if (fhd & 0x04) at += 4;   // (content checksum)
    // (a whole one is one frame to the file's end. The damaged ones of some copies are one frame shorter than the file
    // whose content is the zero-started original again, with bytes left after it: the game's decoder refuses them)
    return at == d.size();
}

inline bool decodes(const std::filesystem::path& p) {
    std::vector<uint8_t> d;
    return read_file(p, d) && frame_looks_whole(d);
}

/// The name's last part: "_Nrm.bntx.zs", "_t0.bntx.zs" (upstream's (_[A-Za-z]+\d*)?(\.[^_]*)$)
inline std::string kind_of(const std::string& name) {
    const size_t dot = name.find('.', name.rfind('_') == std::string::npos ? 0 : name.rfind('_'));
    if (dot == std::string::npos) return name;
    const size_t us = name.rfind('_', dot);
    if (us == std::string::npos) return name.substr(dot);
    size_t i = us + 1;
    while (i < dot && isalpha((unsigned char)name[i])) i++;
    const bool letters = i > us + 1;
    while (i < dot && isdigit((unsigned char)name[i])) i++;
    return letters && i == dot ? name.substr(us) : name.substr(dot);
}

inline std::string stand_in_for(const std::filesystem::path& folder, const std::string& name, uintmax_t size,
                                const std::vector<std::string>& damaged) {
    const std::string kind = kind_of(name);
    std::string best;
    size_t best_prefix = 0;
    uintmax_t best_diff = UINTMAX_MAX;
    std::error_code ec;
    for (const auto& e : std::filesystem::directory_iterator(folder, ec)) {
        const std::string other = e.path().filename().string();
        if (other == name || other.size() < kind.size() || other.compare(other.size() - kind.size(), kind.size(), kind)) continue;
        bool bad = false;
        for (const std::string& d : damaged) bad |= d == other;
        if (bad) continue;
        size_t prefix = 0;
        while (prefix < name.size() && prefix < other.size() && name[prefix] == other[prefix]) prefix++;
        const uintmax_t osize = e.file_size(ec);
        const uintmax_t diff = osize > size ? osize - size : size - osize;
        if (prefix < best_prefix || (prefix == best_prefix && diff >= best_diff && !best.empty())) continue;
        if (!decodes(e.path())) continue;
        best = other, best_prefix = prefix, best_diff = diff;
    }
    return best;
}

/// tex: the game's romfs\Tex folder. What was done, for the log.
inline std::vector<Fix> repair(const std::filesystem::path& tex) {
    static const char* const names[] = {"Rock_WaterTemple_Gate_M_01_Nrm.bntx.zs", "CmnTex_Map_Soil_FairyFountain_Floor_D_Nrm.bntx.zs",
                                        "RBake_Scene_GanonStage_G_2_1_d0_t0.bntx.zs"};
    std::vector<std::string> damaged;
    std::error_code ec;
    for (const char* n : names) {
        const std::filesystem::path p = tex / n;
        if (std::filesystem::exists(p, ec) && !decodes(p)) damaged.push_back(n);
    }
    std::vector<Fix> done;
    for (const std::string& n : damaged) {
        const std::filesystem::path p = tex / n;
        Fix fix{n, stand_in_for(tex, n, std::filesystem::file_size(p, ec), damaged)};
        if (!fix.stand_in.empty()) {
            const std::filesystem::path tmp = tex / (n + ".mako-tmp"), kept = tex / (n + ".damaged");
            std::filesystem::copy_file(tex / fix.stand_in, tmp, std::filesystem::copy_options::overwrite_existing, ec);
            if (!ec) std::filesystem::rename(p, kept, ec);   // (a new name for the old file: a hard link's other names keep theirs)
            if (!ec) std::filesystem::rename(tmp, p, ec);
            if (ec) {
                std::filesystem::remove(tmp, ec);
                if (!std::filesystem::exists(p, ec) && std::filesystem::exists(kept, ec)) std::filesystem::rename(kept, p, ec);
                fix.stand_in.clear();
            }
        }
        done.push_back(fix);
    }
    return done;
}

} // namespace mkwvk::damaged
