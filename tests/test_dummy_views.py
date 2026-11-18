"""Without nullDescriptor, a texture or storage image that does not resolve must get a dummy view, never VK_NULL_HANDLE
(VUID-VkWriteDescriptorSet-descriptorType-02997). Runs the real make_dummies against stubbed Vulkan calls."""
import argparse
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}", "--headers", "{vulkan_headers}"]

ROOT = Path(__file__).resolve().parents[1]


def block(source, marker):
    start = source.index(marker)
    at = source.index('{', start) + 1
    depth = 1
    while depth:
        depth += (source[at] == '{') - (source[at] == '}')
        at += 1
    return source[start:at]


FIXTURE = r'''
#include <vulkan/vulkan.h>
#include <cstdio>
#include <cstdlib>
typedef struct VmaAllocation_T* VmaAllocation;
struct { VkDevice device = (VkDevice)1; bool null_descriptor = false; VkPhysicalDeviceFeatures features{}; } dev;
struct Texture;
struct Dummies { Texture* tex[7]{}; VkImageView view[7]{}; } dummies;
thread_local VkCommandBuffer rec_cmd = VK_NULL_HANDLE;
static int images = 0, fail_image = -1, views = 0, cleared = 0;
bool create_image(const VkImageCreateInfo&, VkImage& image, VmaAllocation& mem) {
    if (images++ == fail_image) return false;
    image = (VkImage)(uintptr_t)(0x100 + images), mem = (VmaAllocation)(uintptr_t)(0x200 + images);
    return true;
}
static int destroyed = 0;
void destroy_image(VkImage, VmaAllocation) { destroyed++; }
void logf(const char*, ...) {}
void vkCmdPipelineBarrier2(VkCommandBuffer, const VkDependencyInfo*) {}
void vkCmdClearColorImage(VkCommandBuffer, VkImage, VkImageLayout, const VkClearColorValue*, uint32_t, const VkImageSubresourceRange*) { cleared++; }
VkResult vkCreateImageView(VkDevice, const VkImageViewCreateInfo*, const VkAllocationCallbacks*, VkImageView* v) {
    *v = (VkImageView)(uintptr_t)(0x300 + ++views);
    return VK_SUCCESS;
}
/* DUMMIES */
static void require(bool ok, const char* what) { if (!ok) { std::fprintf(stderr, "FAIL: %s\n", what); std::exit(1); } }
int main(int argc, char** argv) {
    const char* c = argc > 1 ? argv[1] : "made";
    rec_cmd = (VkCommandBuffer)1;
    if (!std::strcmp(c, "made")) {
        dev.features.imageCubeArray = VK_TRUE;
        make_dummies();
        for (int v = 0; v < 7; v++) require(dummies.view[v] != VK_NULL_HANDLE, "every view type has a dummy view");
        require(images == 3 && cleared == 3, "three images made and cleared");
        make_dummies();
        require(images == 3, "made once");
    } else if (!std::strcmp(c, "no-cube-array")) {
        make_dummies();
        require(dummies.view[VK_IMAGE_VIEW_TYPE_CUBE_ARRAY] == VK_NULL_HANDLE, "no cube array view without imageCubeArray");
        require(dummies.view[VK_IMAGE_VIEW_TYPE_2D] != VK_NULL_HANDLE, "2D view made");
    } else if (!std::strcmp(c, "null-descriptor")) {
        dev.null_descriptor = true;
        make_dummies();
        require(images == 0 && dummies.view[1] == VK_NULL_HANDLE, "nothing made with nullDescriptor");
    } else if (!std::strcmp(c, "image-fails")) {
        fail_image = 1;
        make_dummies();
        require(destroyed == 1 && dummies.view[1] == VK_NULL_HANDLE, "the images made are given back");
    }
    return 0;
}
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, default=ROOT)
    p.add_argument('--headers', type=Path, required=True)
    p.add_argument('--cxx', default='g++')
    a = p.parse_args()
    draw = (a.source / 'gpu/vk/vk_draw.cpp').read_text(encoding='utf-8')
    # (a storage image that does not resolve gets the dummy view too, not VK_NULL_HANDLE)
    assert 'if (!view && !dev.null_descriptor) view = VK_NULL_HANDLE;' not in draw, 'storage image written as VK_NULL_HANDLE'
    fixture = FIXTURE.replace('#include <cstdlib>', '#include <cstdlib>\n#include <cstring>\n#include <cstdint>')
    fixture = fixture.replace('/* DUMMIES */', block(draw, 'void make_dummies('))
    with tempfile.TemporaryDirectory(prefix='dummy-views-') as tmp:
        cpp, exe = Path(tmp) / 'fixture.cpp', Path(tmp) / 'fixture.exe'
        cpp.write_text(fixture, encoding='utf-8')
        subprocess.run([a.cxx, '-std=c++20', '-O1', '-Wall', '-Wextra', '-Werror', '-Wno-missing-field-initializers',
                        '-Wno-unused-parameter', '-I' + str(a.headers), str(cpp), '-o', str(exe)], check=True)
        for case in ['made', 'no-cube-array', 'null-descriptor', 'image-fails']:
            subprocess.run([str(exe), case], check=True, timeout=15)


if __name__ == '__main__':
    main()
