"""Exercise the Builder's state-list import and cache save with game-free call stubs."""
import argparse, os, struct, subprocess, tempfile
from pathlib import Path
RUN_ALL_ARGS = ["--cxx", "{cxx}"]


def block(source, marker):
    start = source.index(marker)
    at = source.index('{', start) + 1
    end, depth = at, 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[at:end - 1]


p=argparse.ArgumentParser();p.add_argument('--source',type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument('--cxx',default='clang++');a=p.parse_args()
body=block((a.source/'gpu/vk/vk_main.cpp').read_text(encoding='utf-8'), 'if (prepare_only()) {')
draw=(a.source/'gpu/vk/vk_draw.cpp').read_text(encoding='utf-8')
readers='\n'.join(marker+'{'+block(draw,marker)+'}' for marker in
                 ('bool predicted_keys_read(std::vector<uint64_t>& keys)', 'bool predicted_complete()',
                  'const std::vector<uint64_t>& predicted_keys()'))
already_prepared=block((a.source/'gpu/vk/vk_draw.cpp').read_text(encoding='utf-8'),
                       'if (why == PrepareWhy::None && !env_on("RX_VK_PREPARE_AGAIN")) {')
cpp=r"""
#include "vk_progress.h"
#include "crash_markers.h"   // (the stage libraries' marker, prepare_run's, as vk_draw.cpp includes it)
using namespace mkwvk;
#include <cstdio>
#include <cstdint>
#include <cstdlib>
#include <string>
#include <vector>
using std::size_t;
// A tiny damaged record must be rejected before allocating its declared (up to 512 MB) payload.
void* operator new(size_t n){if(n>(1u<<20))std::abort();if(void* p=std::malloc(n?n:1))return p;std::abort();}
void operator delete(void* p) noexcept{std::free(p);}
void operator delete(void* p,size_t) noexcept{std::free(p);}
std::string keys_path;
std::string predicted_keys_path(){return keys_path;}
uint64_t program_cache_stamp(){return 42;}
"""+readers+r"""
std::vector<int> calls;
bool empty_states=false;
void state_list_prepare(void(*progress)(size_t,size_t),bool open_seed=false){
 if(!open_seed||!progress)std::exit(7);
 calls.push_back(6);
 if(!empty_states){
  progress(1,4);
  progress(4,4);
 }
}
int seed_open(){std::exit(8);}
void logf(const char*,...){std::exit(9);}
bool warm_libraries(void(*)(size_t,size_t)){std::exit(10);}
struct PreparedFor {int warmed=1;};
void prepared_write(const std::string&, PreparedFor){std::exit(11);}
bool fresh_seed=true;
bool reuse_seed(void(*progress)(size_t,size_t),bool background,bool refresh_states){
 const PreparedFor already{};
 PreparedFor prepared_for=already;
 const int warmed=already.warmed;
 const bool libraries=false;
 const std::string warming="warming",path="prepared";
 """+already_prepared+r"""
}
bool prepare_run(void(*progress)(size_t,size_t),bool background=false,bool refresh_states=false){
 if(background||!refresh_states)std::exit(3);
 calls.push_back(1);
 return fresh_seed || reuse_seed(progress,background,refresh_states);
}
void predict_run(void(*)(size_t,size_t)){calls.push_back(5);}
bool pending=false;
bool predict_pending(){return pending;}
bool all_mode=true;
bool compile_all(){return all_mode;}   // (the level read; the real completion reader is cut out above)
void precompile_run(void(*progress)(size_t,size_t)){calls.push_back(2);progress(1,2);}
void pipeline_cache_save(bool force){if(!force)std::exit(2);calls.push_back(3);}
std::string skipped_path(){return "sentinel";}
void prepare_watchdog(){}   // (vk_main.cpp: the run's watchdog, tests/test_prepare_stall.py)
void prepare_moved(int,size_t,size_t){}
bool prepare_left_workers(){return false;}
int driver_faults(){return 0;}
[[noreturn]] void prepare_end(int){std::exit(12);}
void prepare_guess(size_t out[3]){out[0]=out[1]=out[2]=1;}
int fake_remove(const char*){calls.push_back(4);return 0;}
#define remove fake_remove
bool run(){
"""+body+r"""
}
int main(int argc,char** argv){
 if(argc!=6)return 1;
 const std::string mode=argv[1];
 keys_path=argv[4];
 const bool complete=std::string(argv[5])=="1";
 if(mode=="recheck"){
  if(predicted_complete())return 20;
  FILE* f=fopen(keys_path.c_str(),"wb");if(!f)return 21;
  const uint64_t head[2]={42,0};fwrite(head,8,2,f);fclose(f);
  if(!predicted_complete())return 22;
  f=fopen(keys_path.c_str(),"wb");if(!f)return 23;
  fwrite(head,1,7,f);fclose(f);
  return predicted_complete()?24:0;
 }
 if(predicted_complete()!=complete)return 25;
 const auto& keys=predicted_keys();
 if(!complete&&!keys.empty())return 26;
 if(complete&&keys.size()!=(mode=="nonzero"?2u:0u))return 27;
 fresh_seed=mode=="fresh";
 empty_states=mode=="empty";
 pending=mode=="pending";
 all_mode=std::string(argv[2])=="all";
 std::vector<int> want{1};
 if(!fresh_seed)want.push_back(6);
 if(std::string(argv[3])=="1")want.push_back(5);
 for(int call:{2,3,4})want.push_back(call);
 if(!run()||calls!=want){fprintf(stderr,"unexpected prediction scheduling in %s/%s\n",argv[1],argv[2]);return 2;}
 calls.clear();
 if(reuse_seed(nullptr,false,false)||!calls.empty())return 3;
}
"""
with tempfile.TemporaryDirectory(prefix='prepare-cache-') as tmp:
    src=Path(tmp)/'fixture.cpp';exe=Path(tmp)/'fixture.exe';src.write_text(cpp)
    subprocess.run([a.cxx,'-std=c++20','-include',str(a.source/'gpu'/'vk'/'compat'/'hookshot_env.h'),'-I',str(a.source/'gpu'/'vk'),str(src),'-o',str(exe)],check=True)   # (env_on: the switches' rule, gpu/vk/compat/hookshot_env.h)
    env={k:v for k,v in os.environ.items() if k not in ('RX_VK_SEED_CHECK','RX_VK_PREPARE_AGAIN')}
    # (Most: the prediction's part of the bar goes after a fresh seed too, out of the total (0.600 at half the noted pipelines).
    # Left in, the step to the noted pipelines counted it done at its guess: the bar jumped by the prediction's share, 0.714)
    records={
        'missing':None, 'zero':struct.pack('<QQ',42,0), 'nonzero':struct.pack('<QQQQ',42,2,7,9),
        'empty':b'', 'header':struct.pack('<Q',42), 'wrong-stamp':struct.pack('<QQ',43,0),
        'oversized':struct.pack('<QQ',42,(64<<20)+1), 'payload':struct.pack('<QQQ',42,2,7),
        'zero-trailing':struct.pack('<QQ',42,0)+b'x', 'count-short':struct.pack('<QQQQ',42,1,7,9),
        'large-short':struct.pack('<QQ',42,64<<20),
    }
    def check(mode, level, record, predicts, expected=None):
        keys=Path(tmp)/'predicted.keys'
        keys.unlink(missing_ok=True)
        if records[record] is not None: keys.write_bytes(records[record])
        complete=record in ('zero','nonzero')
        result=subprocess.run([str(exe),mode,level,str(int(predicts)),str(keys),str(int(complete))],
                              capture_output=True,text=True,env=env)
        assert result.returncode==0, (mode,level,record,result.returncode,result.stdout,result.stderr)
        if expected is not None:
            progress=[line.split()[1] for line in result.stdout.splitlines() if line.startswith('@@progress ')]
            assert progress == expected, (mode, level, record, progress)
    # The reproduced Most -> All upgrade: unchanged seed/driver and no prediction completion record.
    check('refresh','all','missing',True)
    for record in records:
        check('nonzero' if record=='nonzero' else 'refresh','all',record,record not in ('zero','nonzero'))
        check('nonzero' if record=='nonzero' else 'refresh','most',record,False)
    for mode in ('fresh','pending'):
        for record in ('missing','zero'):
            for level in ('all','most'): check(mode,level,record,level=='all')
    check('recheck','all','missing',False)   # Missing -> valid zero -> truncated, in one process: no cached absence.
    for mode, level, expected in [('fresh', 'all', ['0.714']), ('fresh', 'most', ['0.600']), ('refresh', 'all', ['0.125','0.500','0.750']),
                                  ('refresh', 'most', ['0.125','0.500','0.750']), ('empty', 'all', ['0.500']), ('empty', 'most', ['0.500'])]:
        check(mode,level,'zero',mode=='fresh' and level=='all',expected)
    print("PASS: Builder upgrades Most to All, skips valid completed predictions (including zero keys), and preserves import/progress/save")
