// (hookshot) The built-in shaders from disk under RX_VK_SHADER_DIR. See vk_builtin_spv.h.
#include "vk_builtin_spv.h"

#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <map>
#include <mutex>
#include <string>
#include <vector>

namespace mkwvk {

void logf(const char* fmt, ...);   // (vk_main.cpp)

namespace {

std::mutex mu;
std::map<std::string, std::vector<uint32_t>> files;   // (by name: a file's words, or none for the compiled-in ones)

/// CLEAR_VERT_SPV -> clear_vert, the stem of its header clear_vert_spv.h
std::string stem_of(const char* name) {
    std::string s(name);
    if (s.size() > 4 && s.compare(s.size() - 4, 4, "_SPV") == 0) s.resize(s.size() - 4);
    for (char& c : s) c = (char)tolower((unsigned char)c);
    return s;
}

/// The file's words, or why they cannot be a shader module's: null when it is SPIR-V by its first word and size
const char* read_spv(const std::string& path, std::vector<uint32_t>& words) {
    FILE* f = fopen(path.c_str(), "rb");   // (UTF-8: the manifest's code page on Windows)
    if (!f) return "";   // (none: the compiled-in words, without a word in the log)
    std::vector<unsigned char> bytes;
    unsigned char buf[65536];
    for (size_t n; (n = fread(buf, 1, sizeof buf, f)) > 0;) bytes.insert(bytes.end(), buf, buf + n);
    fclose(f);
    if (bytes.size() < 20 || bytes.size() % 4) return "not a whole number of words, or shorter than SPIR-V's header";
    words.resize(bytes.size() / 4);
    for (size_t i = 0; i < words.size(); i++)   // (SPIR-V's words are little-endian as glslang writes them)
        words[i] = (uint32_t)bytes[4 * i] | (uint32_t)bytes[4 * i + 1] << 8 | (uint32_t)bytes[4 * i + 2] << 16 |
                   (uint32_t)bytes[4 * i + 3] << 24;
    if (words[0] != 0x07230203u) return "not SPIR-V (its first word is not the magic number)";
    return nullptr;
}

} // namespace

BuiltinSpv builtin_spv(const char* name, const uint32_t* words, size_t size) {
    static const char* const dir = getenv("RX_VK_SHADER_DIR");
    if (!dir || !*dir) return {words, size};
    std::lock_guard<std::mutex> lock(mu);
    const std::string stem = stem_of(name);
    auto it = files.find(stem);
    if (it == files.end()) {
        const std::string path = std::string(dir) + "/" + stem + ".spv";
        std::vector<uint32_t> read;
        const char* why = read_spv(path, read);
        if (why && *why) logf("vk: built-in shader %s: %s is %s; the compiled-in one is used", stem.c_str(), path.c_str(), why);
        if (why) read.clear();
        else logf("vk: built-in shader %s from %s (%zu bytes; compiled in: %zu) (RX_VK_SHADER_DIR)", stem.c_str(), path.c_str(),
                  read.size() * 4, size);
        it = files.emplace(stem, std::move(read)).first;
    }
    if (it->second.empty()) return {words, size};
    return {it->second.data(), it->second.size() * 4};
}

} // namespace mkwvk
