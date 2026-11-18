// (hookshot) The GPU's clock on the Steam Deck (vk_gpu_clock.h; why and when: gpu_clock.h).
//
// The device's render node (VK_EXT_physical_device_drm: /dev/dri/renderD<minor>) is opened once more, beside the driver's own
// file, and an amdgpu context is made on it with DRM_IOCTL_AMDGPU_CTX (AMDGPU_CTX_OP_ALLOC_CTX). That context asks for the
// stable power state (AMDGPU_CTX_OP_SET_STABLE_PSTATE), which the driver applies to the whole device. The file stays open
// until the process ends: then the driver frees the context and puts back the level it found (auto), whether the game closed
// or crashed. Nothing is submitted on the context. The level is read from sysfs first (/sys/dev/char/<major>:<minor>/device/
// power_dpm_force_performance_level, readable by every user), so that a level someone chose is left alone. On the Steam Deck
// by default, elsewhere only when RX_VK_GPU_CLOCK asks for it (gpu_clock.h looked_at, choose): there, unset, nothing is
// opened or read.
#include "vk_gpu_clock.h"

#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>

#ifdef __linux__
#include <fcntl.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <unistd.h>
#endif

#include "gpu_clock.h"
#include "vk_internal.h"

namespace mkwvk {

#ifdef __linux__
namespace {

// The amdgpu context ioctl as the kernel's include/uapi/drm/amdgpu_drm.h has it (union drm_amdgpu_ctx, DRM_IOCTL_AMDGPU_CTX),
// written out so that the build needs neither libdrm nor the kernel's headers; tests/test_gpu_clock.py compares it with the
// system's header where there is one
struct CtxIn {
    uint32_t op, flags, ctx_id;
    int32_t priority;
};
union CtxOut {
    struct {
        uint32_t ctx_id, pad;
    } alloc;
    struct {
        uint64_t flags;
        uint32_t hangs, reset_status;
    } state;
    struct {
        uint32_t flags, pad;
    } pstate;
};
union Ctx {
    CtxIn in;
    CtxOut out;
};
static_assert(sizeof(Ctx) == 16, "union drm_amdgpu_ctx is 16 bytes");
constexpr uint32_t kOpAllocCtx = 1;          // (AMDGPU_CTX_OP_ALLOC_CTX)
constexpr uint32_t kOpSetStablePstate = 6;   // (AMDGPU_CTX_OP_SET_STABLE_PSTATE)
// (DRM_IOWR(DRM_COMMAND_BASE + DRM_AMDGPU_CTX, union drm_amdgpu_ctx): DRM_IOCTL_BASE 'd', DRM_COMMAND_BASE 0x40, DRM_AMDGPU_CTX 2)
const unsigned long kIoctlAmdgpuCtx = _IOWR('d', 0x40 + 0x02, Ctx);

bool read_line(const char* path, char* out, size_t n) {
    FILE* f = fopen(path, "r");
    if (!f) return false;
    const bool ok = fgets(out, (int)n, f) != nullptr;
    fclose(f);
    if (ok) out[strcspn(out, "\r\n")] = 0;
    return ok;
}

} // namespace

void gpu_clock_device_created(bool drm) {
    const VkPhysicalDeviceProperties& p = dev.props;
    gpu_clock::Facts f;
    f.amd = p.vendorID == 0x1002;
    f.deck = gpu_clock::steam_deck(p.deviceName, getenv("SteamDeck"), p.deviceType == VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU);
    f.deck_apu = gpu_clock::deck_apu(p.deviceName);
    f.env = getenv("RX_VK_GPU_CLOCK");
    if (!gpu_clock::looked_at(f)) return;   // (no line: not the Deck and not asked, =0, or another vendor, with no such state)
    VkPhysicalDeviceDrmPropertiesEXT node{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DRM_PROPERTIES_EXT};
    if (drm) {
        VkPhysicalDeviceProperties2 p2{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2};
        p2.pNext = &node;
        vkGetPhysicalDeviceProperties2(dev.physical, &p2);
    }
    if (!node.hasRender) {
        logf("vk: GPU clock: the driver's own (the device's render node is not known: no VK_EXT_physical_device_drm)");
        return;
    }
    char path[96], level[48] = "";
    snprintf(path, sizeof path, "/sys/dev/char/%lld:%lld/device/power_dpm_force_performance_level", (long long)node.renderMajor,
             (long long)node.renderMinor);
    f.level = read_line(path, level, sizeof level) ? level : nullptr;
    const gpu_clock::Choice c = gpu_clock::choose(f);
    if (c.pstate == gpu_clock::NONE) {
        logf("vk: GPU clock: the driver's own: %s (the power level: %s)", c.why, f.level ? level : "not read");
        return;
    }
    char node_path[48];
    snprintf(node_path, sizeof node_path, "/dev/dri/renderD%lld", (long long)node.renderMinor);
    const int fd = open(node_path, O_RDWR | O_CLOEXEC);
    struct stat st{};
    if (fd < 0 || fstat(fd, &st) != 0 || !S_ISCHR(st.st_mode) ||
        st.st_rdev != makedev((unsigned)node.renderMajor, (unsigned)node.renderMinor)) {
        logf("vk: GPU clock: the driver's own: %s is not the device's render node (%s)", node_path, fd < 0 ? strerror(errno) : "");
        if (fd >= 0) close(fd);
        return;
    }
    Ctx a{};
    a.in.op = kOpAllocCtx;
    if (ioctl(fd, kIoctlAmdgpuCtx, &a) != 0) {
        logf("vk: GPU clock: the driver's own: no amdgpu context on %s (%s)", node_path, strerror(errno));
        close(fd);
        return;
    }
    const uint32_t id = a.out.alloc.ctx_id;
    a = Ctx{};
    a.in.op = kOpSetStablePstate, a.in.ctx_id = id, a.in.flags = c.pstate;
    if (ioctl(fd, kIoctlAmdgpuCtx, &a) != 0) {
        logf("vk: GPU clock: the driver's own: amdgpu refused the %s power state (%s)", gpu_clock::name(c.pstate), strerror(errno));
        close(fd);   // (the context with it)
        return;
    }
    // (fd stays open, and the context on it, until the process ends: the driver then puts the level back)
    char now[48] = "";
    read_line(path, now, sizeof now);
    logf("vk: GPU clock: amdgpu's %s power state held while the game runs (%s; the power level %s -> %s). RX_VK_GPU_CLOCK=0 "
         "leaves the clocks to the driver", gpu_clock::name(c.pstate), c.why, f.level ? level : "not read", now[0] ? now : "not read");
}

#else
void gpu_clock_device_created(bool) {}
#endif

} // namespace mkwvk
