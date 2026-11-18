"""Windows monitor labels: real source with synthetic DisplayConfig APIs; no window/game.

Run: python -I -B tests/test_monitor_friendly_names.py --cc clang
Also syntax-checks the new helper against real Windows headers when run on Windows.
"""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

RUN_ALL_ARGS = ['--cc', 'clang']
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from srccut import block

STUBS = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>
#include <wctype.h>
#define CHECK(x) do { if(!(x)){fprintf(stderr,"FAIL %d: %s\n",__LINE__,#x);exit(1);} } while(0)
typedef wchar_t WCHAR;
typedef unsigned UINT32;
typedef int LONG;
typedef int BOOL;
typedef int HMONITOR;
typedef void *HDC;
typedef intptr_t LPARAM;
typedef struct {int left,top,right,bottom;} RECT;
typedef RECT *LPRECT;
typedef struct {unsigned cbSize;RECT rcMonitor;unsigned dwFlags;WCHAR szDevice[32];} MONITORINFOEXW;
typedef MONITORINFOEXW MONITORINFO;
typedef struct {unsigned cb;WCHAR DeviceID[128],DeviceString[128];} DISPLAY_DEVICEW;
typedef struct {int adapterId;UINT32 id;} TARGET;
typedef struct {TARGET targetInfo;} DISPLAYCONFIG_PATH_INFO;
typedef struct {int unused;} DISPLAYCONFIG_MODE_INFO;
typedef struct {int type;unsigned size;int adapterId;UINT32 id;} HEADER;
typedef struct {HEADER header;WCHAR monitorDevicePath[128],monitorFriendlyDeviceName[128];} DISPLAYCONFIG_TARGET_DEVICE_NAME;
typedef struct {char id[512],name[256];int width,height,flags;} MkwVkMonitor;
#define CALLBACK
#define TRUE 1
#define FALSE 0
#define QDC_ONLY_ACTIVE_PATHS 2
#define DISPLAYCONFIG_DEVICE_INFO_GET_TARGET_NAME 2
#define ERROR_SUCCESS 0
#define ERROR_INSUFFICIENT_BUFFER 122
#define CP_UTF8 65001
#define HOS_MONITOR_MAX 4
#define HOS_MONITOR_PRIMARY 1
#define HOS_MONITOR_CURRENT 2
#define MONITORINFOF_PRIMARY 1
#define MONITOR_DEFAULTTONEAREST 2
static void *hwnd;
static MkwVkMonitor window_monitors[4];
static HMONITOR window_monitor_handles[4];
static int window_monitor_count,scenario,queries,allocations,fail_alloc,alloc_calls;
static int GetMonitorInfoW(HMONITOR h,MONITORINFO *mi){(void)h;wcscpy(mi->szDevice,L"DISPLAY2");mi->rcMonitor=(RECT){-1920,0,0,1080};mi->dwFlags=1;return 1;}
static int EnumDisplayDevicesW(const WCHAR *s,int n,DISPLAY_DEVICEW *d,int flags){(void)s;(void)n;CHECK(flags==1);wcscpy(d->DeviceID,L"monitor:b");wcscpy(d->DeviceString,L"Generic PnP Monitor");return 1;}
static HMONITOR MonitorFromWindow(void *w,int flags){(void)w;(void)flags;return 7;}
static int lstrcmpiW(const WCHAR *a,const WCHAR *b){while(*a && towlower(*a)==towlower(*b)){a++;b++;}return (int)towlower(*a)-(int)towlower(*b);}
static int WideCharToMultiByte(int cp,int flags,const WCHAR *s,int n,char *out,int cap,void *a,void *b){
    (void)flags;(void)n;(void)a;(void)b;CHECK(cp==CP_UTF8);int used=0;
    if(scenario==7 && s[0]==L'P')return 0;
    for(;*s;s++){unsigned c=(unsigned)*s;if(used+3>=cap)return 0;
        if(c<128)out[used++]=(char)c;else {out[used++]=(char)(0xc0|(c>>6));out[used++]=(char)(0x80|(c&63));}}
    out[used]=0;return used+1;
}
static LONG GetDisplayConfigBufferSizes(int flags,UINT32 *paths,UINT32 *modes){CHECK(flags==2);*paths=scenario==8?0:2;*modes=0;return scenario==1?5:0;}
static LONG QueryDisplayConfig(int flags,UINT32 *paths,DISPLAYCONFIG_PATH_INFO *p,UINT32 *modes,DISPLAYCONFIG_MODE_INFO *m,void *topology){
    (void)modes;(void)m;CHECK(flags==2 && *paths==2 && !topology);queries++;
    if(scenario==2)return 5;
    if(scenario==9 || (scenario==6 && queries<3))return 122;
    p[0].targetInfo=(TARGET){42,10};p[1].targetInfo=(TARGET){42,20};return 0;
}
static LONG DisplayConfigGetDeviceInfo(HEADER *h){
    CHECK(h->adapterId==42 && h->size==sizeof(DISPLAYCONFIG_TARGET_DEVICE_NAME) && h->type==2);
    if(scenario==3)return 5;
    DISPLAYCONFIG_TARGET_DEVICE_NAME *t=(void *)h;
    wcscpy(t->monitorDevicePath,(h->id==20 && scenario!=5)?L"MONITOR:B":L"monitor:a");
    wcscpy(t->monitorFriendlyDeviceName,scenario==4?L"":(h->id==20?L"Panel \u00e9":L"Wrong panel"));return 0;
}
static void *test_calloc(size_t n,size_t size){if(++alloc_calls==fail_alloc)return NULL;void *p=calloc(n,size);if(p)allocations++;return p;}
static void test_free(void *p){if(p)allocations--;free(p);}
#define calloc test_calloc
#define free test_free
'''

MAIN = r'''
static void run(int s,int failure,const char *expected){
    scenario=s;queries=0;window_monitor_count=0;alloc_calls=0;fail_alloc=failure;
    CHECK(collect_monitor(7,NULL,NULL,0));CHECK(window_monitor_count==1);
    CHECK(!strcmp(window_monitors[0].name,expected));
    CHECK(!strcmp(window_monitors[0].id,"monitor:b"));
    CHECK(window_monitors[0].width==1920 && window_monitors[0].flags==1);
    CHECK(window_monitor_handles[0]==7 && allocations==0);
}
int main(void){
    run(0,0,"Panel \xc3\xa9"); /* matches interface B despite first active target A */
    for(int s=1;s<=5;s++)run(s,0,"Generic PnP Monitor");
    run(6,0,"Panel \xc3\xa9");CHECK(queries==3); /* hotplug race retries */
    run(7,0,"Generic PnP Monitor"); /* conversion failure */
    run(8,0,"Generic PnP Monitor");CHECK(queries==0);
    run(9,0,"Generic PnP Monitor");CHECK(queries==3); /* bounded retry */
    run(0,1,"Generic PnP Monitor");run(0,2,"Generic PnP Monitor");
    puts("Windows friendly monitor name: 12 scenarios passed; identity and ownership preserved");
    return 0;
}
'''

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cc', default='clang')
    parser.add_argument('--source', type=Path, default=ROOT / 'host/display.c')
    args = parser.parse_args()
    raw = args.source.read_text(encoding='utf-8')
    marker = 'static int monitor_friendly_name('
    helper = block(raw, marker) if marker in raw else ''
    source = STUBS + helper + block(raw, 'static BOOL CALLBACK collect_monitor(') + MAIN
    with tempfile.TemporaryDirectory(prefix='monitor-names-') as temp:
        path = Path(temp) / 'test.c'
        exe = Path(temp) / ('test.exe' if sys.platform == 'win32' else 'test')
        path.write_text(source, encoding='utf-8')
        subprocess.run([args.cc, '-std=c11', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', str(path), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
        if sys.platform == 'win32' and helper:
            path.write_text('#define WIN32_LEAN_AND_MEAN\n#include <windows.h>\n#include <stdlib.h>\n' + helper +
                            '\nint probe(const WCHAR *id,char *s){return monitor_friendly_name(id,s,256);}\n', encoding='utf-8')
            subprocess.run([args.cc, '-std=c11', '-Wall', '-Wextra', '-Werror', '-fsyntax-only', str(path)], check=True)
            print('Friendly-name helper: real Windows header syntax passed')

if __name__ == '__main__':
    main()
