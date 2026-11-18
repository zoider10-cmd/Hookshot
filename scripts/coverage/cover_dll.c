/* cover_dll.c: which lifted functions run, and when each first ran (scripts/coverage/cover.py loads it into the game).

   Loaded into bin\hookshot.exe before its entry point (cover.py starts the game suspended and queues LoadLibraryW on its
   main thread). It reads the lifted functions' offsets in the exe (COVER_FNS: a file of sorted, distinct uint32 RVAs that
   cover.py made from the exe's own symbol table, f_<guest address>), writes an int3 (0xCC) over the first byte of each,
   and keeps the bytes it replaced. A vectored handler takes the breakpoint the first time a function is entered, puts the
   byte back, notes the time since the start (ms) and lets the thread go on at the same address. Each function costs one
   exception, once (a few microseconds); after that it runs as it always did.

   Every COVER_FLUSH_MS (5000) it rewrites COVER_OUT (temp file, then rename), and once more at a normal exit:
     "LSCOV1\0\0", u64 start (Unix ms), u32 count, u32 functions seen, u32 first_ms[count] (0 = never ran)
   Nothing here reads or writes game data: the file holds offsets' times only; the offsets file is cover.py's.

   The .text pages become private copies (they are written): ~400 MB more committed memory for the run. The game's own
   handlers (commit on touch) see access violations only; breakpoints that are not ours are passed on. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

static uint8_t *base;
static uint32_t *rva, n;
static uint8_t *orig;
static volatile uint32_t *first_ms;
static volatile LONG seen;
static LARGE_INTEGER t0, freq;
static uint64_t start_unix_ms;
static wchar_t out_path[MAX_PATH], tmp_path[MAX_PATH + 8], log_path[MAX_PATH + 8];
static CRITICAL_SECTION flush_lock;

static void say(const char *fmt, ...) {
    char line[512];
    va_list ap;
    va_start(ap, fmt);
    int k = vsnprintf(line, sizeof line, fmt, ap);
    va_end(ap);
    if (k < 0) return;
    HANDLE h = CreateFileW(log_path, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, OPEN_ALWAYS, 0, NULL);
    if (h == INVALID_HANDLE_VALUE) return;
    DWORD w;
    WriteFile(h, line, (DWORD)strlen(line), &w, NULL);
    WriteFile(h, "\r\n", 2, &w, NULL);
    CloseHandle(h);
}

static uint32_t now_ms(void) {
    LARGE_INTEGER t;
    QueryPerformanceCounter(&t);
    uint64_t ms = (uint64_t)(t.QuadPart - t0.QuadPart) * 1000 / (uint64_t)freq.QuadPart;
    return ms ? (uint32_t)ms : 1;   /* (0 means "never ran") */
}

static int64_t find(uint32_t r) {
    uint32_t lo = 0, hi = n;
    while (lo < hi) {
        uint32_t mid = (lo + hi) >> 1;
        if (rva[mid] < r) lo = mid + 1;
        else hi = mid;
    }
    return lo < n && rva[lo] == r ? (int64_t)lo : -1;
}

static LONG CALLBACK on_break(EXCEPTION_POINTERS *e) {
    if (e->ExceptionRecord->ExceptionCode != EXCEPTION_BREAKPOINT) return EXCEPTION_CONTINUE_SEARCH;
    const uintptr_t a = (uintptr_t)e->ExceptionRecord->ExceptionAddress;
    if (a < (uintptr_t)base || a - (uintptr_t)base > 0xFFFFFFFFu) return EXCEPTION_CONTINUE_SEARCH;
    const int64_t i = find((uint32_t)(a - (uintptr_t)base));
    if (i < 0) return EXCEPTION_CONTINUE_SEARCH;
    volatile uint8_t *p = (volatile uint8_t *)a;
    if (*p == 0xCC) *p = orig[i];   /* (another thread may have put it back already: the same byte either way) */
    if (!first_ms[i] && !InterlockedCompareExchange((volatile LONG *)&first_ms[i], (LONG)now_ms(), 0))
        InterlockedIncrement(&seen);
    e->ContextRecord->Rip = a;   /* (the breakpoint's own address, whichever way Windows reported it) */
    return EXCEPTION_CONTINUE_EXECUTION;
}

static void flush(void) {
    EnterCriticalSection(&flush_lock);
    HANDLE h = CreateFileW(tmp_path, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, 0, NULL);
    if (h != INVALID_HANDLE_VALUE) {
        DWORD w;
        uint32_t head[2] = {n, (uint32_t)seen};
        BOOL ok = WriteFile(h, "LSCOV1\0\0", 8, &w, NULL) && WriteFile(h, &start_unix_ms, 8, &w, NULL) &&
                  WriteFile(h, head, sizeof head, &w, NULL) && WriteFile(h, (const void *)first_ms, n * 4, &w, NULL);
        CloseHandle(h);
        if (ok) MoveFileExW(tmp_path, out_path, MOVEFILE_REPLACE_EXISTING);
    }
    LeaveCriticalSection(&flush_lock);
}

static DWORD WINAPI flusher(void *p) {
    const DWORD every = (DWORD)(uintptr_t)p;
    for (;;) {
        Sleep(every);
        flush();
    }
    return 0;
}

static int start(void) {
    wchar_t fns[MAX_PATH], every_s[32];
    if (!GetEnvironmentVariableW(L"COVER_FNS", fns, MAX_PATH) || !GetEnvironmentVariableW(L"COVER_OUT", out_path, MAX_PATH))
        return 0;
    swprintf(tmp_path, MAX_PATH + 8, L"%ls.tmp", out_path);
    swprintf(log_path, MAX_PATH + 8, L"%ls.log", out_path);
    DWORD every = 5000;
    if (GetEnvironmentVariableW(L"COVER_FLUSH_MS", every_s, 32)) every = (DWORD)_wtoi(every_s);
    if (every < 500) every = 500;
    QueryPerformanceFrequency(&freq);
    QueryPerformanceCounter(&t0);
    FILETIME ft;
    GetSystemTimeAsFileTime(&ft);
    start_unix_ms = ((((uint64_t)ft.dwHighDateTime << 32) | ft.dwLowDateTime) - 116444736000000000ull) / 10000;
    InitializeCriticalSection(&flush_lock);

    HANDLE h = CreateFileW(fns, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
    if (h == INVALID_HANDLE_VALUE) { say("cover: cannot open COVER_FNS"); return 0; }
    LARGE_INTEGER sz;
    GetFileSizeEx(h, &sz);
    n = (uint32_t)(sz.QuadPart / 4);
    rva = (uint32_t *)VirtualAlloc(NULL, (SIZE_T)n * 4, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    orig = (uint8_t *)VirtualAlloc(NULL, n, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    first_ms = (volatile uint32_t *)VirtualAlloc(NULL, (SIZE_T)n * 4, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    DWORD got = 0;
    BOOL ok = rva && orig && first_ms && ReadFile(h, rva, n * 4, &got, NULL) && got == n * 4;
    CloseHandle(h);
    if (!ok) { say("cover: cannot read COVER_FNS"); return 0; }

    base = (uint8_t *)GetModuleHandleW(NULL);
    IMAGE_NT_HEADERS *nt = (IMAGE_NT_HEADERS *)(base + ((IMAGE_DOS_HEADER *)base)->e_lfanew);
    IMAGE_SECTION_HEADER *s = IMAGE_FIRST_SECTION(nt), *text = NULL;
    for (int k = 0; k < nt->FileHeader.NumberOfSections; k++)
        if (!memcmp(s[k].Name, ".text", 6)) text = &s[k];
    if (!text) { say("cover: no .text section"); return 0; }
    const uint32_t lo = text->VirtualAddress, hi = text->VirtualAddress + text->Misc.VirtualSize;
    for (uint32_t i = 0; i < n; i++)
        if (rva[i] < lo || rva[i] >= hi || (i && rva[i] <= rva[i - 1])) {
            say("cover: offset %u (%#x) is outside .text or out of order: wrong exe for this list?", i, rva[i]);
            return 0;
        }
    DWORD old;
    if (!VirtualProtect(base + lo, hi - lo, PAGE_EXECUTE_READWRITE, &old)) {
        say("cover: VirtualProtect failed (%lu)", GetLastError());
        return 0;
    }
    AddVectoredExceptionHandler(1, on_break);
    const uint32_t patch0 = now_ms();
    for (uint32_t i = 0; i < n; i++) {
        orig[i] = base[rva[i]];
        base[rva[i]] = 0xCC;
    }
    FlushInstructionCache(GetCurrentProcess(), base + lo, hi - lo);
    say("cover: %u functions marked in %u ms; writing %ls every %lu ms", n, now_ms() - patch0, out_path, every);
    flush();
    CreateThread(NULL, 0, flusher, (void *)(uintptr_t)every, 0, NULL);
    return 1;
}

static int started;

BOOL WINAPI DllMain(HINSTANCE inst, DWORD why, void *reserved) {
    (void)inst;
    if (why == DLL_PROCESS_ATTACH) {
        started = start();
    } else if (why == DLL_PROCESS_DETACH && started) {
        /* (at process exit the other threads are gone, the flusher perhaps inside flush(): entering its lock then would end the
           process, so only when it is free; the flusher's last write stands otherwise) */
        (void)reserved;
        if (TryEnterCriticalSection(&flush_lock)) {
            LeaveCriticalSection(&flush_lock);
            flush();
        }
        say("cover: exit, %ld functions ran", seen);
    }
    return TRUE;
}
