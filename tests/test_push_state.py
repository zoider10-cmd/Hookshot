"""The descriptors are built as plain words and pushed through a descriptor update template (gpu/vk/vk_draw.cpp).

build_descriptors writes each binding's descriptors as the driver reads them (a buffer or image descriptor 3 words, a texel
buffer view 1), and bind_descriptors keeps the words it pushed: the same words again push nothing (one comparison), a few
bindings changed push only those as writes pointing into the words, more push the whole set through the program's template
(vkCmdPushDescriptorSetWithTemplateKHR). Without a template (RX_VK_DESC_TEMPLATE=0, the recorder on, a driver without one)
every binding is a write made from the words. A pooled set is written through the template too. The idea is Fritchii's
(one template per pipeline layout, descriptors as plain records in one buffer). Before this, each build made a write a
binding and three arrays of infos, and each bind encoded and compared them word by word.

The check cuts the words' layout, the writer, the writes made from it and bind_descriptors out of the source and runs them
against a stand-in driver that records each call.
python -I -B tests/test_push_state.py --headers <Vulkan-Headers include> [--cxx g++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}", "--headers", "{vulkan_headers}"]

ROOT = Path(__file__).resolve().parents[1]


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


FIXTURE = r'''#define VK_NO_PROTOTYPES
#include <vulkan/vulkan.h>
#include <array>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <exception>
#include <string>
#include <vector>
#define CHECK(x) do { if (!(x)) { std::fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); std::exit(1); } } while (0)
namespace fx {   // (the stand-ins: getenv here is not the C library's)
#define FINE_SCOPE(x) (void)0
#define FINE_N(x, n) (void)0
bool g_fine = false;
enum { FC_PUSH_FULL, FC_PUSH_WRITES, FC_PUSH_DESCS, FC_PUSH_DELTA, FC_POOL_SETS, FC_POOL_DESCS, FC_PUSH_TEMPLATE, FC_PUSH_NONE };
int64_t fine_n[8]{};
void logf(const char*, ...) {}
struct Program {
    uint64_t key = 0; bool push = true; VkPipelineLayout layout{}; VkDescriptorSetLayout set_layout{};
    std::vector<VkDescriptorType> binding_types; std::vector<uint32_t> binding_words;
};
@WRITER@
DescWriter writer;
DescWriter& dw() { return writer; }
bool with_template = true;
const VkDescriptorUpdateTemplate kTemplate = reinterpret_cast<VkDescriptorUpdateTemplate>(uintptr_t(30));
VkDescriptorUpdateTemplate desc_template(const Program&, VkPipelineBindPoint) { return with_template ? kTemplate : VK_NULL_HANDLE; }
struct Device { VkDevice device{}; } dev;
struct Recording { VkDescriptorPool pool = reinterpret_cast<VkDescriptorPool>(uintptr_t(11)); std::vector<VkDescriptorPool> extra; } recording;
Recording* cur = &recording;
VkDescriptorPool make_pool() { return VK_NULL_HANDLE; }
// (the stand-in driver: what each call was given)
struct Call { std::string what; const void* data = nullptr; std::vector<VkWriteDescriptorSet> writes; VkDescriptorSet set{}; };
std::vector<Call> calls;
void vkCmdPushDescriptorSetKHR(VkCommandBuffer, VkPipelineBindPoint, VkPipelineLayout, uint32_t set, uint32_t n, const VkWriteDescriptorSet* w) {
    CHECK(set == 0);
    calls.push_back({"push", nullptr, std::vector<VkWriteDescriptorSet>(w, w + n)});
}
void vkCmdPushDescriptorSetWithTemplateKHR(VkCommandBuffer, VkDescriptorUpdateTemplate t, VkPipelineLayout, uint32_t set, const void* data) {
    CHECK(t == kTemplate && set == 0);
    calls.push_back({"template", data});
}
VkResult vkAllocateDescriptorSets(VkDevice, const VkDescriptorSetAllocateInfo* ai, VkDescriptorSet* out) {
    CHECK(ai->descriptorSetCount == 1);
    *out = reinterpret_cast<VkDescriptorSet>(uintptr_t(12));
    return VK_SUCCESS;
}
void vkDestroyDescriptorPool(VkDevice, VkDescriptorPool, const VkAllocationCallbacks*) {}
void vkUpdateDescriptorSetWithTemplate(VkDevice, VkDescriptorSet set, VkDescriptorUpdateTemplate t, const void* data) {
    CHECK(t == kTemplate);
    calls.push_back({"update template", data, {}, set});
}
void vkUpdateDescriptorSets(VkDevice, uint32_t n, const VkWriteDescriptorSet* w, uint32_t, const VkCopyDescriptorSet*) {
    calls.push_back({"update", nullptr, std::vector<VkWriteDescriptorSet>(w, w + n)});
}
void vkCmdBindDescriptorSets(VkCommandBuffer, VkPipelineBindPoint, VkPipelineLayout, uint32_t, uint32_t, const VkDescriptorSet* s,
                             uint32_t, const uint32_t*) {
    calls.push_back({"bind", nullptr, {}, *s});
}
const char* getenv(const char*) { return nullptr; }
bool env_on(const char*) { return false; }
@PUSHED@;
std::array<Pushed, 2>& pushed() { static std::array<Pushed, 2> p; return p; }
@BIND@

template <class T> T h(uintptr_t v) { return reinterpret_cast<T>(v); }
}  // namespace fx
int main() {
    using namespace fx;
    // (the words lie as the driver's structs: a write's arrays point into them)
    static_assert(sizeof(VkDescriptorBufferInfo) == 24 && sizeof(VkDescriptorImageInfo) == 24 && sizeof(VkBufferView) == 8);
    Program p;
    p.layout = h<VkPipelineLayout>(20);
    p.binding_types = {VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER, VK_DESCRIPTOR_TYPE_STORAGE_TEXEL_BUFFER,
                       VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE};
    p.binding_words = {0, 6, 7, 13, 16};   // (2 buffers, 1 view, 2 textures, 1 image)
    CHECK(desc_words(VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER) == 3 && desc_words(VK_DESCRIPTOR_TYPE_UNIFORM_TEXEL_BUFFER) == 1 &&
          desc_words(VK_DESCRIPTOR_TYPE_STORAGE_TEXEL_BUFFER) == 1 && desc_words(VK_DESCRIPTOR_TYPE_STORAGE_IMAGE) == 3);
    DescWriter& w = dw();
    auto build = [&](uintptr_t view0, uintptr_t view1, uintptr_t texel, uintptr_t range) {
        w.reset(), w.prog = &p;
        w.put_buffer({h<VkBuffer>(1), 0x100, range}), w.put_buffer({h<VkBuffer>(2), 0x200, 0x40});
        w.put_view(h<VkBufferView>(texel));
        w.put_image(h<VkSampler>(5), h<VkImageView>(view0)), w.put_image(h<VkSampler>(6), h<VkImageView>(view1));
        w.put_image(VK_NULL_HANDLE, h<VkImageView>(9));
    };
    build(7, 8, 3, 0x80);
    CHECK(desc_whole(p, w) && w.data.size() == 16);
    // (the writes made from the words: the driver's structs, over the same memory)
    const VkWriteDescriptorSet t = desc_write(p, w, 2);
    CHECK(t.dstBinding == 2 && t.descriptorCount == 2 && t.descriptorType == VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER);
    CHECK(t.pImageInfo && !t.pBufferInfo && !t.pTexelBufferView);
    CHECK(t.pImageInfo[1].sampler == h<VkSampler>(6) && t.pImageInfo[1].imageView == h<VkImageView>(8) &&
          t.pImageInfo[1].imageLayout == VK_IMAGE_LAYOUT_GENERAL);
    const VkWriteDescriptorSet u = desc_write(p, w, 0);
    CHECK(u.descriptorCount == 2 && u.pBufferInfo && u.pBufferInfo[0].range == 0x80 && u.pBufferInfo[1].buffer == h<VkBuffer>(2) &&
          u.pBufferInfo[1].offset == 0x200);
    const VkWriteDescriptorSet v = desc_write(p, w, 1);
    CHECK(v.descriptorCount == 1 && v.pTexelBufferView && v.pTexelBufferView[0] == h<VkBufferView>(3));
    const VkWriteDescriptorSet s = desc_write(p, w, 3);
    CHECK(s.descriptorCount == 1 && s.pImageInfo[0].imageView == h<VkImageView>(9) && !s.pImageInfo[0].sampler);
    // (the images in build order, across bindings: what the upscale stand-ins read)
    CHECK(desc_image(w, 0)->imageView == h<VkImageView>(7) && desc_image(w, 1)->imageView == h<VkImageView>(8) &&
          desc_image(w, 2)->imageView == h<VkImageView>(9) && !desc_image(w, 3));
    VkImageView in{}, out{};
    CHECK(desc_stand_in_views(2, &in, &out) && in == h<VkImageView>(7) && out == h<VkImageView>(9));

    const VkCommandBuffer cmd = h<VkCommandBuffer>(21), cmd2 = h<VkCommandBuffer>(22);
    const VkPipelineBindPoint gfx = VK_PIPELINE_BIND_POINT_GRAPHICS;
    // 1. the first bind in a command buffer: the whole set through the template, the words remembered
    CHECK(bind_descriptors(cmd, gfx, p));
    CHECK(calls.size() == 1 && calls[0].what == "template" && calls[0].data == w.data.data());
    CHECK(pushed()[0].words == w.data && pushed()[0].cmd == cmd && pushed()[0].layout == p.layout);
    // 2. the same again: nothing
    calls.clear();
    build(7, 8, 3, 0x80);
    CHECK(bind_descriptors(cmd, gfx, p) && calls.empty());
    // 3. one binding of four changed (a texture's view): that binding alone, as a write into the words
    build(7, 18, 3, 0x80);
    CHECK(bind_descriptors(cmd, gfx, p));
    CHECK(calls.size() == 1 && calls[0].what == "push" && calls[0].writes.size() == 1);
    CHECK(calls[0].writes[0].dstBinding == 2 && calls[0].writes[0].descriptorCount == 2 &&
          calls[0].writes[0].pImageInfo == reinterpret_cast<const VkDescriptorImageInfo*>(w.data.data() + 7));
    CHECK(pushed()[0].words == w.data);
    // 4. two of four (half): still the changed ones alone
    calls.clear();
    build(7, 8, 4, 0x80);
    CHECK(bind_descriptors(cmd, gfx, p) && calls.size() == 1 && calls[0].what == "push" && calls[0].writes.size() == 2);
    CHECK(calls[0].writes[0].dstBinding == 1 && calls[0].writes[1].dstBinding == 2 && pushed()[0].words == w.data);
    // 5. three of four: the whole set through the template
    calls.clear();
    build(17, 8, 3, 0x90);
    CHECK(bind_descriptors(cmd, gfx, p) && calls.size() == 1 && calls[0].what == "template" && pushed()[0].words == w.data);
    // 6. another command buffer: the whole set again, whatever is the same
    calls.clear();
    CHECK(bind_descriptors(cmd2, gfx, p) && calls.size() == 1 && calls[0].what == "template");
    // 7. the compute bind point keeps its own: a whole push there, and the graphics one's left as it was
    calls.clear();
    CHECK(bind_descriptors(cmd2, VK_PIPELINE_BIND_POINT_COMPUTE, p) && calls.size() == 1 && calls[0].what == "template");
    CHECK(pushed()[0].cmd == cmd2 && pushed()[1].cmd == cmd2);
    // 8. no template: every binding a write at a full push, the changed ones after
    with_template = false;
    calls.clear();
    CHECK(bind_descriptors(cmd, gfx, p) && calls.size() == 1 && calls[0].what == "push" && calls[0].writes.size() == 4);
    for (uint32_t b = 0; b < 4; b++) CHECK(calls[0].writes[b].dstBinding == b);
    CHECK(calls[0].writes[1].pTexelBufferView == reinterpret_cast<const VkBufferView*>(w.data.data() + 6));
    calls.clear();
    build(27, 8, 5, 0x10);   // (three of four changed, and no template: the three as writes)
    CHECK(bind_descriptors(cmd, gfx, p) && calls.size() == 1 && calls[0].what == "push" && calls[0].writes.size() == 3);
    // 9. a sampler missing: nothing pushed, what was pushed kept
    const std::vector<uint64_t> before = pushed()[0].words;
    calls.clear();
    w.data[10] = 0;   // (binding 2's second sampler)
    CHECK(!bind_descriptors(cmd, gfx, p) && calls.empty() && pushed()[0].words == before);
    // 10. words that are not this layout's: left out
    build(27, 8, 5, 0x10);
    w.data.pop_back();
    CHECK(!desc_whole(p, w) && !bind_descriptors(cmd, gfx, p) && calls.empty() && !desc_image(w, 0));
    // 11. a pooled set (over the push limit): written through the template, then bound; without one, by writes into the set
    p.push = false;
    with_template = true;
    build(7, 8, 3, 0x80);
    CHECK(bind_descriptors(cmd, gfx, p) && calls.size() == 2 && calls[0].what == "update template" &&
          calls[0].data == w.data.data() && calls[1].what == "bind" && calls[0].set == calls[1].set);
    CHECK(!pushed()[0].cmd);   // (a set bound: the next push is whole)
    with_template = false;
    calls.clear();
    CHECK(bind_descriptors(cmd, gfx, p) && calls.size() == 2 && calls[0].what == "update" && calls[0].writes.size() == 4 &&
          calls[0].writes[3].dstSet == h<VkDescriptorSet>(12) && calls[1].what == "bind");
    std::printf("PASS: descriptors built as words, pushed through the template, changed bindings alone\n");
}
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="g++")
    p.add_argument("--headers", type=Path, required=True)
    a = p.parse_args()
    source = (ROOT / "gpu" / "vk" / "vk_draw.cpp").read_text(encoding="utf-8")
    writer = block(source, "constexpr uint32_t desc_words(") + "\n" + block(source, "struct DescWriter {") + ";"
    bind = block(source, "bool bind_descriptors(")
    for needle, why in (
        ("std::memcmp(ps.words.data(), wr.data.data(), bytes)", "the same words are not found with one comparison"),
        ("vkCmdPushDescriptorSetWithTemplateKHR(cmd, tmpl, p.layout, 0, wr.data.data())", "a whole push is not through the template"),
        ("vkUpdateDescriptorSetWithTemplate(dev.device, set, tmpl, wr.data.data())", "a pooled set is not written through the template"),
        ('getenv("RX_VK_DESC_DELTA")', "the delta's switch is gone"),
    ):
        if needle not in bind:
            raise SystemExit("bind_descriptors: " + why + " (not found: " + needle + ")")
    templ = block(source, "VkDescriptorUpdateTemplate desc_template(const Program& p, VkPipelineBindPoint bp) {")
    for needle, why in (
        ("rec::template_bytes_note(t, (size_t)p.binding_words.back() * 8)", "the recorder is not told the template's data size"),
        ('getenv("RX_VK_DESC_TEMPLATE")', "the template has no off switch"),
        ("VK_DESCRIPTOR_UPDATE_TEMPLATE_TYPE_PUSH_DESCRIPTORS_KHR", "no push template"),
        ("(size_t)p.binding_words[b] * 8, (size_t)per * 8", "the template's entries do not read the words' layout"),
    ):
        if needle not in templ:
            raise SystemExit("desc_template: " + why + " (not found: " + needle + ")")
    helpers = "\n".join(block(source, m) for m in (
        "VkWriteDescriptorSet desc_write(const Program& p, const DescWriter& w, uint32_t b) {", "void desc_writes(",
        "bool desc_whole(const Program& p, const DescWriter& w) {", "const VkDescriptorImageInfo* desc_image(",
        "bool desc_stand_in_views("))
    fixture = (FIXTURE.replace("@WRITER@", writer).replace("@PUSHED@", block(source, "struct Pushed {"))
               .replace("@BIND@", helpers + "\n" + bind))
    with tempfile.TemporaryDirectory(prefix="push-state-") as tmp:
        cpp = Path(tmp) / "fixture.cpp"
        exe = Path(tmp) / "fixture.exe"
        cpp.write_text(fixture, encoding="utf-8")
        subprocess.run([a.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-Wno-missing-field-initializers",
                        "-I" + str(a.headers), str(cpp), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True, timeout=20)


if __name__ == "__main__":
    main()
