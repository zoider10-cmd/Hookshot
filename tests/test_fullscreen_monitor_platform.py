"""Game-free monitor policy, Windows placement and SDL2/3 call-order fixtures. No window or game.

Compile only when authorized: python -I -B tests/test_fullscreen_monitor_platform.py --cc clang
"""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

RUN_ALL_ARGS = ["--cc", "clang"]
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT / "tests"))
from srccut import block

BASE = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#define CHECK(x) do {if(!(x)){fprintf(stderr,"FAIL %d %s\n",__LINE__,#x);exit(1);}}while(0)
static void hos_log(const char *s,...) {(void)s;}
typedef int SRWLOCK;
#define SRWLOCK_INIT 0
static int locked;
static void AcquireSRWLockExclusive(SRWLOCK *p){(void)p;CHECK(!locked);locked=1;}
static void ReleaseSRWLockExclusive(SRWLOCK *p){(void)p;CHECK(locked);locked=0;}
static void AcquireSRWLockShared(SRWLOCK *p){AcquireSRWLockExclusive(p);}
static void ReleaseSRWLockShared(SRWLOCK *p){ReleaseSRWLockExclusive(p);}
const char *hos_options_file(void){return "";}
'''

POLICY = r'''
int main(void) {
    monitor_loaded=1;
    MkwVkMonitor list[3]={{"key:A","Panel",1920,1080,HOS_MONITOR_PRIMARY|HOS_MONITOR_CURRENT},
                         {"key:B","Panel",2560,1440,0},{"key:C","Third",3840,2160,0}};
    char checked[512];
    CHECK(hos_monitor_copy_id(checked,sizeof checked,"key:B"));
    CHECK(!hos_monitor_copy_id(checked,sizeof checked,"bad\nkey"));
    CHECK(!hos_monitor_copy_id(checked,3,"long"));
    hos_monitor_publish(list,3,0); hos_monitor_select("key:B"); monitor_start=1;
    int w,h; CHECK(hos_monitor_screen_size(&w,&h) && w==2560 && h==1440);
    monitor_start=0; CHECK(hos_monitor_screen_size(&w,&h) && w==1920);
    monitor_start=1; hos_monitor_publish(list,3,1);
    CHECK(hos_monitor_screen_size(&w,&h) && w==1920); /* actual window wins after creation */
    MkwVkMonitor temp=list[0];list[0]=list[1];list[1]=temp;
    CHECK(hos_monitor_find(list,3,"key:B")==0); /* persistence isn't an index */
    strcpy(list[2].id,"key:B"); CHECK(hos_monitor_find(list,3,"key:B")==-1);
    hos_monitor_publish(list+1,1,0); /* selected display disappeared */
    CHECK(hos_monitor_screen_size(&w,&h) && w==1920);
    char want[512];hos_monitor_wanted(want);CHECK(!strcmp(want,"key:B"));
    CHECK(hos_monitor_count()==1 && !hos_monitor_info(1,&temp));
    CHECK(hos_monitor_info(0,&temp) && temp.width==1920);
    hos_monitor_select("");hos_monitor_wanted(want);CHECK(!*want);
    puts("fullscreen monitor policy passed");return 0;
}
'''

WINDOWS = r'''
typedef int LONG;
typedef void *HWND;
typedef int HMONITOR;
typedef struct {int left,top,right,bottom;} RECT;
typedef struct {unsigned cbSize; RECT rcMonitor;} MONITORINFO;
typedef struct {unsigned length; RECT rect;} WINDOWPLACEMENT;
#define WS_OVERLAPPEDWINDOW 0xff
#define GWL_STYLE 0
#define HWND_TOP ((void *)1)
#define SWP_NOOWNERZORDER 1
#define SWP_FRAMECHANGED 2
#define SWP_NOMOVE 4
#define SWP_NOSIZE 8
#define SWP_NOZORDER 16
#define MONITOR_DEFAULTTONEAREST 0
static int fullscreen,mouse_captured,clipped,placements,position_fail,restore_fail;
static LONG style=WS_OVERLAPPEDWINDOW;
static RECT position={20,30,1300,750};
static const RECT rects[2]={{0,0,1920,1080},{-2560,0,0,1440}};
static WINDOWPLACEMENT windowed_place;
static MkwVkMonitor window_monitors[2]={{"one","One",1920,1080,0},{"two","Two",2560,1440,0}};
static HMONITOR window_monitor_handles[2]={1,2};
static int window_monitor_count=2;
static void refresh_monitors(void){}
static LONG GetWindowLongA(HWND w,int k){(void)w;(void)k;return style;}
static LONG SetWindowLongA(HWND w,int k,LONG s){(void)w;(void)k;LONG old=style;style=s;return old;}
static HMONITOR MonitorFromWindow(HWND w,int k){(void)w;(void)k;return 1;}
static int GetMonitorInfoA(HMONITOR m,MONITORINFO *mi){if(m<1||m>2)return 0;mi->rcMonitor=rects[m-1];return 1;}
static int GetWindowPlacement(HWND w,WINDOWPLACEMENT *p){(void)w;placements++;p->rect=position;return 1;}
static int SetWindowPlacement(HWND w,const WINDOWPLACEMENT *p){(void)w;if(restore_fail)return 0;position=p->rect;return 1;}
static int GetWindowRect(HWND w,RECT *r){(void)w;*r=position;return 1;}
static int EqualRect(const RECT *a,const RECT *b){return !memcmp(a,b,sizeof *a);}
static unsigned long GetLastError(void){return 5;}
static int SetWindowPos(HWND w,HWND z,int x,int y,int width,int height,int flags){
    (void)w;(void)z;if(position_fail)return 0;
    if(!(flags&SWP_NOMOVE)){position.left=x;position.top=y;}
    if(!(flags&SWP_NOSIZE)){position.right=x+width;position.bottom=y+height;}return 1;
}
static void mouse_capture(HWND w,int on){(void)w;mouse_captured=on;clipped++;}
'''
WINDOWS_MAIN = r'''
int main(void){
    monitor_loaded=1;
    RECT initial=position;
    hos_monitor_select("two");mouse_captured=1;
    set_fullscreen((void *)1,1);CHECK(fullscreen && position.left==-2560 && placements==1 && clipped==2);
    hos_monitor_select("one");set_fullscreen((void *)1,1);
    CHECK(fullscreen && position.left==0 && placements==1); /* don't overwrite windowed placement */
    restore_fail=1;set_fullscreen((void *)1,0);CHECK(fullscreen && style==0);
    restore_fail=0;set_fullscreen((void *)1,0);CHECK(!fullscreen && EqualRect(&position,&initial));
    position_fail=1;set_fullscreen((void *)1,1);CHECK(!fullscreen && style==WS_OVERLAPPEDWINDOW);
    puts("fullscreen monitor Windows placement passed");return 0;
}
'''

SDL = r'''
static int version=3,positioned,entered,synced,mode_fail,last_x,last_y,actual_fullscreen;
static struct {void *GetWindowPosition,*SetWindowPosition,*SetWindowFullscreen,*SyncWindow;} f;
#define CALL(type,fn) ((type)f.fn)
static _Bool position3(void *w,int x,int y){(void)w;positioned++;last_x=x;last_y=y;return 0;} /* Wayland windowed Unsupported */
static int pending_display=-1,active_display=-1,enter_fail;
static void position2(void *w,int x,int y){
    (void)position3(w,x,y);
    if ((x&0xffff0000)==0x2fff0000) pending_display=x&0xffff;
    /* SDL2 only changes saved windowed placement while fullscreen. */
}
static _Bool full3(void *w,_Bool on){(void)w;entered++;CHECK(positioned);if(!mode_fail)actual_fullscreen=on;return !mode_fail;}
static int full2(void *w,uint32_t flags){
    (void)w;entered++;
    if(mode_fail || (flags && enter_fail))return -1;
    if(actual_fullscreen==(flags!=0))return 0; /* SDL2's unchanged-flags early return. */
    actual_fullscreen=flags!=0;
    if(flags)active_display=pending_display;
    return 0;
}
static _Bool get3(void *w,int *x,int *y){(void)w;*x=20;*y=30;return 1;}
static void get2(void *w,int *x,int *y){
    (void)w; *x=actual_fullscreen?1000*(active_display+1):last_x;
    *y=actual_fullscreen?200:last_y;
} /* Recapturing a later fullscreen or failed-entry position must not pass restoration. */
static _Bool sync3(void *w){(void)w;synced++;return 1;}
static int hos_sdl_is_fullscreen(void *w){(void)w;return actual_fullscreen;}
'''
SDL_MAIN = r'''
int main(void){
    f.GetWindowPosition=(void *)get3;f.SetWindowPosition=(void *)position3;
    f.SetWindowFullscreen=(void *)full3;f.SyncWindow=(void *)sync3;
    CHECK(hos_sdl_fullscreen_target((void *)1,1,7));
    CHECK(last_x==(0x2fff0000|7) && entered==1 && synced==1);
    CHECK(hos_sdl_fullscreen_target((void *)1,1,8)); /* retarget doesn't replace saved windowed location */
    CHECK(hos_sdl_fullscreen_target((void *)1,0,UINT32_MAX) && last_x==20 && last_y==30);
    CHECK(!hos_sdl_fullscreen_target((void *)1,1,0x10000));
    mode_fail=1;CHECK(!hos_sdl_fullscreen_target((void *)1,1,3));mode_fail=0;
    CHECK(hos_sdl_fullscreen_target((void *)1,0,UINT32_MAX) && last_x==20 && last_y==30);
    version=2;f.GetWindowPosition=(void *)get2;f.SetWindowPosition=(void *)position2;
    f.SetWindowFullscreen=(void *)full2;
    CHECK(hos_sdl_fullscreen_target((void *)1,1,0)); /* SDL2 display index zero is a real target */
    CHECK(last_x==0x2fff0000 && active_display==0);
    CHECK(hos_sdl_fullscreen_target((void *)1,1,1) && active_display==1 && actual_fullscreen);
    int before_position=positioned;
    mode_fail=1;
    CHECK(!hos_sdl_fullscreen_target((void *)1,1,2));
    CHECK(actual_fullscreen && active_display==1 && positioned==before_position);
    mode_fail=0;enter_fail=1;
    CHECK(!hos_sdl_fullscreen_target((void *)1,1,2) && !actual_fullscreen);
    enter_fail=0;
    CHECK(hos_sdl_fullscreen_target((void *)1,1,2) && active_display==2);
    CHECK(hos_sdl_fullscreen_target((void *)1,0,UINT32_MAX) && last_x==20 && last_y==30);
    puts("fullscreen monitor SDL call order passed");return 0;
}
'''


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--cc",default="clang");args=p.parse_args()
    common=(ROOT/"host/fullscreen_monitor.c").read_text(encoding="utf-8").replace('#include "hos.h"',"").replace('#include <windows.h>',"")
    windows=(ROOT/"host/display.c").read_text(encoding="utf-8")
    sdl=(ROOT/"host/hos_sdl.c").read_text(encoding="utf-8")
    for symbol in ("SDL_GetDisplays","SDL_GetNumVideoDisplays","SDL_GetDisplayName","SDL_SetWindowPosition"):
        assert symbol in sdl, symbol
    assert "same==1 && token<=0xffff" in block(sdl,"int hos_sdl_monitor_list(")
    cases={"policy":BASE+common+POLICY,
           "windows":BASE+common+WINDOWS+block(windows,"static HMONITOR fullscreen_target(")+block(windows,"static void set_fullscreen(")+WINDOWS_MAIN,
           "sdl":BASE+'#include "fullscreen_monitor.h"\n'+SDL+block(sdl,"int hos_sdl_fullscreen_target(")+SDL_MAIN}
    with tempfile.TemporaryDirectory(prefix="fullscreen-monitor-") as temp:
        for name,source in cases.items():
            path=Path(temp)/(name+".c");exe=Path(temp)/(name+(".exe" if sys.platform=="win32" else ""))
            path.write_text(source,encoding="utf-8")
            subprocess.run([args.cc,"-std=c11","-Wall","-Wextra","-I",str(ROOT/"host"),str(path),"-o",str(exe)],check=True)
            subprocess.run([str(exe)],check=True)


if __name__=="__main__":main()
