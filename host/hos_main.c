/* Horizon OS layer, native host: process start and boot.

   What rtld and nn::init::Start do on hardware (see ports/zelda-totk/PORT.md, "How the game starts"), done here:
   map the guest window, load the relocated image (nx_image.py already linked it), make this host thread the
   guest main thread, run every module's DT_INIT in rtld's order (the SDK crt's _init: TLS registration with musl,
   then the module's constructors), then nninitStartup and nnMain.

   Usage: <game>.exe [image.bin] [--romfs <dir>] [--user <dir>] [--trace] [--prepare-shaders] [--compile-shaders all|most]
   Environment: HOS_TRACE=1 (log HLE calls), HOS_MEMORY_MB (memory the game is told it has),
                HOS_NVN_CONTINUE=1 (go on past nvnBootstrapLoader). */
#include "hos.h"
#ifndef HOOKSHOT_ENV_H   /* (env_on: the switches' one rule) */
#include "../gpu/vk/compat/hookshot_env.h"
#endif
#include "hos_paths.h"
#include "game_layout.h"
#include "options_path.h"
#include "hos_wide_size.h"   /* (the widescreen picture's size, shared with the Insert menu) */
#include "../gpu/vk/vk_api.h"
#include "../gpu/vk/oot_cheat_items.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifndef HOOKSHOT_VERSION   /* (nx2/build.py gives it: the release and a fingerprint of the sources, nx2/version.py) */
#define HOOKSHOT_VERSION "unknown"
#endif
const char *hos_version(void) { return HOOKSHOT_VERSION; }   /* (discord_rpc.c's status) */

#if defined(_WIN32) || defined(__EMSCRIPTEN__)
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <mmsystem.h>
#else
#include <windows.h>   /* (linux: host/posix's) */
#include <sys/mman.h>
#ifdef __linux__
#include <sys/prctl.h>
#include <sys/sysinfo.h>
#endif
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/syscall.h>
#endif
#include "hos_atomic_file.h"   /* (the files the saves' move copies, saves-moved.txt and the stand-ins' clean-up: whole or not at all) */
/* (linux) the separator of the paths the executable's folder is joined with */
#ifdef _WIN32
#define SEP 92
#define SEP_S "\\"
#else
#define SEP '/'
#define SEP_S "/"
#endif

/* (hookshot) the map Link is in and his age, as the last map: line, for the performance summary (gpu/vk/perf_report.cpp
   through MkwVkHost perf_info): "" while no save is loaded (before one, and back at the title) */
static SRWLOCK map_lock = SRWLOCK_INIT;
static char map_now[100];
void hos_movie_stats(int64_t out[5]);   /* nn_video.c */
const char *hos_perf_info(char *map, int cap, int64_t movie[5]) {
    AcquireSRWLockShared(&map_lock);
    snprintf(map, (size_t)cap, "%s", map_now);
    ReleaseSRWLockShared(&map_lock);
    hos_movie_stats(movie);
    return HOOKSHOT_VERSION;
}

#ifdef A64_MEM_ZERO
/* web: guest address = wasm address; the guest window is wasm memory below the host's data (-sGLOBAL_BASE) */
extern char __global_base;
uint64_t hos_space_end;
#define GUEST_SPACE (hos_space_end)
#else
#define GUEST_SPACE HOS_GUEST_SPACE
#endif
#define IMAGE_BASE hos_image_base   /* (the lift's: Eden's layout) */

#ifdef _WIN32
static void no_power_throttling(void) {
    const char *e = getenv("HOS_POWER_THROTTLING");
    if (e && atoi(e)) return;
    typedef BOOL(WINAPI * SetInfo)(HANDLE, int, LPVOID, DWORD);
    SetInfo set = (SetInfo)(void *)GetProcAddress(GetModuleHandleA("kernel32.dll"), "SetProcessInformation");
    if (!set) return;
    struct { ULONG version, control, state; } s = {1, 0x1 | 0x4, 0};
    if (!set(GetCurrentProcess(), 4, &s, sizeof s)) {
        s.control = 0x1;
        set(GetCurrentProcess(), 4, &s, sizeof s);
    }
}
#endif

int hos_game_is_mkw(void) { return !strcmp(hos_main_build_id, "d00e4f399e411d0613aa8d26b1c02fef"); }

/* gen/hos_image.c (build.py lift) */
extern const uint64_t hos_main_stack_size;
extern const int hos_main_priority, hos_main_core, hos_module_count;
extern const uint64_t hos_module_init[];
extern const char *const hos_module_name[];
extern const uint64_t hos_entry_nninitStartup, hos_entry_nnMain;
extern const uint64_t hos_entry_init_libc0, hos_entry_init_libc1, hos_entry_init_libc2, hos_entry_nnosInitialize,
    hos_entry_nninitInitializeSdkModule;
/* nn_fs.c */
extern const char *hos_romfs_dir, *hos_user_dir;

/* HOS_LARGE_PAGES=1 (experiment): the guest window in 2 MB pages, for fewer TLB misses (the game touches hundreds of MB
   of scattered heap; 4 KB pages cover only ~12 MB of it in the CPU's TLB). The whole window is then physical memory at
   once (4 GB, locked), and Windows needs the account to hold "Lock pages in memory" (SeLockMemoryPrivilege, Local
   Security Policy > User Rights Assignment; log off and on after): without it this logs why and uses normal pages. */
int hos_large_pages;   /* (hos_mem.c: freed pages are not discarded then) */
#if defined(_WIN32) && !defined(A64_MEM_ZERO)
#pragma comment(lib, "advapi32.lib")   /* (the token privilege calls) */
static void *reserve_large(SIZE_T size) {
    HANDLE token;
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, &token)) return NULL;
    TOKEN_PRIVILEGES tp = {0};
    tp.PrivilegeCount = 1;
    tp.Privileges[0].Attributes = SE_PRIVILEGE_ENABLED;
    const BOOL looked = LookupPrivilegeValueA(NULL, "SeLockMemoryPrivilege", &tp.Privileges[0].Luid);
    const BOOL adjusted = looked && AdjustTokenPrivileges(token, FALSE, &tp, 0, NULL, NULL);
    const DWORD err = GetLastError();
    CloseHandle(token);
    if (!adjusted || err == ERROR_NOT_ALL_ASSIGNED) {
        hos_log("mem: HOS_LARGE_PAGES: this account does not hold SeLockMemoryPrivilege (\"Lock pages in memory\"): "
                "normal pages");
        return NULL;
    }
    const SIZE_T large = GetLargePageMinimum();
    if (!large || size % large) return NULL;
    void *p = VirtualAlloc((void *)A64_HOST_BASE, size, MEM_RESERVE | MEM_COMMIT | MEM_LARGE_PAGES, PAGE_READWRITE);
    if (!p) hos_log("mem: HOS_LARGE_PAGES: %llu MB of large pages not available (error %lu): normal pages",
                    (unsigned long long)(size >> 20), GetLastError());
    return p;
}
#endif

#if !defined(_WIN32) && !defined(A64_MEM_ZERO)
extern int hos_guest_memfd;   /* (below) */
static int startup_stderr = -1;   /* (keep startup warnings visible if stderr becomes hookshot_log.txt) */
#endif
/* The guest window lives at the constant A64_HOST_BASE (rt/a64.h), so lifted code never loads its base. */
static int reserve_guest(void) {
#if defined(A64_MEM_ZERO)
    hos_space_end = (uint64_t)(uintptr_t)&__global_base & ~0xFFFFULL;
    return hos_space_end >= (1ULL << 30);
#elif defined(_WIN32)
    /* Committed but untouched pages cost no physical memory. Not write-watched: lifted stores and host writes mark
       their pages themselves (the soft write watch, rt/a64.h A64_MARK), and the renderer reads those marks. */
    if (env_on("HOS_LARGE_PAGES") && reserve_large(GUEST_SPACE) == (void *)A64_HOST_BASE) {
        hos_large_pages = 1;
        hos_log("mem: the guest window is in large pages (%llu MB)", (unsigned long long)(GUEST_SPACE >> 20));
        return 1;
    }
    /* mkw-recomp: 512 GB reserved, committed as the runtime hands memory out (hos_commit) or on first touch */
    void hos_commit_init(void);
    hos_commit_init();
    return VirtualAlloc((void *)A64_HOST_BASE, GUEST_SPACE, MEM_RESERVE, PAGE_NOACCESS) == (void *)A64_HOST_BASE;
#else
    /* (linux) the whole window readable and writable at once, its pages made as they are first touched (no commit
       step: MAP_NORESERVE). Decommitting is madvise (host/posix/win32_posix.c VirtualFree): the pages read as zero. */
    void hos_commit_init(void);
    hos_commit_init();   /* (the crash report) */
    /* The window is a memfd's, shared, so the Vulkan back end can hand the GPU the game's own pages as a dma-buf
       (udmabuf, gpu/vk/vk_memory.cpp import_dma_buf) instead of a host pointer: amdgpu checks every page of a host-pointer
       import again at each command submission, 15-45 ms a submission in Kokiri Forest. Pages of a shared mapping are freed
       with MADV_REMOVE, not MADV_DONTNEED (hos_posix_guest_discard). HOS_GUEST_MEMFD=0: anonymous memory, as before */
    {
        /* (only where /dev/udmabuf can be opened: a shared mapping's pages cannot be host-pointer imports (RADV:
           VK_ERROR_INVALID_EXTERNAL_HANDLE), so a pool udmabuf refused would be no import at all. A pool larger than udmabuf's
           size_limit_mb (64 MB unless raised) is imported as several dma-bufs bound into one sparse buffer, so no setting is
           needed. HOS_GUEST_MEMFD=1: the memfd all the same) */
        const char *e = getenv("HOS_GUEST_MEMFD");
        int usable = 0;
        {
            const int u = open("/dev/udmabuf", O_RDWR | O_CLOEXEC);
            if (u < 0 && (errno == EACCES || errno == EPERM)) {
                const int err = errno;
                static int warned;
                if (!warned) {
                    warned = 1;
                    const char *warning = "WARNING: /dev/udmabuf permission denied; GPU imports may be slower, especially on AMD/RADV. "
                        "Ask your administrator for access via its device group or a device-specific udev rule "
                        "(see README, On Linux). Do not run the game as root.";
                    if (startup_stderr >= 0) dprintf(startup_stderr, "%s (%s)\n", warning, strerror(err));
                    hos_log("%s (%s)", warning, strerror(err));
                }
            }
            if (startup_stderr >= 0) close(startup_stderr), startup_stderr = -1;
            if (u >= 0) {
                close(u);
                /* (issue 1135) usable whatever size_limit_mb says: the renderer reads the limit itself and takes udmabuf's
                   default, 64 MB, when it can't (gpu/vk/vk_memory.cpp import_dma_buf), and a limit too small only makes more
                   dma-bufs. A Flatpak's or Steam's container shows /dev/udmabuf but not /sys/module */
                FILE *f = fopen("/sys/module/udmabuf/parameters/size_limit_mb", "r");
                if (f)
                    fclose(f);
                else
                    hos_log("mem: udmabuf's size_limit_mb cannot be read (in a container?): its default, 64 MB, assumed");
                usable = 1;
            }
            if (!usable && !e)
                hos_log("mem: guest memory stays host-pointer imports for the GPU (slow submissions on AMD): "
                        "/dev/udmabuf cannot be opened");
        }
        if (e ? atoi(e) != 0 : usable) {
            const int fd = (int)syscall(SYS_memfd_create, "hookshot-guest", 1u /* MFD_CLOEXEC */ | 2u /* MFD_ALLOW_SEALING */);
            if (fd >= 0 && ftruncate(fd, (off_t)GUEST_SPACE) == 0) {
                fcntl(fd, 1033 /* F_ADD_SEALS */, 0x0002 /* F_SEAL_SHRINK */ | 0x0004 /* F_SEAL_GROW */);
                void *p = mmap((void *)A64_HOST_BASE, GUEST_SPACE, PROT_READ | PROT_WRITE,
                               MAP_SHARED | MAP_FIXED_NOREPLACE | MAP_NORESERVE, fd, 0);
                if (p == (void *)A64_HOST_BASE) {
                    hos_guest_memfd = fd;
                    hos_log("mem: the guest window is a memfd's (%d), shared with the GPU as dma-bufs", fd);
                    return 1;
                }
                if (p != MAP_FAILED) munmap(p, GUEST_SPACE);
            }
            if (fd >= 0) close(fd);
            hos_log("mem: no memfd for the guest window (errno %d): anonymous memory", errno);
        }
    }
    if (mmap((void *)A64_HOST_BASE, GUEST_SPACE, PROT_READ | PROT_WRITE,
             MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED_NOREPLACE | MAP_NORESERVE, -1, 0) != (void *)A64_HOST_BASE)
        return 0;
    /* (issue 312) no transparent huge pages in the guest window: the renderer imports its pools as userptr memory, and every
       collapse khugepaged makes in them changes their mappings, which the kernel answers by pinning the pages again at the
       next submission: ~250 ms a submit on RADV while the GPU sat idle. HOS_THP=1: as before */
    if (!env_on("HOS_THP")) madvise((void *)A64_HOST_BASE, GUEST_SPACE, MADV_NOHUGEPAGE);
#ifdef __linux__
    /* (HOS_NO_THP=1, experiment: none outside the window either. With THP "always" 400-450 MB of the host heap's and the binary's bss are huge
       pages, each resident whole when any of its 2 MB is touched) */
    if (env_on("HOS_NO_THP")) prctl(PR_SET_THP_DISABLE, 1, 0, 0, 0);
#endif
    return 1;
#endif
}

#if !defined(_WIN32) && !defined(A64_MEM_ZERO)
/* the guest window's memfd for the Vulkan back end (-1: anonymous memory), and freeing guest pages so that
   they read as zero again on either kind of mapping */
int hos_guest_memfd = -1;
int hos_posix_guest_memfd(void) { return hos_guest_memfd; }
int hos_posix_guest_discard(void *p, size_t n) {
    return madvise(p, n, hos_guest_memfd >= 0 ? MADV_REMOVE : MADV_DONTNEED);
}
#endif

/* The guest window, for the renderer (MkwVkHost.guest_base and guest_size, host/rx_backend.c). */
uint8_t *hos_guest_base(void) { return A64_MEM; }
uint64_t hos_guest_size(void) { return GUEST_SPACE; }

/* Call guest code at `addr` as a fresh call from the top of the main thread's stack, with whatever arguments the
   caller put in x0-x7 (call_guest clears x0 and x1 first; call_guest_args keeps them). */
static void call_guest_args(Ctx *c, uint64_t addr, uint64_t sp, const char *what) {
    A64Fn f = a64_lookup(addr);
    if (!addr || !f) hos_fatal(c, "%s: no function at %#llx", what, (unsigned long long)addr);
    hos_log("boot: %s (%#llx)", what, (unsigned long long)addr);
    c->x[30] = 0;
    c->x[31] = sp;
    void hos_mem_checkpoint(const char *what);
    hos_mem_checkpoint(what);
    f(c);
}
static void call_guest(Ctx *c, uint64_t addr, uint64_t sp, const char *what) {
    c->x[0] = c->x[1] = 0;
    call_guest_args(c, addr, sp, what);
}

#ifndef _WIN32
/* (linux) Saves live in $XDG_DATA_HOME/hookshot (~/.local/share/hookshot), so a rebuilt game folder still finds them.
   A user/ folder beside the executable from before is moved there the first time, entry by entry. Anything that
   cannot be moved keeps the old place. --user still wins.
   A symbolic link in it, to saves the player keeps elsewhere (a synced folder, another drive), is made again in the
   new place, to the same folder, and never entered. It was moved as it stood, and one written from where it stood
   ("../../saves") then named nothing; from another drive it was copied as the folder it names and delete_tree emptied
   that folder, which is not Hookshot's: the next start found the link still here, kept the old place, and showed no
   saves. A user/ that is a link itself is the player's choice of place, and is used as it is. */
static int is_dir(const char *p) {
    const DWORD a = GetFileAttributesA(p);
    return a != INVALID_FILE_ATTRIBUTES && (a & FILE_ATTRIBUTE_DIRECTORY);
}
static int is_link(const char *p) {
    struct stat st;
    return lstat(p, &st) == 0 && S_ISLNK(st.st_mode);
}
static const char *move_old, *move_from, *move_new;   /* (the user folder on the move, as realpath names it and as given, and the new place) */
static int moved_to(char *target, const char *dir) {   /* (a target under dir: named where it will be) */
    char there[MAX_PATH];
    const size_t n = dir && dir[0] == SEP ? strlen(dir) : 0;
    if (!n || strncmp(target, dir, n) || target[n] != SEP) return 0;
    snprintf(there, sizeof there, "%s%s", move_new, target + n);
    snprintf(target, MAX_PATH, "%s", there);
    return 1;
}
static int copy_link(const char *from, const char *to) {   /* (to what it names, in full; one that names nothing: as written) */
    char target[MAX_PATH];
    if (!realpath(from, target)) {
        const ssize_t n = readlink(from, target, sizeof target - 1);
        if (n < 0) return 0;
        target[n] = 0;
    }
    /* (to an entry that moves too: where it will be. One whose entry went first names nothing by now, so its text is
       checked too: else it named the old place, and only when the folder listed it before the entry) */
    if (!moved_to(target, move_old)) moved_to(target, move_from);
    return symlink(target, to) == 0;
}
static int has_link(const char *p) {
    if (is_link(p)) return 1;
    if (!is_dir(p)) return 0;
    char pattern[MAX_PATH];
    snprintf(pattern, sizeof pattern, "%s" SEP_S "*", p);
    WIN32_FIND_DATAA fd;
    HANDLE h = FindFirstFileA(pattern, &fd);
    int found = 0;
    if (h != INVALID_HANDLE_VALUE) {
        do {
            if (!strcmp(fd.cFileName, ".") || !strcmp(fd.cFileName, "..")) continue;
            char a[MAX_PATH];
            snprintf(a, sizeof a, "%s" SEP_S "%s", p, fd.cFileName);
            found = has_link(a);
        } while (!found && FindNextFileA(h, &fd));
        FindClose(h);
    }
    return found;
}
static int copy_tree(const char *from, const char *to) {
    if (is_link(from)) return copy_link(from, to);
    if (!is_dir(from)) {
        return hos_atomic_copy_file(from, to);   /* (each file whole under its name, or not there) */
    }
    if (!CreateDirectoryA(to, NULL) && !is_dir(to)) return 0;
    char pattern[MAX_PATH];
    snprintf(pattern, sizeof pattern, "%s" SEP_S "*", from);
    WIN32_FIND_DATAA fd;
    HANDLE h = FindFirstFileA(pattern, &fd);
    int ok = 1;
    if (h != INVALID_HANDLE_VALUE) {
        do {
            if (!strcmp(fd.cFileName, ".") || !strcmp(fd.cFileName, "..")) continue;
            char a[MAX_PATH], b[MAX_PATH];
            snprintf(a, sizeof a, "%s" SEP_S "%s", from, fd.cFileName);
            snprintf(b, sizeof b, "%s" SEP_S "%s", to, fd.cFileName);
            ok = copy_tree(a, b);
        } while (ok && FindNextFileA(h, &fd));
        FindClose(h);
    }
    return ok;
}
static void delete_tree(const char *p) {
    if (!is_dir(p) || is_link(p)) {   /* (a link goes; what it names stays) */
        DeleteFileA(p);
        return;
    }
    char pattern[MAX_PATH];
    snprintf(pattern, sizeof pattern, "%s" SEP_S "*", p);
    WIN32_FIND_DATAA fd;
    HANDLE h = FindFirstFileA(pattern, &fd);
    if (h != INVALID_HANDLE_VALUE) {
        do {
            if (!strcmp(fd.cFileName, ".") || !strcmp(fd.cFileName, "..")) continue;
            char a[MAX_PATH];
            snprintf(a, sizeof a, "%s" SEP_S "%s", p, fd.cFileName);
            delete_tree(a);
        } while (FindNextFileA(h, &fd));
        FindClose(h);
    }
    RemoveDirectoryA(p);
}
static const char *saves_dir(const char *beside) {
    static char dir[MAX_PATH];
    const char *xdg = getenv("XDG_DATA_HOME"), *home = getenv("HOME");
    if (is_link(beside)) return beside;
    if (xdg && xdg[0] == '/') snprintf(dir, sizeof dir, "%s", xdg);
    else if (home && home[0] == '/') {
        snprintf(dir, sizeof dir, "%s/.local", home);
        CreateDirectoryA(dir, NULL);
        snprintf(dir, sizeof dir, "%s/.local/share", home);
    } else return beside;
    CreateDirectoryA(dir, NULL);
    snprintf(dir + strlen(dir), sizeof dir - strlen(dir), "/hookshot");
    CreateDirectoryA(dir, NULL);
    if (GetFileAttributesA(dir) == INVALID_FILE_ATTRIBUTES) return beside;
    char pattern[MAX_PATH];
    snprintf(pattern, sizeof pattern, "%s" SEP_S "*", beside);
    int moved = 0, kept = 0;
    char real[MAX_PATH];
    move_old = realpath(beside, real), move_from = beside, move_new = dir;
    /* (looked at first, then moved: with an entry the new place has already, the old place is kept, and it keeps them all.
       The others used to go all the same, and the game then ran here without them. So does one that cannot go, a copy that
       fails (a full disk): the entries that went before it come back, and a copied one's old place goes only once all are
       there. They used to stay in the new place, and the next start found them there and kept the old place without them) */
    struct { char *name; int copied; } *went = NULL;
    size_t n_went = 0;
    for (int move = 0; move < 2 && !kept; move++) {
        WIN32_FIND_DATAA fd;
        HANDLE h = FindFirstFileA(pattern, &fd);
        if (h == INVALID_HANDLE_VALUE) return dir;
        do {
            if (!strcmp(fd.cFileName, ".") || !strcmp(fd.cFileName, "..") || (move && kept)) continue;
            char from[MAX_PATH], to[MAX_PATH];
            snprintf(from, sizeof from, "%s" SEP_S "%s", beside, fd.cFileName);
            snprintf(to, sizeof to, "%s" SEP_S "%s", dir, fd.cFileName);
            if (!move) {
                kept += GetFileAttributesA(to) != INVALID_FILE_ATTRIBUTES;
                continue;
            }
            void *more = realloc(went, (n_went + 1) * sizeof *went);
            char *name = more ? _strdup(fd.cFileName) : NULL;
            if (more) went = more;
            if (!name) kept++;
            else if (!has_link(from) && MoveFileExA(from, to, 0)) went[n_went].name = name, went[n_went++].copied = 0;
            else if (copy_tree(from, to)) went[n_went].name = name, went[n_went++].copied = 1;
            else delete_tree(to), free(name), kept++;
        } while (FindNextFileA(h, &fd));
        FindClose(h);
    }
    for (size_t i = 0; i < n_went; i++) {
        char from[MAX_PATH], to[MAX_PATH];
        snprintf(from, sizeof from, "%s" SEP_S "%s", beside, went[i].name);
        snprintf(to, sizeof to, "%s" SEP_S "%s", dir, went[i].name);
        if (!kept) {
            moved++;
            if (went[i].copied) delete_tree(from);
        } else if (went[i].copied) delete_tree(to);
        else if (!MoveFileExA(to, from, 0)) hos_log("saves: %s could not come back to %s", to, from);
        free(went[i].name);
    }
    free(went);
    if (kept) {
        hos_log("saves: %d of %s's entries could not go to %s: the saves stay in %s", kept, beside, dir, beside);
        return beside;
    }
    RemoveDirectoryA(beside);
    if (moved) {
        char note[MAX_PATH];
        const char *sep = strrchr(beside, SEP);
        snprintf(note, sizeof note, "%.*s" SEP_S "saves-moved.txt", sep ? (int)(sep - beside) : 0, beside);
        char text[MAX_PATH + 160];
        const int n = snprintf(text, sizeof text, "Mako's saves are now in\n%s\n\nThey moved there from the user folder that was here.\n", dir);
        if (n > 0 && (size_t)n < sizeof text) hos_atomic_write(note, text, (size_t)n);
        hos_log("saves: moved from %s to %s", beside, dir);
    }
    return dir;
}
#endif

#ifdef _WIN32
/* (sharkiix version) "SAVE FOLDER" beside the game: a save dropped there (from Eden, Lichii, Ryujinx, a Switch, another
   Hookshot: the folder holding slot_00, slot_01 ... and account.sav, or a folder above it, at any depth) is copied into
   the game's saves at the start. The saves there before are kept in SAVE FOLDER\_backup <date>, what was imported goes to
   SAVE FOLDER\_imported <date>, and a message says so. option.sav (the game's settings) is not taken.
   HOS_NO_SAVE_FOLDER=1: off */
static int sf_is_dir(const char *p) {
    const DWORD a = GetFileAttributesA(p);
    return a != INVALID_FILE_ATTRIBUTES && (a & FILE_ATTRIBUTE_DIRECTORY);
}
static int sf_copy(const char *from, const char *to) {
    if (!sf_is_dir(from)) return CopyFileA(from, to, FALSE) != 0;
    if (!CreateDirectoryA(to, NULL) && !sf_is_dir(to)) return 0;
    char pattern[MAX_PATH];
    snprintf(pattern, sizeof pattern, "%s\\*", from);
    WIN32_FIND_DATAA fd;
    HANDLE h = FindFirstFileA(pattern, &fd);
    int ok = 1;
    if (h != INVALID_HANDLE_VALUE) {
        do {
            if (!strcmp(fd.cFileName, ".") || !strcmp(fd.cFileName, "..")) continue;
            char a[MAX_PATH], b[MAX_PATH];
            snprintf(a, sizeof a, "%s\\%s", from, fd.cFileName);
            snprintf(b, sizeof b, "%s\\%s", to, fd.cFileName);
            ok = sf_copy(a, b);
        } while (ok && FindNextFileA(h, &fd));
        FindClose(h);
    }
    return ok;
}
/* a folder holding slot_XX folders with a progress.sav in them */
const char *hos_save_dir(void);   /* (Mako) master_quest.c: "save", or "save_mq" in Master Quest */
static int sf_is_save_root(const char *dir) {
    char pattern[MAX_PATH];
    snprintf(pattern, sizeof pattern, "%s\\slot_*", dir);
    WIN32_FIND_DATAA fd;
    HANDLE h = FindFirstFileA(pattern, &fd);
    int found = 0;
    if (h == INVALID_HANDLE_VALUE) return 0;
    do {
        char p[MAX_PATH];
        snprintf(p, sizeof p, "%s\\%s\\progress.sav", dir, fd.cFileName);
        if ((fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) && GetFileAttributesA(p) != INVALID_FILE_ATTRIBUTES) found = 1;
    } while (!found && FindNextFileA(h, &fd));
    FindClose(h);
    return found;
}
static int sf_find(const char *dir, char *out, int depth, int top) {
    if (sf_is_save_root(dir)) {
        snprintf(out, MAX_PATH, "%s", dir);
        return 1;
    }
    if (depth <= 0) return 0;
    char pattern[MAX_PATH];
    snprintf(pattern, sizeof pattern, "%s\\*", dir);
    WIN32_FIND_DATAA fd;
    HANDLE h = FindFirstFileA(pattern, &fd);
    if (h == INVALID_HANDLE_VALUE) return 0;
    int found = 0;
    do {
        if (!(fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) || fd.cFileName[0] == '.') continue;
        if (top && fd.cFileName[0] == '_') continue;   /* (_backup, _imported: ours) */
        char sub[MAX_PATH];
        snprintf(sub, sizeof sub, "%s\\%s", dir, fd.cFileName);
        found = sf_find(sub, out, depth - 1, 0);
    } while (!found && FindNextFileA(h, &fd));
    FindClose(h);
    return found;
}
static void save_folder_import(const char *game_dir, const char *user_dir) {
    char sf[MAX_PATH], note[MAX_PATH], root[MAX_PATH];
    snprintf(sf, sizeof sf, "%s\\SAVE FOLDER", game_dir);
    CreateDirectoryA(sf, NULL);
    snprintf(note, sizeof note, "%s\\LISEZ-MOI - READ ME.txt", sf);
    if (GetFileAttributesA(note) == INVALID_FILE_ATTRIBUTES) {
        FILE *f = fopen(note, "w");
        if (f) {
            fprintf(f,
                "=== SAVE FOLDER (Mako) ===\n\n"
                "FRANCAIS\n"
                "Pour jouer avec ta sauvegarde, glisse-la dans ce dossier puis lance le jeu.\n"
                "Ca marche avec une sauvegarde d'Eden, Lichii, Ryujinx, d'une Switch ou d'un autre Hookshot :\n"
                "mets le dossier qui contient slot_00, slot_01... et account.sav (par exemple le dossier\n"
                "0400486024DEC000 d'un emulateur), ou directement son contenu.\n"
                "Au lancement, le jeu l'importe tout seul et affiche un message.\n"
                "Tes anciennes sauvegardes sont gardees dans \"_backup <date>\", rien n'est perdu.\n"
                "Ce que tu as importe est range dans \"_imported <date>\".\n\n"
                "ENGLISH\n"
                "To play with your save, drop it into this folder, then start the game.\n"
                "Works with a save from Eden, Lichii, Ryujinx, a Switch or another Hookshot:\n"
                "put the folder holding slot_00, slot_01... and account.sav (for example an emulator's\n"
                "0400486024DEC000 folder), or just its contents.\n"
                "At start the game imports it by itself and shows a message.\n"
                "Your previous saves are kept in \"_backup <date>\": nothing is lost.\n"
                "What was imported is moved to \"_imported <date>\".\n");
            fclose(f);
        }
    }
    if (!sf_find(sf, root, 6, 1)) return;
    SYSTEMTIME t;
    GetLocalTime(&t);
    char stamp[64], target[MAX_PATH], backup[MAX_PATH], done[MAX_PATH];
    snprintf(stamp, sizeof stamp, "%04d-%02d-%02d %02dh%02d-%02d", t.wYear, t.wMonth, t.wDay, t.wHour, t.wMinute, t.wSecond);
    CreateDirectoryA(user_dir, NULL);
    /* (into the saves this start plays with: the randomizer's own folder while it is on, oot_rando.c) */
    const char *hos_save_folder(void);
    snprintf(target, sizeof target, "%s\\%s", user_dir, hos_save_folder());
    CreateDirectoryA(target, NULL);
    snprintf(target, sizeof target, "%s\\%s\\5a3c9e1f0b7d24680000000000000001", user_dir, hos_save_folder());
    snprintf(backup, sizeof backup, "%s\\_backup %s", sf, stamp);
    if (sf_is_dir(target) && !sf_copy(target, backup)) {
        hos_log("save folder: the saves could not be backed up into %s: nothing imported", backup);
        MessageBoxA(NULL, "SAVE FOLDER: the current saves could not be backed up, so nothing was imported.\n"
                          "SAVE FOLDER : les sauvegardes actuelles n'ont pas pu etre copiees, rien n'a ete importe.",
                    HOS_GAME_TITLE, MB_OK | MB_ICONWARNING | MB_TOPMOST);
        return;
    }
    CreateDirectoryA(target, NULL);
    int slots = 0, ok = 1;
    char pattern[MAX_PATH];
    snprintf(pattern, sizeof pattern, "%s\\*", root);
    WIN32_FIND_DATAA fd;
    HANDLE h = FindFirstFileA(pattern, &fd);
    if (h != INVALID_HANDLE_VALUE) {
        do {
            if (!strcmp(fd.cFileName, ".") || !strcmp(fd.cFileName, "..")) continue;
            const int slot = (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) && !strncmp(fd.cFileName, "slot_", 5);
            if (!slot && _stricmp(fd.cFileName, "account.sav")) continue;   /* (option.sav: the game's own settings stay) */
            char a[MAX_PATH], b[MAX_PATH];
            snprintf(a, sizeof a, "%s\\%s", root, fd.cFileName);
            snprintf(b, sizeof b, "%s\\%s", target, fd.cFileName);
            if (!sf_copy(a, b)) ok = 0;
            else slots += slot;
        } while (FindNextFileA(h, &fd));
        FindClose(h);
    }
    /* what was imported: everything in SAVE FOLDER but ours, moved aside so the next start does not import it again */
    snprintf(done, sizeof done, "%s\\_imported %s", sf, stamp);
    CreateDirectoryA(done, NULL);
    snprintf(pattern, sizeof pattern, "%s\\*", sf);
    h = FindFirstFileA(pattern, &fd);
    if (h != INVALID_HANDLE_VALUE) {
        do {
            if (!strcmp(fd.cFileName, ".") || !strcmp(fd.cFileName, "..") || fd.cFileName[0] == '_' ||
                !_stricmp(fd.cFileName, "LISEZ-MOI - READ ME.txt"))
                continue;
            char a[MAX_PATH], b[MAX_PATH];
            snprintf(a, sizeof a, "%s\\%s", sf, fd.cFileName);
            snprintf(b, sizeof b, "%s\\%s", done, fd.cFileName);
            MoveFileExA(a, b, 0);
        } while (FindNextFileA(h, &fd));
        FindClose(h);
    }
    hos_log("save folder: %d slots imported from %s (%s), the saves before kept in %s", slots, root,
            ok ? "all copied" : "some failed", backup);
    char msg[1600];
    snprintf(msg, sizeof msg,
             "SAVE FOLDER: %d save slot(s) imported%s.\nYour previous saves are kept in:\n%s\n\n"
             "SAVE FOLDER : %d emplacement(s) de sauvegarde importe(s)%s.\nTes anciennes sauvegardes sont gardees dans :\n%s",
             slots, ok ? "" : " (some files failed)", backup, slots, ok ? "" : " (certains fichiers ont echoue)", backup);
    MessageBoxA(NULL, msg, HOS_GAME_TITLE, MB_OK | MB_ICONINFORMATION | MB_TOPMOST | MB_SETFOREGROUND);
}
#endif
/* (hookshot) What a write of a setting that a kill cut left (host/hos_atomic_file.h), at the start, before the game reads any
   setting: a "<name>.hosnew" beside the setting. language.txt is the game folder's; mouse_sens.txt is the user folder's; the
   settings file is where options_path.c chose it (the user folder's with --user, HOS_OPTIONS_FILE's, else the game folder's):
   the options' one-time copy into the user folder leaves its stand-in there. */
static void recover_writes(void) {
    char path[MAX_PATH];
    const DWORD len = hos_game_path_a(path, MAX_PATH);
    char *slash = len ? strrchr(path, SEP) : NULL;
    if (slash) {
        snprintf(slash + 1, (size_t)(path + MAX_PATH - slash - 1), "language.txt");
        hos_atomic_remove_stale(path);
    }
    if (hos_options_file()[0]) hos_atomic_remove_stale(hos_options_file());
    snprintf(path, sizeof path, "%s" SEP_S "mouse_sens.txt", hos_user_dir);
    hos_atomic_remove_stale(path);
}

/* hookshot_env.txt beside the game: NAME=VALUE lines set as environment variables before anything reads them, for the
   switches players are asked to test (RX_VK_NOOPT and the rest). Lines starting with # are notes. On Linux this runs
   before the window, so HOS_HEADLESS and HOS_WINDOW_SIZE are already set when the window is made.
   HOS_ENV_FILE=<path> reads that file instead: a scripted or A/B test run brings its own switches and leaves the
   player's hookshot_env.txt as it is.
   (hookshot) hookshot_env.txt is a file players pass around, so it sets only the game's own switches (RX_, HOS_,
   HOOKSHOT_, EDEN_, NVN_ and SDL_ names), never HOS_ENV_FILE, HOS_CONTROL_PEER_SID or SDL's library override, and no
   value that is a path but RX_VK_DLSS_DIR's: the system's variables (the Vulkan loader's layers, PATH and the like) can
   load code, and the dump switches write files where they name. The file HOS_ENV_FILE names sets anything. */
static int env_line_allowed(const char *name, const char *value) {
    static const char *const prefixes[] = {"RX_", "HOS_", "HOOKSHOT_", "EDEN_", "NVN_", "SDL_"};
    int ok = 0;
    for (size_t i = 0; i < sizeof prefixes / sizeof *prefixes; i++) ok |= !strncmp(name, prefixes[i], strlen(prefixes[i]));
    if (!ok || !strcmp(name, "HOS_ENV_FILE") || !strcmp(name, "SDL_DYNAMIC_API")) return 0;
    /* (hookshot) nor HOS_CONTROL_PEER_SID: it lets one more account into the control bridge's pipe (host/control.c), so a
       shared file would let another user of this PC steer the game and read its memory. The environment still sets it */
    if (!strcmp(name, "HOS_CONTROL_PEER_SID")) return 0;
    /* (hookshot) nor the libraries SDL loads by name (SDL_VULKAN_LIBRARY, SDL_OPENGL_LIBRARY, SDL_VIDEO_GL_DRIVER,
       SDL_VIDEO_EGL_DRIVER...): a bare file name is looked for beside the game and in the current folder on Windows */
    if (!strncmp(name, "SDL_", 4) && (strstr(name, "_LIB") || strstr(name, "GL_DRIVER"))) return 0;
    for (const char *p = name; *p; p++)
        if (!((*p >= 'A' && *p <= 'Z') || (*p >= '0' && *p <= '9') || *p == '_')) return 0;
    /* (hookshot) the switches that name a file to write or a folder take no value here, not even a bare name: one
       resolves in the game's folder (HOS_SAMPLE_FILE=hookshot_vk.dll emptied the renderer) */
    const size_t nl = strlen(name);
    int names_file = (nl > 5 && (!strcmp(name + nl - 5, "_FILE") || !strcmp(name + nl - 4, "_DIR"))) ||
                     !strcmp(name, "RX_VK_FRAME_LOG") || !strcmp(name, "HOS_PRESENT_TRACE");
    /* (hookshot) and the test switches whose value is a file or folder under another name (HOS_AUDIO_DUMP=image.bin
       overwrote the game's image), or that press buttons and menu keys on a timer (a shared file erased a save from
       the file select) */
    static const char *const by_name[] = {
        "HOS_AUDIO_DUMP", "HOS_AUDIO_WB_DUMP", "HOS_SHADER_DUMP", "HOS_FS_OVERLAY", "HOS_MODS", "HOS_INPUT_LIVE",
        "HOS_INPUT_SCRIPT", "HOS_SAMPLE_ALL", "HOS_SLOW_FRAMES", "HOS_CHAIN", "HOS_WATCH", "HOS_CRASH_TEST", "HOOKSHOT_BUILDER_HOME", "RX_VK_SHOTS", "RX_VK_SHOT_GO",
        "RX_VK_FRAMELOG", "RX_VK_HANG_DUMP", "RX_VK_DUMP", "RX_VK_DUMP_SPV", "RX_VK_DUMP_MESH_SPV", "RX_VK_DUMP_STAGES",
        "RX_VK_DUMP_FAILED", "RX_VK_IR", "RX_VK_MENU_SCRIPT"};
    for (size_t i = 0; i < sizeof by_name / sizeof *by_name; i++) names_file |= !strcmp(name, by_name[i]);
    /* RX_VK_DLSS_DIR: a folder on this PC, not a share (\\server\x or //server/x) or a device path */
    if (!strcmp(name, "RX_VK_DLSS_DIR"))
        return !((value[0] == '\\' || value[0] == '/') && (value[1] == '\\' || value[1] == '/'));
    if (names_file) return 0;
    const int drive = ((value[0] | 0x20) >= 'a' && (value[0] | 0x20) <= 'z' && value[1] == ':');
    return !strpbrk(value, "/\\") && !drive && value[0] != '~' && strcmp(value, ".") && strcmp(value, "..");
}
static void load_hookshot_env(void) {
    char path[MAX_PATH + 32];
    const char *other = getenv("HOS_ENV_FILE");
    if (other && *other) {
        snprintf(path, sizeof path, "%s", other);
    } else {
        DWORD n = hos_game_path_a(path, MAX_PATH);
        while (n && path[n - 1] != 92 && path[n - 1] != 47) n--;
        memcpy(path + n, "hookshot_env.txt", 17);
    }
    FILE *f = fopen(path, "r");
    if (!f) return;
    /* The environment the game was started with wins over the file: a switch set for one launch (HOS_FULLSCREEN=0 in a
       shell, a script's RX_VK_PACE=1) beats the same name saved in the file. The file's own later lines still replace its
       earlier ones: the names it set are kept here (for the whole run: a second read sets them again), so they are not taken
       for the environment's */
    static char from_file[256][128];   /* (names of up to 127 characters; a file with more names than this has its later
                                          lines for the names past it taken as the environment's, logged as left out) */
    static int from_file_n;
    char line[512];
    while (fgets(line, sizeof line, f)) {
        char *s = line;
        if ((unsigned char)s[0] == 0xEF && (unsigned char)s[1] == 0xBB && (unsigned char)s[2] == 0xBF) s += 3;   /* (Notepad's BOM) */
        while (*s == ' ' || *s == 9) s++;
        size_t len = strlen(s);
        while (len && (s[len - 1] == 10 || s[len - 1] == 13 || s[len - 1] == ' ' || s[len - 1] == 9)) s[--len] = 0;
        if (!len || *s == '#' || !strchr(s, '=')) continue;
        char *eq = strchr(s, '=');
        *eq = 0;
        if (!(other && *other) && !env_line_allowed(s, eq + 1)) {
            fprintf(stderr, "env: hookshot_env.txt: %s left out (only the game's switches, and no paths, are taken from it)\n", s);
            continue;
        }
        int ours = 0;
        for (int i = 0; i < from_file_n && !ours; i++) ours = !strcmp(from_file[i], s);
        if (!ours && getenv(s)) {
            fprintf(stderr, "env: %s: %s left out (set in the environment, which goes first)\n",
                    other && *other ? "HOS_ENV_FILE" : "hookshot_env.txt", s);
            continue;
        }
        if (!ours && from_file_n < (int)(sizeof from_file / sizeof *from_file) && strlen(s) < sizeof from_file[0])
            strcpy(from_file[from_file_n++], s);
#ifdef _WIN32
        *eq = '=';
        _putenv(s);
#else
        setenv(s, eq + 1, 1);
#endif
    }
    fclose(f);
}

/* Switches this build no longer reads, still set (in the environment or hookshot_env.txt, as older issues told players):
   one log line each, naming what took its place, so a bug report shows the switch did nothing. The host's own: the
   renderer's removed switches (RX_) are the GONE rows of gpu/vk/switches.def, said by its start (switches.h) */
static void removed_switch_notes(void) {
    static const char *const gone[][2] = {
        {"HOS_FIX_RES", NULL},
        {"HOS_RECORD_STUTTERS", "HOS_PROFILE=1 (the profiling mode: docs/development.md#the-profiling-mode)"},
        {"HOS_SCENE_NATIVE", NULL},
        {"TOTK_MINIMAL_LAYOUT", NULL},
    };
    for (size_t i = 0; i < sizeof gone / sizeof *gone; i++)
        if (getenv(gone[i][0])) {
            if (gone[i][1]) hos_log("env: %s is no longer read: use %s", gone[i][0], gone[i][1]);
            else hos_log("env: %s is no longer read: it does nothing", gone[i][0]);
        }
}

int hos_oot_protect_hearts;
/* Trace the request before the save manager queues it. */
int hos_oot_trace_save(Ctx *c) {
    int rx_option(int id, int otherwise);
    const uint64_t caller = c->x[30];
    const uint64_t parent = caller == 0x80bc7764ULL ? recomp_load64(c, c->x[31] + 24) : 0;
    if (env_on("HOS_OOT_TRACE_SAVES")) hos_log("save trace: reason=%u mode=%u caller=%#llx request_site=%#llx", (unsigned)c->x[1], (unsigned)c->x[2],
            (unsigned long long)caller, (unsigned long long)(parent ? parent : caller));
    const unsigned reason = (uint32_t)c->x[1];
    /* A crossing can queue both arrival requests in addition to the transition request. */
    const int transition = (parent == 0x80bc7710ULL && reason == 6) ||
        (parent == 0x80bc7864ULL && reason == 2) ||
        (parent == 0x832a9764ULL && reason == 1);
    if (caller == 0x80bc7764ULL && transition &&
        (uint32_t)c->x[2] == 0 && !rx_option(HOS_OPT_TRANSITION_AUTOSAVE, 1)) {
        if (env_on("HOS_OOT_TRACE_SAVES")) hos_log("save trace: transition autosave suppressed");
        c->x[0] = 0;
        return 1;
    }
    return 0;
}

volatile int hos_oot_live_action;   /* (test runs) the live input file's "!cheat <action>": host/nn_hid.c */

int hos_oot_hearts_enabled(void) {
    int rx_option(int id, int otherwise);
    const int menu = rx_option(HOS_OPT_CHEAT_HEARTS, -1);
    return menu < 0 ? hos_oot_protect_hearts : menu;
}

int hos_oot_is_player(Ctx *c, uint64_t actor) {
    if (recomp_load64(c, actor) != 0x84b6c460ULL) return 0;
    // Other actors share this vtable. The actor's resource record identifies Link.
    const uint64_t resource = recomp_load64(c, actor + 16);
    return resource && recomp_load32(c, resource + 88) == 0x79616c50 &&
           recomp_load16(c, resource + 92) == 0x7265 &&
           recomp_load8(c, resource + 94) == 0;
}

/* Movement speed (the Debug tab's row): Link's character controller and the row's percent, as oot_player_speed saw them on
   his last update (0: none, or 1x) */
static uint64_t oot_speed_controller;
static int oot_speed_percent = 100;

/* A character controller's forward speed being set (nx2/oot_patches.py patch_cct_speed: s0, in metres a second, or a frame when
   per_second is 0): Link's scaled by the row while it is above 1x and the player steers him (a scene's walk, as the one into a
   map, keeps its pace), the physics step moving him by it with its collisions. Only speeds up to 15 m/s (his run is 4.5): a ledge
   climb sets some 55 for a frame, and scaled it threw him past the ledge. Every other controller as it is. */
void hos_oot_cct_speed(Ctx *c, uint64_t controller, int per_second) {
    if (!controller || controller != __atomic_load_n(&oot_speed_controller, __ATOMIC_RELAXED)) return;
    const int percent = __atomic_load_n(&oot_speed_percent, __ATOMIC_RELAXED);
    int hos_move_stick_held(void);   /* host/nn_hid.c */
    if (percent <= 100 || percent > 400 || !hos_move_stick_held()) return;
    float speed;
    memcpy(&speed, &c->vreg[0][0], sizeof speed);
    if (!(fabsf(speed) * (per_second ? 1.0f : 60.0f) <= 15.0f)) return;   /* (and NaN) */
    speed *= percent / 100.0f;
    memcpy(&c->vreg[0][0], &speed, sizeof speed);
}

#if defined(_WIN32) || defined(__linux__)   /* (the debug tools: host/posix has what they call) */
/* OneShotAddOrRemovePouchContent (f_828d4a70) for one pouch content by actor name: delta > 0 adds, < 0 removes.
   Returns the event status (top bits of the result word), or -1 when the pouch is not ready. */
static int oot_pouch_change(Ctx *c, const char *name, int delta) {
    const uint64_t pouch_singleton = recomp_load64(c, 0x84c9e0d0ULL);
    const uint64_t state_singleton = recomp_load64(c, 0x84c9e2a8ULL);
    const uint64_t actor_db = recomp_load64(c, 0x84eb6888ULL);
    const uint64_t actor_info = recomp_load64(c, 0x84e8c060ULL);
    A64Fn edit = a64_lookup(0x828d4a70ULL);
    if (!edit || !pouch_singleton || !recomp_load64(c, pouch_singleton) ||
        !state_singleton || !recomp_load64(c, state_singleton) || !actor_db || !actor_info || !delta ||
        strlen(name) >= 0x60) return -1;

    // OneShotAddOrRemovePouchContent reads the event parameters through pointers.
    const Ctx saved = *c;
    const uint64_t event = (c->x[31] - 0xe0) & ~0xfULL;
    memset(A64_PTR(event), 0, 0xe0);
    memcpy(A64_PTR(event + 0x80), name, strlen(name) + 1);
    recomp_store64_sp(c, event + 0x20, event + 0x60);
    recomp_store64_sp(c, event + 0x30, event + 0x70);
    recomp_store64_sp(c, event + 0x38, event + 0x68);
    recomp_store64_sp(c, event + 0x48, event + 0x74);
    recomp_store64_sp(c, event + 0x50, event + 0x74);
    recomp_store64_sp(c, event + 0x60, event + 0x80);
    recomp_store64_sp(c, event + 0x68, 0x83f0a6d8ULL); // Script
    recomp_store32_sp(c, event + 0x70, (uint32_t)delta);
    c->x[31] = event;
    c->x[0] = event;
    edit(c);
    const int result = (int)(recomp_load32(c, event + 0x18) >> 30);
    *c = saved;
    return result;
}

/* QueryGetPouchContentNumByActorName (f_82a3c260): f_805b63e0(pouch manager, &name, 0, 0) counts one content. */
static int oot_pouch_count(Ctx *c, const char *name) {
    const uint64_t manager = recomp_load64(c, 0x84e98e28ULL);
    A64Fn count = a64_lookup(0x805b63e0ULL);
    if (!manager || !count || strlen(name) >= 0x60) return -1;
    const Ctx saved = *c;
    const uint64_t frame = (c->x[31] - 0x80) & ~0xfULL;
    memcpy(A64_PTR(frame + 0x10), name, strlen(name) + 1);
    recomp_store64_sp(c, frame, frame + 0x10);
    c->x[31] = frame;
    c->x[0] = manager, c->x[1] = frame, c->x[2] = 0, c->x[3] = 0;
    count(c);
    const int n = (int)(int32_t)c->x[0];
    *c = saved;
    return n;
}

static void oot_edit_pouch(Ctx *c, int action) {
    static const char *const items[] = {
        "Item_DekuSeed", "Item_DekuNut", "Item_DekuStick", "Item_Bomb", "Item_Arrow_Normal"
    };
    const unsigned item = (unsigned)(action - 200) / 32;
    const int delta = (action - 200) % 32 - 10;
    if (item >= sizeof items / sizeof items[0] || !delta || delta < -10 || delta > 10) return;
    const int result = oot_pouch_change(c, items[item], delta);
    if (result >= 0) hos_log("cheats: pouch %s %+d (event status %d)", items[item], delta, result);
}

/* The Inventory page (gpu/vk/oot_cheat_items.h): counts go to the menu twice a second, edits come back as actions. */
#define OOT_ITEM_NAME(label, name, kind) name,
#define OOT_ITEM_KIND(label, name, kind) kind,
#define OOT_NO_SECTION(name)
static const char *const oot_item_names[] = {OOT_CHEAT_ITEMS(OOT_NO_SECTION, OOT_ITEM_NAME)};
static const unsigned char oot_item_kinds[] = {OOT_CHEAT_ITEMS(OOT_NO_SECTION, OOT_ITEM_KIND)};
#define OOT_ITEM_COUNT (sizeof oot_item_names / sizeof oot_item_names[0])

static int oot_item_count(Ctx *c, const char *name);
static int oot_gamedata_bool(Ctx *c, uint32_t hash, int *value);
static int oot_gamedata_set_bool(Ctx *c, uint32_t hash, int value);
static int oot_gamedata_string(Ctx *c, uint32_t hash, char *buf, size_t size);

static void oot_family_levels_refresh(Ctx *c);   /* (below: the shelves of a family, hos_oot_shelf_map) */
static void oot_inventory_refresh(Ctx *c, int64_t now) {
    void rx_option_set(int id, int value);
    static int64_t next;
    static int probed;
    if (now < next) return;
    next = now + 500000000LL;
    int loaded = 0;   /* (a save's counts read: the first item's is not -1) */
    for (unsigned i = 0; i < OOT_ITEM_COUNT; i++) {
        const int count = oot_item_count(c, oot_item_names[i]);
        if (!i) loaded = count >= 0;
        rx_option_set(OOT_CHEAT_ITEM_BASE + (int)i, count);
    }
    {   /* Link's age for the Debug tab's Switch age row: 0 child, 1 adult, -1 no save loaded (Sequence_IsChildhood) */
        int child = 1;
        rx_option_set(OOT_CHEAT_AGE_ID, loaded && oot_gamedata_bool(c, 0xcea220d3u, &child) ? (child ? 0 : 1) : -1);
    }
    static char logged[100];
    if (!loaded && logged[0]) {   /* back to the title or the file select: the summary's time there is not the last map's */
        logged[0] = 0;
        AcquireSRWLockExclusive(&map_lock);
        map_now[0] = 0;
        ReleaseSRWLockExclusive(&map_lock);
    }
    if (loaded) {   /* the map Link is in and his age, logged when either changes: where a log's problem happened, the "Where in
                       the game" of the Insert menu's Bug report (gpu/vk/vk_bug_report.cpp reads the last of these lines) */
        char map[80], line[100];
        int child = 1;
        if (oot_gamedata_string(c, 0x1d6189dau, map, sizeof map) && map[0]) {   /* Sequence_CurrentBanc */
            snprintf(line, sizeof line, "%s (%s)", map,
                     oot_gamedata_bool(c, 0xcea220d3u, &child) ? (child ? "child" : "adult") : "age not known");
            if (strcmp(line, logged)) {
                hos_log("map: %s", line), snprintf(logged, sizeof logged, "%s", line);
                AcquireSRWLockExclusive(&map_lock);   /* (the performance summary's map: hos_perf_info) */
                snprintf(map_now, sizeof map_now, "%s", line);
                ReleaseSRWLockExclusive(&map_lock);
            }
        }
    }
    if (loaded) oot_family_levels_refresh(c);
    if (!probed && oot_pouch_count(c, "Item_DekuSeed") >= 0) {
        probed = 1;   /* (each editor value, plus the alternative pouch spellings) */
        static const char *const probes[] = {OOT_CHEAT_ITEM_PROBES};
        const unsigned total = (unsigned)(OOT_ITEM_COUNT + sizeof probes / sizeof probes[0]);
        char line[512];
        size_t used = 0;
        for (unsigned i = 0; i < total; i++) {   /* (several short lines: the log cuts long ones) */
            const char *name = i < OOT_ITEM_COUNT ? oot_item_names[i] : probes[i - OOT_ITEM_COUNT];
            const int count = i < OOT_ITEM_COUNT ? oot_item_count(c, name) : oot_pouch_count(c, name);
            used += (size_t)snprintf(line + used, sizeof line - used, " %s=%d", name, count);
            if (used > 300 || i + 1 == total) hos_log("cheats: inventory probe:%s", line), used = 0;
        }
    }
}

/* Learned songs use saved IsGet.<actor> Bool flags rather than pouch quantities.
   These are their MurmurHash3 x86-32 hashes with seed 0. */
static uint32_t oot_song_flag(const char *name) {
    static const struct { const char *name; uint32_t hash; } songs[] = {
        {"Item_Melody_ZeldaLullaby", 0x01c20002u},
        {"Item_Melody_EponaSong", 0xb492ac33u},
        {"Item_Melody_SariaSong", 0xd3f8bfccu},
        {"Item_Melody_SunSong", 0x165dd1adu},
        {"Item_Melody_TimeSong", 0x03b3450eu},
        {"Item_Melody_StormSong", 0x2b39dd4fu},
        {"Item_Melody_ForestMinuet", 0xdc0a0b54u},
        {"Item_Melody_FireBolero", 0x49041ab9u},
        {"Item_Melody_WaterSerenade", 0x3fa63986u},
        {"Item_Melody_ShadowNocturne", 0xc2fb95f4u},
        {"Item_Melody_SpiritRequiem", 0x802a36a8u},
        {"Item_Melody_LightPrelude", 0xd6320ba4u},
    };
    for (unsigned i = 0; i < sizeof songs / sizeof songs[0]; i++)
        if (!strcmp(name, songs[i].name)) return songs[i].hash;
    return 0;
}

/* Masks share one slot (the Happy Mask Shop lends one at a time). The game takes "Item_Mask_X" when adding one and
   may keep it as "Armor_Child_Mask_X", so both spellings count and a new mask first returns the one held. */
static int oot_mask_alias(const char *name, char *alias, size_t size) {
    if (!strncmp(name, "Armor_Child_Mask_", 17)) return snprintf(alias, size, "Item_Mask_%s", name + 17), 1;
    return 0;
}

static int oot_item_count(Ctx *c, const char *name) {
    const uint32_t song = oot_song_flag(name);
    if (song) {
        int learned = 0;
        return oot_gamedata_bool(c, song, &learned) ? learned : -1;
    }
    char alias[64];
    const int n = oot_pouch_count(c, name);
    if (!oot_mask_alias(name, alias, sizeof alias)) return n;
    const int m = oot_pouch_count(c, alias);
    return n > m ? n : m;
}

/* (the randomizer's fork) What Link carries a counted item in. The game takes none of an item whose holder he has not: a
   Deku Seed added without a Bullet Bag was accepted (event status 2) and the count stayed 0, time after time; the same with
   Deku Nuts (their bag is in no row of the Inventory page) and Deku Sticks. Seen in the log of a game where Unlock worked and
   every amount stayed 0, the bags all 0 in the page's probe line. An amount raised from the page gives the smallest holder
   first when he has none. */
static const char *oot_item_holder(const char *name) {
    static const char *const pairs[][2] = {
        {"Item_DekuStick", "Item_StickBag_Small"}, {"Item_DekuNut", "Item_NutBag_Small"}, {"Item_Bomb", "Item_BombBag_Small"},
        {"Item_Bombchu", "Item_BombBag_Small"}, {"Item_DekuSeed", "Item_BulletBag_Small"}, {"Item_Arrow_Normal", "Item_Quiver_Small"},
    };
    for (unsigned i = 0; i < sizeof pairs / sizeof pairs[0]; i++)
        if (!strcmp(name, pairs[i][0])) return pairs[i][1];
    /* (the randomizer's fork) A song added without an ocarina was accepted and not kept, as a seed without a bag was
       (seen in the log: Item_Melody_ZeldaLullaby +1, had 0, now 0, event status 2, time after time, in a new game).
       Taken to be the same: a song is given the Fairy Ocarina first when Link has neither ocarina. Not seen yet. */
    if (!strncmp(name, "Item_Melody_", 12)) return "Item_Ocarina_Fairy";
    return NULL;
}

static void oot_inventory_edit(Ctx *c, int action) {
    const unsigned item = (unsigned)(action - OOT_CHEAT_ITEM_ACTION) / 256, op = (unsigned)(action - OOT_CHEAT_ITEM_ACTION) % 256;
    if (item >= OOT_ITEM_COUNT) return;
    const char *name = oot_item_names[item];
    const int have = oot_item_count(c, name);
    const uint32_t song = oot_song_flag(name);
    if (song) {
        if (op != 200 || have < 0) return;   /* songs have no editable quantity */
        if (!oot_gamedata_set_bool(c, song, !have)) {
            hos_log("cheats: song %s: learned flag unavailable", name);
            return;
        }
        hos_log("cheats: song %s %s (had %d, now %d)", name, have ? "relocked" : "unlocked", have, oot_item_count(c, name));
        return;
    }
    char alias[64];
    const int is_mask = oot_mask_alias(name, alias, sizeof alias);
    int delta = 0;
    if (op == 200) delta = have > 0 ? -have : 1;   /* unlock / relock */
    else if (op < 128) delta = (int)op - 64;
    if (!delta || have < 0) return;
    if (is_mask && delta > 0) {   /* return whichever mask is in the slot first */
        for (unsigned i = 0; i < OOT_ITEM_COUNT; i++) {
            char other_alias[64];
            if (i == item || !oot_mask_alias(oot_item_names[i], other_alias, sizeof other_alias)) continue;
            const char *spellings[2] = {oot_item_names[i], other_alias};
            for (unsigned k = 0; k < 2; k++) {
                const int held = oot_pouch_count(c, spellings[k]);
                if (held > 0) hos_log("cheats: inventory returned %s (status %d)", spellings[k], oot_pouch_change(c, spellings[k], -held));
            }
        }
        delta = 1;
    }
    {   /* (an amount raised: its holder first, when Link has none of that kind. Any size counts) */
        const char *holder = delta > 0 ? oot_item_holder(name) : NULL;
        if (holder) {
            char other[64];
            int held = oot_pouch_count(c, holder);
            const size_t stem = strlen(holder) - 5;   /* (..._Small: the same name with _Medium and _Large) */
            if (!strcmp(holder, "Item_Ocarina_Fairy")) {   /* (a song's: either ocarina) */
                if (oot_pouch_count(c, "Item_Ocarina_Time") > 0) held = 1;
            } else {
                snprintf(other, sizeof other, "%.*sMedium", (int)stem, holder);
                if (oot_pouch_count(c, other) > 0) held = 1;
                snprintf(other, sizeof other, "%.*sLarge", (int)stem, holder);
                if (oot_pouch_count(c, other) > 0) held = 1;
            }
            if (held == 0) hos_log("cheats: inventory %s first, to carry %s in (event status %d)", holder, name, oot_pouch_change(c, holder, 1));
        }
    }
    int result = -1;
    if (is_mask && delta < 0) {   /* remove under whichever spelling holds it */
        const char *spellings[2] = {name, alias};
        for (unsigned k = 0; k < 2; k++) {
            const int held = oot_pouch_count(c, spellings[k]);
            if (held > 0) result = oot_pouch_change(c, spellings[k], -held);
        }
    } else {
        result = oot_pouch_change(c, is_mask ? alias : name, delta);   /* (masks are added as Item_Mask_X, as the shop does) */
    }
    hos_log("cheats: inventory %s %+d (had %d, now %d, event status %d)", name, delta, have, oot_item_count(c, name), result);
}

static void oot_set_time(Ctx *c, unsigned hour) {
    // ExecuteWmSetTime passes seconds since midnight to the world manager.
    const uint64_t singleton = recomp_load64(c, 0x84c9e898ULL);
    const uint64_t world = singleton ? recomp_load64(c, singleton) : 0;
    A64Fn set_time = a64_lookup(0x834722d0ULL);
    if (!set_time || !world || !recomp_load64(c, world + 0x510)) {
        hos_log("cheats: world clock unavailable");
        return;
    }
    const Ctx saved = *c;
    c->x[0] = world;
    c->x[1] = hour * 3600;
    set_time(c);
    *c = saved;
    hos_log("cheats: requested %02u:00", hour);
}

/* Cross-map teleport (build e0f3ccfa). Map changes in this game only run through an event: an entrance actor
   requests the Dm_SY_BancChangeGo event with NextBanc / NextStartPos / BootEventName arguments, the event calls
   GameSystemActor's ReserveBancChange, and the sequence's ChangeBancOnEvent loads the map when the event ends.
   This builds the same event request (see work/oot-teleport-research.md). The menu labels in gpu/vk/vk_menu.cpp
   (teleport_names) follow this table's order. */
typedef struct {
    const char *child_banc, *child_start, *child_boot;
    const char *adult_banc, *adult_start, *adult_boot;
} OotDestination;
static const OotDestination oot_destinations[] = {   /* (generated: work/oot-teleport-tools/write_destinations.py) */
    {"KokiriForest_Child", "LostWoodBridge_FrontOfHyruleField", "Dm_SY_BancChangeArrive",
     "KokiriForest_Adult", "LostWoodBridge_FrontOfHyruleField", "Dm_SY_BancChangeArrive"},   /* Kokiri Forest */
    {"HyruleField_Child", "HyruleField_FrontOfLostWoodBridge", "Dm_SY_BancChangeArrive",
     "HyruleField_Adult", "HyruleField_FrontOfLostWoodBridge", "Dm_SY_BancChangeArrive"},   /* Hyrule Field */
    {"KakarikoVillage_Child", "KakarikoVillage_Entrance", "Dm_SY_BancChangeArrive_KakarikoVillage_01",
     "KakarikoVillage_Adult", "KakarikoVillage_Entrance", "Dm_SY_BancChangeArrive_KakarikoVillage_01"},   /* Kakariko Village */
    {"Market_Child", "Market_Entrance", "Dm_SY_BancChangeArrive_Market_02",
     "Market_Adult", "Market_Entrance", "Dm_SY_BancChangeArrive_Market_02"},   /* Market */
    {"HyruleCastle", "HyruleCastle_Entrance", "Dm_SY_BancChangeArrive_HyruleCastle_01",
     "GanonCastle", "GanonCastleEntrance", "Dm_SY_BancChangeArrive_GanonCastle_01"},   /* Hyrule Castle */
    {"LostWood_Child", "LostWood_FrontOfSacredForestMeadow", "Dm_SY_BancChangeArrive_LostWood",
     "LostWood_Adult", "LostWood_FrontOfSacredForestMeadow", "Dm_SY_BancChangeArrive_LostWood"},   /* Lost Woods */
    {"SacredForestMeadow_Child", "OutsideOfForestTemple", "Dm_SY_BancChangeArrive_SacredForestMeadow_01",
     "SacredForestMeadow_Adult", "OutsideOfForestTemple", "Dm_SY_BancChangeArrive_SacredForestMeadow_01"},   /* Sacred Forest Meadow */
    {"HyruleField_Child", "LakeHylia_FromGerudoValley", "Dm_SY_BancChangeArrive_LakeHylia_02",
     "HyruleField_Adult", "LakeHylia_FromGerudoValley", "Dm_SY_BancChangeArrive_LakeHylia_02"},   /* Lake Hylia */
    {"Graveyard_Child", "GraveYard_KakarikoSide", "Dm_SY_BancChangeArrive_Graveyard_01",
     "Graveyard_Adult", "GraveYard_KakarikoSide", "Dm_SY_BancChangeArrive_Graveyard_01"},   /* Graveyard */
    {"DeathMountainTrail_Child", "MountainTrail_KakarikoSide", "Dm_SY_BancChangeArrive_DeathMountainTrail_01",
     "DeathMountainTrail_Adult", "MountainTrail_KakarikoSide", "Dm_SY_BancChangeArrive_DeathMountainTrail_01"},   /* Death Mountain Trail */
    {"DeathMountainCrater_Child", "Crater_GoronCitySide", "DeathMountainCrater_Arrive",
     "DeathMountainCrater_Adult", "Crater_GoronCitySide", "DeathMountainCrater_Arrive"},   /* Death Mountain Crater */
    {"GoronCity_Child", "GoronCity_MountainTrailSide", "Dm_SY_BancChangeArrive_GoronCity_01",
     "GoronCity_Adult", "GoronCity_MountainTrailSide", "Dm_SY_BancChangeArrive_GoronCity_01"},   /* Goron City */
    {"ZoraRiver_Child", "ZoraRiver_Entrance", "Dm_SY_BancChangeArrive",
     "ZoraRiver_Adult", "ZoraRiver_Entrance", "Dm_SY_BancChangeArrive"},   /* Zora's River */
    {"ZoraDomain_Child", "ZoraDomain_FromZoraRiver", "Dm_SY_BancChangeArrive",
     "ZoraDomain_Adult", "ZoraDomain_FromZoraRiver", "Dm_SY_BancChangeArrive"},   /* Zora's Domain */
    {"ZoraFountain_Child", "ZoraFountain_FromZoraDomain", "Dm_SY_BancChangeArrive",
     "ZoraFountain_Adult", "ZoraFountain_FromZoraDomain", "Dm_SY_BancChangeArrive"},   /* Zora's Fountain */
    {"GerudoValley_Child", "GerudoValley_Entrance", "FromHyruleField_ArriveGerudoValley",
     "GerudoValley_Adult", "GerudoValley_Entrance", "FromHyruleField_ArriveGerudoValley"},   /* Gerudo Valley */
    {NULL, NULL, NULL,
     "GerudoFortress_Adult", "GerudoFortress_FromHountedWasteland", "Dm_SY_BancChangeArrive_GerudoFortress_02"},   /* Gerudo Fortress */
    {"HountedWasteland_Child", "HountedWasteland_FromGerudoFortress", "FromGerudoFortress_ArriveWateland",
     "HountedWasteland_Adult", "HountedWasteland_FromGerudoFortress", "FromGerudoFortress_ArriveWateland"},   /* Haunted Wasteland */
    {"DesertColossus_Child", "DesertColossus_FromHountedWasteland", "Dm_SY_BancChangeArrive_DesertColossus_01",
     "DesertColossus_Adult", "DesertColossus_FromHountedWasteland", "Dm_SY_BancChangeArrive_DesertColossus_01"},   /* Desert Colossus */
    {"InsideTheDekuTree", "Entrance", "Dm_SY_BancChangeArrive_InsideTheDekuTree_01",
     "InsideTheDekuTree", "Entrance", "Dm_SY_BancChangeArrive_InsideTheDekuTree_01"},   /* Inside the Deku Tree */
    {"DodongoCavern", "DodongoCavern_MountainTrailSide", "Dm_SY_BancChangeArrive",
     "DodongoCavern", "DodongoCavern_MountainTrailSide", "Dm_SY_BancChangeArrive"},   /* Dodongo's Cavern */
    {"InsideJabuJabuBelly", "InsideJabuJabuBelly_FromZoraFountain", "Dm_SY_BancChangeArrive",
     "InsideJabuJabuBelly", "InsideJabuJabuBelly_FromZoraFountain", "Dm_SY_BancChangeArrive"},   /* Jabu-Jabu's Belly */
    {"ForestTemple", "ForestTemple", "Dm_SY_BancChangeArrive",
     "ForestTemple", "ForestTemple", "Dm_SY_BancChangeArrive"},   /* Forest Temple */
    {"FireTemple", "FireTemple", "Dm_SY_BancChangeArrive",
     "FireTemple", "FireTemple", "Dm_SY_BancChangeArrive"},   /* Fire Temple */
    {"WaterTemple", "WaterTemple_FromLakeHylia", "SageOfWater_Arrival_WaterTemple",
     "WaterTemple", "WaterTemple_FromLakeHylia", "SageOfWater_Arrival_WaterTemple"},   /* Water Temple */
    {"ShadowTemple", "Entrance", "ShadowTemple_Arrive",
     "ShadowTemple", "Entrance", "ShadowTemple_Arrive"},   /* Shadow Temple */
    {"SpiritTemple", "SpiritTemple_FromRightHand", "Dm_SY_BancChangeArrive",
     "SpiritTemple", "SpiritTemple_FromRightHand", "Dm_SY_BancChangeArrive"},   /* Spirit Temple */
    {"BottomOfTheWell", "Well_KakarikoSide", "Dm_SY_BancChangeArrive",
     "BottomOfTheWell", "Well_KakarikoSide", "Dm_SY_BancChangeArrive"},   /* Bottom of the Well */
    {"IceCavern", "IceCavern_FromZoraFountain", "SageOfWater_Arrival_IceCavern",
     "IceCavern", "IceCavern_FromZoraFountain", "SageOfWater_Arrival_IceCavern"},   /* Ice Cavern */
    {"GerudoTrainingGround", "GerudoTrainingGround_FromGerudoFortress", "FromGerudoFortress_ArriveTrainingGround",
     "GerudoTrainingGround", "GerudoTrainingGround_FromGerudoFortress", "FromGerudoFortress_ArriveTrainingGround"},   /* Gerudo Training Ground */
    {"InsideGanonCastle", "Entrance", "Dm_SY_BancChangeArrive_InsideGanonCastle_01",
     "InsideGanonCastle", "Entrance", "Dm_SY_BancChangeArrive_InsideGanonCastle_01"},   /* Ganon's Castle */
};
/* (the randomizer's fork) The Debug tab's Teleport page, its Bosses: each boss's room, the action OOT_TELEPORT_ACTION + the
   destinations' count + its place here. The teleport to the dungeon's map, then Link put at the place as the Tracker's Go
   there puts him (a metre above it, held three seconds). The places are the game's own start points in each boss's room,
   by its door (the room's StartPos nearest the room's centre, from the map files), away from the room's blue warp: put
   where the boss is, Link was above Gohma's ceiling and was taken out of the dungeon (seen without a window). Twinrova's
   room has none: the place just inside its door. Asked for by the game's owner, to test the bosses without the dungeons.
   A fight starts as Link comes through the room's door (the door's shutter or a request at the doorway asks for the
   boss's event); put inside, he found the boss and no fight (King Dodongo, Barinade, Ganondorf: the owner, 2026-11-16).
   So the boss's own event (the game's event list, RSDB/EventSetting) is asked for once he has been held in the room. */
typedef struct {
    const char *folder, *ages;   /* (the dungeon's map folder; C the child, A the adult has it) */
    float place[3];
    const char *event;           /* (what starts the fight, from the map's request or door in the room) */
    uint32_t seen;               /* (0, or the dungeon's entry scene's played flag (HavePlayedEvent.Goto_<dungeon>), set first:
                                    that scene walked Link back to the entrance from the boss's room, and held the camera) */
} OotBossRoom;
static const OotBossRoom oot_boss_rooms[] = {
    {"InsideTheDekuTree", "CA", {6.7f, 47.0f, 67.6f}, "InsideTheDekuTree_BossArea_ShutIn"},           /* Gohma */
    {"DodongoCavern", "CA", {24.0f, 73.4f, -77.6f}, "Get_StoneOfFire_AppearBoss"},             /* King Dodongo */
    {"InsideJabuJabuBelly", "CA", {42.4f, 102.0f, -98.1f}, "Get_StoneOfWater_BossAppear"},      /* Barinade */
    {"ForestTemple", "CA", {-6.0f, 74.7f, -66.0f}, "ForestTemple_SageOfForest_PhantomGanonAppearance"},              /* Phantom Ganon */
    {"FireTemple", "CA", {-64.5f, 102.5f, 0.0f}, "SageOfFire_BossAppear", 0xde8666fau},                /* Volvagia */
    {"WaterTemple", "CA", {-4.5f, 131.4f, -75.3f}, "Demo_SageOfWater_BossAppears", 0x3be817e9u},              /* Morpha */
    {"ShadowTemple", "CA", {-138.3f, -11.5f, 22.0f}, "ShadowTemple_BossAppear"},            /* Bongo Bongo */
    {"SpiritTemple", "CA", {0.0f, 135.0f, -121.3f}, "SageOfSpirit_BossStart"},             /* Twinrova */
    {"InsideGanonCastle", "CA", {0.0f, 171.1f, -11.3f}, "Common_Dungeon_OpenDoorChainLock_UnlockGanonBossRoomMoveTo0"},
                                                                 /* Ganondorf: his door's unlock, which calls Defeat_Ganon's
                                                                    BossAppear_1 (his entrance scene alone left the room empty) */
};
#define OOT_DESTINATIONS (sizeof oot_destinations / sizeof oot_destinations[0])
#define OOT_BOSS_ROOMS (sizeof oot_boss_rooms / sizeof oot_boss_rooms[0])
#define OOT_AGE_ACTION 999   /* (the Cheats page's Age row) */
#define OOT_TELEPORT_ACTION 1000   /* (pouch edits use 200 to 348) */
#define OOT_GAMEDATA_SLOT 0x84c9e180ULL   /* GameDataMgr, as ReserveBancChange's readers load it */
#define OOT_EVENTMGR_SLOT 0x84c9e090ULL   /* EventMgr, as SeqOneShotRequestEvent loads it */
#define OOT_EVENT_ARG_SIZE 0x1b20ULL      /* EventRequestArg: SeqOneShotRequestEvent reserves this much stack */

static uint64_t oot_singleton(Ctx *c, uint64_t slot) {
    const uint64_t holder = recomp_load64(c, slot);
    return holder ? recomp_load64(c, holder) : 0;
}

/* GameDataMgr getters by MurMur3 name hash: f_8022d9c0 (bool) and f_80cd0ea0 (String64). 1 when found. */
static int oot_gamedata_bool(Ctx *c, uint32_t hash, int *value) {
    const uint64_t mgr = oot_singleton(c, OOT_GAMEDATA_SLOT);
    A64Fn get = a64_lookup(0x8022d9c0ULL);
    if (!mgr || !get) return 0;
    const Ctx saved = *c;
    const uint64_t out = (c->x[31] - 0x40) & ~0xfULL;
    recomp_store64_sp(c, out, 0);
    c->x[31] = out;
    c->x[0] = mgr, c->x[1] = out, c->x[2] = hash;
    get(c);
    const int found = (int)(c->x[0] & 1);
    *value = recomp_load8(c, out) & 1;
    *c = saved;
    return found;
}

static int oot_gamedata_string(Ctx *c, uint32_t hash, char *buf, size_t size) {
    const uint64_t mgr = oot_singleton(c, OOT_GAMEDATA_SLOT);
    A64Fn get = a64_lookup(0x80cd0ea0ULL);
    buf[0] = 0;
    if (!mgr || !get) return 0;
    const Ctx saved = *c;
    const uint64_t out = (c->x[31] - 0x40) & ~0xfULL;
    recomp_store64_sp(c, out, 0);
    c->x[31] = out;
    c->x[0] = mgr, c->x[1] = out, c->x[2] = hash;
    get(c);
    const int found = (int)(c->x[0] & 1);
    const uint64_t text = recomp_load64(c, out);
    *c = saved;
    if (!found || !text) return 0;
    for (size_t i = 0; i + 1 < size; i++) {
        buf[i] = (char)recomp_load8(c, text + i);
        buf[i + 1] = 0;
        if (!buf[i]) break;
    }
    return 1;
}

/* One argument of an EventRequestArg: the array of 200-byte entries at arg+8, capacity arg+0, count arg+16.
   Entry: +0 type (1 string pointer, 4 bool), +8 name buffer, +16 its capacity, +152 the value. As
   QueryBancChangeEventRequestArg (f_829df380) fills them. A string value is a pointer the request does not copy. */
static int oot_event_arg(Ctx *c, uint64_t arg, const char *name, uint32_t type, uint64_t value) {
    const uint32_t capacity = recomp_load32(c, arg), count = recomp_load32(c, arg + 16);
    if (count >= capacity) return 0;
    const uint64_t entry = recomp_load64(c, arg + 8) + (uint64_t)count * 200;
    const uint64_t name_buf = recomp_load64(c, entry + 8);
    const uint32_t name_cap = recomp_load32(c, entry + 16);
    const size_t length = strlen(name);
    if (!name_buf || length + 1 > name_cap) return 0;
    memcpy(A64_PTR(name_buf), name, length + 1);
    if (type == 4) recomp_store8(c, entry + 152, value & 1);
    else recomp_store64(c, entry + 152, value);
    recomp_store32(c, entry, type);
    recomp_store32(c, arg + 16, count + 1);
    return 1;
}

/* (the Main sequence's "Event" test: an event is playing) */
static int oot_event_playing(Ctx *c) {
    const uint64_t events = oot_singleton(c, OOT_EVENTMGR_SLOT);
    return events && recomp_load64(c, events + 104);
}

static struct {
    int64_t requested_at, check_at;
    unsigned destination;
    const char *why, *banc;   /* (the last call's: why it was not sent, the map it was sent to; the control bridge's reply) */
    uint64_t result;          /* (and the event manager's answer to the request: 0 seen when the map did not change) */
} teleport;

/* An event of the game's asked for by its name, with Link the one who starts it: the request oot_teleport makes,
   without a map to go to. 1 when it was sent. */
static int oot_event_request(Ctx *c, uint64_t actor, const char *event) {
    const uint64_t events = oot_singleton(c, OOT_EVENTMGR_SLOT);
    A64Fn make_arg = a64_lookup(0x80d99f10ULL), request = a64_lookup(0x80d9a820ULL);
    A64Fn set_link = a64_lookup(0x802dc440ULL), release_link = a64_lookup(0x8022b6f0ULL);
    if (!events || !make_arg || !request || !set_link || !release_link) return 0;
    const Ctx saved = *c;
    const uint64_t arg = (c->x[31] - OOT_EVENT_ARG_SIZE - 0x100) & ~0xfULL;
    c->x[31] = arg;
    c->x[0] = arg;
    make_arg(c);
    const uint64_t buf = recomp_load64(c, arg + 6800);
    const uint32_t cap = recomp_load32(c, arg + 6808);
    const int ok = buf && strlen(event) + 1 <= cap;
    if (ok) {
        memcpy(A64_PTR(buf), event, strlen(event) + 1);
        c->x[31] = arg;
        c->x[0] = arg + 0x1950, c->x[1] = actor, c->x[2] = 0;
        set_link(c);
        c->x[31] = arg;
        c->x[0] = events, c->x[1] = arg;
        request(c);
    }
    for (unsigned i = 0; i < 2; i++) {   /* (the arg's two actor links, as oot_teleport gives them back) */
        const uint64_t link = arg + (i ? 0x1950 : 0x1968);
        recomp_store64(c, link, 0x84994b20ULL);
        c->x[31] = arg;
        c->x[0] = link;
        release_link(c);
    }
    *c = saved;
    return ok;
}

/* (the randomizer's fork) Open Door of Time: the Master Sword takes Link through time from a new game's start.
   The sword's own logic asks for its events only at and after the story's step for them (the quest DoorOfTime at
   Step06: tools/rando/rando_seed.py OPEN_DOOR has what was found): before, the button at the sword does nothing.
   So when A is pressed beside the sword, in the Market's map of either age, and half a second later nothing of the
   game's is playing, the game's own plain way through time is asked for here: Market_Child_Field_ChildToAdult, or
   Market_Adult_Field_AdultToChild. Where the game answers the button itself (the story's drawing, the plain way once
   the story is past it, a talk) its event is playing by then and nothing is asked for.
   The door's flag is set here too for a save that has it put out (a save from before the setting was on). */
static float oot_link_place[3];   /* (where Link is: oot_tracker_refresh, below) */
static int oot_pouch_count(Ctx *c, const char *name);
static int oot_pouch_change(Ctx *c, const char *name, int by);
#define OOT_SWORD_X 137.6f
#define OOT_SWORD_Z (-34.0f)
#define OOT_SWORD_NEAR 1.8f
#define OOT_DOOR_FLAG 0x727c2cbdu   /* Market_Child_TimeTempleDoor_Opened */
/* (the adult's Market has its location, and so its minimap, only once the scene of an adult leaving the temple has
   played, which the plain way through time never reaches: tools/rando/rando_seed.py OPEN_DOOR. Set like the door's) */
#define OOT_LEFT_TEMPLE_FLAG 0xc1b29b0au   /* HavePlayedEvent.Dm_TimeTemple_0065 */
static void oot_time_door(Ctx *c, int64_t now, uint64_t actor) {
    int hos_rando_open_door(void);   /* host/oot_rando.c */
    int hos_pad_a_held(void);        /* host/nn_hid.c */
    static int held;
    static int64_t ask_at, flag_at;
    if (!hos_rando_open_door()) return;
    if (now >= flag_at) {   /* (each second) */
        int open = 1;
        flag_at = now + 1000000000LL;
        if (oot_gamedata_bool(c, OOT_DOOR_FLAG, &open) && !open && oot_gamedata_set_bool(c, OOT_DOOR_FLAG, 1))
            hos_log("rando: the Door of Time's flag was put out in this save: it is set (Open Door of Time)");
        open = 1;
        if (oot_gamedata_bool(c, OOT_LEFT_TEMPLE_FLAG, &open) && !open && oot_gamedata_set_bool(c, OOT_LEFT_TEMPLE_FLAG, 1))
            hos_log("rando: the adult's Market had no location in this save: its flag is set (Open Door of Time)");
    }
    const int a = hos_pad_a_held(), pressed = a && !held;
    held = a;
    const float dx = oot_link_place[0] - OOT_SWORD_X, dz = oot_link_place[2] - OOT_SWORD_Z;
    char banc[80];
    const int beside = dx * dx + dz * dz <= OOT_SWORD_NEAR * OOT_SWORD_NEAR && oot_gamedata_string(c, 0x1d6189dau, banc, sizeof banc) &&
                       !strncmp(banc, "Market_", 7);   /* Sequence_CurrentBanc */
    if (!beside) {
        ask_at = 0;
        return;
    }
    if (pressed && !ask_at && !oot_event_playing(c)) ask_at = now + 500000000LL;
    if (!ask_at || now < ask_at) return;
    ask_at = 0;
    int loading = 0, child = 1;
    if (oot_event_playing(c) || (oot_gamedata_bool(c, 0xef2b60c2u, &loading) && loading)) return;   /* (the game answered: Sequence_IsLoadingBanc) */
    oot_gamedata_bool(c, 0xcea220d3u, &child);   /* Sequence_IsChildhood */
    const char *event = child ? "Market_Child_Field_ChildToAdult" : "Market_Adult_Field_AdultToChild";
    /* (the plain way through time does not give the sword: the story's drawing does, Dm_TimeTemple_0030. Seen
       without a window: an adult made so had none. So Link is given it here the first time) */
    if (child && oot_pouch_count(c, "Weapon_Sword_Master") == 0)
        hos_log("rando: Open Door of Time: the Master Sword is given (event status %d)", oot_pouch_change(c, "Weapon_Sword_Master", 1));
    hos_log("rando: Open Door of Time: %s asked for at the Master Sword (%s)", event, oot_event_request(c, actor, event) ? "sent" : "NOT SENT");
}

/* (the age switch: the age it has just set, for the teleport that follows it at once; -1: read Link's. The flag is set
   through the game's setter, which queues the write, so read back at once it was still the old age: the switch
   reloaded the same age's map, which put the age back, and Link was only taken to the start of the area. Reported in
   play, 2026-11-15) */
static int oot_teleport_child = -1;

static int oot_teleport(Ctx *c, uint64_t actor, unsigned index) {
    teleport.why = "no such destination", teleport.banc = NULL;
    if (index >= sizeof oot_destinations / sizeof oot_destinations[0]) return 0;
    const int64_t now = hos_now_ns();
    if (teleport.requested_at && now - teleport.requested_at < 8000000000LL) {
        hos_log("cheats: teleport ignored, a request is still in progress");
        teleport.why = "another teleport is still in progress (one every 8 s)";
        return 0;
    }
    const uint64_t events = oot_singleton(c, OOT_EVENTMGR_SLOT);
    A64Fn make_arg = a64_lookup(0x80d99f10ULL), request = a64_lookup(0x80d9a820ULL);
    A64Fn set_link = a64_lookup(0x802dc440ULL), release_link = a64_lookup(0x8022b6f0ULL);
    if (!events || !make_arg || !request || !set_link || !release_link) {
        hos_log("cheats: teleport unavailable (event manager %#llx)", (unsigned long long)events);
        teleport.why = "the game's event manager is not there yet";
        return 0;
    }
    if (recomp_load64(c, events + 104)) {   /* (the Main sequence's "Event" test: an event is playing) */
        hos_log("cheats: teleport waits until the current event ends");
        teleport.why = "an event is playing (a cutscene, a map change's)";
        return 0;
    }
    int loading = 0, child = 1;
    if (oot_gamedata_bool(c, 0xef2b60c2u, &loading) && loading) {   /* Sequence_IsLoadingBanc */
        hos_log("cheats: teleport ignored while a map loads");
        teleport.why = "a map is loading";
        return 0;
    }
    if (oot_teleport_child >= 0) child = oot_teleport_child;
    else if (!oot_gamedata_bool(c, 0xcea220d3u, &child)) hos_log("cheats: Sequence_IsChildhood not found, using child maps");
    const OotDestination *d = &oot_destinations[index];
    const char *banc = child ? d->child_banc : d->adult_banc;
    const char *start = child ? d->child_start : d->adult_start;
    const char *boot = child ? d->child_boot : d->adult_boot;
    if (!banc) {
        hos_log("cheats: teleport %u has no %s map", index, child ? "child" : "adult");
        teleport.why = child ? "this destination has no map for the child" : "this destination has no map for the adult";
        return 0;
    }

    /* The event reads its string arguments after this request returns, so they live in memory that stays. */
    static uint64_t strings;
    if (!strings) strings = hos_sys_alloc(512, 16);
    if (!strings) return teleport.why = "out of memory", 0;
    memset(A64_PTR(strings), 0, 512);
    memcpy(A64_PTR(strings), banc, strlen(banc) + 1);
    memcpy(A64_PTR(strings + 128), start, strlen(start) + 1);
    memcpy(A64_PTR(strings + 256), boot, strlen(boot) + 1);

    const char *event_env = getenv("HOS_OOT_TELEPORT_EVENT");
    const char *event = event_env && *event_env ? event_env : "Dm_SY_BancChangeGo";
    const char *starter_env = getenv("HOS_OOT_TELEPORT_STARTER");
    const int with_starter = !(starter_env && !strcmp(starter_env, "0"));

    const Ctx saved = *c;
    const uint64_t arg = (c->x[31] - OOT_EVENT_ARG_SIZE - 0x100) & ~0xfULL;
    c->x[31] = arg;
    c->x[0] = arg;
    make_arg(c);
    int ok = 1;
    {   /* the event's name: arg+6800 points at its buffer, arg+6808 the capacity */
        const uint64_t buf = recomp_load64(c, arg + 6800);
        const uint32_t cap = recomp_load32(c, arg + 6808);
        if (!buf || strlen(event) + 1 > cap) ok = 0;
        else memcpy(A64_PTR(buf), event, strlen(event) + 1);
    }
    ok = ok && oot_event_arg(c, arg, "NextBanc", 1, strings);
    ok = ok && oot_event_arg(c, arg, "NextStartPos", 1, strings + 128);
    ok = ok && oot_event_arg(c, arg, "BootEventName", 1, strings + 256);
    ok = ok && oot_event_arg(c, arg, "IsCheckAir", 4, 0);
    if (ok && with_starter) {   /* the starter actor (arg+0x1950), as OneShotEventMemberRequestEventByEventName sets it */
        c->x[31] = arg;
        c->x[0] = arg + 0x1950, c->x[1] = actor, c->x[2] = 0;
        set_link(c);
    }
    uint64_t result = 0;
    if (ok) {
        c->x[31] = arg;
        c->x[0] = events, c->x[1] = arg;
        request(c);
        result = c->x[0];
    }
    /* SeqOneShotRequestEvent's cleanup of the arg's two actor links */
    for (unsigned i = 0; i < 2; i++) {
        const uint64_t link = arg + (i ? 0x1950 : 0x1968);
        recomp_store64(c, link, 0x84994b20ULL);
        c->x[31] = arg;
        c->x[0] = link;
        release_link(c);
    }
    *c = saved;
    /* (issues 2217, 2588) A map-hiding area can leave this saved flag set when a debug teleport skips its exit.
       Only clear it once the event manager takes the request; the destination may hide its own minimap.
       Use the game's Bool setter (mgr, value, hash): it queues the change for the live value AND the save's copy.
       Writing only the live byte restores the HUD until the next load, but saves keep the old hidden value. */
    int hidden = 0;
    if (ok && result && oot_gamedata_bool(c, 0x9a4dd779u, &hidden) && hidden) {
        A64Fn set_bool = a64_lookup(0x806a2b20ULL);
        const uint64_t mgr = oot_singleton(c, OOT_GAMEDATA_SLOT);
        if (set_bool && mgr) {
            c->x[0] = mgr, c->x[1] = 0, c->x[2] = 0x9a4dd779u;   /* MapIconDeactivateByAreaActor */
            set_bool(c);
            *c = saved;
            hos_log("cheats: teleport: the area left had hidden the minimap (MapIconDeactivateByAreaActor): restore queued");
        } else {   /* (another game build: say so, a report's log then shows why the minimap stayed away) */
            hos_log("cheats: teleport: the area left had hidden the minimap (MapIconDeactivateByAreaActor): %s not found, left hidden",
                    set_bool ? "the game data manager" : "the game's Bool setter");
        }
    }
    teleport.requested_at = now;
    teleport.check_at = now + 1500000000LL;
    teleport.destination = index;
    hos_log("cheats: teleport %s to %s at %s (boot %s, event %s, starter %d): request %s, result %#llx",
            child ? "child" : "adult", banc, start, boot, event, with_starter, ok ? "sent" : "not built",
            (unsigned long long)result);
    teleport.result = result;
    if (ok) teleport.banc = banc;
    else teleport.why = "the game's event request could not be built";
    return ok;   /* (sent; the request's own result is only logged) */
}

/* Writes a GameData bool directly: GameDataMgr+32 is the (hash, index) table (+44 its size), the bools are 24-byte
   entries at GameDataMgr+24 (+16 their count) with the value at +22, as f_8022d9c0 reads them. 1 when found. */
/* A truth value of the list set. By the game's own setter (f_806a2b20: the manager, the value, the name's hash), which
   puts the write in the manager's queue: the value is the game's some frames later, and it is in the next save.
   (Until 2026-11-14 the value's byte was written where it is, +22 of the flag's 24 bytes: the game saw it at once, but
   a save made after did not have it. Seen in a save's file: HavePlayedEvent.Dm_TimeTemple_0065 set so, then the
   game's own save, and the file had it false.) Where the setter is not found the byte is written as before. */
static int oot_gamedata_set_bool(Ctx *c, uint32_t hash, int value) {
    const uint64_t mgr = oot_singleton(c, OOT_GAMEDATA_SLOT);
    if (!mgr) return 0;
    const uint64_t table = recomp_load64(c, mgr + 32);
    const uint32_t size = recomp_load32(c, mgr + 44);
    if (!table || !size) return 0;
    for (uint32_t probe = 0, slot = hash % size; probe < size; probe++, slot = (slot + 1) % size) {
        const uint32_t key = recomp_load32(c, table + slot * 8ULL);
        if (!key) return 0;
        if (key != hash) continue;
        const uint32_t index = recomp_load32(c, table + slot * 8ULL + 4), count = recomp_load32(c, mgr + 16);
        if (index >= count) return 0;
        A64Fn set = a64_lookup(0x806a2b20ULL);
        if (set) {
            const Ctx saved = *c;
            c->x[0] = mgr, c->x[1] = value ? 1 : 0, c->x[2] = hash;
            set(c);
            *c = saved;
        } else {
            recomp_store8(c, recomp_load64(c, mgr + 24) + index * 24ULL + 22, value ? 1 : 0);
        }
        return 1;
    }
    return 0;
}

/* A whole value of the list of flags that is one of a set of names (Data.Enum: a quest's step is one, the hash of the
   step's name), read and written directly: GameDataMgr+0x258 are the entries, 56 bytes each with the value at +0x1c
   and again at +0x20, and +0x260 their (hash, index) table (+0x26c its size), as the bools' are at +24 and +32 (found
   in the manager's memory written to a file: the quests AllSage and DoorOfTime, by their steps' hashes). 1 when found. */
static int oot_gamedata_enum(Ctx *c, uint32_t hash, uint32_t *value, int set) {
    const uint64_t mgr = oot_singleton(c, OOT_GAMEDATA_SLOT);
    if (!mgr) return 0;
    const uint64_t table = recomp_load64(c, mgr + 0x260);
    const uint32_t size = recomp_load32(c, mgr + 0x26c);
    if (!table || !size) return 0;
    for (uint32_t probe = 0, slot = hash % size; probe < size; probe++, slot = (slot + 1) % size) {
        const uint32_t key = recomp_load32(c, table + slot * 8ULL);
        if (!key) return 0;
        if (key != hash) continue;
        const uint32_t index = recomp_load32(c, table + slot * 8ULL + 4), count = recomp_load32(c, mgr + 0x250);
        if (index >= count) return 0;
        const uint64_t entry = recomp_load64(c, mgr + 0x258) + index * 56ULL;
        if (set) {
            recomp_store32(c, entry + 0x1c, *value);
            recomp_store32(c, entry + 0x20, *value);
        } else *value = recomp_load32(c, entry + 0x1c);
        return 1;
    }
    return 0;
}

/* (the randomizer's fork) Ganon's Castle's bridge (the setting rando_ganon_bridge: 1 open, 2 once Link holds the six
   medallions). The bridge (Obj_GanonCastle_Bridge_A_01 in GanonCastle_Static) is made once its scene has played
   (HavePlayedEvent.GanonCastle_Adult_Field_Rainbow), and the castle's field asks for that scene (Defeat_Ganon's flow,
   GanonCastle_Adult_Field_Rainbow) when the quest Defeat_Ganon is at its Ready step and Link stands at the castle's edge.
   The game sets Ready only after the Shadow and Spirit sages' scenes (AllSage's SageRoom_AllSage_LastSage, which moves
   that quest on). So here the quest is set from NotReady to Ready by the setting, and the bridge's own scene then plays
   and moves the quest on as the game does (its first action, to Step01); the castle's inside reads the later steps.
   Should the sages' scene later set the quest back to Ready after the bridge's has played, the step it had is put back
   (Ready with the bridge's scene played is a step the game never has). */
#define OOT_STEP_DEFEAT_GANON 0x746f47c0u   /* Step_Defeat_Ganon (a Data.Enum: its value the hash of a step's name) */
#define OOT_STEP_NOTREADY 0x57b849f0u        /* NotReady */
#define OOT_STEP_READY 0x17bfaa46u           /* Ready */
#define OOT_STEP_01 0xeb62add9u              /* Step01: what the bridge's scene moves Ready on to */
#define OOT_RAINBOW_FLAG 0x75022258u         /* HavePlayedEvent.GanonCastle_Adult_Field_Rainbow */
static const char *const oot_medallions[6] = {"Item_Medal_Forest", "Item_Medal_Fire", "Item_Medal_Water",
                                              "Item_Medal_Shadow", "Item_Medal_Spirit", "Item_Medal_Light"};
static void oot_ganon_bridge(Ctx *c, int64_t now) {
    int hos_rando_ganon_bridge(void);   /* host/oot_rando.c */
    static int64_t next_at;
    static uint32_t later;   /* (the quest's last step past Ready seen this session) */
    const int mode = hos_rando_ganon_bridge();
    if (!mode || now < next_at) return;
    next_at = now + 1000000000LL;   /* (each second) */
    uint32_t step = 0;
    if (!oot_gamedata_enum(c, OOT_STEP_DEFEAT_GANON, &step, 0)) return;
    if (step != OOT_STEP_NOTREADY && step != OOT_STEP_READY) {
        later = step;
        return;
    }
    if (step == OOT_STEP_READY) {
        int played = 0;
        if (later || (oot_gamedata_bool(c, OOT_RAINBOW_FLAG, &played) && played)) {
            uint32_t back = later ? later : OOT_STEP_01;
            if (oot_gamedata_enum(c, OOT_STEP_DEFEAT_GANON, &back, 1))
                hos_log("rando: Ganon's quest was set back to Ready after the bridge's scene: its step %08x is put back (Ganon's Castle bridge)",
                        back);
        }
        return;
    }
    int held = 0;
    if (mode == 2)
        for (int i = 0; i < 6; i++) held += oot_pouch_count(c, oot_medallions[i]) > 0;
    if (mode == 1 || held == 6) {
        uint32_t ready = OOT_STEP_READY;
        if (oot_gamedata_enum(c, OOT_STEP_DEFEAT_GANON, &ready, 1))
            hos_log("rando: Ganon's quest set to Ready: the bridge's scene plays at the castle's edge (Ganon's Castle bridge, %s)",
                    mode == 1 ? "Open" : "6 medallions");
    }
}

/* A whole number of the list of flags (Data.Int: PlayerStatus.MaxLife, in quarter hearts), read or written directly:
   the Ints are kept as the Enums are, from GameDataMgr+0xc8 (host/oot_state_tap.c state_kind): +0xd0 how many, +0xd8
   the entries of 40 bytes with the value at +0x1c, +0xe0 the (hash, index) table and +0xec its size. 1 when found. */
static int oot_gamedata_int(Ctx *c, uint32_t hash, int32_t *value, int set) {
    const uint64_t mgr = oot_singleton(c, OOT_GAMEDATA_SLOT);
    if (!mgr) return 0;
    const uint64_t table = recomp_load64(c, mgr + 0xe0);
    const uint32_t size = recomp_load32(c, mgr + 0xec);
    if (!table || !size) return 0;
    for (uint32_t probe = 0, slot = hash % size; probe < size; probe++, slot = (slot + 1) % size) {
        const uint32_t key = recomp_load32(c, table + slot * 8ULL);
        if (!key) return 0;
        if (key != hash) continue;
        const uint32_t index = recomp_load32(c, table + slot * 8ULL + 4), count = recomp_load32(c, mgr + 0xd0);
        if (index >= count) return 0;
        const uint64_t entry = recomp_load64(c, mgr + 0xd8) + index * 40ULL;
        if (set) {
            if (recomp_load32(c, entry + 0x20) == recomp_load32(c, entry + 0x1c)) recomp_store32(c, entry + 0x20, (uint32_t)*value);
            recomp_store32(c, entry + 0x1c, (uint32_t)*value);
        } else *value = (int32_t)recomp_load32(c, entry + 0x1c);
        return 1;
    }
    return 0;
}

/* What the game knows by an actor's hash (the list of flags' Bool64bitKey: a chest, a shelf that sells out): found in
   the running game by looking for known hashes in its memory. GameDataMgr+0xc58 is how many there are, +0xc60 their
   table, sorted by the hash, of 16 bytes each (the hash, then its reset type in the low half of the next word), and
   +0xc70 what follows the table. The place of a hash in the table, or -1. */
#define OOT_KEYED_COUNT 0xc58
#define OOT_KEYED_TABLE 0xc60
#define OOT_KEYED_VALUES 0xc70
static int64_t oot_gamedata_keyed_index(Ctx *c, uint64_t key, uint32_t *reset) {
    const uint64_t mgr = oot_singleton(c, OOT_GAMEDATA_SLOT);
    if (!mgr) return -1;
    const uint32_t count = recomp_load32(c, mgr + OOT_KEYED_COUNT);
    const uint64_t table = recomp_load64(c, mgr + OOT_KEYED_TABLE);
    if (!table || !count || count > 0x100000) return -1;
    uint32_t low = 0, high = count;
    while (low < high) {
        const uint32_t mid = low + (high - low) / 2;
        const uint64_t at = recomp_load64(c, table + mid * 16ULL);
        if (at == key) {
            if (reset) *reset = recomp_load32(c, table + mid * 16ULL + 8);
            return mid;
        }
        if (at < key) low = mid + 1;
        else high = mid;
    }
    return -1;
}

/* The truth value the game keeps by an actor's hash: the byte at 12 of its 16 in the table (github.com/Mozencaz/OotrR
   live_memory.py has it so, after the PracticeROM's notes). 1 and *out, or 0 when the table has no such hash. */
static int oot_gamedata_keyed_bool(Ctx *c, uint64_t key, int *out) {
    const int64_t i = oot_gamedata_keyed_index(c, key, NULL);
    if (i < 0) return 0;
    *out = recomp_load8(c, recomp_load64(c, oot_singleton(c, OOT_GAMEDATA_SLOT) + OOT_KEYED_TABLE) + (uint64_t)i * 16 + 12) != 0;
    return 1;
}
/* (set by the game's own setter, f_80f27130: the manager, the value, the hash. It puts the write in a queue of the
   manager's, as the truth values by name have one; the byte written where it is was not in the next save) */
static int oot_gamedata_keyed_set_bool(Ctx *c, uint64_t key, int value) {
    const uint64_t mgr = oot_singleton(c, OOT_GAMEDATA_SLOT);
    A64Fn set = a64_lookup(0x80f27130ULL);
    if (!set || oot_gamedata_keyed_index(c, key, NULL) < 0) return 0;
    const Ctx saved = *c;
    c->x[0] = mgr, c->x[1] = value ? 1 : 0, c->x[2] = key;
    set(c);
    *c = saved;
    return 1;
}

/* (the randomizer's fork) What the Tracker tab says is collected: the randomizer's own record. The game's flag for a chest
   opened was looked for and not found (tools/rando/README.md says where), so the record is kept here: the pouch
   manager's add (hos_oot_pouch_add, below) sees every item given and tells oot_tracker_item, which marks the check of
   the seed that gives that item nearest to where Link stands, in the map he is in (a check further than
   OOT_CHECK_NEAR is not his; an item only one check of the whole seed still gives is that check's wherever he is: a
   gift given indoors). What each check gives is the last field of its line of <game folder>/mods/rando-seed/checks.txt.
   The record is <game folder>/rando/collected.txt: the seed's stamp it is of (the first line of the seed's
   rando_stamp.txt), then the collected checks' places in the checks file. Another seed's record is not taken. It is
   one record for the folder, not for a save: a new game of the same seed keeps it until it is forgotten (the Tracker
   tab's first row, the action 6), and a save from before a check was collected still says it is. Checks collected
   before there was a record are not in it.
   Since 2026-11-14 that is so only of a seed made before (a gift's line without a key): a gift's line has the key of
   a chest's second value, which nothing else uses (tools/rando/rando_seed.py gift_keys), and is marked as a chest is. A check
   that is an actor of a map (a chest, a Gold Skulltula, a Piece of Heart: its line has the actor's hash) is marked
   in the save itself: the game's list has a truth value for every such actor by its hash (Bool64bitKey), saved,
   which the game was not seen to set for a chest (no save looked at had one, and a chest with it set was shut as
   before: seen without a window in Mido's house). It is set when the check is collected, by the game's own setter,
   and the mark of such a check is what the save loaded says (oot_shelf_flags). A shelf has its own flag. So a save
   from before, and a new game of the seed, have their own marks.
   Found 2026-11-17 (bug 70, a blue rupee chest never marked): the game does keep a chest opened, in the flag
   IsTreasureBoxOpen.<the chest's actor hash, in decimal> (murmur3, as every flag; REALAZK's OOTRR named it, checked
   here in saves: 0 for the chests not opened, 1 for Mido's house's opened ones). A chest's check is marked by it too
   (oot_shelf_flags), so a chest whose item reaches Link by no add the record sees (a blue rupee's) is marked. */
#define OOT_CHECK_NEAR 60.0f
static float oot_load_float(Ctx *c, uint64_t addr);
static int oot_gamedata_string(Ctx *c, uint32_t hash, char *buf, size_t size);
int hos_rando_on(void);   /* host/oot_rando.c */
static int oot_banc_in_folder(const char *banc, const char *folder);
static struct {
    char item[64], folder[40];
    float place[3];
    signed char done;
    uint64_t piece;   /* (a Piece of Heart lying in the world: its actor's hash; 0: another kind of check) */
    int boss;         /* (a boss's Heart Container: tools/rando/rando_seed.py BOSS_HEARTS, bug 31) */
    uint32_t shelf;   /* (a shop's shelf: the hash of the flag it waits for, "still for sale"; 0: another kind of check) */
    signed char sold; /* (a shelf bought, or a check with a key collected, just now: its flag is to be set, oot_shelf_flags) */
    uint64_t key;     /* (an actor of a map: its hash, by which the save keeps a truth value; 0: none) */
    uint32_t opened;  /* (a chest: the hash of the game's own flag IsTreasureBoxOpen.<key in decimal>, set when it is opened, bug 70; 0: none) */
} oot_checks[OOT_TRACKER_MAX];
static int oot_check_count = -1;
static char oot_checks_seed[200];   /* (the stamp the checks and the record are of) */
static float oot_link_place[3];
static char oot_link_map[80];
static SRWLOCK oot_checks_lock = SRWLOCK_INIT;

/* <game folder>/<tail>, into out: 1, or 0 when the game's folder is not known */
static int oot_game_file(char *out, size_t size, const char *tail) {
    char exe[MAX_PATH];
    const DWORD n = hos_game_path_a(exe, MAX_PATH);
    if (!n || n >= MAX_PATH) return 0;
    char *slash = strrchr(exe, '\\');
    char *other = strrchr(exe, '/');
    if (other > slash) slash = other;
    if (!slash) return 0;
    *slash = 0;
    snprintf(out, size, "%s/%s", exe, tail);
    return 1;
}

/* (the lock held) the record, written whole */
static void oot_tracker_save(void) {
    char path[MAX_PATH + 48];
    FILE *f = oot_game_file(path, sizeof path, "rando/collected.txt") ? fopen(path, "w") : NULL;
    if (!f) return;
    fprintf(f, "seed %s\n", oot_checks_seed);
    for (int i = 0; i < oot_check_count; i++)
        if (oot_checks[i].done == 1) fprintf(f, "%d\n", i);
    fclose(f);
}

/* (the lock held) the seed's stamp as it is now, the first line of its file without the line's end: 1, or 0 with no seed */
static int oot_tracker_stamp(char *out, size_t size) {
    char path[MAX_PATH + 48];
    FILE *f = oot_game_file(path, sizeof path, "mods/rando-seed/rando_stamp.txt") ? fopen(path, "r") : NULL;
    out[0] = 0;
    if (!f) return 0;
    if (!fgets(out, (int)size, f)) out[0] = 0;
    fclose(f);
    out[strcspn(out, "\r\n")] = 0;
    return out[0] != 0;
}

/* MurmurHash3 x86 32, seed 0: the hash the game names its flags by (as host/oot_state_tap.c state_murmur) */
static uint32_t oot_flag_hash(const char *s) {
    const size_t n = strlen(s);
    uint32_t h = 0, k;
    size_t i = 0;
    for (; i + 4 <= n; i += 4) {
        k = (uint32_t)(unsigned char)s[i] | (uint32_t)(unsigned char)s[i + 1] << 8 | (uint32_t)(unsigned char)s[i + 2] << 16 |
            (uint32_t)(unsigned char)s[i + 3] << 24;
        k *= 0xcc9e2d51u, k = k << 15 | k >> 17, k *= 0x1b873593u;
        h ^= k, h = h << 13 | h >> 19, h = h * 5 + 0xe6546b64u;
    }
    k = 0;
    switch (n & 3) {
    case 3: k ^= (uint32_t)(unsigned char)s[i + 2] << 16; /* fall through */
    case 2: k ^= (uint32_t)(unsigned char)s[i + 1] << 8; /* fall through */
    case 1: k ^= (uint32_t)(unsigned char)s[i]; k *= 0xcc9e2d51u, k = k << 15 | k >> 17, k *= 0x1b873593u, h ^= k;
    }
    h ^= (uint32_t)n, h ^= h >> 16, h *= 0x85ebca6bu, h ^= h >> 13, h *= 0xc2b2ae35u, h ^= h >> 16;
    return h;
}

/* (the lock held) the seed's checks with what each gives, and the record of that seed */
static void oot_tracker_load(const char *stamp) {
    char path[MAX_PATH + 48], line[400];
    static char kinds[OOT_TRACKER_MAX + 1][80];   /* (each check's name, to find the shelves by) */
    oot_check_count = 0;
    snprintf(oot_checks_seed, sizeof oot_checks_seed, "%s", stamp);
    FILE *f = oot_game_file(path, sizeof path, "mods/rando-seed/checks.txt") ? fopen(path, "r") : NULL;
    while (f && oot_check_count < OOT_TRACKER_MAX && fgets(line, sizeof line, f)) {
        char area[48], ages[4], needs[192] = "", hash[32] = "", item[64] = "";   /* (needs: a rule's ways apart by "/", two of a whole rule each) */
        char *kind = kinds[oot_check_count];
        if (line[0] == '#') continue;   /* (the lines the menu takes, in its order: gpu/vk/vk_menu.cpp tracker_load) */
        const int got = sscanf(line, "%47[^|]|%79[^|]|%39[^|]|%3[^|]|%f %f %f|%191[A-Z0-9,/-]|%31[0-9a-fA-F-]|%63[A-Za-z0-9_]", area, kind,
                               oot_checks[oot_check_count].folder, ages, &oot_checks[oot_check_count].place[0],
                               &oot_checks[oot_check_count].place[1], &oot_checks[oot_check_count].place[2], needs, hash, item);
        if (got < 7) continue;
        snprintf(oot_checks[oot_check_count].item, sizeof oot_checks[0].item, "%s", got >= 10 ? item : "");
        /* (tools/rando/rando_seed.py names such a check "Piece of Heart", and no other kind begins so) */
        oot_checks[oot_check_count].piece = got >= 9 && !strncmp(kind, "Piece of Heart", 14) ? strtoull(hash, NULL, 16) : 0;
        oot_checks[oot_check_count].boss = !strncmp(kind, "Heart Container, ", 17);   /* (the seed's name for a boss's) */
        oot_checks[oot_check_count].key = got >= 9 ? strtoull(hash, NULL, 16) : 0;   /* ("-": 0) */
        oot_checks[oot_check_count].opened = 0;
        if (oot_checks[oot_check_count].key && strstr(kind, "hest")) {   /* ("Chest ...", "Big chest ...": tools/rando/rando_seed.py's names) */
            char flag[64];
            snprintf(flag, sizeof flag, "IsTreasureBoxOpen.%llu", (unsigned long long)oot_checks[oot_check_count].key);
            oot_checks[oot_check_count].opened = oot_flag_hash(flag);
        }
        oot_checks[oot_check_count].shelf = 0;
        oot_checks[oot_check_count].sold = 0;
        oot_checks[oot_check_count++].done = 0;
    }
    if (f) fclose(f);
    /* (the shelves' flags: <a shelf's name in the checks file>|<its flag's hash>|<the flag>, tools/rando/rando_seed.py
       shelf_flags. A seed made before there were any has no such file, and its shelves are as they were) */
    int shelves = 0;
    f = oot_game_file(path, sizeof path, "mods/rando-seed/shelf_flags.txt") ? fopen(path, "r") : NULL;
    while (f && fgets(line, sizeof line, f)) {
        char name[80];
        unsigned flag = 0;
        if (sscanf(line, "%79[^|]|%x", name, &flag) != 2 || !flag) continue;
        for (int i = 0; i < oot_check_count; i++)
            if (!strcmp(kinds[i], name)) {
                oot_checks[i].shelf = flag, shelves++;
                break;
            }
    }
    if (f) fclose(f);
    if (shelves) hos_log("rando: tracker: %d shop shelves wait for a flag of their own", shelves);
    int collected = 0;
    f = oot_game_file(path, sizeof path, "rando/collected.txt") ? fopen(path, "r") : NULL;
    if (f && fgets(line, sizeof line, f)) {
        line[strcspn(line, "\r\n")] = 0;
        if (!strncmp(line, "seed ", 5) && !strcmp(line + 5, oot_checks_seed))   /* (this seed's record) */
            while (fgets(line, sizeof line, f)) {
                const int i = atoi(line);
                if (line[0] >= '0' && line[0] <= '9' && i < oot_check_count && oot_checks[i].done != 1) oot_checks[i].done = 1, collected++;
            }
    }
    if (f) fclose(f);
    hos_log("rando: tracker: %d checks of the seed, %d of them collected by the record", oot_check_count, collected);
}

/* A shop's shelf that sold its item is for sale again when its map is loaded again (the shelf's actor keeps what it
   sold, and nothing saved: tools/rando/README.md). So each shelf of a seed waits for a flag of its own, "still for
   sale" (the goods list's Release). The flag is the save's, and it is what says a shelf was bought: a shelf bought
   just now (oot_tracker_item) has its flag put out here, once, and at every other time the record of a shelf is put
   as the flag says. (Until 2026-11-14 the flags were kept as the record said, and the record is the folder's, not a
   save's: reported from play, a quiver bought was not for sale again in a save from before it was bought, nor in a
   new game of the same seed.) Each second. Returns how many flags or marks were changed. */
static int oot_shelf_flags(Ctx *c) {
    int changed = 0, marks = 0;
    AcquireSRWLockExclusive(&oot_checks_lock);
    for (int i = 0; i < oot_check_count; i++) {
        int now = 0;
        if (oot_checks[i].shelf) {
            if (!oot_gamedata_bool(c, oot_checks[i].shelf, &now)) continue;
            if (oot_checks[i].sold) {
                oot_checks[i].sold = 0;
                if (now && oot_gamedata_set_bool(c, oot_checks[i].shelf, 0)) changed++;
            } else if ((oot_checks[i].done == 1) != !now) {
                oot_checks[i].done = !now;
                marks++;
            }
        } else if (oot_checks[i].key) {   /* (an actor of a map: the save's truth value by its hash, true once collected) */
            if (!oot_gamedata_keyed_bool(c, oot_checks[i].key, &now)) continue;
            /* (bug 70: a chest the game says is open is collected, whatever it gave: a blue rupee's rupees reach Link by
               no add the record sees. Its own truth value is set too, so the mark stays with the save) */
            int open = 0;
            if (!now && !oot_checks[i].sold && oot_checks[i].opened && oot_gamedata_bool(c, oot_checks[i].opened, &open) && open) {
                if (oot_gamedata_keyed_set_bool(c, oot_checks[i].key, 1)) changed++;
                now = 1;
            }
            if (oot_checks[i].sold) {
                oot_checks[i].sold = 0;
                if (!now && oot_gamedata_keyed_set_bool(c, oot_checks[i].key, 1)) changed++;
            } else if ((oot_checks[i].done == 1) != now) {
                oot_checks[i].done = now;
                marks++;
            }
        }
    }
    if (marks) oot_tracker_save();
    ReleaseSRWLockExclusive(&oot_checks_lock);
    return changed + marks;
}

/* (the randomizer's fork) Progressive items: the families, smallest first; a tier may have a second spelling (the
   pouch's name of the same thing). Used by the pouch's add (hos_oot_pouch_add), by a chest's content name as the
   chest is made (hos_oot_drop_name: what it shows and says), and by the tracker (a check whose item is of the same
   family as the one given). */
static const char *const oot_families[][3][2] = {
    {{"Item_BombBag_Small"}, {"Item_BombBag_Medium"}, {"Item_BombBag_Large"}},
    {{"Item_Range_Bow", "Weapon_Range_Bow"}, {"Item_Quiver_Medium"}, {"Item_Quiver_Large"}},
    {{"Item_Range_SlingShot", "Weapon_Range_SlingShot"}, {"Item_BulletBag_Medium"}, {"Item_BulletBag_Large"}},
    {{"Item_Hookshot"}, {"Item_Longshot"}},
    {{"Item_Gauntlet_Goron", "Armor_Child_Gauntlet_Goron"}, {"Item_Gauntlet_Silver", "Armor_Adult_Gauntlet_Silver"}, {"Item_Gauntlet_Gold", "Armor_Adult_Gauntlet_Gold"}},
    {{"Item_Scale_Silver"}, {"Item_Scale_Gold"}},
    {{"Item_Wallet_Medium"}, {"Item_Wallet_Large"}},
    {{"Item_StickBag_Small"}, {"Item_StickBag_Medium"}, {"Item_StickBag_Large"}},
    {{"Item_NutBag_Small"}, {"Item_NutBag_Medium"}, {"Item_NutBag_Large"}},
    {{"Item_FairyBless_MP"}, {"Item_FairyBless_MPDouble"}},
};
#define OOT_FAMILIES ((int)(sizeof oot_families / sizeof oot_families[0]))
/* (what a chest can show and say: the game has a "You got" message (PouchContent.msbt, <name>_GetMessage) for these
   spellings and not for the others of the same thing. A chest made to give one without a message stopped in its
   scene, the model shown and no words (seen without a window 2026-11-16, the first Deku Nut bag). So a chest shows
   the spelling with the message; the first Stick and Nut bags have none: such a chest shows its own item as before) */
static const char *const oot_show_as[][2] = {
    {"Item_Range_Bow", "Weapon_Range_Bow"}, {"Item_Range_SlingShot", "Weapon_Range_SlingShot"},
    {"Item_Gauntlet_Goron", "Armor_Child_Gauntlet_Goron"}, {"Item_Gauntlet_Silver", "Armor_Adult_Gauntlet_Silver"},
    {"Item_Gauntlet_Gold", "Armor_Adult_Gauntlet_Gold"},
};
static const char *const oot_no_show[] = {"Item_StickBag_Small", "Item_NutBag_Small"};

/* the family a content is of (its index), and which spelling it was given by; -1 for none */
static int oot_family_of(const char *name, int *spelling) {
    for (int f = 0; f < OOT_FAMILIES; f++)
        for (int t = 0; t < 3 && oot_families[f][t][0]; t++)
            for (int a = 0; a < 2; a++)
                if (oot_families[f][t][a] && !strcmp(name, oot_families[f][t][a])) {
                    if (spelling) *spelling = a;
                    return f;
                }
    return -1;
}

int hos_rando_progressive(void);   /* host/oot_rando.c */

/* An item given (hos_oot_pouch_add): the check that gives it is collected */
static void oot_tracker_item(const char *name) {
    AcquireSRWLockExclusive(&oot_checks_lock);
    int best = -1, elsewhere = -1, others = 0;
    float nearest = 1e30f;
    /* (with Progressive items a check gives the family's next, by its own name or, since the chest says so, by that
       next's: a check of the same family is the one) */
    const int family = hos_rando_progressive() ? oot_family_of(name, NULL) : -1;
    for (int i = 0; i < oot_check_count; i++) {
        if (oot_checks[i].done == 1) continue;
        if (strcmp(oot_checks[i].item, name) && (family < 0 || oot_family_of(oot_checks[i].item, NULL) != family)) continue;
        if (!oot_banc_in_folder(oot_link_map, oot_checks[i].folder)) {
            others++, elsewhere = i;
            continue;
        }
        const float dx = oot_checks[i].place[0] - oot_link_place[0], dy = oot_checks[i].place[1] - oot_link_place[1],
                    dz = oot_checks[i].place[2] - oot_link_place[2];
        const float away = sqrtf(dx * dx + dy * dy + dz * dz);
        if (away < nearest) nearest = away, best = i;
    }
    if (best >= 0 && nearest > OOT_CHECK_NEAR) best = -1;
    if (best < 0 && others == 1 && nearest > 1e29f) best = elsewhere;   /* (the one check left that gives it, in another map's file) */
    if (best < 0) {
        /* (a shop's shelf gives its item by the name the pouch has it by, which is not always the seed's: seen without
           a window, the Lens of Truth bought was Armor_Child_GlassTruth and a purple rupee Obj_Rupee_Purple, and
           neither shelf was marked. So a shelf near Link whose item's name without its first word (Item_, TBox_,
           Obj_) is the end of the name given is the one) */
        const size_t length = strlen(name);
        for (int i = 0; i < oot_check_count && best < 0; i++) {
            const char *tail = oot_checks[i].shelf && oot_checks[i].done != 1 ? strchr(oot_checks[i].item, '_') : NULL;
            const size_t n = tail ? strlen(tail) : 0;   /* (with its "_": a whole word's end) */
            if (n < 2 || n > length || strcmp(name + length - n, tail) || !oot_banc_in_folder(oot_link_map, oot_checks[i].folder)) continue;
            const float dx = oot_checks[i].place[0] - oot_link_place[0], dy = oot_checks[i].place[1] - oot_link_place[1],
                        dz = oot_checks[i].place[2] - oot_link_place[2];
            const float away = sqrtf(dx * dx + dy * dy + dz * dz);
            if (away <= OOT_CHECK_NEAR) best = i, nearest = away;
        }
    }
    if (best >= 0) {
        oot_checks[best].done = 1;
        if (oot_checks[best].shelf || oot_checks[best].key) oot_checks[best].sold = 1;
        oot_tracker_save();
        if (nearest < 1e29f) hos_log("rando: tracker: %s got: check %d is collected (%.1f m from Link)", name, best, nearest);
        else hos_log("rando: tracker: %s got: check %d is collected (the one left that gives it)", name, best);
    }
    ReleaseSRWLockExclusive(&oot_checks_lock);
}

/* (the randomizer's fork) Heart Pieces: what a Piece of Heart lying in the world gives. The seed leaves the piece in
   its map as the game has it, so it is taken once and stays taken as every piece does, and says in its check's line
   what it gives (tools/rando/rando_seed.py HEART). When a Piece of Heart enters the pouch within OOT_PIECE_NEAR metres
   of such a check's place, in that place's map, and not by an event's action (a chest's and a character's piece come
   from 0x828d50ac), the item of that check is put in the pouch in its place (hos_oot_pouch_add). The scene is the
   piece's: it shows a Piece of Heart and says so.
   Tried before this, and left: the item itself lying there, made a pick-up. Made from the token it was there again
   each time its map was entered; made from the piece too (seen in play, the Megaton Hammer of Zora's River); and with
   the saved truth value of the piece's own hash set by the game's setter (f_80f27130, as the piece's own
   OneShotHeartPieceTakenDeadAfter calls it) it was there again all the same. out: the item, when 1 is returned.
   The piece is counted all the same: its own taking counts it, apart from the pouch's add (seen in play and in runs
   with HOS_OOT_PIECES=1, which logs the count as it changes: an ordinary piece is counted some tenths of a second
   after the add, the Gerudo Valley's two seconds before it; with the add's name changed, and the name the caller
   tells the item got by changed too, it was counted still). So one piece is taken out of the pouch again
   (hos_oot_pouch_add, and oot_piece_back for a piece counted when Link had none). Left: the Gerudo Valley's piece
   taken with three in the pouch has made a heart by the time of the add, and that heart stays. */
#define OOT_PIECE_NEAR 12.0f
#define OOT_PIECE "Obj_Heart_Piece"
#define OOT_PIECE_VALLEY "Obj_GerudoValley_Heart_Piece"
#define OOT_CONTAINER "Obj_Heart_Container"
#define OOT_PIECE_WAIT 600   /* (the player's updates a piece counted late is waited for: some seconds) */
static int oot_piece_back;   /* (a piece to take back out of the pouch: the updates it is still waited for) */
/* (bug 31: a boss's Heart Container that gives the seed's item still made a heart, seen without a window: five hearts
   became six with the add renamed. Its own taking raises PlayerStatus.MaxLife, as a piece's counts the piece. So the
   max is followed at each update (oot_max_was: what it was before its last rise, oot_max_rose: when), and after the
   renamed add it is put back for some seconds to what it was before the container: oot_container_max) */
#define OOT_MAX_LIFE 0xfbe01da1u   /* (PlayerStatus.MaxLife, Int, quarter hearts: host/oot_state_tap.c) */
#define OOT_LIFE 0x31ab5580u       /* (PlayerStatus.Life) */
#define OOT_MAX_RECENT 5000000000LL
static int32_t oot_max_now = -1, oot_max_was = -1, oot_container_max = -1;
static int64_t oot_max_rose;
static int oot_container_back;   /* (the updates the container's heart is still taken back for) */
/* (a piece that gives another item still healed Link, as a piece does: bug 4, reported 2026-11-13. Until this time
   Link's life is not let rise over what it was before the piece: oot_piece_heal, in the player's update. The heal is
   not the life write that patch_life hooks (tried: no heal went through it, and Link was healed all the same)) */
#define OOT_PIECE_NO_HEAL 15000000000LL
static int64_t oot_no_heal_until;
static uint32_t oot_life_seen, oot_life_held;   /* (Link's life, in quarters, at the player's last update; kept) */
static void oot_piece_heal(Ctx *c, int64_t now, uint64_t actor) {
    if (!hos_oot_is_player(c, actor)) return;
    const uint64_t life_at = recomp_load64(c, actor + 7184);
    if (life_at < HOS_HEAP_BASE || (life_at & 7)) return;   /* (not made yet: seen 0x2f) */
    const uint32_t life = recomp_load32(c, life_at + 8);
    /* (bug 31: the boss container's heart in Link's own max life too, which the hearts shown and the heals go by: the
       actor's +7192, as its life is +7184 (the heal's clamp in f_804bd8c0). PlayerStatus.MaxLife alone was put back
       and six hearts were still shown) */
    const int32_t keep = __atomic_load_n(&oot_container_max, __ATOMIC_RELAXED);
    const uint64_t max_at = recomp_load64(c, actor + 7192);
    if (keep > 0 && __atomic_load_n(&oot_container_back, __ATOMIC_ACQUIRE) > 0 && max_at >= HOS_HEAP_BASE && !(max_at & 7)) {
        const uint32_t max = recomp_load32(c, max_at + 8);
        if (max > (uint32_t)keep) {
            recomp_store32(c, max_at + 8, (uint32_t)keep);
            if (life > (uint32_t)keep) recomp_store32(c, life_at + 8, (uint32_t)keep);
            hos_log("rando: the boss's Heart Container's heart is taken back from Link (max life %u -> %d quarters)", max, keep);
        }
    }
    static int told;
    if (!told && getenv("HOS_OOT_PIECES")) told = 1, hos_log("rando: Link's life read: %u quarters (at 0x%llx)", life, (unsigned long long)life_at);
    if (now >= __atomic_load_n(&oot_no_heal_until, __ATOMIC_ACQUIRE)) {
        __atomic_store_n(&oot_life_seen, life, __ATOMIC_RELAXED);
        return;
    }
    const uint32_t held = __atomic_load_n(&oot_life_held, __ATOMIC_RELAXED);
    if (life > held) {
        recomp_store32(c, life_at + 8, held);
        hos_log("rando: the Piece of Heart's heal is taken back (%u -> %u quarters)", life, held);
    } else {
        __atomic_store_n(&oot_life_held, life, __ATOMIC_RELAXED);   /* (a hit taken meanwhile stands) */
    }
}
/* (the randomizer's fork) A bag found is a full bag. What Link carries a counted item in (a Bomb Bag, a quiver or the
   bow, a Bullet Bag or the Slingshot, a Deku Stick bag, a Deku Nut bag) came empty when a seed gave it: a Deku Nut bag
   bought with no nuts held showed nothing in the Items screen, and was taken for a thing that did nothing (its owner's
   report, 2026-11-13, and their word: fill it, a bigger quiver or Bomb Bag too). So when one is put in the pouch
   (hos_oot_pouch_add notes which, the one given after the progressive step), what it holds is added until the count
   stops going up: the pouch keeps what the bag holds and no more. The adds are a few updates later, when the bag is in
   the pouch, and a few updates apart: an add is counted an update after it is made (seen: the count read at once was
   the one before), so each is looked at before the next (the player's update, oot_update_player_cheats). Seen without
   a window: the game fills a bigger bag itself, and the first one too for bombs, arrows and seeds; the first Deku
   Stick bag and Deku Nut bag came empty and are filled by this. With the randomizer on only. */
enum { OOT_FILL_WAIT = 12, OOT_FILL_STEP = 10, OOT_FILL_STEPS = 12, OOT_FILL_APART = 4 };
#define OOT_FILL_RUPEES "TBox_Rupee_Gold"
static const char *const oot_fills[][2] = {   /* what a holder's name starts with, and what it holds */
    {"Item_BombBag_", "Item_Bomb"}, {"Item_Quiver_", "Item_Arrow_Normal"}, {"Item_Range_Bow", "Item_Arrow_Normal"},
    {"Weapon_Range_Bow", "Item_Arrow_Normal"}, {"Item_BulletBag_", "Item_DekuSeed"}, {"Item_Range_SlingShot", "Item_DekuSeed"},
    {"Weapon_Range_SlingShot", "Item_DekuSeed"}, {"Item_StickBag_", "Item_DekuStick"}, {"Item_NutBag_", "Item_DekuNut"},
    /* (and a wallet its rupees, asked for after the bags: the game leaves a wallet found as full as the one before it.
       Rupees are added as the chests' gold rupee, 200 of them, and the count of that content is the rupees Link has:
       seen without a window, 24, 224, 424 after each. One at a time, OOT_FILL_RUPEES: ten would be 2000) */
    {"Item_Wallet_", OOT_FILL_RUPEES},
};
enum { OOT_FILLS = sizeof oot_fills / sizeof oot_fills[0] };
/* A bow or a Slingshot got with nothing to carry its ammunition in. Seen in the logs of a game, 2026-11-14 (its
   owner asked for the bow and the Slingshot to come full): a bow bought from a shelf, and a Slingshot, had ten of
   theirs added and Link then had none ("filled: Link has 0 (1 adds)"). The game gives the first quiver and the first
   Bullet Bag in the scenes of its own bow and Slingshot, not with the items; another randomizer of this game gives
   both at a new game's start for the same reason (github.com/Mozencaz/OotrR randomizer_core.py BASE_REQUIRED). So
   when what a holder holds is to be filled and Link has none of the things that carry it, the smallest is given
   first, once, and the fill is made after it. NOT SEEN YET: the game was being played. */
static const char *const oot_fill_bags[][4] = {   /* what is held; the smallest thing that carries it; the larger ones */
    {"Item_Arrow_Normal", "Item_Quiver_Small", "Item_Quiver_Medium", "Item_Quiver_Large"},
    {"Item_DekuSeed", "Item_BulletBag_Small", "Item_BulletBag_Medium", "Item_BulletBag_Large"},
};
static int oot_fill_bagged[OOT_FILLS];   /* (the smallest carrier was looked for, since the holder was got) */
static int oot_fill_wait[OOT_FILLS];   /* (a holder got: the updates until what it holds is added, or looked at again) */
static int oot_fill_last[OOT_FILLS];   /* (the count before the last add; -1: none made yet) */
static int oot_fill_adds[OOT_FILLS];   /* (the adds made) */
/* (a bag the game itself gives with what goes in it, when Link has none: three Deku Nuts bought with no bag came with
   the bag, and the fill then made them twenty. Reported from play, 2026-11-14, and seen in that game's log: the bag
   added from 0x828d50ac with x4 2 and x7 0, as the Bomb Bag given with a chest's bombs is. Such a bag is not filled:
   hos_oot_pouch_add sets this for the add it is in) */
static int oot_fill_quiet;
/* (the randomizer's fork) Ammo pick-ups and Rupees fill the wallet (launcher settings, asked for 2026-11-17): a pick-up
   lying in the world or dropped by grass, pots and enemies comes into the pouch from 0x80c8f7e8 (seen without a window:
   Hyrule Field's Deku Nut, "pouch add Obj_DekuNut x1 (lr 0x80c8f7e8", as Pieces of Heart and the bosses' containers
   do), not from a chest's (0x828d50ac) nor a shop's. Ammo: 5 each raises the add's count to 5; Fill the bag fills what
   it holds the way a bag found is filled (oot_fills), without giving a bag Link has not. Rupees: the wallet filled. */
static const char *const oot_pickup_ammo[][2] = {   /* a pick-up's name (its start), and what it adds to */
    {"Obj_Bomb", "Item_Bomb"}, {"Obj_DekuNut", "Item_DekuNut"}, {"Obj_DekuSeed", "Item_DekuSeed"},
    {"Obj_DekuStick", "Item_DekuStick"}, {"Obj_ArrowBundle_", "Item_Arrow_Normal"},
};
static void oot_fill_start(const char *holds, const char *why) {
    for (int k = 0; k < (int)OOT_FILLS; k++)
        if (!strcmp(oot_fills[k][1], holds)) {
            oot_fill_last[k] = -1, oot_fill_adds[k] = 0, oot_fill_bagged[k] = 1;   /* (no bag given: oot_fill_bags) */
            __atomic_store_n(&oot_fill_wait[k], OOT_FILL_WAIT, __ATOMIC_RELEASE);
            hos_log("rando: %s: %s will be filled", why, holds);
            return;
        }
}
int hos_rando_ammo_pickups(void);   /* host/oot_rando.c */
int hos_rando_rupee_fill(void);
static void oot_pickup_qol(Ctx *c, const char *name) {
    if (c->x[30] != 0x80c8f7e8ULL || (int32_t)c->x[3] <= 0) return;
    const int ammo = hos_rando_ammo_pickups();
    for (unsigned k = 0; ammo && k < sizeof oot_pickup_ammo / sizeof oot_pickup_ammo[0]; k++) {
        if (strncmp(name, oot_pickup_ammo[k][0], strlen(oot_pickup_ammo[k][0])) || (!strcmp(oot_pickup_ammo[k][0], "Obj_Bomb") && strcmp(name, "Obj_Bomb")))
            continue;
        if (ammo == 1 && (int32_t)c->x[3] < 5) {
            hos_log("rando: ammo pick-up %s x%d: 5 given", name, (int)(int32_t)c->x[3]);
            c->x[3] = 5;
        } else if (ammo == 2) {
            oot_fill_start(oot_pickup_ammo[k][1], name);
        }
        return;
    }
    if (hos_rando_rupee_fill() && !strncmp(name, "Obj_Rupee_", 10)) oot_fill_start(OOT_FILL_RUPEES, name);
}
static void oot_fill_note(const char *item) {
    for (int k = 0; k < (int)OOT_FILLS; k++)
        if (!strncmp(item, oot_fills[k][0], strlen(oot_fills[k][0]))) {
            if (oot_fill_quiet) {
                hos_log("rando: %s is the game's own, given with what goes in it: not filled", item);
                return;
            }
            oot_fill_last[k] = -1, oot_fill_adds[k] = 0, oot_fill_bagged[k] = 0;
            __atomic_store_n(&oot_fill_wait[k], OOT_FILL_WAIT, __ATOMIC_RELEASE);
            hos_log("rando: %s got: its %s will be filled", item, oot_fills[k][1]);
            return;
        }
}
static int oot_piece_gives(char *out, size_t size, int boss) {   /* (boss: a boss's Heart Container's check instead) */
    int best = -1;
    float nearest = boss ? 1e30f : OOT_PIECE_NEAR;   /* (a dungeon has one boss container: where it falls is not asked) */
    AcquireSRWLockShared(&oot_checks_lock);
    for (int i = 0; i < oot_check_count; i++) {
        if (!(boss ? oot_checks[i].boss : oot_checks[i].piece != 0) || !oot_banc_in_folder(oot_link_map, oot_checks[i].folder)) continue;
        const float dx = oot_checks[i].place[0] - oot_link_place[0], dy = oot_checks[i].place[1] - oot_link_place[1],
                    dz = oot_checks[i].place[2] - oot_link_place[2];
        const float away = sqrtf(dx * dx + dy * dy + dz * dz);
        if (away < nearest) nearest = away, best = i;
    }
    const int other = best >= 0 && oot_checks[best].item[0] && strcmp(oot_checks[best].item, boss ? OOT_CONTAINER : OOT_PIECE);
    if (other) snprintf(out, size, "%s", oot_checks[best].item);
    ReleaseSRWLockShared(&oot_checks_lock);
    return other;
}

/* The record forgotten (the Tracker tab's first row: a new game of the same seed) */
static void oot_tracker_forget(void) {
    AcquireSRWLockExclusive(&oot_checks_lock);
    for (int i = 0; i < oot_check_count; i++) oot_checks[i].done = 0;
    oot_tracker_save();
    ReleaseSRWLockExclusive(&oot_checks_lock);
    hos_log("rando: tracker: the record of what is collected is forgotten");
}

/* Where Link is, each frame, and each second: the seed's checks read when the seed is another, and each check's word to
   the menu, in the file's order */
static void oot_tracker_refresh(Ctx *c, int64_t now, uint64_t actor) {
    void rx_option_set(int id, int value);
    static int64_t next, next_stamp;
    for (unsigned i = 0; i < 3; i++) oot_link_place[i] = oot_load_float(c, actor + 796 + i * 4);
    if (now < next) return;
    next = now + 1000000000LL;
    if (!hos_rando_on()) return;
    rx_option_set(OOT_TRACKER_ON, 1);   /* (the Tracker tab reads the seed only then: vk_menu.cpp tracker_load) */
    {
        const int changed = oot_shelf_flags(c);
        if (changed) hos_log("rando: tracker: %d shop shelves put out, or marked as the save says", changed);
    }
    {   /* (a test's: HOS_OOT_SETFLAG="<hash in hex>=<0 or 1>,..." sets those truth values of the game's list once, some
           seconds into the game, and says what each was: to try a scene's steps one at a time) */
        static int turn;
        const char *set = getenv("HOS_OOT_SETFLAG");
        if (set && ++turn == 8) {
            while (*set) {
                char *end;
                const uint32_t hash = (uint32_t)strtoul(set, &end, 16);
                if (*end != '=') break;
                const int value = end[1] == '1';
                int was = -1;
                const int found = oot_gamedata_bool(c, hash, &was);
                hos_log("test: flag %08x was %d%s: set to %d (%s)", hash, was, found ? "" : " (not found)", value,
                        oot_gamedata_set_bool(c, hash, value) ? "done" : "NOT DONE");
                set = end + 2;
                if (*set == ',') set++;
            }
        }
    }
#ifdef _WIN32
    {   /* (a test's: HOS_OOT_FIND64="<64-bit value in hex>,..." looks for those values in all of the game's memory at
           the seconds of HOS_OOT_FIND64_AT="<second>,..." (20 without it), and says where each is and what is beside
           it, with the flags' manager's own words: to find where the game keeps what it knows by an actor's hash) */
        static int turn;
        const char *find = getenv("HOS_OOT_FIND64");
        if (find && *find) {
            const char *at = getenv("HOS_OOT_FIND64_AT");
            turn++;
            int now_is = at ? 0 : turn == 20;
            for (const char *p = at; p && *p;) {
                char *end;
                if ((int)strtol(p, &end, 10) == turn) now_is = 1;
                if (end == p) break;
                p = *end == ',' ? end + 1 : end;
            }
            if (now_is) {
                uint64_t keys[16];
                int n = 0, hits[16] = {0};
                for (const char *p = find; *p && n < 16;) {
                    char *end;
                    keys[n] = strtoull(p, &end, 16);
                    if (end == p) break;
                    n++;
                    p = *end == ',' ? end + 1 : end;
                }
                const uint64_t mgr = oot_singleton(c, OOT_GAMEDATA_SLOT);
                hos_log("test: find64 at second %d: the flags' manager is at %#llx", turn, (unsigned long long)mgr);
                for (unsigned row = 0; mgr && row < 0x4c0 / 32; row++)
                    hos_log("test: mgr+%03x: %016llx %016llx %016llx %016llx", row * 32,
                            (unsigned long long)recomp_load64(c, mgr + row * 32), (unsigned long long)recomp_load64(c, mgr + row * 32 + 8),
                            (unsigned long long)recomp_load64(c, mgr + row * 32 + 16), (unsigned long long)recomp_load64(c, mgr + row * 32 + 24));
                for (uint64_t a = 0x1000; a < HOS_GUEST_SPACE && !(n == 1 && !keys[0]);) {   /* ("0": no search) */
                    MEMORY_BASIC_INFORMATION m;
                    if (!VirtualQuery(GP(a), &m, sizeof m)) break;
                    const uint64_t base = (uint64_t)((uint8_t *)m.BaseAddress - (uint8_t *)GP(0));
                    const uint64_t end = base + m.RegionSize;
                    const int readable = m.State == MEM_COMMIT && !(m.Protect & (PAGE_GUARD | PAGE_NOACCESS)) &&
                                         (m.Protect & (PAGE_READWRITE | PAGE_READONLY | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE | PAGE_WRITECOPY));
                    if (readable && base >= 0x84000000ULL)   /* (past the game's code) */
                        for (uint64_t g = base > a ? base : a; g + 8 <= end; g += 4) {
                            uint64_t v;
                            memcpy(&v, GP(g), 8);
                            for (int k = 0; k < n; k++)
                                if (v == keys[k] && hits[k]++ < 24) {
                                    uint64_t w[6] = {0};
                                    if (g >= base + 16 && g + 32 <= end) memcpy(w, GP(g - 16), sizeof w);
                                    hos_log("test: find64 %016llx at %#llx: %016llx %016llx [%016llx] %016llx %016llx %016llx",
                                            (unsigned long long)keys[k], (unsigned long long)g, (unsigned long long)w[0], (unsigned long long)w[1],
                                            (unsigned long long)w[2], (unsigned long long)w[3], (unsigned long long)w[4], (unsigned long long)w[5]);
                                }
                        }
                    a = end > a ? end : a + 0x1000;
                }
                {   /* (HOS_OOT_KEYED_DUMP="<file>": the keyed table and the manager's words about it, as they are) */
                    const char *path = getenv("HOS_OOT_KEYED_DUMP");
                    char name[600];
                    if (path) snprintf(name, sizeof name, "%s.%d", path, turn);
                    FILE *f = path && mgr ? fopen(name, "wb") : NULL;
                    if (f) {
                        /* (everything the manager keeps is in one stretch of memory, from the manager itself to past
                           the keyed table: seen in its own words) */
                        const uint64_t last = recomp_load64(c, mgr + OOT_KEYED_VALUES) + 0x4000;
                        uint64_t done = 0;
                        for (uint64_t a = mgr & ~0xfffULL; a < last && last - mgr < (64ULL << 20); a += 0x1000) {
                            MEMORY_BASIC_INFORMATION m;
                            static const uint8_t none[0x1000];
                            const int ok = VirtualQuery(GP(a), &m, sizeof m) && m.State == MEM_COMMIT && !(m.Protect & (PAGE_GUARD | PAGE_NOACCESS));
                            fwrite(ok ? (const uint8_t *)GP(a) : none, 1, 0x1000, f);
                            done += 0x1000;
                        }
                        fclose(f);
                        hos_log("test: the manager's memory written, %llu bytes from %#llx", (unsigned long long)done, (unsigned long long)(mgr & ~0xfffULL));
                    }
                }
                for (int k = 0; k < n; k++) {
                    uint32_t reset = 0;
                    const int64_t i = oot_gamedata_keyed_index(c, keys[k], &reset);
                    const uint64_t values = mgr ? recomp_load64(c, mgr + OOT_KEYED_VALUES) : 0;
                    hos_log("test: find64 %016llx: %d places; place %lld of the keyed table, reset %u; after the table: word %08x (bit %d), byte %02x (bit %d), byte of its own %02x",
                            (unsigned long long)keys[k], hits[k], (long long)i, reset,
                            i >= 0 && values ? recomp_load32(c, values + (i >> 5) * 4) : 0,
                            i >= 0 && values ? (int)(recomp_load32(c, values + (i >> 5) * 4) >> (i & 31) & 1) : -1,
                            i >= 0 && values ? (unsigned)recomp_load8(c, values + (i >> 3)) : 0,
                            i >= 0 && values ? (int)(recomp_load8(c, values + (i >> 3)) >> (i & 7) & 1) : -1,
                            i >= 0 && values ? (unsigned)recomp_load8(c, values + i) : 0);
                }
            }
        }
    }
#endif
    if (getenv("HOS_OOT_WHERE"))   /* (a test's: HOS_OOT_WHERE=1 says where Link is each second) */
        hos_log("test: Link is at %.2f %.2f %.2f", oot_link_place[0], oot_link_place[1], oot_link_place[2]);
    {   /* (a test's: HOS_OOT_WATCHFLAG="<hash in hex>,..." says each of those truth values of the game's list when it
           is first read and each time it changes: to see which flag an item given sets) */
        static int was[32], first = 1;
        const char *watch = getenv("HOS_OOT_WATCHFLAG");
        for (int k = 0; watch && *watch && k < 32; k++) {
            char *end;
            const uint32_t hash = (uint32_t)strtoul(watch, &end, 16);
            if (end == watch) break;
            int value = -1;
            if (!oot_gamedata_bool(c, hash, &value)) value = -1;
            if (first || value != was[k]) hos_log("test: flag %08x is %d", hash, value);
            was[k] = value;
            watch = *end == ',' ? end + 1 : end;
        }
        first = 0;
    }
    {   /* (a test's: HOS_OOT_KEYED="<hash in hex>,..." says each second from the 60th what the truth values kept by
           those actors' hashes are, when one changed; HOS_OOT_KEYED_SET="<second>" sets them all true at that second) */
        static int turn;
        static char last[64];
        const char *keys = getenv("HOS_OOT_KEYED"), *at = getenv("HOS_OOT_KEYED_SET");
        if (keys && ++turn >= 60) {
            char now_is[64] = "";
            int n = 0;
            while (*keys && n < 60) {
                char *end;
                const uint64_t key = strtoull(keys, &end, 16);
                int v = 0;
                if (end == keys) break;
                if (at && turn == atoi(at)) oot_gamedata_keyed_set_bool(c, key, 1);
                now_is[n++] = oot_gamedata_keyed_bool(c, key, &v) ? (v ? '1' : '0') : '?';
                keys = *end ? end + 1 : end;
            }
            now_is[n] = 0;
            if (strcmp(now_is, last)) hos_log("test: keyed, second %d: %s", turn, now_is), strcpy(last, now_is);
        }
    }
    {   /* (a test's: HOS_OOT_SETENUM="<hash in hex>=<a value's hash in hex>,..." sets those values of the list's Data.Enum
           once, some seconds into the game, and says what each was: a quest's step) */
        static int turn;
        const char *set = getenv("HOS_OOT_SETENUM");
        if (set && ++turn == 8) {
            while (*set) {
                char *end;
                const uint32_t hash = (uint32_t)strtoul(set, &end, 16);
                if (*end != '=') break;
                uint32_t value = (uint32_t)strtoul(end + 1, &end, 16), was = 0;
                const int found = oot_gamedata_enum(c, hash, &was, 0);
                hos_log("test: enum %08x was %08x%s: set to %08x (%s)", hash, was, found ? "" : " (not found)", value,
                        oot_gamedata_enum(c, hash, &value, 1) ? "done" : "NOT DONE");
                set = end;
                if (*set == ',') set++;
            }
        }
    }
    {   /* (a test's: HOS_OOT_GIVE="<item>,<item>,..." puts those in the pouch, one a second from the tenth second on, as
           a scene's gift is put there, and says how many Link then has: to try what follows an item without playing up
           to it (a Deku Nut bag is in no row of the Debug tab's inventory) */
        static int turn;
        const char *give = getenv("HOS_OOT_GIVE");
        if (give && ++turn >= 10) {
            int k = turn - 10;
            while (k > 0 && *give) {
                give += strcspn(give, ",");
                if (*give == ',') give++;
                k--;
            }
            char item[64];
            const size_t length = strcspn(give, ",");
            if (length && length < sizeof item) {
                memcpy(item, give, length);
                item[length] = 0;
                const int result = oot_pouch_change(c, item, 1);
                hos_log("test: %s given (event status %d): Link has %d", item, result, oot_pouch_count(c, item));
            }
        }
    }
    {   /* (the randomizer's fork) Hyrule Field's clock. Until the owl's first cutscene there the field's sky stays the
           day's whatever time is asked for: no day turned to night, and the Sun's Song's night was day again at once
           (seen in play). What ends it is the flag HyruleField_ArriveEntrance (its MurmurHash3 below), the first thing
           the owl's event sets; tools/rando/rando_seed.py FIELD_CLOCK has how it was found. A seed's new game starts
           with it set; a save made before that has it put out still, so it is set here, once a second while it is
           not. The owl's event begins all the same. */
        int reached = 1;
        if (oot_gamedata_bool(c, 0x804aec99u, &reached) && !reached) {
            const int done = oot_gamedata_set_bool(c, 0x804aec99u, 1);
            static int said;
            if (said++ < 4) hos_log("rando: Hyrule Field's sky was held as the day's (HyruleField_ArriveEntrance was not set): the flag is set%s",
                                    done ? "" : ", NOT FOUND");
        }
    }
    {   /* (the randomizer's fork) The d-pad's HUD (Navi and the boots, by the hearts): a new game has none of it until the
           first scene in the Deku Tree. What shows it is a flag no file of the game names, known by its hash alone
           (tools/rando/rando_seed.py DPAD_HUD has how it was found). A seed's new game starts with it set; a save made
           before that has it put out, so it is set here, once a second while it is not. The HUD comes at the next
           load of an area. */
        int shown = 1;
        if (oot_gamedata_bool(c, 0x7be57cb0u, &shown) && !shown) {
            const int done = oot_gamedata_set_bool(c, 0x7be57cb0u, 1);
            static int said;
            if (said++ < 4) hos_log("rando: the d-pad's HUD was not shown yet (flag 7be57cb0 put out): the flag is set%s", done ? "" : ", NOT FOUND");
        }
    }
    {   /* (the randomizer's fork) The minimap, the same way: a new game had none of it until the owl's scenes in Hyrule
           Field. Its flag too is known by its hash alone (tools/rando/rando_seed.py MINIMAP); set here for a save that
           has it put out, once a second while it is not. It comes at the next load of an area. */
        int shown = 1;
        if (oot_gamedata_bool(c, 0x2e315eb6u, &shown) && !shown) {
            const int done = oot_gamedata_set_bool(c, 0x2e315eb6u, 1);
            static int said;
            if (said++ < 4) hos_log("rando: the minimap was not shown yet (flag 2e315eb6 put out): the flag is set%s", done ? "" : ", NOT FOUND");
        }
    }
    char map[80];
    oot_gamedata_string(c, 0x1d6189dau, map, sizeof map);   /* Sequence_CurrentBanc */
    AcquireSRWLockExclusive(&oot_checks_lock);
    memcpy(oot_link_map, map, sizeof oot_link_map);
    if (oot_check_count < 0 || now >= next_stamp) {   /* (a seed made anew while the game runs: its checks, and no record of another's) */
        next_stamp = now + 15000000000LL;
        char stamp[sizeof oot_checks_seed];
        oot_tracker_stamp(stamp, sizeof stamp);
        if (oot_check_count < 0 || strcmp(stamp, oot_checks_seed)) oot_tracker_load(stamp);
    }
    for (int i = 0; i < oot_check_count; i++) rx_option_set(OOT_TRACKER_BASE + i, oot_checks[i].done == 1);
    {   /* (where Link is, for the Tracker tab's order: a check of the map he is in, the first of the file) */
        int here = -1;
        for (int i = 0; i < oot_check_count && here < 0; i++)
            if (oot_banc_in_folder(oot_link_map, oot_checks[i].folder)) here = i;
        rx_option_set(OOT_TRACKER_HERE, here);
    }
    ReleaseSRWLockExclusive(&oot_checks_lock);
}

/* Age toggle: flips Sequence_IsChildhood (what the Temple of Time event sets) and reloads the current map, or the
   Market when this map is not in oot_destinations, through the teleport so the other age's map and Link load. 1: the map
   change was sent (teleport.banc its map); 0: not, teleport.why says why (the control bridge's reply) */
static int oot_toggle_age(Ctx *c, uint64_t actor) {
    int child = 1;
    if (!oot_gamedata_bool(c, 0xcea220d3u, &child)) {
        hos_log("cheats: age toggle: Sequence_IsChildhood not found");
        teleport.why = "Link's age is not in the game's data (Sequence_IsChildhood not found)", teleport.banc = NULL;
        return 0;
    }
    char current[80];
    oot_gamedata_string(c, 0x1d6189dau, current, sizeof current);   /* Sequence_CurrentBanc */
    unsigned target = 3;   /* Market (the Temple of Time is in it) */
    for (unsigned i = 0; i < sizeof oot_destinations / sizeof oot_destinations[0]; i++) {
        const OotDestination *d = &oot_destinations[i];
        const char *other = child ? d->adult_banc : d->child_banc;
        if (other && ((d->child_banc && !strcmp(d->child_banc, current)) || (d->adult_banc && !strcmp(d->adult_banc, current)))) {
            target = i;
            break;
        }
    }
    if (!oot_gamedata_set_bool(c, 0xcea220d3u, !child)) {
        hos_log("cheats: age toggle: could not write Sequence_IsChildhood");
        teleport.why = "Link's age could not be written (Sequence_IsChildhood)", teleport.banc = NULL;
        return 0;
    }
    hos_log("cheats: age toggle: %s -> %s, reloading via destination %u (current map \"%s\")",
            child ? "child" : "adult", child ? "adult" : "child", target, current);
    oot_teleport_child = !child;   /* (the age just set: the setter's write is queued, oot_teleport_child) */
    const int sent = oot_teleport(c, actor, target);
    oot_teleport_child = -1;
    if (!sent) {
        oot_gamedata_set_bool(c, 0xcea220d3u, child);
        hos_log("cheats: age toggle undone, the map change was not requested");
        return 0;
    }
    return 1;
}

static void oot_teleport_followup(Ctx *c) {
    if (!teleport.check_at || hos_now_ns() < teleport.check_at) return;
    teleport.check_at = 0;
    char next[80], current[80];
    oot_gamedata_string(c, 0xee27bf71u, next, sizeof next);     /* Sequence_ReservedNextBanc */
    oot_gamedata_string(c, 0x1d6189dau, current, sizeof current);   /* Sequence_CurrentBanc */
    const uint64_t events = oot_singleton(c, OOT_EVENTMGR_SLOT);
    hos_log("cheats: teleport check: reserved \"%s\", current \"%s\", event playing %d", next, current,
            events && recomp_load64(c, events + 104) ? 1 : 0);
}

/* (hookshot) the control bridge (host/control.c): the map the game is in (Sequence_CurrentBanc), read on the game's thread
   with the player's update every 250 ms and kept for the bridge's thread; the last one known (it stays through loads and
   menus, where Link is not updated). And the debug teleport by destination, as the Cheats page asks for it: taken at the
   next update of the player, in play, and what came of it (sent, or refused and why) kept for the bridge's reply */
static SRWLOCK oot_map_lock = SRWLOCK_INIT;
static char oot_map[80];
static int oot_flags = -1;   /* (1 an event playing, 2 a map loading, 4 the child; -1 not read yet) */
static void oot_map_refresh(Ctx *c, int64_t now) {
    static int64_t next;
    if (now < next) return;
    next = now + 250000000LL;
    char map[80];
    if (!oot_gamedata_string(c, 0x1d6189dau, map, sizeof map) || !map[0]) return;   /* Sequence_CurrentBanc */
    int loading = 0, child = 1;
    oot_gamedata_bool(c, 0xef2b60c2u, &loading);   /* Sequence_IsLoadingBanc */
    oot_gamedata_bool(c, 0xcea220d3u, &child);     /* Sequence_IsChildhood */
    const uint64_t events = oot_singleton(c, OOT_EVENTMGR_SLOT);
    const int flags = (events && recomp_load64(c, events + 104) ? 1 : 0) | (loading ? 2 : 0) | (child ? 4 : 0);
    AcquireSRWLockExclusive(&oot_map_lock);
    memcpy(oot_map, map, sizeof oot_map);
    oot_flags = flags;
    ReleaseSRWLockExclusive(&oot_map_lock);
}
/* (with the map) whether an event (a cutscene, a map change's) is playing, a map is loading, Link is the child: 0 before any */
int hos_oot_state(int *event, int *loading, int *child) {
    AcquireSRWLockShared(&oot_map_lock);
    const int f = oot_flags;
    ReleaseSRWLockShared(&oot_map_lock);
    if (f < 0) return 0;
    *event = f & 1, *loading = (f >> 1) & 1, *child = (f >> 2) & 1;
    return 1;
}
int hos_oot_current_map(char *out, size_t cap) {
    AcquireSRWLockShared(&oot_map_lock);
    const int have = oot_map[0] != 0;
    if (have) snprintf(out, cap, "%s", oot_map);
    ReleaseSRWLockShared(&oot_map_lock);
    return have;
}
int hos_oot_destination(int index, const char **child, const char **adult) {
    if (index < 0 || index >= (int)(sizeof oot_destinations / sizeof oot_destinations[0])) return 0;
    *child = oot_destinations[index].child_banc, *adult = oot_destinations[index].adult_banc;
    return 1;
}
/* The bridge's teleport: asked on its thread, taken at the player's next update (oot_bridge_teleport_take), and what came
   of it kept for the bridge, by ticket. A later ask replaces one not taken yet. (oot_map_lock) */
#define OOT_BRIDGE_AGE 0x10000   /* (oot_bridge_tp.asked: the age switch to the child, | 1 to the adult; not a destination) */
static struct {
    int asked;    /* the destination + 1 waiting to be taken, OOT_BRIDGE_AGE | adult the age switch; 0 none */
    int ticket;   /* the last ask's */
    int taking;   /* the ticket taken by the player's update and not done yet (it is not replaced meanwhile) */
    int done_ticket, result, accepted;   /* the last one taken: 1 sent, -1 refused, 2 (the age switch) Link was that age
                                            already; accepted: the event manager's answer */
    char why[96], map[80];
} oot_bridge_tp;
int hos_oot_teleport_ask(int index) {
    if (index < 0 || index >= (int)(sizeof oot_destinations / sizeof oot_destinations[0])) return 0;
    AcquireSRWLockExclusive(&oot_map_lock);
    const int ticket = ++oot_bridge_tp.ticket;
    __atomic_store_n(&oot_bridge_tp.asked, index + 1, __ATOMIC_RELAXED);   /* (read without the lock first: take) */
    ReleaseSRWLockExclusive(&oot_map_lock);
    return ticket;
}
/* The bridge's age switch to the adult (1) or the child (0): the Debug tab's Switch age (oot_toggle_age), asked and taken as
   a teleport is, with the same tickets, result and cancel. The age wanted goes with it and is checked when it is taken (the
   bridge's sample of Link's age can be old): already that age, nothing is done (result 2) */
int hos_oot_age_ask(int adult) {
    AcquireSRWLockExclusive(&oot_map_lock);
    const int ticket = ++oot_bridge_tp.ticket;
    __atomic_store_n(&oot_bridge_tp.asked, OOT_BRIDGE_AGE | (adult ? 1 : 0), __ATOMIC_RELAXED);
    ReleaseSRWLockExclusive(&oot_map_lock);
    return ticket;
}
/* 1 sent (map: the map it goes to; accepted: whether the game's event manager took the request), -1 refused (why: the
   reason), 2 (the age switch) Link was that age already, nothing done, 0 not taken yet (or being taken), -2 replaced by a
   later ask or cancelled */
int hos_oot_teleport_result(int ticket, char *why, size_t why_cap, char *map, size_t map_cap, int *accepted) {
    AcquireSRWLockShared(&oot_map_lock);
    int r = -2;
    if (oot_bridge_tp.done_ticket == ticket) {
        r = oot_bridge_tp.result, *accepted = oot_bridge_tp.accepted;
        snprintf(why, why_cap, "%s", oot_bridge_tp.why);
        snprintf(map, map_cap, "%s", oot_bridge_tp.map);
    } else if (oot_bridge_tp.taking == ticket || (oot_bridge_tp.ticket == ticket && oot_bridge_tp.asked)) r = 0;
    ReleaseSRWLockShared(&oot_map_lock);
    return r;
}
void hos_oot_teleport_cancel(int ticket) {   /* (the bridge gave up waiting: not taken later behind its back) */
    AcquireSRWLockExclusive(&oot_map_lock);
    if (oot_bridge_tp.ticket == ticket) __atomic_store_n(&oot_bridge_tp.asked, 0, __ATOMIC_RELAXED);
    ReleaseSRWLockExclusive(&oot_map_lock);
}
static int oot_bridge_teleport_take(int *ticket) {   /* (the player's update) the destination + 1 asked for, or 0 */
    if (!__atomic_load_n(&oot_bridge_tp.asked, __ATOMIC_RELAXED)) return 0;
    AcquireSRWLockExclusive(&oot_map_lock);
    const int asked = oot_bridge_tp.asked;
    *ticket = oot_bridge_tp.ticket;
    if (asked) oot_bridge_tp.taking = *ticket;   /* (still "not taken yet" to the bridge until done) */
    __atomic_store_n(&oot_bridge_tp.asked, 0, __ATOMIC_RELAXED);
    ReleaseSRWLockExclusive(&oot_map_lock);
    return asked;
}
static void oot_bridge_teleport_done(int ticket, int sent) {   /* sent: 1, 0 refused (teleport.why), 2 already that age */
    AcquireSRWLockExclusive(&oot_map_lock);
    if (sent == 2) {
        oot_bridge_tp.done_ticket = ticket, oot_bridge_tp.result = 2, oot_bridge_tp.taking = 0, oot_bridge_tp.accepted = 0;
        oot_bridge_tp.why[0] = oot_bridge_tp.map[0] = 0;
        ReleaseSRWLockExclusive(&oot_map_lock);
        return;
    }
    oot_bridge_tp.done_ticket = ticket, oot_bridge_tp.result = sent ? 1 : -1, oot_bridge_tp.taking = 0;
    oot_bridge_tp.accepted = sent && teleport.result != 0;
    snprintf(oot_bridge_tp.why, sizeof oot_bridge_tp.why, "%s", sent || !teleport.why ? "" : teleport.why);
    snprintf(oot_bridge_tp.map, sizeof oot_bridge_tp.map, "%s", sent && teleport.banc ? teleport.banc : "");
    ReleaseSRWLockExclusive(&oot_map_lock);
}

static uint64_t oot_gameplay_view(Ctx *c) {
    const uint64_t singleton = recomp_load64(c, 0x84ca6bc0ULL);
    const uint64_t manager = singleton ? recomp_load64(c, singleton) : 0;
    const uint64_t cameras = manager && recomp_load32(c, manager + 32) ? recomp_load64(c, manager + 40) : 0;
    const uint64_t camera = cameras ? recomp_load64(c, cameras) : 0;
    return camera ? recomp_load64(c, camera + 120) : 0;
}

static float oot_load_float(Ctx *c, uint64_t addr) {
    const uint32_t bits = recomp_load32(c, addr);
    float value;
    memcpy(&value, &bits, sizeof value);
    return value;
}

static _Thread_local uint64_t flight_transform_controller;
static _Thread_local uint64_t flight_pose_actor;
static _Thread_local float flight_transform_yaw;
static int64_t flight_player_seen;

/* Link's controller (vtable 0x84c54f10, the one OneShotPhysicsCctChangePosition moves) from his components, 0 when the chain
   is not there */
static uint64_t oot_player_controller(Ctx *c, uint64_t components) {
    const unsigned offsets[] = {80, 32, 16, 8};
    uint64_t controller = components;
    for (unsigned i = 0; i < sizeof offsets / sizeof offsets[0]; i++) {
        controller = recomp_load64(c, controller + offsets[i]);
        if (!controller) return 0;
    }
    return recomp_load64(c, controller) == 0x84c54f10ULL ? controller : 0;
}

/* Movement speed (the Debug tab's row, HOS_OPT_CHEAT_SPEED in percent): Link's controller and the percent for
   hos_oot_cct_speed, which scales the forward speed the game sets on it. (The controller's speed rate beside it, +476, is no
   use: the game sets it again before each step.) */
static void oot_player_speed(Ctx *c, uint64_t components) {
    int rx_option(int id, int otherwise);
    static int logged = 100;
    int percent = rx_option(HOS_OPT_CHEAT_SPEED, 100);
    if (percent < 100 || percent > 400) percent = 100;
    __atomic_store_n(&oot_speed_controller, percent > 100 ? oot_player_controller(c, components) : 0, __ATOMIC_RELAXED);
    __atomic_store_n(&oot_speed_percent, percent, __ATOMIC_RELAXED);
    if (percent != logged) hos_log("cheats: movement speed %d%%", percent);
    logged = percent;
}

/* Whether the game moved Link since the flight last placed him: he is more than 2 units (the flight moves him 4 a second)
   from where it holds him. A respawn after a fall or a warp keeps his actor, so the flight took him straight back to
   where it had him, over the same drop: he fell, respawned and fell again until the flight was switched off. It starts
   again from where the game put him instead. */
static int oot_flight_moved_away(Ctx *c, uint64_t actor, const float held[3]) {
    float apart = 0;
    for (unsigned i = 0; i < 3; i++) {
        const float d = oot_load_float(c, actor + 796 + i * 4) - held[i];
        apart += d * d;
    }
    return apart > 2.0f * 2.0f;
}

/* (the randomizer's fork) a map (banc: "KokiriForest_Child", "HyruleCastle") is of a Banc folder ("KokiriForest") */
static int oot_banc_in_folder(const char *banc, const char *folder) {
    const size_t n = strlen(folder);
    return n && !strncmp(banc, folder, n) && (!banc[n] || banc[n] == '_');
}

/* (the randomizer's fork) <game folder>/rando/<name>, into out: 1, or 0 when the game's folder is not known */
static int oot_place_file(char *out, size_t size, const char *name) {
    char exe[MAX_PATH];
    const DWORD n = hos_game_path_a(exe, MAX_PATH);
    if (!n || n >= MAX_PATH) return 0;
    char *slash = strrchr(exe, '\\');
    char *other = strrchr(exe, '/');
    if (other > slash) slash = other;
    if (!slash) return 0;
    *slash = 0;
    snprintf(out, size, "%s/rando/%s", exe, name);
    return 1;
}

/* (the randomizer's fork) Skip cutscenes: the game's own skip, asked of a cutscene as soon as it plays. An event (the
   event manager's current one, +104) has a list of players (+3768, count +3760) and plays one of them (+3864): its
   flowchart, or a cutscene the flowchart started. A player's name is at +8, and a cutscene's player is of the class
   OOT_TIMELINE_PLAYER (a flowchart's is another). The skip is the game's sequence action
   SeqOneShotEventRequestForceSkip (f_832f1890): the player's +544, whose twelfth virtual function (+88) it calls.
   Only a cutscene is skipped: asked of a flowchart the skip ends the whole event before its steps have run (the event
   of Saria's goodbye started over and over, seen without a window). With a cutscene skipped its flowchart goes on: the
   talk after Saria's goodbye played and the ocarina was given. Asked again each half second while the cutscene still
   plays (the skip fades out first). Not asked of the events the game itself lets nobody skip (its three
   EventSettingComponentLists with a SkipSetting), nor of the title's and the credits'.
   HOS_OOT_SKIP_EVENTS=1 is the setting on, 2 only logs each event and the player it plays. */
#define OOT_TIMELINE_PLAYER 0x84c82d58ULL
/* (a video's player, "RecordMovieTimelineEvent": the goddesses' story in Zelda's courtyard, Dm_HrlCastle_0045, and the
   other videos of Event/Movie. Seen in the owner's log of 2026-11-15 as "not a cutscene (class 84c82c88)": it played.
   The skip asked of it does nothing (tried without a window: the video played its 40 seconds, and the buttons did
   nothing either), so it is only named in the log; the seed passes over the step that starts it, SCENE_VIDEOS) */
#define OOT_MOVIE_PLAYER 0x84c82c88ULL
int hos_rando_skip_cutscenes(void);   /* host/oot_rando.c */
static int oot_cutscene_kept(const char *name) {
    static const char *const kept[] = {"Dm_Title", "Dm_StaffCredit", "Dm_Kokiri_0000", "Dm_SY_"};
    for (size_t i = 0; i < sizeof kept / sizeof kept[0]; i++)
        if (!strncmp(name, kept[i], strlen(kept[i]))) return 1;
    return 0;
}

static void oot_skip_cutscene_locked(Ctx *c);
/* (asked from Link's update and from the gameplay camera's view each frame, hos_oot_free_view: a cutscene without Link,
   the Deku Tree's story of Ganondorf after Gohma (Dm_Kokiri_0090), was asked once at its start and played its 45 s,
   bug 30: Link's update did not run again until it ended. One caller at a time) */
static void oot_skip_cutscene(Ctx *c) {
    static SRWLOCK lock = SRWLOCK_INIT;
    if (!TryAcquireSRWLockExclusive(&lock)) return;
    oot_skip_cutscene_locked(c);
    ReleaseSRWLockExclusive(&lock);
}
static void oot_skip_cutscene_locked(Ctx *c) {
    static uint64_t was_event, was_player;
    static int64_t asked_at;
    static int env = -1;
    if (env < 0) env = getenv("HOS_OOT_SKIP_EVENTS") ? atoi(getenv("HOS_OOT_SKIP_EVENTS")) : 0;
    if (!env && !hos_rando_skip_cutscenes()) return;
    const uint64_t events = oot_singleton(c, OOT_EVENTMGR_SLOT);
    const uint64_t event = events ? recomp_load64(c, events + 104) : 0;
    if (!event) {
        was_event = was_player = 0;
        return;
    }
    const uint64_t list = recomp_load64(c, event + 3768);
    const uint32_t count = recomp_load32(c, event + 3760), at = recomp_load32(c, event + 3864);
    const uint64_t player = list && at < count ? recomp_load64(c, list + 8ULL * at) : 0;
    if (!player) return;
    const uint64_t kind = recomp_load64(c, player);
    const int cutscene = kind == OOT_TIMELINE_PLAYER;
    const int is_new = event != was_event || player != was_player;
    if (!cutscene && !is_new) {
        return;
    }
    char name[64] = "";
    const uint64_t text = recomp_load64(c, player + 8);
    for (int n = 0; text && n < 63; n++) {
        name[n] = (char)recomp_load8(c, text + n), name[n + 1] = 0;
        if (!name[n]) break;
    }
    /* (every player an event starts is logged, with its class when it is not a cutscene's: a log then lists what plays
       and what is not skipped, without HOS_OOT_SKIP_EVENTS) */
    if (is_new) {
        if (cutscene) hos_log("rando: event: player %u of %u, \"%s\": a cutscene", at, count, name);
        else if (kind == OOT_MOVIE_PLAYER) hos_log("rando: event: player %u of %u, \"%s\": a video (not skipped here: the seed leaves it out)", at, count, name);
        else hos_log("rando: event: player %u of %u, \"%s\": not a cutscene (class %llx)", at, count, name,
                     (unsigned long long)recomp_load64(c, player));
    }
    was_event = event, was_player = player;
    if (env == 2 || !cutscene || oot_cutscene_kept(name)) return;
    const int64_t now = hos_now_ns();
    if (!is_new && now - asked_at < 500000000LL) return;
    asked_at = now;
    const uint64_t line = recomp_load64(c, player + 544);
    const uint64_t skip = line ? recomp_load64(c, recomp_load64(c, line) + 88) : 0;
    A64Fn fn = skip ? a64_lookup(skip) : 0;
    if (is_new) hos_log("rando: the cutscene %s is skipped%s", name, fn ? "" : " (no skip found: it plays)");
    if (!fn) return;
    const Ctx saved = *c;
    c->x[31] = (c->x[31] - 0x200) & ~0xfULL;
    c->x[0] = line;
    fn(c);
    *c = saved;
}

static void oot_update_player_cheats(Ctx *c, uint64_t actor, uint64_t components) {
    int rx_option(int id, int otherwise);
    oot_skip_cutscene(c);
    for (int k = 0; k < (int)OOT_FILLS; k++) {   /* (a bag found is a full bag: oot_fill_note) */
        if (__atomic_load_n(&oot_fill_wait[k], __ATOMIC_ACQUIRE) <= 0) continue;
        if (__atomic_sub_fetch(&oot_fill_wait[k], 1, __ATOMIC_RELEASE) > 0) continue;
        const char *holds = oot_fills[k][1];
        if (!oot_fill_bagged[k]) {   /* (a bow or a Slingshot with nothing to carry its ammunition in: oot_fill_bags) */
            oot_fill_bagged[k] = 1;
            int given = 0;
            for (unsigned b = 0; b < sizeof oot_fill_bags / sizeof oot_fill_bags[0] && !given; b++) {
                if (strcmp(holds, oot_fill_bags[b][0])) continue;
                int has = 0;
                for (int t = 1; t < 4; t++) has += oot_pouch_count(c, oot_fill_bags[b][t]) > 0;
                if (has) break;
                given = oot_pouch_change(c, oot_fill_bags[b][1], 1) >= 0;
                hos_log("rando: Link has nothing to carry %s in: %s is %s", holds, oot_fill_bags[b][1], given ? "given" : "NOT GIVEN");
            }
            if (given) {   /* (the fill after the carrier is in the pouch) */
                __atomic_store_n(&oot_fill_wait[k], OOT_FILL_WAIT, __ATOMIC_RELEASE);
                continue;
            }
        }
        const int now = oot_pouch_count(c, holds);
        /* (until the count stops going up: the bag is full. The first add is made whatever the count; each after it
           when the one before raised it) */
        if ((oot_fill_last[k] < 0 || now > oot_fill_last[k]) && oot_fill_adds[k] < OOT_FILL_STEPS &&
            oot_pouch_change(c, holds, strcmp(holds, OOT_FILL_RUPEES) ? OOT_FILL_STEP : 1) >= 0) {
            oot_fill_last[k] = now, oot_fill_adds[k]++;
            __atomic_store_n(&oot_fill_wait[k], OOT_FILL_APART, __ATOMIC_RELEASE);
            continue;
        }
        hos_log("rando: %s filled: Link has %d (%d adds)", holds, now, oot_fill_adds[k]);
    }
    if (__atomic_load_n(&oot_piece_back, __ATOMIC_ACQUIRE) > 0) {   /* (Heart Pieces: hos_oot_pouch_add) */
        const int left = __atomic_sub_fetch(&oot_piece_back, 1, __ATOMIC_RELEASE);
        if (!(left % 4) && oot_pouch_count(c, OOT_PIECE) > 0) {
            const int result = oot_pouch_change(c, OOT_PIECE, -1);
            __atomic_store_n(&oot_piece_back, 0, __ATOMIC_RELEASE);
            hos_log("rando: the Piece of Heart counted with the seed's item is taken out (%d)", result);
        }
    }
    {   /* (bug 31: Link's max life followed, and a boss container's heart taken back: oot_container_back) */
        int32_t max;
        if (oot_gamedata_int(c, OOT_MAX_LIFE, &max, 0)) {
            if (max > oot_max_now && oot_max_now >= 0) oot_max_was = oot_max_now, oot_max_rose = hos_now_ns();
            oot_max_now = max;
            const int32_t keep = __atomic_load_n(&oot_container_max, __ATOMIC_RELAXED);
            if (__atomic_load_n(&oot_container_back, __ATOMIC_ACQUIRE) > 0) {
                __atomic_sub_fetch(&oot_container_back, 1, __ATOMIC_RELEASE);
                if (keep > 0 && max > keep) {
                    int32_t life, was = max, to = keep;
                    oot_gamedata_int(c, OOT_MAX_LIFE, &to, 1);
                    if (oot_gamedata_int(c, OOT_LIFE, &life, 0) && life > keep) oot_gamedata_int(c, OOT_LIFE, &to, 1);
                    oot_max_now = keep;
                    hos_log("rando: the boss's Heart Container's heart is taken back (max life %d -> %d quarters)", was, keep);
                }
            }
        }
    }
    if (getenv("HOS_OOT_PIECES")) {   /* (a test's: the count as it changes) */
        static int last = -2, turn;
        if (!(turn++ % 4)) {
            const int now = oot_pouch_count(c, OOT_PIECE);
            if (now != last) hos_log("rando: Pieces of Heart in the pouch: %d -> %d", last, now), last = now;
        }
    }
    static uint64_t flying_actor, marked_actor, marked_controller;
    static int64_t last_tick, last_player_tick, hold_until, trace_until, trace_next;
    static const char *boss_event;   /* (a boss room's fight, asked for after Link is put there: oot_boss_rooms) */
    static int64_t boss_event_at;
    /* (the randomizer's fork) the Tracker tab's Go there: a check's place and its map's folder, read from
       <game folder>/rando/goto_check.txt at the action 5. waiting: the teleport to that map was sent, and the place is
       taken once Link is in it with no event playing and no map loading for a second and a half. */
    static struct {
        float place[3];
        char folder[40], ages[8];
        int waiting;
        int64_t until, settled;
    } check;
    int go = 0, boss = -1;
    static float target[3], velocity[3], mark[3], yaw;
    int flying = rx_option(HOS_OPT_CHEAT_FLIGHT, 0) > 0;
    /* An event that takes Link (a map change he flew into, the age toggle's, a cutscene) waits for him to stand, and the
       flight holds him in the air: the screen the event had faded stayed black until the flight was switched off, and a
       second request met "waits until the current event ends". While an event plays he is let go and lands; the flight
       takes him again, from where he then stands, when it has ended. */
    if (flying && oot_event_playing(c)) flying = 0;
    if (!flying) flying_actor = 0;
    const int64_t now = hos_now_ns();
    __atomic_store_n(&flight_player_seen, now, __ATOMIC_RELAXED);
    if (marked_actor != actor || now - last_player_tick > 2000000000LL) marked_controller = 0;
    last_player_tick = now;
    int action = rx_option(HOS_OPT_CHEAT_ACTION, 0);
    if (!action) action = __atomic_exchange_n(&hos_oot_live_action, 0, __ATOMIC_RELAXED);
    int bridge_ticket = 0;   /* (the control bridge's teleport or age switch, host/control.c: what came of it is kept for its reply) */
    int bridge_adult = -1;   /* (the bridge's age switch: the age wanted, 1 the adult) */
    if (!action) {
        const int asked = oot_bridge_teleport_take(&bridge_ticket);
        if (asked & OOT_BRIDGE_AGE) action = OOT_AGE_ACTION, bridge_adult = asked & 1;
        else if (asked) action = OOT_TELEPORT_ACTION + asked - 1;
    }
    oot_teleport_followup(c);
    oot_piece_heal(c, now, recomp_load64(c, components + 800) - 0x1d50);   /* (Link's own actor: hos_oot_lift_player) */
    oot_inventory_refresh(c, now);
    oot_tracker_refresh(c, now, actor);
    oot_time_door(c, now, actor);
    oot_ganon_bridge(c, now);
    oot_player_speed(c, components);
    oot_map_refresh(c, now);
    {   /* (a test's: HOS_OOT_CLOCK_LOG=1 logs the world's clock every 5 seconds: the object at the world manager's +0x510,
           which ExecuteWmSetTime's set call reads, its words at +0x28 (seconds in the day) and +0x2c (days): bug 81, the
           night that stood still) */
        static int on = -1;
        static int64_t next_at;
        if (on < 0) { const char *e = getenv("HOS_OOT_CLOCK_LOG"); on = e && *e == '1'; }
        if (on && now >= next_at) {
            next_at = now + 5000000000LL;
            const uint64_t singleton = recomp_load64(c, 0x84c9e898ULL);
            const uint64_t world = singleton ? recomp_load64(c, singleton) : 0;
            const uint64_t clock = world ? recomp_load64(c, world + 0x510) : 0;
            if (clock)
                hos_log("test: clock +0x20..0x3c: %d %d %d %d %d %d %d %d", (int)recomp_load32(c, clock + 0x20), (int)recomp_load32(c, clock + 0x24),
                        (int)recomp_load32(c, clock + 0x28), (int)recomp_load32(c, clock + 0x2c), (int)recomp_load32(c, clock + 0x30),
                        (int)recomp_load32(c, clock + 0x34), (int)recomp_load32(c, clock + 0x38), (int)recomp_load32(c, clock + 0x3c));
            hos_log("test: Link at %.1f %.1f %.1f", oot_link_place[0], oot_link_place[1], oot_link_place[2]);   /* (to go back there) */
        }
    }
    if (action >= OOT_CHEAT_ITEM_ACTION && action < OOT_CHEAT_ITEM_ACTION + 256 * (int)OOT_ITEM_COUNT) {
        oot_inventory_edit(c, action);
    } else if (action == OOT_AGE_ACTION) {
        int child = 1;   /* (the bridge's: Link's age now, not its sample's; already the age wanted, nothing to flip) */
        if (bridge_adult >= 0 && oot_gamedata_bool(c, 0xcea220d3u, &child) && !child == bridge_adult) {
            hos_log("cheats: age toggle: Link is the %s already", child ? "child" : "adult");
            oot_bridge_teleport_done(bridge_ticket, 2);
        } else {
            const int sent = oot_toggle_age(c, actor);
            if (bridge_ticket) oot_bridge_teleport_done(bridge_ticket, sent);
        }
    } else if (action >= OOT_TELEPORT_ACTION + (int)OOT_DESTINATIONS && action < OOT_TELEPORT_ACTION + (int)(OOT_DESTINATIONS + OOT_BOSS_ROOMS)) {
        boss = action - OOT_TELEPORT_ACTION - (int)OOT_DESTINATIONS;   /* (a boss's room: taken below, as Go there) */
    } else if (action >= OOT_TELEPORT_ACTION) {
        const int sent = oot_teleport(c, actor, (unsigned)(action - OOT_TELEPORT_ACTION));
        if (bridge_ticket) oot_bridge_teleport_done(bridge_ticket, sent);
    } else if (action >= 200) {
        oot_edit_pouch(c, action);
    } else if (action == 6) {   /* (the Tracker tab's first row: forget what is collected) */
        if (hos_rando_on()) oot_tracker_forget();
    } else if (action == 7) {   /* (the Tracker tab's Return home: a child to the Kokiri Forest, an adult to the Market. The
                                   randomizer's own way out of a place with no way back, the Colossus by the Requiem alone:
                                   not a debug tool, so with the debug tools off too) */
        if (hos_rando_on()) {
            int child = 1;
            oot_gamedata_bool(c, 0xcea220d3u, &child);   /* Sequence_IsChildhood */
            const char *home = child ? "KokiriForest_Child" : "Market_Adult";
            unsigned index = 0;
            const unsigned count = sizeof oot_destinations / sizeof oot_destinations[0];
            for (; index < count; index++) {
                const char *banc = child ? oot_destinations[index].child_banc : oot_destinations[index].adult_banc;
                if (banc && !strcmp(banc, home)) break;
            }
            hos_log("rando: return home: %s (%s)", home, index == count ? "the teleport has no such map" : oot_teleport(c, actor, index) ? "sent" : "NOT SENT");
        }
    } else if (action >= 100 && action < 124) {
        oot_set_time(c, action - 100);
    }
    /* (the randomizer's tools are the randomizer's: the Tracker tab's Go there and the place in rando\goto.txt do nothing
       in the normal game or in Master Quest) */
    if ((action == 5 && hos_rando_on()) || boss >= 0) {   /* (a boss's room is a debug tool's: in any game) */
        char path[MAX_PATH + 32], current[80];
        int read = 0;
        if (boss >= 0) {
            const OotBossRoom *room = &oot_boss_rooms[boss];
            memcpy(check.place, room->place, sizeof check.place);
            snprintf(check.folder, sizeof check.folder, "%s", room->folder);
            snprintf(check.ages, sizeof check.ages, "%s", room->ages);
            read = 5;
            boss_event = room->event, boss_event_at = 0;
            if (room->seen) oot_gamedata_set_bool(c, room->seen, 1);
            hos_log("cheats: boss room %d: %s", boss, room->folder);
        } else {
            FILE *f = oot_place_file(path, sizeof path, "goto_check.txt") ? fopen(path, "r") : NULL;
            read = f ? fscanf(f, "%f %f %f %39s %7s", &check.place[0], &check.place[1], &check.place[2], check.folder, check.ages) : 0;
            if (f) fclose(f);
        }
        check.waiting = 0;
        int child = 1;
        oot_gamedata_bool(c, 0xcea220d3u, &child);   /* Sequence_IsChildhood */
        oot_gamedata_string(c, 0x1d6189dau, current, sizeof current);   /* Sequence_CurrentBanc */
        if (read != 5) {
            hos_log("cheats: go to a check: rando/goto_check.txt does not say one");
        } else if (!strchr(check.ages, child ? 'C' : 'A')) {
            hos_log("cheats: go to a check: %s's map of %s does not have it (change Link's age first)", child ? "the child" : "the adult", check.folder);
        } else if (oot_banc_in_folder(current, check.folder)) {
            go = 1;
        } else {
            unsigned index = 0;
            const unsigned count = sizeof oot_destinations / sizeof oot_destinations[0];
            for (; index < count; index++) {
                const char *banc = child ? oot_destinations[index].child_banc : oot_destinations[index].adult_banc;
                if (banc && oot_banc_in_folder(banc, check.folder)) break;
            }
            if (index == count) hos_log("cheats: go to a check: the teleport has no map of %s", check.folder);
            else if (oot_teleport(c, actor, index)) check.waiting = 1, check.until = now + 60000000000LL, check.settled = 0;
        }
    } else if (check.waiting) {
        char current[80];
        int loading = 0;
        oot_gamedata_string(c, 0x1d6189dau, current, sizeof current);
        oot_gamedata_bool(c, 0xef2b60c2u, &loading);   /* Sequence_IsLoadingBanc */
        if (now > check.until) {
            check.waiting = 0;
            hos_log("cheats: go to a check: Link did not arrive in %s (in \"%s\")", check.folder, current);
        } else if (!oot_banc_in_folder(current, check.folder) || loading || oot_event_playing(c)) {
            check.settled = 0;
        } else if (!check.settled) {
            check.settled = now;
        } else if (now - check.settled > (boss_event ? 5000000000LL : 1500000000LL)) {
            /* (a boss room's: five seconds, so a dungeon's arrival scene has begun and ended first. The Water Temple's,
               Goto_WaterTemple, began after a second and a half and walked Link to the entrance, which he never reached
               from Morpha's room: the camera stayed on it and Link could not be moved; the owner, 2026-11-16) */
            check.waiting = 0, go = 1;
        }
    }
    if (boss_event && boss_event_at && now >= boss_event_at && !oot_event_playing(c)) {   /* (a boss room's fight: above) */
        hos_log("cheats: boss room: the fight's event %s %s", boss_event, oot_event_request(c, actor, boss_event) ? "asked for" : "NOT SENT");
        boss_event = NULL, boss_event_at = 0;
    }
    if (now < trace_until && now >= trace_next) {   /* (where Link is, twice a second, for a while after a go-to) */
        trace_next = now + 500000000LL;
        hos_log("cheats: go-to trace: Link at %.2f %.2f %.2f%s", oot_load_float(c, actor + 796), oot_load_float(c, actor + 800),
                oot_load_float(c, actor + 804), now < hold_until ? " (held)" : "");
    }
    if (!flying && action != 2 && action != 3 && !go && now >= hold_until) return;

    // Follow OneShotPhysicsCctChangePosition to Link's controller.
    const uint64_t controller = oot_player_controller(c, components);
    if (!controller || recomp_load64(c, 0x84c54f10ULL + 0xe8) != 0x806d2530ULL) return;
    A64Fn change_position = a64_lookup(0x806d2530ULL);
    if (!change_position) return;

    if (action == 2) {
        for (unsigned i = 0; i < 3; i++) {
            const uint32_t bits = recomp_load32(c, actor + 796 + i * 4);
            memcpy(&mark[i], &bits, sizeof bits);
        }
        marked_actor = actor;
        marked_controller = controller;
        hos_log("cheats: marked position %.2f %.2f %.2f", mark[0], mark[1], mark[2]);
        {   /* (the randomizer's fork) and written beside the game, <game folder>/rando/position.txt: where Link stands, in
               the map files' own coordinates, for finding what a map file has at a place */
            char path[MAX_PATH + 32];
            FILE *f = oot_place_file(path, sizeof path, "position.txt") ? fopen(path, "w") : NULL;
            if (f) fprintf(f, "%.2f %.2f %.2f\n", mark[0], mark[1], mark[2]), fclose(f);
        }
    }
    if (action == 3) {
        /* (the randomizer's fork) Return to mark goes to the place written in <game folder>/rando/goto.txt, "x y z" in the
           map files' coordinates, when that file says another place than the last one taken from it: a map's actor (a
           Business Scrub, a chest) is reached by its coordinates. A place marked after that is the mark again. */
        static char taken[96];
        char path[MAX_PATH + 32], line[96] = "";
        FILE *f = hos_rando_on() && oot_place_file(path, sizeof path, "goto.txt") ? fopen(path, "r") : NULL;
        if (f) {
            float place[3], hold = 3;
            if (fgets(line, sizeof line, f) && strcmp(line, taken) && sscanf(line, "%f %f %f %f", &place[0], &place[1], &place[2], &hold) >= 3) {
                memcpy(mark, place, sizeof mark);
                memcpy(taken, line, sizeof taken);
                marked_actor = actor;
                marked_controller = controller;
                /* A place far from where Link stood has no ground yet (seen in play: he fell out of the map and was put
                   back, a heart less): he is held there for three seconds, while the map around him is loaded. */
                hold_until = now + (int64_t)(fminf(fmaxf(hold, 0), 60) * 1e9f);
                trace_until = hold_until + 8000000000LL, trace_next = 0;
                hos_log("cheats: the mark is rando/goto.txt's place, %.2f %.2f %.2f", mark[0], mark[1], mark[2]);
            }
            fclose(f);
        }
    }
    if (go) {   /* (the check's place is the mark, and Link is held there as at a go-to) */
        memcpy(mark, check.place, sizeof mark);
        marked_actor = actor;
        marked_controller = controller;
        hold_until = now + 3000000000LL;
        trace_until = hold_until + 8000000000LL, trace_next = 0;
        hos_log("cheats: go to a check: %s, %.2f %.2f %.2f", check.folder, mark[0], mark[1], mark[2]);
        if (boss_event) boss_event_at = hold_until + 1000000000LL;   /* (the boss's event, once he has been held there) */
    }
    if (action == 2 || marked_controller != controller) hold_until = 0;
    const int returning = (action == 3 || go || now < hold_until) && marked_controller == controller;
    if (action == 3 && !returning) hos_log("cheats: no mark for this player controller");
    if (!flying && !returning) return;
    const int64_t elapsed = now - last_tick;
    if (flying_actor != actor)
        yaw = atan2f(oot_load_float(c, actor + 816), oot_load_float(c, actor + 840));
    if (returning) {
        memcpy(target, mark, sizeof target);
        memset(velocity, 0, sizeof velocity);
        flying_actor = flying ? actor : 0;
    } else if (flying_actor != actor || elapsed < 0 || elapsed > 250000000 || oot_flight_moved_away(c, actor, target)) {
        for (unsigned i = 0; i < 3; i++) target[i] = oot_load_float(c, actor + 796 + i * 4);
        memset(velocity, 0, sizeof velocity);
        flying_actor = actor;
        last_tick = now;
        return;
    } else if (elapsed == 0) {
        return;
    }
    last_tick = now;

    DWORD foreground = 0;
    GetWindowThreadProcessId(GetForegroundWindow(), &foreground);
    if (!returning) {
        const float dt = fminf((float)elapsed * 1e-9f, 0.05f);
        float desired[3] = {0};
        if (foreground == GetCurrentProcessId() && !rx_option(1, 0) && !rx_option(HOS_OPT_CHEAT_CAMERA, 0)) {
            uint64_t hos_flight_input(void);
            const uint64_t axes = hos_flight_input();
            const float right = (int16_t)axes / 32767.0f, forward = (int16_t)(axes >> 16) / 32767.0f;
            const int vertical = (GetAsyncKeyState(VK_PRIOR) < 0) - (GetAsyncKeyState(VK_NEXT) < 0);
            const uint64_t view = oot_gameplay_view(c);
            float rx = 1, rz = 0;
            if (view && recomp_load64(c, view) == 0x84c18a88ULL) {
                const float x = oot_load_float(c, view + 8), z = oot_load_float(c, view + 16);
                const float length = hypotf(x, z);
                if (length > 0.01f) rx = x / length, rz = z / length;
            }
            desired[0] = rx * right + rz * forward;
            desired[1] = vertical ? vertical : (int16_t)(axes >> 32);
            desired[2] = rz * right - rx * forward;
        }
        const float length = sqrtf(desired[0] * desired[0] + desired[1] * desired[1] + desired[2] * desired[2]);
        const float speed = 4.0f / fmaxf(1.0f, length);
        const float blend = 1.0f - expf(-12.0f * dt);
        for (unsigned i = 0; i < 3; i++) {
            velocity[i] += (desired[i] * speed - velocity[i]) * blend;
            target[i] += velocity[i] * dt;
        }
        if (hypotf(desired[0], desired[2]) > 0.08f) {
            const float delta = remainderf(atan2f(desired[0], desired[2]) - yaw, 6.28318531f);
            yaw += fmaxf(-8.0f * dt, fminf(delta, 8.0f * dt));
        }
    }

    const Ctx saved = *c;
    const uint64_t arg = c->x[31] - 16;
    for (unsigned i = 0; i < 3; i++) {
        uint32_t bits;
        memcpy(&bits, &target[i], sizeof bits);
        recomp_store32_sp(c, arg + i * 4, bits);
    }
    recomp_store32_sp(c, arg + 12, 0);
    c->x[31] = arg;
    c->x[0] = controller;
    c->x[1] = arg;
    flight_transform_yaw = yaw;
    flight_pose_actor = flying && !returning ? actor : 0;
    flight_transform_controller = flying && !returning ? controller : 0;
    change_position(c);
    flight_transform_controller = 0;
    *c = saved;
    if ((action == 3 || go) && returning) hos_log("cheats: returned to %.2f %.2f %.2f", mark[0], mark[1], mark[2]);
}
#endif

int hos_oot_player_seen(void) {
#if defined(_WIN32) || defined(__linux__)   /* (the debug tools: host/posix has what they call) */
    const int64_t seen = __atomic_load_n(&flight_player_seen, __ATOMIC_RELAXED);
    return seen && hos_now_ns() - seen < 250000000;
#else
    return 0;
#endif
}

int hos_oot_flight_shortcut_ready(void) {
    return hos_oot_player_seen();
}

#if defined(_WIN32) || defined(__linux__)   /* (the debug tools: host/posix has what they call) */
static void oot_write_flight_rotation(Ctx *c, uint64_t matrix) {
    const float s = sinf(flight_transform_yaw), co = cosf(flight_transform_yaw);
    const float rotation[3][3] = {{co, 0, s}, {0, 1, 0}, {-s, 0, co}};
    for (unsigned row = 0; row < 3; row++) {
        for (unsigned col = 0; col < 3; col++) {
            uint32_t bits;
            memcpy(&bits, &rotation[row][col], sizeof bits);
            recomp_store32(c, matrix + row * 16 + col * 4, bits);
        }
    }
}
#endif

void hos_oot_flight_rotation(Ctx *c, uint64_t controller, uint64_t matrix) {
#if defined(_WIN32) || defined(__linux__)   /* (the debug tools: host/posix has what they call) */
    if (flight_transform_controller == controller) oot_write_flight_rotation(c, matrix);
#else
    (void)c;
    (void)controller;
    (void)matrix;
#endif
}

void hos_oot_flight_pose(Ctx *c, uint64_t actor, uint64_t matrix) {
#if defined(_WIN32) || defined(__linux__)   /* (the debug tools: host/posix has what they call) */
    if (flight_pose_actor == actor) {
        flight_pose_actor = 0;
        oot_write_flight_rotation(c, matrix);
    }
#else
    (void)c;
    (void)actor;
    (void)matrix;
#endif
}

/* (the randomizer's fork) Progressive items. f_8112d570 is the pouch manager's add: x0 the manager, x1 a string view of
   the content's actor name ({the text, its room as a 32-bit number}), x2 how many (the event action
   OneShotAddOrRemovePouchContent, f_828d4a70, calls it so, and a dozen other places do). nx2/oot_patches.py calls this at
   its start. With the setting on, an upgrade of a family on its way into the pouch is made the next of the family that
   Link has not: he has the Silver Gauntlets' place in the family when he carries them or the Golden ones (a bigger one
   may take the smaller one's place in the pouch). The name is not written over where it is (it may be the game's own
   text): the call is given a view of its own, in memory that stays. What the chest's scene shows and says is the item
   it was shuffled as; what is put in the pouch is this. A name given in two spellings (the item's and the pouch's)
   is answered in the one it came in. */
/* And the Bomb Bag the game gives with bombs. A chest's bombs, when Link has no bag, are got in three adds (seen in the
   log of a game, twice): the event action adds Item_BombBag_Small (from 0x828d50ac, x4 2, x7 0), the bag is filled
   (Item_Bomb, 20), then the action adds the bundle as every chest's item is added (x4 7, x7 1). The first is the
   game's own kindness and gave the randomizer's gating item for five bombs: with the randomizer on it is not made
   (1 is returned, and the add is left at once with nothing added), so the bombs find no bag and are not kept, as
   bombs dropped by a Gold Skulltula are not. A Bomb Bag of a chest's own comes as the bundle does and is added.
   x3 is how many (20, 5, 1); x2 is not. */
int hos_rando_progressive(void);   /* host/oot_rando.c */
int hos_rando_on(void);   /* (host/oot_rando.c: the randomizer is on) */
#if defined(_WIN32) || defined(__linux__)
/* The add's content made `give`: the call is given a view of its own, in memory that stays (the name is not written
   over where it is: it may be the game's own text). Returns the view the call has now. */
static uint64_t oot_pouch_name(Ctx *c, uint64_t view, const char *give) {
    static uint64_t blocks;
    static unsigned turn;
    if (!blocks) blocks = hos_sys_alloc(8 * 256, 16);
    if (!blocks) return view;
    const uint64_t block = blocks + (uint64_t)(__atomic_fetch_add(&turn, 1, __ATOMIC_RELAXED) % 8) * 256;
    memcpy(A64_PTR(block), A64_PTR(view - 16), 64);   /* (the view as it is, with what is before it: a string object's start) */
    memcpy(A64_PTR(block + 96), give, strlen(give) + 1);
    recomp_store64(c, block + 16, block + 96);
    recomp_store32(c, block + 24, 128);
    c->x[1] = block + 16;
    return block + 16;
}
#endif
#if defined(_WIN32) || defined(__linux__)
/* With Progressive items: what a content of a family gives Link now, the next of the family he has not (by the
   spelling it was named by); NULL when it is of no family, or he has the family whole (it is given as it is). */
static const char *oot_progressive_give(Ctx *c, const char *name) {
    int spelling = 0;
    const int f = oot_family_of(name, &spelling);
    if (f < 0) return NULL;
    int tiers = 0;
    while (tiers < 3 && oot_families[f][tiers][0]) tiers++;
    int level = 0;   /* (how many of the family Link has: the highest he carries, and all under it) */
    for (int t = tiers - 1; t >= 0 && !level; t--)
        for (int a = 0; a < 2; a++)
            if (oot_families[f][t][a] && oot_pouch_count(c, oot_families[f][t][a]) > 0) level = t + 1;
    if (level >= tiers) return NULL;
    return oot_families[f][level][spelling] ? oot_families[f][level][spelling] : oot_families[f][level][0];
}
#endif

/* (the randomizer's fork) Progressive items, what a chest shows and says. f_80bf1c00 is handed an actor as it is made
   (x0, a drop's component; x1, what the actor is made with) and reads the actor's Drop__DropActor (a chest's content)
   from the actor's list of parameters (x1+0x40, +0x270, then [0]: the list at +0x10, its count of names at +0, the
   names at +8, its count of values at +0x10, the values at +0x18, all pointers) into the component's own name (+0x48,
   its size the 32 bits at +0x50). The chest's scene (Dm_SY_Treasurebox) shows, names and adds its ContentName, which
   is not that copy: seen without a window 2026-11-16, the copy made the family's next, the scene still said "a bigger
   Deku-nut bag". So the value in the list is pointed at the family's next too, a string of the host's own that stays,
   for what reads the list after. Called as f_80bf1c00 returns (nx2/oot_patches.py patch_drop_name). Seen in play
   2026-11-15: a Bomb Bag in Mido's house with no bag had said "bigger bomb bag". HOS_OOT_DROP_NAME=0 turns it off. */
#if defined(_WIN32) || defined(__linux__)
static uint64_t oot_kept_name(const char *give) {   /* (a string in the game's memory that stays, one per name) */
    static struct { char name[48]; uint64_t at; } kept[32];
    static int count;
    for (int i = 0; i < count; i++)
        if (!strcmp(kept[i].name, give)) return kept[i].at;
    if (count >= 32 || strlen(give) >= sizeof kept[0].name) return 0;
    const uint64_t at = hos_sys_alloc(64, 16);
    if (!at) return 0;
    memcpy(A64_PTR(at), give, strlen(give) + 1);
    snprintf(kept[count].name, sizeof kept[count].name, "%s", give);
    kept[count].at = at;
    count++;
    return at;
}
#endif

/* (characters' looks, tools/rando/rando_cosmetics.py) Link shown as another character: his code asks the model for his own
   bones by name (where his sword and shield hang, his straps), which the other model has not; f_801d3620 then answers -1
   and its callers used that unasked (seen in play 2026-11-16: the shield on the ground, the game fell when it was raised).
   The cosmetics write <game>/mods/zz-cosmetics-models/bone_fallbacks.txt, "<Link's bone>=<the nearest of its parents the
   other model has>", read here once; f_801d3620 (nx2/oot_patches.py patch_bone_fallback) asks again with that name when its
   own is not found. No file (no look of Link's chosen): nothing changes. Returns the other name's string in the game's
   memory, or 0. */
uint64_t hos_oot_bone_fallback(Ctx *c, uint64_t name) {
#if defined(_WIN32) || defined(__linux__)
    static SRWLOCK lock = SRWLOCK_INIT;
    static int loaded;
    static struct { char from[64]; uint64_t to; } *table;
    static int count;
    if (!name) return 0;
    AcquireSRWLockExclusive(&lock);
    if (!loaded) {
        loaded = 1;
        char path[MAX_PATH + 64];
        FILE *f = oot_game_file(path, sizeof path, "mods/zz-cosmetics-models/bone_fallbacks.txt") ? fopen(path, "rb") : NULL;
        if (f) {
            char line[160];
            static struct { char name[64]; uint64_t at; } names[64];
            int nnames = 0;
            table = calloc(1024, sizeof *table);
            while (table && count < 1024 && fgets(line, sizeof line, f)) {
                line[strcspn(line, "\r\n")] = 0;
                char *eq = strchr(line, '=');
                if (!eq || eq == line || !eq[1] || strlen(line) >= 64 || strlen(eq + 1) >= 64) continue;
                *eq = 0;
                uint64_t to = 0;
                for (int i = 0; i < nnames && !to; i++)
                    if (!strcmp(names[i].name, eq + 1)) to = names[i].at;
                if (!to && nnames < 64 && (to = hos_sys_alloc(64, 16)) != 0) {
                    memcpy(A64_PTR(to), eq + 1, strlen(eq + 1) + 1);
                    snprintf(names[nnames].name, sizeof names[nnames].name, "%s", eq + 1);
                    names[nnames++].at = to;
                }
                if (!to) continue;
                snprintf(table[count].from, sizeof table[count].from, "%s", line);
                table[count++].to = to;
            }
            fclose(f);
            hos_log("rando: characters' looks: %d of Link's bones answered by another (bone_fallbacks.txt)", count);
        }
    }
    uint64_t to = 0;
    if (count) {
        char want[64];
        int i = 0;
        for (; i < 63; i++) {
            want[i] = (char)recomp_load8(c, name + i);
            if (!want[i]) break;
        }
        want[i] = 0;
        for (int k = 0; k < count && !to; k++)
            if (!strcmp(table[k].from, want)) to = table[k].to;
    }
    ReleaseSRWLockExclusive(&lock);
    return to;
#else
    (void)c; (void)name;
    return 0;
#endif
}

/* (the randomizer's fork) The day's 15:00 cap, bug 58: the world's clock stops at 15:00 until the cutscene Dm_HrlField_0020
   (Zelda's escape, the Door of Time's story) has played, and a shuffle reaches it late or never: the owner stood five
   minutes in Hyrule Field at fast forward and the day never ended (seen without a window: the clock's seconds climbed
   to 54000 and stayed). f_803edf70 asks this after the scene's flag (nx2/oot_patches.py patch_clock_cap): with the
   randomizer on, no limit. HOS_OOT_CLOCK_CAP=1 keeps the game's cap. */
int hos_oot_field_clock_free(void) {
    static int keep = -1;
    if (keep < 0) { const char *e = getenv("HOS_OOT_CLOCK_CAP"); keep = e && *e == '1'; }
    return !keep && hos_rando_on();
}

/* (the randomizer's fork) The R item wheel, bug 57: the game opens it only with more than one item the age can use
   (f_8331efa0, SeqQueryIsOpenableShortCut's calculate: nx2/oot_patches.py patch_wheel_fewest asks this for the count
   compared with). A shuffle can leave a child one (the owner's run: the Hookshot on ZR, R did nothing). With the
   randomizer on, more than 0. HOS_OOT_WHEEL_TWO=1 keeps the game's two. */
int hos_oot_wheel_fewest(void) {
    static int keep = -1;
    if (keep < 0) { const char *e = getenv("HOS_OOT_WHEEL_TWO"); keep = e && *e == '1'; }
    return keep || !hos_rando_on() ? 1 : 0;
}

void hos_oot_drop_name(Ctx *c, uint64_t self, uint64_t made) {
#if defined(_WIN32) || defined(__linux__)
    static int on = -1;
    if (on < 0) { const char *e = getenv("HOS_OOT_DROP_NAME"); on = !(e && *e == '0'); }
    if (!on || !self || !made || !hos_rando_on() || !hos_rando_progressive()) return;
    /* (the list, as f_80bf1c00 finds it) */
    uint64_t list = recomp_load64(c, made + 0x40);
    if (list) list = recomp_load64(c, list + 0x270);
    if (list) list = recomp_load64(c, list);
    if (list) list = recomp_load64(c, list + 0x10);
    if (!list) return;
    const int names = (int)recomp_load32(c, list), values = (int)recomp_load32(c, list + 0x10);
    const uint64_t name_at = recomp_load64(c, list + 8), value_at = recomp_load64(c, list + 0x18);
    if (!name_at || !value_at || names <= 0 || names > 4096) return;
    static const char key[] = "Drop__DropActor";
    int found = -1;
    for (int i = 0; i < names && i < values && found < 0; i++) {
        const uint64_t k = recomp_load64(c, name_at + 8ULL * i);
        if (!k) continue;
        int same = 1;
        for (int j = 0; j < (int)sizeof key && same; j++) same = (char)recomp_load8(c, k + j) == key[j];
        if (same) found = i;
    }
    if (found < 0) return;
    const uint64_t value = recomp_load64(c, value_at + 8ULL * found);
    if (!value) return;
    char name[96];
    int length = 0;
    for (; length + 1 < (int)sizeof name; length++) {
        name[length] = (char)recomp_load8(c, value + length);
        if (!name[length]) break;
    }
    name[length] = 0;
    if (oot_family_of(name, NULL) < 0) return;
    uint64_t saved[31];
    memcpy(saved, c->x, sizeof saved);   /* (oot_pouch_count calls the game: the registers are given back as they were) */
    const char *give = oot_progressive_give(c, name);
    memcpy(c->x, saved, sizeof saved);
    if (!give) return;
    for (size_t i = 0; i < sizeof oot_show_as / sizeof oot_show_as[0]; i++)
        if (!strcmp(give, oot_show_as[i][0])) give = oot_show_as[i][1];
    for (size_t i = 0; i < sizeof oot_no_show / sizeof oot_no_show[0]; i++)
        if (!strcmp(give, oot_no_show[i])) {
            hos_log("rando: progressive: a chest's %s gives %s, which has no words of its own: it shows its own", name, give);
            return;
        }
    if (!strcmp(give, name)) return;
    const uint64_t kept = oot_kept_name(give);
    if (!kept) return;
    recomp_store64(c, value_at + 8ULL * found, kept);   /* (the list's value: what reads it after) */
    const uint64_t text = recomp_load64(c, self + 0x48);   /* (the component's own copy) */
    const int size = (int)recomp_load32(c, self + 0x50);
    if (text && size > (int)strlen(give) && size <= 4096) {
        const size_t n = strlen(give);
        for (size_t i = 0; i <= n; i++) recomp_store8(c, text + i, (uint8_t)give[i]);
    }
    hos_log("rando: progressive: a chest's %s shows and gives %s", name, give);
#else
    (void)c; (void)self; (void)made;
#endif
}

/* (the randomizer's fork) Progressive items, what a gift or a shop's sale shows and says. A character's gift, a
   Business Scrub's sale, a quest's reward and a shop's sale name their item in their event (the seed's rewrite of the
   flow: GetInEvent_<...>(ActorName "Item_...")), and the scene's steps take it from there: Link holds up the item of
   that name (Player_Event's EventCreateShowItemFromActorFileName: the AI node ExecuteEventCreateShowItem, f_826ca590,
   its name's input at +0x38 when the numbers at +0x28 and +0x30 are -1), and the window's words are those of the String64
   flag UI_MessageTargetActorName, set before it opens (PouchSystemActor's EventTriggerSetForGetWindow: the AI node
   OneShotSetNonStructGameDataString64, f_8295a4b0, the flag's name's input at +0x30, its value's at +0x40). The pouch's
   add (hos_oot_pouch_add) gives the family's next. Each input is a pointer (its two low bits a tag) to where the name's
   string pointer is kept; that is pointed at a kept string with the family's next, in the spelling a chest shows
   (oot_show_as, oot_no_show), so the steps after read it too. What is shown is chosen once an event (the event manager's
   current event): a step after the add would otherwise show the tier after. kind 0 the flag's node, 1 the show item's.
   Called at the nodes' start (nx2/oot_patches.py patch_get_name). HOS_OOT_GET_NAME=0 turns it off. */
#if defined(_WIN32) || defined(__linux__)
static int oot_guest_string(Ctx *c, uint64_t at, char *out, int size) {
    int n = 0;
    if (!at) return 0;
    for (; n + 1 < size; n++) {
        out[n] = (char)recomp_load8(c, at + n);
        if (!out[n]) break;
    }
    out[n] = 0;
    return n + 1 < size;
}
#endif

void hos_oot_get_name(Ctx *c, uint64_t node, int kind) {
#if defined(_WIN32) || defined(__linux__)
    static int on = -1;
    if (on < 0) { const char *e = getenv("HOS_OOT_GET_NAME"); on = !(e && *e == '0'); }
    if (!on || !node || !hos_rando_on()) return;
    uint64_t slot = 0;
    char name[96];
    if (kind == 0) {
        const uint64_t key_slot = recomp_load64(c, node + 0x30) & ~3ULL;
        char key[64];
        if (!key_slot || !oot_guest_string(c, recomp_load64(c, key_slot), key, sizeof key)) return;
        const int window = !strcmp(key, "UI_MessageTargetActorName"), shop = !strcmp(key, "Shop_SelectItemName");
        if (!window && !shop) return;
        slot = recomp_load64(c, node + 0x40) & ~3ULL;
        if (!slot || !oot_guest_string(c, recomp_load64(c, slot), name, sizeof name)) return;
        static char last[2][96];   /* (each value once in the log, to learn what the shops set) */
        if (strcmp(last[shop], name)) {
            snprintf(last[shop], sizeof last[shop], "%s", name);
            hos_log("rando: progressive: %s set to %s", key, name);
        }
        if (shop) return;
    } else {
        const uint64_t a = recomp_load64(c, node + 0x28) & ~3ULL, b = recomp_load64(c, node + 0x30) & ~3ULL;
        if (!a || !b || (int32_t)recomp_load32(c, a) != -1 || (int32_t)recomp_load32(c, b) != -1) return;
        slot = recomp_load64(c, node + 0x38) & ~3ULL;
        if (!slot || !oot_guest_string(c, recomp_load64(c, slot), name, sizeof name)) return;
    }
    if (!hos_rando_progressive()) return;
    int spelling = 0;
    const int family = oot_family_of(name, &spelling);
    if (family < 0) return;
    /* (once an event: the family's choice kept with the event it was made in) */
    static struct { uint64_t event; int family; const char *give; } chosen[4];
    const uint64_t events = oot_singleton(c, OOT_EVENTMGR_SLOT);
    const uint64_t event = events ? recomp_load64(c, events + 104) : 0;
    const char *give = NULL;
    int found = 0;
    for (int i = 0; i < 4 && !found; i++)
        if (event && chosen[i].event == event && chosen[i].family == family) give = chosen[i].give, found = 1;
    if (!found) {
        uint64_t saved[31];
        memcpy(saved, c->x, sizeof saved);   /* (oot_pouch_count calls the game) */
        give = oot_progressive_give(c, name);
        memcpy(c->x, saved, sizeof saved);
        if (give)
            for (size_t i = 0; i < sizeof oot_show_as / sizeof oot_show_as[0]; i++)
                if (!strcmp(give, oot_show_as[i][0])) give = oot_show_as[i][1];
        if (give)
            for (size_t i = 0; i < sizeof oot_no_show / sizeof oot_no_show[0]; i++)
                if (!strcmp(give, oot_no_show[i])) give = NULL;
        if (event) {
            static int turn;
            chosen[turn].event = event, chosen[turn].family = family, chosen[turn].give = give;
            turn = (turn + 1) % 4;
        }
        hos_log("rando: progressive: %s's %s %s", kind ? "a show item" : "a get window", name,
                give ? (strcmp(give, name) ? "is shown as the family's next" : "is the family's next") : "is shown as it is");
        if (give && strcmp(give, name)) hos_log("rando: progressive: shown: %s", give);
    }
    /* (bugs 54, 55, 56: the item Link holds up is shown by the Item_ spelling. The Armor_ spellings (oot_show_as) have the
       "You got" words, but are the pieces Link wears: held up, nothing showed (the bracelet from a chest, the Silver
       Gauntlets bought). Both spellings' packs name the same model; the game's own bracelet scene, Dm_Goron_0030, holds
       up Item_Gauntlet_Goron. The window's words keep the Armor_ spelling.
       The Weapon_ spellings the same (bug 73, the owner's run 2026-11-18): the Potion Shop keeper's gift, the seed's Fairy
       Slingshot, held up as Weapon_Range_SlingShot made no show item, and the game read the one it had not made: a crash
       (guest lr 0x829630ac, a null actor's +0x270 read in f_80994de0). Every spelling of oot_show_as is held up by its
       Item_ one; a chest's Bow held up as the weapon was also upside down and off-centre, bug 71) */
    if (kind == 1) {
        const char *shown = give ? give : name;
        for (size_t i = 0; i < sizeof oot_show_as / sizeof oot_show_as[0]; i++)
            if (!strcmp(shown, oot_show_as[i][1])) {
                if (strcmp(give ? give : "", oot_show_as[i][0]))
                    hos_log("rando: progressive: a show item's %s is held up as %s", shown, oot_show_as[i][0]);
                give = oot_show_as[i][0];
            }
    }
    if (!give || !strcmp(give, name)) return;
    const uint64_t kept = oot_kept_name(give);
    if (kept) recomp_store64(c, slot, kept);
    (void)spelling;
#else
    (void)c; (void)node; (void)kind;
#endif
}

/* (the randomizer's fork) Progressive items, what a shelf shows. A shelf's look, name and the keeper's words are its
   actor's, which its map file names; the seed writes a shop's map once for each choice of tiers of its shelves of a
   family, and lists them in <seed>/shelf_tiers.txt ("<the map's path>|<item>,<item>...": the items the shuffle put on
   those shelves, in the order of the versions' names; tools/rando/rando_seed.py SHELF_FAMILIES). As the game opens such a
   map (host/mods.c hos_mods_romfs) it is given <seed>/shelf_tiers/<the map's path>.<k>_<k>..., k the tier of each shelf:
   the family's next for what Link has, or the shelf's own item when he has the family whole. What he has is what
   oot_inventory_refresh last read (every half second, a save loaded). The game keeps a map it has opened (seen: the
   Kokiri Forest's was not opened again after the Lost Woods and back), and opens the first one before anything here has
   read the pouch: the levels last read are kept in <user>/<save folder>/family_levels.txt for it. So a shelf shows what
   Link had when the map was first opened in a session; it still gives what the pouch's add gives.
   HOS_OOT_SHELF_TIERS=0 turns it off. */
static volatile int oot_family_level[OOT_FAMILIES + 1] = {[0 ... OOT_FAMILIES] = -1};

static void oot_family_levels_path(char *out, size_t cap) {
    extern const char *hos_user_dir;
    const char *hos_save_folder(void);
    snprintf(out, cap, "%s/%s/family_levels.txt", hos_user_dir ? hos_user_dir : "user", hos_save_folder());
}

static void oot_family_levels_refresh(Ctx *c) {
    int changed = 0, loading = 0;
    /* (not while an event plays or a map loads: the pouch is then the game's to change, and a count read half way
       would be kept for the maps opened next. A precaution: nothing wrong was seen) */
    if (oot_event_playing(c) || (oot_gamedata_bool(c, 0xef2b60c2u, &loading) && loading)) return;   /* (Sequence_IsLoadingBanc) */
    for (int f = 0; f < OOT_FAMILIES; f++) {
        int tiers = 0, level = 0;
        while (tiers < 3 && oot_families[f][tiers][0]) tiers++;
        for (int t = tiers - 1; t >= 0 && !level; t--)
            for (int a = 0; a < 2 && !level; a++)
                if (oot_families[f][t][a] && oot_pouch_count(c, oot_families[f][t][a]) > 0) level = t + 1;
        changed |= __atomic_exchange_n(&oot_family_level[f], level, __ATOMIC_RELAXED) != level;
    }
    if (changed && hos_rando_on() && hos_rando_progressive()) {
        char path[MAX_PATH + 64], line[OOT_FAMILIES + 2];
        oot_family_levels_path(path, sizeof path);
        for (int f = 0; f < OOT_FAMILIES; f++) line[f] = (char)('0' + __atomic_load_n(&oot_family_level[f], __ATOMIC_RELAXED));
        line[OOT_FAMILIES] = 10, line[OOT_FAMILIES + 1] = 0;   /* (a line's end) */
        FILE *out = fopen(path, "wb");
        if (out) fputs(line, out), fclose(out);
    }
}

#if defined(_WIN32) || defined(__linux__)
/* (bug 69) A shelf of a family showed the tier of its map's first opening in a session: the game opens a map file once
   a session and keeps it, so the version given then (hos_oot_shelf_map) stays (the owner's run, 2026-11-17: the Silver
   Scale bought in the Zora shop, the Market's shelf still showed it). But the game reads the kept map's actors again at
   each entry into the area: f_805d7660 reads each actor's name (Gyaml) from it, and asks here with the name's place
   (nx2/oot_patches.py patch_shelf_actor). A shelf's tiers are its actors (tools/rando/rando_seed.py SHELF_FAMILIES): the
   shuffled item's is the shelf's own, <shelf>, each other tier k <shelf>_<k>; the seed lists the shelves in
   shelf_tiers.txt's third field. Any of a shelf's names is answered with the one for what Link has now, a string of the
   host's own in guest memory that stays. The place on the shelf stays the version's given at the opening (each tier had
   its own: a model may sit a little off). HOS_OOT_SHELF_TIERS=0 turns it off with the maps' versions. */
static struct { char actor[48]; int family, own; } oot_tier_shelves[64];
static int oot_tier_shelf_count;
static void oot_tier_shelf_add(const char *actor, const char *item) {
    const int f = oot_family_of(item, NULL);
    if (f < 0 || oot_tier_shelf_count >= (int)(sizeof oot_tier_shelves / sizeof oot_tier_shelves[0]) ||
        strlen(actor) + 3 >= sizeof oot_tier_shelves[0].actor)
        return;
    int tiers = 0, own = 0;
    while (tiers < 3 && oot_families[f][tiers][0]) tiers++;
    for (int t = 0; t < tiers; t++)
        for (int a = 0; a < 2; a++)
            if (oot_families[f][t][a] && !strcmp(oot_families[f][t][a], item)) own = t;
    for (int i = 0; i < oot_tier_shelf_count; i++)   /* (a shelf in two maps' lines: a map's adult and child copies) */
        if (!strcmp(oot_tier_shelves[i].actor, actor)) return;
    snprintf(oot_tier_shelves[oot_tier_shelf_count].actor, sizeof oot_tier_shelves[0].actor, "%s", actor);
    oot_tier_shelves[oot_tier_shelf_count].family = f, oot_tier_shelves[oot_tier_shelf_count].own = own;
    __atomic_store_n(&oot_tier_shelf_count, oot_tier_shelf_count + 1, __ATOMIC_RELEASE);
}
/* which of the shelves `name` is a tier of (-1 none), and that tier in *tier */
static int oot_tier_shelf_of(const char *name, int *tier) {
    const int count = __atomic_load_n(&oot_tier_shelf_count, __ATOMIC_ACQUIRE);
    for (int i = 0; i < count; i++) {
        const size_t n = strlen(oot_tier_shelves[i].actor);
        if (strncmp(name, oot_tier_shelves[i].actor, n)) continue;
        if (!name[n]) { *tier = oot_tier_shelves[i].own; return i; }
        if (name[n] == '_' && name[n + 1] >= '0' && name[n + 1] <= '2' && !name[n + 2]) { *tier = name[n + 1] - '0'; return i; }
    }
    return -1;
}
/* the tier a shelf shows for what Link has now (-1: not read yet) */
static int oot_tier_shelf_want(int i) {
    const int f = oot_tier_shelves[i].family;
    const int level = __atomic_load_n(&oot_family_level[f], __ATOMIC_RELAXED);
    if (level < 0) return -1;
    int tiers = 0;
    while (tiers < 3 && oot_families[f][tiers][0]) tiers++;
    return level < tiers ? level : oot_tier_shelves[i].own;
}
#endif
uint64_t hos_oot_shelf_actor(Ctx *c, uint64_t name_at) {
#if defined(_WIN32) || defined(__linux__)
    static const char head[] = "Shop_Rando_";
    if (!name_at || !__atomic_load_n(&oot_tier_shelf_count, __ATOMIC_ACQUIRE)) return name_at;
    for (int i = 0; head[i]; i++)
        if ((char)recomp_load8(c, name_at + i) != head[i]) return name_at;
    char name[64];
    size_t n = 0;
    for (; n + 1 < sizeof name; n++)
        if (!(name[n] = (char)recomp_load8(c, name_at + n))) break;
    name[n] = 0;
    if (n + 1 >= sizeof name) return name_at;
    int tier = 0;
    const int i = oot_tier_shelf_of(name, &tier);
    const int want = i >= 0 ? oot_tier_shelf_want(i) : -1;
    static int trace = -1;   /* (a test's: HOS_OOT_SHELF_TRACE=1 logs every shop shelf's name read, and its tier) */
    if (trace < 0) { const char *e = getenv("HOS_OOT_SHELF_TRACE"); trace = e && *e == '1'; }
    if (trace) hos_log("rando: progressive: map actor %s: shelf %d, tier %d, wanted %d", name, i, tier, want);
    if (want < 0 || want == tier) return name_at;
    static uint64_t names;   /* (a slot of 64 bytes for each shelf's tier: written once, then the same each time) */
    if (!names) names = hos_sys_alloc(sizeof oot_tier_shelves / sizeof oot_tier_shelves[0] * 3 * 64, 16);
    if (!names) return name_at;
    const uint64_t at = names + ((uint64_t)i * 3 + (uint64_t)want) * 64;
    char *slot = (char *)A64_PTR(at);
    if (!slot[0]) {
        if (want == oot_tier_shelves[i].own) snprintf(slot, 64, "%s", oot_tier_shelves[i].actor);
        else snprintf(slot, 64, "%s_%d", oot_tier_shelves[i].actor, want);
    }
    static char told[64][4];
    if (!told[i][want]) told[i][want] = 1, hos_log("rando: progressive: shelf %s shows tier %d now (was %s)", oot_tier_shelves[i].actor, want, name);
    return at;
#else
    (void)c;
    return name_at;
#endif
}

int hos_oot_shelf_map(const char *rel, char *out, size_t cap) {
#if defined(_WIN32) || defined(__linux__)
    static SRWLOCK lock = SRWLOCK_INIT;
    static int loaded, on = -1, count;
    static struct { char rel[160]; char items[3][40]; int n; } maps[64];
    if (on < 0) { const char *e = getenv("HOS_OOT_SHELF_TIERS"); on = !(e && *e == '0'); }
    if (!on || !rel || _strnicmp(rel, "Banc/", 5) || !hos_rando_on() || !hos_rando_progressive()) return 0;
    AcquireSRWLockExclusive(&lock);
    if (!loaded) {
        loaded = 1;
        char path[MAX_PATH + 64], line[512];
        FILE *f = oot_game_file(path, sizeof path, "mods/rando-seed/shelf_tiers.txt") ? fopen(path, "rb") : NULL;
        while (f && count < 64 && fgets(line, sizeof line, f)) {
            line[strcspn(line, "\r\n")] = 0;
            char *bar = strchr(line, '|');
            if (!bar || bar - line >= (int)sizeof maps[0].rel) continue;
            *bar = 0;
            snprintf(maps[count].rel, sizeof maps[count].rel, "%s", line);
            char *actors = strchr(bar + 1, '|');   /* (the shelves' actors: a seed from bug 69's fix on) */
            if (actors) *actors++ = 0;
            int n = 0;
            for (char *item = strtok(bar + 1, ","); item && n < 3; item = strtok(NULL, ","))
                snprintf(maps[count].items[n++], sizeof maps[count].items[0], "%s", item);
            maps[count].n = n;
            int k = 0;
            for (char *actor = actors ? strtok(actors, ",") : NULL; actor && k < n; actor = strtok(NULL, ","), k++)
                oot_tier_shelf_add(actor, maps[count].items[k]);
            /* (a map named twice is left as the seed's own: a seed made before fixes 39 listed the Market once for each
               of its two shops, whose versions had overwritten each other, and the game stayed black entering it) */
            int twice = 0;
            for (int i = 0; i < count; i++)
                if (!_stricmp(maps[i].rel, maps[count].rel)) maps[i].n = 0, twice = 1;
            if (twice) hos_log("rando: progressive: %s is listed twice in shelf_tiers.txt: the seed's own map is used", maps[count].rel);
            if (n && !twice) count++;
        }
        if (f) fclose(f);
        if (count) hos_log("rando: progressive: %d shop map(s) with shelves of a family (shelf_tiers.txt)", count);
        oot_family_levels_path(path, sizeof path);   /* (the last levels read, for a map opened before the pouch is read) */
        f = count && __atomic_load_n(&oot_family_level[0], __ATOMIC_RELAXED) < 0 ? fopen(path, "rb") : NULL;
        const char *test = getenv("HOS_OOT_FAMILY_LEVELS");   /* (a test's: those digits in place of the file's) */
        if (test && strlen(test) < sizeof line) snprintf(line, sizeof line, "%s", test);
        if (((test && *test) || (f && fgets(line, sizeof line, f))) && strspn(line, "0123") >= (size_t)OOT_FAMILIES) {
            for (int k = 0; k < OOT_FAMILIES; k++) __atomic_store_n(&oot_family_level[k], line[k] - '0', __ATOMIC_RELAXED);
            hos_log("rando: progressive: the families' levels last read, until the pouch is read: %.*s", OOT_FAMILIES, line);
        }
        if (f) fclose(f);
    }
    int found = -1;
    for (int i = 0; i < count && found < 0; i++)
        if (maps[i].n && !_stricmp(maps[i].rel, rel)) found = i;
    char combo[16] = "";
    int ok = found >= 0;
    for (int k = 0; ok && k < maps[found].n; k++) {
        const int f = oot_family_of(maps[found].items[k], NULL);
        const int level = f >= 0 ? __atomic_load_n(&oot_family_level[f], __ATOMIC_RELAXED) : -1;
        if (level < 0) { ok = 0; break; }
        int tiers = 0, own = 0;
        while (tiers < 3 && oot_families[f][tiers][0]) tiers++;
        for (int t = 0; t < tiers; t++)
            for (int a = 0; a < 2; a++)
                if (oot_families[f][t][a] && !strcmp(oot_families[f][t][a], maps[found].items[k])) own = t;
        const size_t used = strlen(combo);
        snprintf(combo + used, sizeof combo - used, "%s%d", k ? "_" : "", level < tiers ? level : own);
    }
    int given = 0;
    if (ok) {
        char tail[260];
        snprintf(tail, sizeof tail, "mods/rando-seed/shelf_tiers/%s.%s", maps[found].rel, combo);
        if (oot_game_file(out, cap, tail) && GetFileAttributesA(out) != INVALID_FILE_ATTRIBUTES) given = 1;
        hos_log("rando: progressive: the shop's map %s %s its shelves' tiers %s", rel, given ? "is given with" : "has no file for", combo);
    } else if (found >= 0) {
        hos_log("rando: progressive: the shop's map %s is the seed's own (what Link has not read yet)", rel);
    }
    ReleaseSRWLockExclusive(&lock);
    return given;
#else
    (void)rel; (void)out; (void)cap;
    return 0;
#endif
}

#if defined(_WIN32) || defined(__linux__)
/* (bug 42) A bomb added while Link has no Bomb Bag: bombs (Item_Bomb), a chest's bundle (Item_BombBundle_*), a bomb
   lying in the world (Obj_Bomb: not a bomb flower, Obj_BombFlower_*). Not Bombchus, which need no bag, nor an add as a
   save is loaded. 1: it is to add nothing */
static int oot_bombs_bagless(Ctx *c, const char *name) {
    if ((int32_t)c->x[3] <= 0 || c->x[30] == 0x8112d4b8ULL) return 0;
    if (strcmp(name, "Item_Bomb") && strncmp(name, "Item_BombBundle_", 16) && strcmp(name, "Obj_Bomb")) return 0;
    static const char *const bags[3] = {"Item_BombBag_Small", "Item_BombBag_Medium", "Item_BombBag_Large"};
    for (int i = 0; i < 3; i++)
        if (oot_pouch_count(c, bags[i]) != 0) return 0;   /* (-1, not known: as if he had one) */
    return 1;
}
#endif
int hos_oot_pouch_add(Ctx *c) {
#if defined(_WIN32) || defined(__linux__)
    if (!hos_rando_on()) return 0;
    uint64_t view = c->x[1];
    const uint64_t text = view ? recomp_load64(c, view) : 0;
    if (!text) return 0;
    char name[96];
    size_t length = 0;
    for (; length + 1 < sizeof name; length++) {
        name[length] = (char)recomp_load8(c, text + length);
        if (!name[length]) break;
    }
    name[length] = 0;
    /* (every content added, with where the call came from and its other arguments: the game gives a Bomb Bag with a
       chest's bombs when Link has none, seen in play, and that add is to be told from a chest's own Bomb Bag) */
    hos_log("rando: pouch add %s x%d (lr %#llx, x2 %#llx x4 %#llx x5 %#llx x6 %#llx x7 %#llx)", name, (int)(int32_t)c->x[3],
            (unsigned long long)c->x[30], (unsigned long long)c->x[2], (unsigned long long)c->x[4], (unsigned long long)c->x[5],
            (unsigned long long)c->x[6], (unsigned long long)c->x[7]);
    oot_fill_quiet = c->x[30] == 0x828d50acULL && (uint32_t)c->x[4] == 2 && !(c->x[7] & 1);   /* (the game's own bag: oot_fill_note) */
    if (!strcmp(name, "Item_BombBag_Small") && c->x[30] == 0x828d50acULL && (uint32_t)c->x[4] == 2 && !(c->x[7] & 1)) {
        hos_log("rando: the Bomb Bag the game gives with bombs is not given");
        return 1;
    }
    /* (an item given: the tracker's record. Not the pouch as a save is loaded (from 0x8112d4b8), an add inside another (a bag
       filled, a bundle's own: from 0x8112f998 and 0x8112e19c), nor the debug inventory's (x4 9)) */
    static int debug_counts = -1;   /* (a test's: HOS_OOT_TRACK_DEBUG=1 has the debug inventory's adds marked too) */
    if (debug_counts < 0) { const char *e = getenv("HOS_OOT_TRACK_DEBUG"); debug_counts = e && *e == '1'; }
    if ((int32_t)c->x[3] > 0 && c->x[30] != 0x8112d4b8ULL && c->x[30] != 0x8112f998ULL && c->x[30] != 0x8112e19cULL &&
        ((uint32_t)c->x[4] != 9 || debug_counts)) {
        /* (Heart Pieces: a piece lying in the world that the seed made another item gives that item) */
        char gives[64];
        if ((!strcmp(name, OOT_PIECE) || !strcmp(name, OOT_PIECE_VALLEY)) && c->x[30] != 0x828d50acULL &&
            oot_piece_gives(gives, sizeof gives, 0)) {
            hos_log("rando: the Piece of Heart lying here is the seed's %s: that is given", gives);
            /* (and the piece's heal is not: bug 4, oot_piece_heal) */
            __atomic_store_n(&oot_life_held, __atomic_load_n(&oot_life_seen, __ATOMIC_RELAXED), __ATOMIC_RELAXED);
            __atomic_store_n(&oot_no_heal_until, hos_now_ns() + OOT_PIECE_NO_HEAL, __ATOMIC_RELEASE);
            /* (the piece is counted all the same, by its own taking and not by this add: see oot_piece_gives. The
               valley's has been counted by now, the others are counted after it. One piece is taken out again: now
               when Link has one, so that the count to come cannot make the fourth of three; else when it has come) */
            const int has = oot_pouch_count(c, OOT_PIECE);
            const int valley = !strcmp(name, OOT_PIECE_VALLEY);
            int result = -2;
            if (has > 0) result = oot_pouch_change(c, OOT_PIECE, -1);
            else if (!valley) __atomic_store_n(&oot_piece_back, OOT_PIECE_WAIT, __ATOMIC_RELEASE);
            hos_log("rando: Link had %d Pieces of Heart at the add: %s", has,
                    has > 0 ? (result >= 0 ? "one is taken out" : "one could not be taken out") :
                    valley ? "none is taken out (the piece made a heart of three)" : "the one to come is taken out");
            view = oot_pouch_name(c, view, gives);
            snprintf(name, sizeof name, "%s", gives);
        } else if (!strcmp(name, OOT_CONTAINER) && c->x[30] != 0x828d50acULL && oot_piece_gives(gives, sizeof gives, 1)) {
            /* (bug 31: a boss's Heart Container that the seed made another item gives that item. The container's add
               gives its heart by itself and the pouch keeps none, so the add renamed gives no heart: nothing to take back) */
            hos_log("rando: the boss's Heart Container here is the seed's %s: that is given", gives);
            /* (and the heart its taking makes is taken back: before the add when it rose just now, else after it) */
            const int recent = oot_max_was >= 0 && hos_now_ns() - oot_max_rose < OOT_MAX_RECENT;
            __atomic_store_n(&oot_container_max, recent ? oot_max_was : oot_max_now, __ATOMIC_RELAXED);
            __atomic_store_n(&oot_container_back, OOT_PIECE_WAIT, __ATOMIC_RELEASE);
            hos_log("rando: Link's max life %d quarters at the add%s: kept at %d", oot_max_now, recent ? " (it rose just now)" : "",
                    recent ? oot_max_was : oot_max_now);
            view = oot_pouch_name(c, view, gives);
            snprintf(name, sizeof name, "%s", gives);
        }
        oot_tracker_item(name);
    }
    /* (bug 42: with no Bomb Bag, the bombs that follow the bag the game is not let give made the inventory's bombs at
       0/0, a slot that can't be used: a bomb added while Link has no bag adds nothing. Here, after the tracker's record
       and a piece's or a container's item named: a check that gave bombs is still a check got) */
    if (oot_bombs_bagless(c, name)) {
        hos_log("rando: %s x%d with no Bomb Bag: nothing is added", name, (int)(int32_t)c->x[3]);
        return 1;
    }
    oot_pickup_qol(c, name);   /* (Ammo pick-ups, Rupees fill the wallet) */
    if ((int32_t)c->x[3] <= 0) return 0;
    if (!hos_rando_progressive()) {
        oot_fill_note(name);   /* (a bag found is a full bag) */
        return 0;
    }
    if (oot_family_of(name, NULL) >= 0) {
        const char *give = oot_progressive_give(c, name);
        if (!give) {   /* (he has them all: the one found is given as it is) */
            oot_fill_note(name);
            return 0;
        }
        hos_log("rando: progressive: %s found: %s given", name, give);
        oot_fill_note(give);
        if (!strcmp(give, name)) return 0;
        oot_pouch_name(c, view, give);
        return 0;
    }
    oot_fill_note(name);   /* (not an upgrade of a family: a holder all the same, or nothing) */
    return 0;
#else
    (void)c;
    return 0;
#endif
}

/* The new-game opening, build e0f3ccfaf50065ae4ea01eb5aeb13b1a45da3348. Sequence/Opening.module.ainb requests
   Opening_Introduction and Opening_LoadingKokiriForest (SeqOneShotRequestEvent, f_80d9a820; the event name is the
   pointer at the request arg + 6800, which that function reads). Opening_Introduction's flowchart writes the state
   on both paths: the clock at 6:00, Meet_DekuTree's challenge Step01, the forest terrain pin, then
   EventTransition of the timeline Dm_Kokiri_0030. Its own skip query (IsEventSkipedMostRecent, f_80de6cb0) then
   takes the short edge: Navi warped to the position that edge names, the in-game music, Navi's talked flag, the
   camera handed back, and an autosave. Opening_LoadingKokiriForest's flowchart plays the timeline Dm_Kokiri_0000
   and then waits until the forest banc has loaded. Neither timeline writes save data. Meet_DekuTree is a later
   flow and is not one of these names.

   With Skip opening on, the request is still sent, so the flowchart applies that edge. The two timelines are not
   started: f_83b5bfb0 is their only starter (EventTransition at 0x80eaba00). Leaving bit 0 of the timeline player
   + 0xf25 clear makes that caller take its own exit at 0x80eac5e0, which finishes the action node, instead of the
   exit at 0x80eac640 that leaves the timeline running. The skip query is answered yes only while one of these two
   requests is the current one, so the short edge runs and a title demo that uses the same query does not. The
   cutscene frame counter is not moved. mode 0 observes a request, 1 a timeline start (return 1: do not start it),
   2 the skip query (return 1: x0 is 1), 3 Link is updating and no event is playing (the opening has let him go). */
int hos_oot_opening(Ctx *c, int mode) {
    int rx_option(int id, int otherwise);
    static int armed;
    static char logged[64];
    char name[80];
    uint64_t p = 0;
    if (mode == 3) {
        armed = 0;
        logged[0] = 0;
        return 0;
    }
    if (!c || rx_option(HOS_OPT_SKIP_OPENING, 0) <= 0) {
        armed = 0;
        return 0;
    }
    name[0] = 0;
    if (mode == 0) {
        const uint64_t arg = c->x[1];
        p = arg ? recomp_load64(c, arg + 6800) : 0;
    } else if (mode == 1 && c->x[1]) {
        p = recomp_load64(c, c->x[1]);   /* EventTransition passes a pointer to the timeline's name */
    }
    if (p) {
        size_t i = 0;
        for (; i + 1 < sizeof name; i++) {
            name[i] = (char)recomp_load8(c, p + i);
            name[i + 1] = 0;
            if (!name[i]) break;
        }
    }
    if (mode == 0) {
        if (!strcmp(name, "Opening_Introduction") || !strcmp(name, "Opening_LoadingKokiriForest")) {
            armed = 1;
            if (strcmp(logged, name)) {
                size_t i = 0;
                for (; name[i] && i + 1 < sizeof logged; i++) logged[i] = name[i];
                logged[i] = 0;
                hos_log("opening skip: %s request sent", name);
            }
        } else if (name[0]) {
            /* a different event (Meet_DekuTree included) is not skipped and drops the arm */
            armed = 0;
            logged[0] = 0;
        }
        return 0;   /* the request is still sent */
    }
    if (!armed) return 0;
    if (mode == 2) {
        c->x[0] = 1;
        return 1;
    }
    if (mode == 1 && (!strcmp(name, "Dm_Kokiri_0000") || !strcmp(name, "Dm_Kokiri_0030"))) {
        const uint64_t player = c->x[0];
        if (player) recomp_store8(c, player + 0xf25, recomp_load8(c, player + 0xf25) & ~(uint64_t)1);
        return 1;
    }
    return 0;
}

void hos_oot_lift_player(Ctx *c, uint64_t actor) {
#if defined(_WIN32) || defined(__linux__)   /* (the debug tools: host/posix has what they call) */
    flight_pose_actor = 0;
    if (recomp_load64(c, actor) != 0x84b45e18ULL) return;
    const uint64_t components = recomp_load64(c, actor + 624);
    const uint64_t movement = components ? recomp_load64(c, components + 800) : 0;
    if (movement < HOS_HEAP_BASE + 0x1d50 || recomp_load64(c, movement + 24) != actor ||
        !hos_oot_is_player(c, movement - 0x1d50)) return;
    if (!oot_event_playing(c)) hos_oot_opening(c, 3);   /* the opening has let Link go: later events keep their own skip */

    // Link can be updated by different guest workers on successive frames.
    static SRWLOCK cheats_lock = SRWLOCK_INIT;
    if (!TryAcquireSRWLockExclusive(&cheats_lock)) return;
    oot_update_player_cheats(c, actor, components);
    void hos_oot_state_tap(uint64_t actor);   /* the control bridge's copied snapshot and per-connection samples */
    hos_oot_state_tap(actor);
    ReleaseSRWLockExclusive(&cheats_lock);
#else
    (void)c;
    (void)actor;
#endif
}

#if defined(_WIN32) || defined(__linux__)   /* (the debug tools: host/posix has what they call) */
static void oot_build_free_view(Ctx *c, uint64_t view, uint64_t out) {
    int rx_option(int id, int otherwise);
    static uint64_t active_view;
    static int64_t last_tick;
    static double eye[3], yaw, pitch;
    const int64_t now = hos_now_ns();
    const int64_t elapsed = now - last_tick;

    if (!view) {
        active_view = 0;
        return;
    }
    if (active_view != view || elapsed > 500000000) {
        double target[3];
        memcpy(eye, A64_PTR(view + 96), sizeof eye);
        memcpy(target, A64_PTR(view + 120), sizeof target);
        const double x = eye[0] - target[0], y = eye[1] - target[1], z = eye[2] - target[2];
        yaw = atan2(x, z);
        pitch = atan2(y, hypot(x, z));
        active_view = view;
        hos_log("cheats: free camera at %.2f %.2f %.2f", eye[0], eye[1], eye[2]);
    }
    last_tick = now;
    DWORD foreground = 0;
    GetWindowThreadProcessId(GetForegroundWindow(), &foreground);
    const double dt = elapsed > 0 && elapsed < 100000000 ? (double)elapsed * 1e-9 : 0;
    const int control = foreground == GetCurrentProcessId() && !rx_option(1, 0);
    int height = 0;
    uint64_t hos_free_camera_input(int *height);
    const uint64_t input = control ? hos_free_camera_input(&height) : 0;
    if (control) {
        yaw -= 1.6 * dt * (int16_t)(input >> 32) / 32767.0;
        pitch -= 1.2 * dt * (int16_t)(input >> 48) / 32767.0;
        pitch = fmax(-1.55, fmin(1.55, pitch));
    }
    const double sy = sin(yaw), cy = cos(yaw), sp = sin(pitch), cp = cos(pitch);
    const double axes[3][3] = {{cy, 0, -sy}, {-sp * sy, cp, -sp * cy}, {cp * sy, sp, cp * cy}};
    if (control) {
        const double step = dt * (GetAsyncKeyState(VK_CONTROL) < 0 ? 30.0 : 8.0);
        const double right = (int16_t)input / 32767.0;
        const double forward = (int16_t)(input >> 16) / 32767.0;
        const int key_height = (GetAsyncKeyState(VK_PRIOR) < 0) - (GetAsyncKeyState(VK_NEXT) < 0);
        eye[1] += step * (key_height ? key_height : height);
        for (int i = 0; i < 3; i++)
            eye[i] += step * (right * axes[0][i] - forward * axes[2][i]);
    }
    for (int row = 0; row < 3; row++) {
        const double *axis = axes[row];
        const float values[4] = {(float)axis[0], (float)axis[1], (float)axis[2],
            (float)-(axis[0] * eye[0] + axis[1] * eye[1] + axis[2] * eye[2])};
        for (int col = 0; col < 4; col++) {
            uint32_t bits;
            memcpy(&bits, &values[col], sizeof bits);
            recomp_store32(c, out + (row * 4 + col) * 4, bits);
        }
    }
}
#endif

void hos_oot_free_view(Ctx *c, uint64_t view) {
#if defined(_WIN32) || defined(__linux__)   /* (the debug tools: host/posix has what they call) */
    int rx_option(int id, int otherwise);
    if (!view || recomp_load64(c, view) != 0x84c18a88ULL) return;

    // Camera zero supplies the gameplay view. The same matrix routine also serves other cameras.
    if (oot_gameplay_view(c) != view) return;
    oot_skip_cutscene(c);   /* (the randomizer's fork: Skip cutscenes, also while Link isn't updated) */

    static SRWLOCK lock = SRWLOCK_INIT;
    AcquireSRWLockExclusive(&lock);
    const int enabled = rx_option(HOS_OPT_CHEAT_CAMERA, 0);
    oot_build_free_view(c, enabled ? view : 0, view + 8);
    ReleaseSRWLockExclusive(&lock);
#else
    (void)c;
    (void)view;
#endif
}

float hos_aspect_ratio = 0;   /* (the window's default shape: host/display.c) */
/* (nx2/oot_wide.py) read by the widescreen patches in the game's code; 0: the game's own 16:9 */
volatile uint64_t hos_wide_out, hos_wide_scene;
volatile float hos_wide_ratio, hos_wide_squeeze, hos_wide_margin;
volatile uint32_t hos_wide_keep_mask = 0xf;   /* (nx2/oot_wide.py KEEP_VTABLES: the screens that keep the whole picture, a bit each; MkwVkHost.wide_menus) */
/* (issues 1241, 2838) Swap can keep a small Linux PC from running out of backing storage without keeping it responsive.
   Warn below the existing 10 GiB floor in physical RAM there too; this is not a promise that 10 GiB is enough.
   The game starts anyway, and headless runs only log the warning. Windows keeps its commit-limit check. */
#define HOS_MEMORY_NEEDED_MB 10240ull
static int memory_notice_text(unsigned long long ram_mb, unsigned long long swap_mb, char *out, size_t cap) {
#if defined(__linux__) && !defined(_WIN32)
    if (ram_mb < HOS_MEMORY_NEEDED_MB) {
        snprintf(out, cap,
                 "This PC has %.1f GiB of RAM and %.1f GiB of swap. Hookshot recommends 16 GB of RAM or more; "
                 "the game alone can use more than 13 GiB.\n\n"
                 "Swap can prevent an out-of-memory exit, but heavy swapping can make the game and desktop unresponsive. "
                 "Close other programs before playing. More swap is not a replacement for RAM. The game starts anyway.",
                 ram_mb / 1024.0, swap_mb / 1024.0);
        return 1;
    }
#endif
    if (ram_mb + swap_mb >= HOS_MEMORY_NEEDED_MB) return 0;
    snprintf(out, cap,
             "This PC has %.1f GB of memory and %.1f GB of swap (the page file on Windows). The game needs about %llu GB of the "
             "two together; with less it can close by itself while it loads.\n\nClose other programs, or add swap (on Windows: "
             "let it manage the page file's size), then start the game again. It starts now anyway.",
             ram_mb / 1024.0, swap_mb / 1024.0, HOS_MEMORY_NEEDED_MB / 1024);
    return 1;
}
#ifndef A64_MEM_ZERO
static void memory_notice(void) {
    unsigned long long ram = 0, swap = 0;   /* (MB) */
#ifdef _WIN32
    MEMORYSTATUSEX m = {sizeof m};
    if (!GlobalMemoryStatusEx(&m)) return;
    ram = m.ullTotalPhys >> 20;
    swap = m.ullTotalPageFile > m.ullTotalPhys ? (m.ullTotalPageFile - m.ullTotalPhys) >> 20 : 0;   /* (the commit limit: RAM and page file) */
#elif defined(__linux__)
    struct sysinfo si;
    if (sysinfo(&si)) return;
    ram = ((unsigned long long)si.totalram * si.mem_unit) >> 20, swap = ((unsigned long long)si.totalswap * si.mem_unit) >> 20;
#else
    return;
#endif
    char text[512];
    if (!memory_notice_text(ram, swap, text, sizeof text)) {
        hos_log("boot: %llu MB of memory, %llu MB of swap", ram, swap);
        return;
    }
#if defined(__linux__) && !defined(_WIN32)
    hos_log("boot: LOW MEMORY: %llu MB of memory, %llu MB of swap; below %llu MB of physical RAM: heavy swapping can make "
            "the game and desktop unresponsive (16 GB RAM or more recommended)", ram, swap, HOS_MEMORY_NEEDED_MB);
#else
    hos_log("boot: LOW MEMORY: %llu MB of memory, %llu MB of swap, below the ~%llu MB the game needs", ram, swap, HOS_MEMORY_NEEDED_MB);
#endif
    if (env_on("HOS_HEADLESS")) return;
#ifndef _WIN32
    int hos_sdl_load(void);
    hos_sdl_load();   /* (host/posix MessageBoxA shows it through the SDL already loaded) */
#endif
    MessageBoxA(NULL, text, "Hookshot", MB_OK | MB_ICONWARNING);
}
#endif
/* (hookshot, linux) What driver_env_choose did with the driver's environment, said again in the game's own log once it is open
   (it runs before, when stderr is still the launcher's) */
static char driver_env_said[1024];
static void driver_env_log(void) {
    if (driver_env_said[0]) hos_log("%s", driver_env_said);
}
#ifdef _WIN32
/* (hookshot) On laptops with two GPUs, the drivers run a program on the dedicated one when it exports these (NVIDIA Optimus, AMD
   PowerXpress): without them a laptop could put the game on its integrated GPU, 5 fps (issue 176) */
__declspec(dllexport) unsigned long NvOptimusEnablement = 1;
__declspec(dllexport) int AmdPowerXpressRequestHighPerformance = 1;

/* (hookshot) The game's paths are UTF-8 char strings through Windows' A functions and fopen: its manifest (nx2/win_manifest.py)
   makes the process's code page UTF-8, from Windows 10 1903 on. Before that, or with the manifest missing, those take the system's
   ANSI code page, and a folder name it cannot spell (Japanese on a Western Windows, an emoji) comes back as "?": nothing opens and
   the game closed with no window and no log. The exe's own path through GetModuleFileNameA must name the exe (a name past MAX_PATH
   bytes fails the same way); when it does not, a message says why (none for the builder's --prepare-shaders run: its log has it). */
static int narrow_paths_ok(int argc, char **argv) {
    char a[MAX_PATH];
    const DWORD n = GetModuleFileNameA(NULL, a, MAX_PATH);
    if (n && n < MAX_PATH && GetFileAttributesA(a) != INVALID_FILE_ATTRIBUTES) return 1;
    wchar_t w[MAX_PATH * 2] = L"";
    GetModuleFileNameW(NULL, w, MAX_PATH * 2);
    fprintf(stderr, "hookshot: this folder's path cannot be opened (code page %u, %s): move the game to a folder with a plain name\n",
            GetACP(), n >= MAX_PATH ? "too long" : "has characters the code page lacks");
    int quiet = env_on("HOS_HEADLESS");
    for (int i = 1; i < argc; i++) quiet |= !strcmp(argv[i], "--prepare-shaders");
    if (!quiet) {
        wchar_t text[MAX_PATH * 2 + 640];
        _snwprintf(text, sizeof text / sizeof text[0],
                   L"Hookshot can't open its files in this folder:\n\n%ls\n\n"
                   L"%ls\n\nMove the game folder somewhere with a shorter name of plain letters and digits (for example C:\\Games\\Hookshot), "
                   L"or update Windows.",
                   w, GetACP() == CP_UTF8 ? L"The path is too long."
                                          : L"Its name has characters this Windows can only give the game from Windows 10 version 1903 on.");
        text[sizeof text / sizeof text[0] - 1] = 0;
        MessageBoxW(NULL, text, L"Hookshot", MB_OK | MB_ICONERROR | MB_SETFOREGROUND);
    }
    return 0;
}

int main(int argc, char **argv) {
#else
static int game_main(int argc, char **argv) {
#endif
#ifdef _WIN32
    {   /* (hookshot) the crash window's helper of this run (host/hos_crash_dialog.c): first, so it starts nothing of the game */
        int hos_crash_helper_main(int argc, char **argv);
        const int helper = hos_crash_helper_main(argc, argv);
        if (helper >= 0) return helper;
    }
    if (!narrow_paths_ok(argc, argv)) return 1;
    hos_game_layout();   /* (the game folder's cache/ and logs/, before anything writes there: host/game_layout.c) */
    {
        void hos_relaunch_keep_env(void);   /* (host/hos_relaunch.c: the environment before the file's lines, for a restart) */
        hos_relaunch_keep_env();
    }
    load_hookshot_env();
    hos_profiling_env();   /* (HOS_PROFILE=1, host/profiling.c: after the file, which may set it) */
#endif
    /* (the settings file, in the user folder: chosen before the crash window's helper, the Discord status and the renderer read
       it, and after hookshot_env.txt, which may set HOS_OPTIONS_FILE; Linux's main chose it already: host/options_path.c) */
    hos_options_choose(argc, argv);
    {
        const char *protect_hearts = getenv("HOS_OOT_PROTECT_HEARTS");
        hos_oot_protect_hearts = protect_hearts && !strcmp(protect_hearts, "1");
    }
#ifdef _WIN32
    {   // (the whole process, not only the window's thread: the renderer asks the window's size from its own, and on a 4K screen at 150%
        // Windows answered such a thread 2560 x 1440: the picture was that size, in the corner of the window. Hookshot issues 15, 18, 20)
        typedef BOOL(WINAPI * SetAware)(void *);
        SetAware set = (SetAware)(void *)GetProcAddress(GetModuleHandleA("user32.dll"), "SetProcessDpiAwarenessContext");
        if (set && !env_on("HOS_DPI_UNAWARE")) set((void *)(intptr_t)-4);
    }
#endif
    void hos_crash_record_prepare(const char *log_path);
    {   // (started from its icon the game has nowhere to log to: hookshot_log.txt in the game folder's logs/ (host/game_layout.c), for players to send in)
#ifdef _WIN32
        {   /* (started again by the Insert menu's Restart now (host/hos_relaunch.c): the run before still has its log open until
               it exits, so wait for it (up to 10 s) before the log moves to .1, or the move fails and its log is overwritten) */
            const char *of = getenv("HOS_RESTART_OF");
            if (of && *of) {
                HANDLE before = OpenProcess(SYNCHRONIZE, FALSE, (DWORD)strtoul(of, NULL, 10));
                if (before) WaitForSingleObject(before, 10000), CloseHandle(before);
                SetEnvironmentVariableA("HOS_RESTART_OF", NULL);   /* (not passed on: a later restart sets its own) */
                _putenv("HOS_RESTART_OF=");
            }
        }
#endif
        HANDLE err = GetStdHandle(STD_ERROR_HANDLE);
        if (!err || err == INVALID_HANDLE_VALUE || GetFileType(err) == FILE_TYPE_UNKNOWN) {
            char path[MAX_PATH + 32];
            DWORD n = hos_game_path_a(path, MAX_PATH);
            while (n && path[n - 1] != 92 && path[n - 1] != 47) n--;
            if (n && n + 5 < MAX_PATH) {   /* (its logs/, which hos_game_layout made; else beside the game, as before) */
                memcpy(path + n, "logs", 5);
                if (GetFileAttributesA(path) != INVALID_FILE_ATTRIBUTES) path[n + 4] = path[n - 1], n += 5;
            }
            memcpy(path + n, "hookshot_log.txt", 17);
            hos_crash_record_prepare(path);   /* recovery before rotation; keep this run's actual destination */
            /* (the four runs before stay as hookshot_log.1.txt (the last) to .4.txt: a player who started the game again after a
               crash sent in the new run's log, and the crash was gone) */
            char from[MAX_PATH + 32], to[MAX_PATH + 32];
            for (int k = 4; k >= 1; k--) {
                if (k == 1) memcpy(from + n, "hookshot_log.txt", 17), memcpy(from, path, n);
                else memcpy(from, path, n), snprintf(from + n, 32, "hookshot_log.%d.txt", k - 1);
                memcpy(to, path, n), snprintf(to + n, 32, "hookshot_log.%d.txt", k);
                MoveFileExA(from, to, MOVEFILE_REPLACE_EXISTING);
            }
#if !defined(_WIN32) && !defined(A64_MEM_ZERO)
            startup_stderr = fcntl(STDERR_FILENO, F_DUPFD_CLOEXEC, 0);
#endif
            /* (opened first: freopen closes stderr when it cannot open the file, and the next file opened would take its
               descriptor. A log that cannot be written leaves the stderr the game was started with) */
            FILE *log = fopen(path, "w");
            if (log) {
                fclose(log);
                if (freopen(path, "w", stderr)) setvbuf(stderr, NULL, _IONBF, 0);
            }
        } else hos_crash_record_prepare(NULL);   /* an externally supplied stderr, not the game's log */
    }
    hos_log("hookshot %s", HOOKSHOT_VERSION);   /* (the log's first line: which build a report comes from) */
    const char *hos_report_run_id(void);
    hos_log("run_id: %s", hos_report_run_id());
    hos_game_layout_log();
    driver_env_log();
    void hos_crash_record_log_notes(void);
    hos_crash_record_log_notes();
    removed_switch_notes();
    void hos_control_start(const char *version);
    hos_control_start(HOOKSHOT_VERSION);   /* (HOS_CONTROL=<socket>: the control bridge, host/control.c) */
    /* (hookshot) the window after a crash: a helper that waits for this run to end (host/hos_crash_dialog.c), started before
       the guest, the renderer, the sound and the input; none for --prepare-shaders, HOS_HEADLESS or HOS_CRASH_WATCH=0 */
    void hos_crash_watch_start(int argc, char **argv);
    hos_crash_watch_start(argc, argv);
    const char *image = NULL;
    /* (hookshot) --compile-shaders all or most: what a preparation of this run builds (gpu/vk/vk_draw.cpp compile_all), over
       compile_shaders= in hookshot_options.ini; as RX_VK_COMPILE_SHADERS, set before --prepare-shaders runs, wherever it stands */
    for (int i = 1; i + 1 < argc; i++)
        if (!strcmp(argv[i], "--compile-shaders")) {
#ifdef _WIN32
            char set[64];
            snprintf(set, sizeof set, "RX_VK_COMPILE_SHADERS=%s", argv[i + 1]);
            _putenv(set);
#else
            setenv("RX_VK_COMPILE_SHADERS", argv[i + 1], 1);
#endif
        }
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--romfs") && i + 1 < argc) hos_romfs_dir = argv[++i];
        else if (!strcmp(argv[i], "--compile-shaders") && i + 1 < argc) i++;   /* (taken above) */
        else if (!strcmp(argv[i], "--user") && i + 1 < argc) hos_user_dir = argv[++i];
        else if (!strcmp(argv[i], "--trace")) hos_trace = 1;
        else if (!strcmp(argv[i], "--prepare-shaders")) {   /* (hookshot) a build's last step: no game */
#ifdef _WIN32
            _putenv("HOOKSHOT_PREPARE_ONLY=1");
#else
            setenv("HOOKSHOT_PREPARE_ONLY", "1", 1);
#endif
            int rx_prepare_shaders(void);
            if (rx_prepare_shaders()) {
                printf("@@done shaders\n");
                return 0;
            }
            printf("@@error no usable Vulkan here: the game prepares its shaders at its first start\n");
            return 3;
        }
        else if (!image) image = argv[i];
    }
#ifdef _WIN32
    {   /* (hookshot) the Discord status (discord_rpc.c), a game run only (a --prepare-shaders run returned above). Linux starts
           it in its own main, below; on Windows it was never started: no status and no "discord:" line in any log */
        void hos_discord_start(void);
        hos_discord_start();
    }
#endif
    static char beside_image[MAX_PATH], beside_romfs[MAX_PATH], beside_user[MAX_PATH];
    if (!image) {   /* (hookshot) started with nothing, as a game is: everything beside the executable (the builder's folder) */
        char dir[MAX_PATH];
        const DWORD len = hos_game_path_a(dir, MAX_PATH);
        char *slash = len ? strrchr(dir, SEP) : NULL;
        if (slash) {
            *slash = 0;
            SetCurrentDirectoryA(dir);
            snprintf(beside_image, MAX_PATH, "%s" SEP_S "image.bin", dir);
            snprintf(beside_romfs, MAX_PATH, "%s" SEP_S "romfs", dir);
            snprintf(beside_user, MAX_PATH, "%s" SEP_S "user", dir);
            if (GetFileAttributesA(beside_image) != INVALID_FILE_ATTRIBUTES) {
                image = beside_image;
                if (!hos_romfs_dir) hos_romfs_dir = beside_romfs;
#ifndef _WIN32
                if (!hos_user_dir) hos_user_dir = saves_dir(beside_user);
#else
                if (!hos_user_dir) hos_user_dir = beside_user;
#endif
            }
        }
    }
    if (!image) {
        fprintf(stderr, "usage: %s [image.bin] [--romfs <dir>] [--user <dir>] [--trace] [--prepare-shaders] [--compile-shaders all|most]\n",
                argv[0]);
        return 2;
    }
    if (env_on("HOS_TRACE")) hos_trace = 1;
    if (env_on("HOS_HLE_STATS")) {
        void hos_hle_stats_start(void);
        hos_hle_stats_start();
    }
    if (!hos_user_dir) hos_user_dir = "user";
    recover_writes();   /* (what a write of a setting that a kill cut left: before anything reads the settings) */
    CreateDirectoryA(hos_user_dir, NULL);
#ifdef _WIN32
    if (beside_user[0] && hos_user_dir == beside_user && !getenv("HOS_NO_SAVE_FOLDER")) {   /* (sharkiix version) */
        char game_dir[MAX_PATH];
        snprintf(game_dir, sizeof game_dir, "%s", beside_user);
        char *slash = strrchr(game_dir, SEP);
        if (slash) *slash = 0, save_folder_import(game_dir, hos_user_dir);
    }
#endif
    hos_options_carry();   /* (a game folder's settings from before into the user folder, once: host/options_path.c) */
    if (!reserve_guest()) {
        fprintf(stderr, "cannot reserve the guest window\n");
        return 1;
    }
    void hos_crash_test_arm(void);
    hos_crash_test_arm();   /* (HOS_CRASH_TEST: a crash on purpose, once the crash handlers are set up: host/hos_crash_dialog.c) */
#ifdef A64_MEM_ZERO
    web_fs_init(NULL, hos_romfs_dir);
    /* (the whole file, no range: the server sends it brotli-compressed, 85 -> 26 MB) */
    const int got = web_fetch_all(image, A64_MEM + IMAGE_BASE, GUEST_SPACE - IMAGE_BASE);
    if (got < 0) {
        fprintf(stderr, "cannot fetch %s\n", image);
        return 1;
    }
    size_t n = (size_t)got;
#else
    FILE *f = fopen(image, "rb");
    if (!f) {
        fprintf(stderr, "cannot open %s\n", image);
        return 1;
    }
    /* exactly the file's size: a read into "the rest of the guest window" (~4 GB) made Windows commit physical memory
       for ~2 GB of it before the game ran (the whole heap was resident from the start, ~1.3 GB of it never used) */
    fseek(f, 0, SEEK_END);
    const long long file_size = _ftelli64(f);
    fseek(f, 0, SEEK_SET);
    if (file_size > 0) hos_commit(IMAGE_BASE, (uint64_t)file_size);
    size_t n = file_size > 0 && (uint64_t)file_size <= GUEST_SPACE - IMAGE_BASE
                   ? fread(A64_MEM + IMAGE_BASE, 1, (size_t)file_size, f) : 0;
    fclose(f);
#endif
    if (IMAGE_BASE + n != hos_image_end) {
        fprintf(stderr, "%s: %zu bytes, the lifted code expects %#llx: lift and image do not match\n", image, n,
                (unsigned long long)(hos_image_end - IMAGE_BASE));
        return 1;
    }
    hos_mem_init(hos_image_end);
    {   /* (hookshot) Widescreen and ultrawide (nx2/oot_wide.py): HOS_ASPECT=<ratio> (2.3889 for 3440x1440), else the Insert menu's
           Aspect ratio (on unless it says 0) takes the main monitor's shape. The game's picture takes that shape at its own height (the
           world wider at the sides on an ultrawide screen, narrower on a 16:10 or 4:3 one), its 16:9 cameras the picture's ratio.
           An output that is not 16:9 takes precedence over both HOS_ASPECT and the Aspect ratio, matching the menu's picture. Wider
           than 16:9 the HUD, menus and movies keep the middle 16:9; narrower they fill the picture's width. Until now the one 16:9
           constant in the game's data was changed and the 16:9 picture stretched to the window. */
        const char *e = getenv("HOS_ASPECT");
        float want = e ? (float)atof(e) : 0.0f;
        if (!e) {
            int saved = -1, version = 0;   /* (the Aspect ratio's ultrawide= and options_version=, -1 / 0 without them) */
            FILE *o = fopen(hos_options_file(), "r");
            if (o) {
                char line[80];
                while (fgets(line, sizeof line, o)) {
                    if (!strncmp(line, "ultrawide=", 10)) saved = atoi(line + 10) != 0;
                    if (!strncmp(line, "options_version=", 16)) version = atoi(line + 16);
                }
                fclose(o);
            }
            void hos_monitor_prepare(void);
            int hos_monitor_screen_size(int *,int *);
            hos_monitor_prepare();
            int sw=0,sh=0;
            if (!hos_monitor_screen_size(&sw,&sh)) {
                sw=GetSystemMetrics(SM_CXSCREEN); sh=GetSystemMetrics(SM_CYSCREEN);
            }
            /* (no line: the monitor's shape; an older file's 16:9 on a screen narrower than 16:9 too: hos_aspect_on) */
            const int on = hos_aspect_on(saved, version, sw, sh);
            if (on && sh > 0) want = (float)sw / (float)sh;
        }
        extern volatile uint64_t hos_wide_out, hos_wide_scene;
        extern volatile float hos_wide_ratio, hos_wide_squeeze, hos_wide_margin;
        uint32_t hos_output_size(int height);
        const uint32_t output_w = hos_output_size(0), output_h = hos_output_size(1);
        /* An output of a shape of its own (the Insert menu's Aspect ratio: 21:9, 16:10, 4:3, a 32:9 surround...) asks for that
           shape, over HOS_ASPECT and Ultrawide, even if the OS reports one monitor (host/hos_wide_size.h) */
        if (hos_output_own_shape(output_w, output_h)) want = (float)output_w / (float)output_h;
        const double game = 16.0 / 9.0;
        /* (a screen narrower than 16:9 too, 16:10 to 5:4: the picture keeps the game's height and is narrower, the
           cameras take its ratio, and the HUD fills its width instead of a middle 16:9 wider than the screen. A 4:3 CRT
           at the 1440 output: picture 1920 x 1440, scene 1440 x 1080, HUD 100%) */
        if (want > game * 1.01 || (want > 1.0f && want < game * 0.99)) {
            const double r = hos_wide_clamp(want);
            /* (the height kept, the width at the screen's ratio, at most hos_wide_max_px() pixels (5120 x 2160's, a 21:9 screen's
               native at the 4K output) with the shape kept: host/hos_wide_size.h, which the Insert menu's Output and Render
               resolution rows share; issue 1031) */
            unsigned ow, oh;
            hos_wide_size(output_h, r, hos_wide_max_px(), &ow, &oh);
            const unsigned sh = oh * 3 / 4, sw = (unsigned)(ow * 0.75 / 8 + 0.5) * 8;   /* (the scene, 3/4 of the picture as shipped) */
            hos_wide_out = (uint64_t)oh << 32 | ow;
            hos_wide_scene = (uint64_t)sh << 32 | sw;
            hos_wide_ratio = (float)ow / (float)oh;
            hos_wide_squeeze = (float)fmin(1.0, game / ((double)ow / oh));   /* (a narrower screen: the whole width) */
            hos_wide_margin = (1.0f - hos_wide_squeeze) / 2.0f;
            hos_aspect_ratio = hos_wide_ratio;
            hos_log("boot: widescreen: picture %ux%u, scene %ux%u, camera ratio %.4f, HUD and movies in the middle %.1f%%", ow, oh, sw, sh,
                    (double)hos_wide_ratio, hos_wide_squeeze * 100.0);
        } else if (want > 1.0f) {
            hos_log("boot: widescreen: a %.4f screen is 16:9: the game's own picture", (double)want);
        }
    }
    hos_log("boot: image %zu MB at %#llx, %llu MB of memory for the game", n >> 20, IMAGE_BASE,
            (unsigned long long)(hos_total_memory >> 20));
#ifndef A64_MEM_ZERO
    memory_notice();
#endif
    void hos_mods_init(const char *image_path);
    hos_mods_init(image);   /* mods.c: <exe folder>\mods (RomFS files) */
    void hos_rando_init(void);
    hos_rando_init();   /* oot_rando.c: the launcher's Randomizer page's seed and settings */

    Ctx *c = hos_boot_main_thread(hos_main_stack_size);
    uint64_t sp = c->x[31];
    void hos_prof_start(void);
    hos_prof_start();   /* HOS_PROFILE_EVERY=<seconds>, the samplers, HOS_PROFILE=1 */
    void hos_chain_start(void);
    hos_chain_start();  /* HOS_CHAIN=<path> */
#ifdef _WIN32
    timeBeginPeriod(1);   /* 1 ms timer resolution: the 60 Hz vsync and the game's frame pacing sleep in short steps */
    no_power_throttling();
#endif
    void hos_display_start(void);
    hos_display_start();  /* the game's window; HOS_HEADLESS=1 for none */
    /* nn::init::Start's order (sdk+0xfa060), with rtld's three callbacks done here: f1 only marks rtld initialized,
       f2 is every module's DT_INIT, f3 the DT_FINIs (not needed: we never return from nnMain to unload). */
    call_guest(c, hos_entry_init_libc0, sp, "_init_libc0");
    c->x[0] = hos_thread_handle(hos_self());   /* the main thread's handle */
    c->x[1] = 0;                               /* program arguments: none (an unmapped address) */
    call_guest_args(c, hos_entry_nnosInitialize, sp, "nnosInitialize");
    void hos_thread_adopt_guest(HosThread *t);
    hos_thread_adopt_guest(hos_self());
    call_guest(c, hos_entry_init_libc1, sp, "_init_libc1");
    /* nninitInitializeSdkModule (sdk+0xfa000) only opens the SDK's service clients (sm:, diag, oe, aoc, err, fs,
       pctl) over IPC; the HLE stands in for every one of them, so it is not run. */
    call_guest(c, hos_entry_nninitStartup, sp, "nninitStartup");
    call_guest(c, hos_entry_init_libc2, sp, "_init_libc2");
    for (int i = 0; i < hos_module_count; i++) {
        char what[64];
        snprintf(what, sizeof what, "%s DT_INIT", hos_module_name[i]);
        call_guest(c, hos_module_init[i], sp, what);
    }
    call_guest(c, hos_entry_nnMain, sp, "nnMain");
    hos_log("nnMain returned");
    void hos_crash_clean_end(void);
    hos_crash_clean_end();
    return 0;
}

#ifndef _WIN32
/* (linux) The window belongs on the process's main thread (SDL), so the game runs on a thread of its own, with the
   stack the guest main thread's lifted code needs (the main thread has the system's 8 MB): host/posix/display_sdl.c */
static int game_argc;
static char **game_argv;
static DWORD WINAPI game_thread(void *p) {
    (void)p;
    const UINT result = (UINT)game_main(game_argc, game_argv);
    void hos_crash_clean_end(void);
    hos_crash_clean_end();
    ExitProcess(result);
}
/* (hookshot, linux) Room in the drivers' own shader caches for what the preparation builds. The pipelines the notes predict (~43,000
   in OoT, vk_draw.cpp predict_run) are built into the driver's disk cache alone, not into hookshot_vk_pipelines.bin, which is read in whole
   at every start. NVIDIA's cache holds 1 GiB by default and cleans itself down to that as it is written: a full preparation filled
   it to the limit (1026 MB) and the pipelines it dropped were compiled again in play. Mesa's (RADV, ANV) has the same 1 GiB default.
   Raised for this process only, before anything loads Vulkan; a value the player set (or hookshot_env.txt) is kept. Windows: the
   NVIDIA driver takes its size from the control panel's Shader Cache Size, which a program cannot set (readme) */
static void driver_cache_room(void) {
    setenv("__GL_SHADER_DISK_CACHE_SIZE", "10737418240", 0);   /* (10 GiB, bytes) */
    setenv("MESA_SHADER_CACHE_MAX_SIZE", "10G", 0);
}
#include <errno.h>
#include <sys/stat.h>
/* (hookshot, linux) NVIDIA's driver keeps no shader cache at all when __GL_SHADER_DISK_CACHE_PATH names a folder that does not exist:
   it neither creates it nor falls back to ~/.cache/nvidia, and every start compiles every pipeline again (a test of 300 pipelines:
   7.9 ms each at the first start and at the second, against 0.06 ms from the cache; driver 620.70). The folder a player or a
   launcher named is made here, before anything loads Vulkan. Mesa makes its own (MESA_SHADER_CACHE_DIR, parents too). Not needed:
   NVIDIA files the cache by the program's file name alone (bin/hookshot), not its folder, bytes or date, nor VkApplicationInfo, so
   an update in place, a folder moved or copied and every Hookshot folder on the PC share one cache (a cache of another driver or
   GPU is the driver's to drop) */
static void driver_cache_folder(void) {
    const char *dir = getenv("__GL_SHADER_DISK_CACHE_PATH");
    if (!dir || !*dir || strlen(dir) >= 4096) return;
    char path[4096];
    strcpy(path, dir);
    for (char *p = path + 1;; p++) {   /* (each parent, then the folder itself: mkdir -p) */
        const char c = *p;
        if (c != '/' && c) continue;
        *p = 0;
        if (mkdir(path, 0700) != 0 && errno != EEXIST) {
            fprintf(stderr, "vk: __GL_SHADER_DISK_CACHE_PATH %s: cannot make %s (%s): NVIDIA's driver keeps no shader cache\n", dir,
                    path, strerror(errno));
            return;
        }
        if (!c) {   /* (a file already at that name counts as made for mkdir, but the driver can't use it) */
            struct stat st;
            if (stat(path, &st) != 0 || !S_ISDIR(st.st_mode))
                fprintf(stderr, "vk: __GL_SHADER_DISK_CACHE_PATH %s: cannot make it, a file has that name: NVIDIA's driver keeps no shader cache\n", dir);
            return;
        }
        *p = '/';
    }
}
/* (hookshot, linux) RADV_FORCE_VRS_CONFIG_FILE dropped before anything loads Vulkan. The Steam Deck's Game Mode sets it for
   Steam and everything it starts, naming a file it writes the Half Rate Shading rate to (/tmp/radv_vrs.<random>, "1x1" when
   off). When that file exists, RADV forces VRS for the device and puts that into every graphics pipeline's key, so nothing
   built without it is found, in the driver's cache or in ours: measured on a Steam Deck OLED (RADV, Mesa 26.2.0-devel), the
   same install compiled its 32,438 noted pipelines at about 20 a second (25-30 minutes) with the variable naming a file, empty
   or "1x1", and loaded them in 22 s without it or with it naming no file. The preparation (the Builder, a first start from the
   desktop) runs without it, so every start from Game Mode compiled again what it built. Dropped only when it names a file that
   exists, which is when RADV reads it; no other driver reads it. RX_VK_HALF_RATE_SHADING=1 keeps it: Steam's Half Rate Shading
   works for Hookshot then (little: RADV leaves a fragment program that reads its position at full rate, and nearly all of
   ours do), and the starts in Game Mode compile their own pipelines. RADV_FORCE_VRS, a rate someone set by hand, is kept.
   The variable is named in HOOKSHOT_DRIVER_ENV_SET for the renderer's driver cache line. A restart (hos_relaunch.c) starts
   again from the first environment and drops it again */
static void driver_env_choose(void) {
    const char *file = getenv("RADV_FORCE_VRS_CONFIG_FILE");
    struct stat st;
    if (!file || !*file || stat(file, &st) != 0) return;
    const char *keep = getenv("RX_VK_HALF_RATE_SHADING");
    if (keep && !strcmp(keep, "1")) {
        snprintf(driver_env_said, sizeof driver_env_said,
                 "vk: RADV_FORCE_VRS_CONFIG_FILE kept (RX_VK_HALF_RATE_SHADING=1): Steam's Half Rate Shading reaches the game, "
                 "and RADV gives every graphics pipeline another key than the preparation's, so they are compiled again");
    } else {
        snprintf(driver_env_said, sizeof driver_env_said,
                 "vk: RADV_FORCE_VRS_CONFIG_FILE=%.300s dropped: with it RADV gives every graphics pipeline another key than the "
                 "preparation's and compiles them all again; Steam's Half Rate Shading has no effect on Hookshot "
                 "(RX_VK_HALF_RATE_SHADING=1 keeps it)", file);
        unsetenv("RADV_FORCE_VRS_CONFIG_FILE");
        setenv("HOOKSHOT_DRIVER_ENV_SET", "RADV_FORCE_VRS_CONFIG_FILE", 1);
    }
    fprintf(stderr, "%s\n", driver_env_said);
}
int main(int argc, char **argv) {
    {   /* (hookshot) the crash window's helper of this run (host/hos_crash_dialog.c): first, so it starts nothing of the game */
        int hos_crash_helper_main(int argc, char **argv);
        const int helper = hos_crash_helper_main(argc, argv);
        if (helper >= 0) return helper;
    }
    int hos_display_init(void);
    void hos_display_loop(void);
    hos_game_layout();   /* (the game folder's cache/ and logs/, before anything writes there, --prepare-shaders too: host/game_layout.c) */
    load_hookshot_env();
    hos_profiling_env();   /* (HOS_PROFILE=1, host/profiling.c: after the file, which may set it) */
    hos_options_choose(argc, argv);   /* (before the Discord status reads it, below: host/options_path.c) */
    driver_cache_room();
    driver_cache_folder();
    driver_env_choose();
    game_argc = argc, game_argv = argv;
    int prepare_shaders = 0;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--prepare-shaders")) prepare_shaders = 1;
        else if (!strcmp(argv[i], "--romfs") || !strcmp(argv[i], "--user") || !strcmp(argv[i], "--compile-shaders")) i++;
    }
    /* The builder's preparation worker needs Vulkan, but no SDL display. */
    const int window = prepare_shaders ? 0 : hos_display_init();
    if (window < 0) {
        hos_log_flush();
        return 1;
    }
    if (!prepare_shaders) {   /* (hookshot) the Discord status (discord_rpc.c): only a game run */
        void hos_discord_start(void);
        hos_discord_start();
    }
    HANDLE t = CreateThread(NULL, 64u << 20, game_thread, NULL, 0, NULL);
    if (!t) {
        fprintf(stderr, "cannot start the game's thread\n");
        return 1;
    }
    SetThreadDescription(t, L"Game");
    if (window) hos_display_loop();   /* (does not return: the window's events until the process ends) */
    WaitForSingleObject(t, INFINITE);
    return 0;
}
#endif
