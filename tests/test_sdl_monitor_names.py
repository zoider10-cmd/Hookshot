"""SDL2/3 friendly UTF-8 display names and existing backend-qualified identity rules.

Compiles the production enumeration function against synthetic SDL APIs; no window/game.
Run: python -I -B tests/test_sdl_monitor_names.py --cc clang
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
#define CHECK(x) do {if(!(x)){fprintf(stderr,"FAIL %d: %s\n",__LINE__,#x);exit(1);}}while(0)
#define HOS_MONITOR_CURRENT 1
#define HOS_MONITOR_PRIMARY 2
typedef struct {char id[512],name[256];int width,height,flags;} MkwVkMonitor;
static int version=3,duplicates,frees;
static const char *backend="wayland";
static uint32_t ids[]={7,9};
static const char *labels[]={"Display \xc3\xa9 model", "Another model"};
static struct {void *GetDisplays,*GetNumVideoDisplays,*GetCurrentVideoDriver,*GetPrimaryDisplay,*GetDisplayName,*GetDesktopDisplayMode;} f;
#define CALL(type,fn) ((type)f.fn)
static uint32_t *get_displays(int *n){*n=2;return ids;}
static int get_count(void){return 2;}
static const char *get_backend(void){return backend;}
static uint32_t get_primary(void){return 7;}
static const char *get_name(uint32_t id){return labels[(version==3?id==9:id==1) && !duplicates];}
static uint32_t hos_sdl_window_display(void *w){(void)w;return version==3?9:1;}
static void hos_sdl_free(void *p){CHECK(p==ids);frees++;}
static int hos_monitor_copy_id(char *dst,size_t cap,const char *src){size_t n=strlen(src);if(n>=cap)return 0;memcpy(dst,src,n+1);return 1;}
static const void *get_mode3(uint32_t id){(void)id;static struct {uint32_t a,b;int w,h;float scale;} mode={0,0,1920,1080,1};return &mode;}
static int get_mode2(int id,void *ptr){(void)id;struct {uint32_t format;int w,h,refresh;void *data;} mode={0,1920,1080,60,NULL};memcpy(ptr,&mode,sizeof mode);return 0;}
'''

MAIN = r'''
int main(void){
    f.GetDisplays=(void *)get_displays;f.GetNumVideoDisplays=(void *)get_count;
    f.GetCurrentVideoDriver=(void *)get_backend;f.GetPrimaryDisplay=(void *)get_primary;
    f.GetDisplayName=(void *)get_name;f.GetDesktopDisplayMode=(void *)get_mode3;
    MkwVkMonitor out[2];uint32_t tokens[2];
    CHECK(hos_sdl_monitor_list((void *)1,out,tokens,2)==2);
    CHECK(!strcmp(out[0].name,"Display \xc3\xa9 model"));
    CHECK(!strcmp(out[0].id,"sdl3:wayland:Display \xc3\xa9 model"));
    CHECK(tokens[0]==7 && tokens[1]==9 && out[1].flags==HOS_MONITOR_CURRENT && frees==1);
    duplicates=1;CHECK(hos_sdl_monitor_list(NULL,out,tokens,2)==2);
    CHECK(!strcmp(out[0].name,out[1].name) && !out[0].id[0] && !out[1].id[0]);
    duplicates=0;version=2;backend="x11";f.GetDesktopDisplayMode=(void *)get_mode2;
    CHECK(hos_sdl_monitor_list((void *)1,out,tokens,2)==2);
    CHECK(!strcmp(out[0].name,"Display \xc3\xa9 model"));
    CHECK(!strcmp(out[0].id,"sdl2:x11:Display \xc3\xa9 model"));
    CHECK(tokens[0]==0 && tokens[1]==1 && out[0].flags==HOS_MONITOR_PRIMARY && frees==2);
    puts("SDL2/3 friendly UTF-8 labels, backend-qualified IDs and ambiguous-name safety passed");
    return 0;
}
'''

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cc', default='clang')
    args = parser.parse_args()
    raw = (ROOT / 'host/hos_sdl.c').read_text(encoding='utf-8')
    source = STUBS + block(raw, 'int hos_sdl_monitor_list(') + MAIN
    with tempfile.TemporaryDirectory(prefix='sdl-monitor-names-') as temp:
        path = Path(temp) / 'test.c'
        exe = Path(temp) / ('test.exe' if sys.platform == 'win32' else 'test')
        path.write_text(source, encoding='utf-8')
        subprocess.run([args.cc, '-std=c11', '-Wall', '-Wextra', '-Werror', str(path), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)

if __name__ == '__main__':
    main()
