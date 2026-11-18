// Fullscreen monitor menu state: the saved identity is independent of enumeration order.
#pragma once
#include <string>
#include <vector>

namespace mkwvk::monitor_choice {
struct Choice {
    std::string id, name;
    int width = 0, height = 0, flags = 0;
};
inline std::string id_key(const char* text) {
    std::string s(text ? text : "");
    while (!s.empty() && (s.back() == '\r' || s.back() == '\n')) s.pop_back();
    if (s.size() >= 512) return {};
    for (unsigned char c : s) if (c < 0x20 || c == 0x7f) return {};
    return s;
}
// 0 Auto; 1..N an unambiguous connected identity; N+1 the retained unavailable choice.
inline int pick(const std::vector<Choice>& choices, const std::string& wanted) {
    if (wanted.empty()) return 0;
    int found = 0;
    for (size_t i = 0; i < choices.size(); i++) if (choices[i].id == wanted) {
        if (found) return (int)choices.size() + 1; // Ambiguity must not silently choose another monitor.
        found = (int)i + 1;
    }
    return found ? found : (int)choices.size() + 1;
}
inline std::string current_id(const std::vector<Choice>& choices) {
    for (const Choice& c : choices) if (c.flags & 1) return c.id;
    return {};
}
} // namespace mkwvk::monitor_choice
