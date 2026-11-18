/* Authored SDL/device spies. The Python driver inserts production source, never a copy of its algorithm. */
typedef void *HMODULE;
typedef void (*FARPROC)(void);
#define HOS_SDL_AUDIO 0x10
static int version, reversed, missing, duplicate, fail_open, fail_resume, stopped;
static int opens, closes, allocations, queried, frame_checks, initializations;
static uint32_t opened_physical;
static char opened_name[128];
static uint64_t clock_ms;
static const char *names[] = {"Speakers", "Headphones"};
static uint32_t physical_ids[] = {10,20};
static int total(void) { return missing ? 1 : 2; }
static int slot(int i) { return reversed ? total()-1-i : i; }
static const char *device_name(int i, int capture) {
    assert(!capture);
    assert(i>=0 && i<total());
    return duplicate ? "Identical" : names[slot(i)];
}
static const char *name3(uint32_t id) {
    for (int i=0;i<total();i++) if (physical_ids[i]==id) return device_name(i,0);
    return NULL;
}
static int count2(int capture) { assert(!capture); return total(); }
static uint32_t *count3(int *n) {
    *n=total();
    uint32_t *p=malloc((size_t)*n * sizeof *p);
    assert(p); allocations++;
    memcpy(p,physical_ids,(size_t)*n * sizeof *p);
    return p;
}
static void release(void *p) { allocations--; free(p); }
static const char *driver(void) { return "pipewire"; }
typedef struct {
    int freq; uint16_t format; uint8_t channels,silence; uint16_t samples,padding;
    uint32_t size; void (*callback)(void *,uint8_t *,int); void *userdata;
} Spec2;
typedef struct { uint32_t format; int channels,freq; } Spec3;
static int format2(int i, int capture, void *spec) {
    queried++;
    ((Spec2 *)spec)->channels=!strcmp(device_name(i,capture),"Headphones") ? 6 : 2;
    return 0;
}
static int default2(char **name, void *spec, int capture) {
    assert(!capture); *name=NULL; ((Spec2 *)spec)->channels=2; return 0;
}
static _Bool format3(uint32_t id, void *spec, int *frames) {
    queried++; *frames=480;
    ((Spec3 *)spec)->channels=id!=UINT32_MAX && name3(id) && !strcmp(name3(id),"Headphones") ? 6 : 2;
    return 1;
}
static void (*callback2)(void *,uint8_t *,int);
static void (*callback3)(void *,void *,int,int);
static void *callback_user;
typedef struct {
    void (*two)(void *,uint8_t *,int);
    void (*three)(void *,void *,int,int);
    void *user;
    int live;
} FakeHandle;
static FakeHandle handles[64];
static unsigned next_handle=1;
static FakeHandle *handle(unsigned id) { assert(id>0 && id<next_handle && handles[id].live); return &handles[id]; }
static uint32_t open2(const char *name, int capture, const void *spec, void *have, int changes) {
    (void)have; assert(!capture && !changes); opens++;
    snprintf(opened_name,sizeof opened_name,"%s", name ? name : "Default");
    if (fail_open) return 0;
    callback2=((const Spec2 *)spec)->callback; callback_user=((const Spec2 *)spec)->userdata;
    assert(next_handle<64); unsigned id=next_handle++;
    handles[id]=(FakeHandle){callback2,NULL,callback_user,1};
    return id;
}
static void pause2(uint32_t dev, int pause) { (void)handle(dev); assert(!pause); }
static int status2(uint32_t dev) { (void)handle(dev); return stopped ? 0 : 1; }
static void close2(uint32_t dev) {
    FakeHandle *h=handle(dev); closes++;
    /* SDL guarantees callbacks have finished on return, including one racing the close. */
    uint8_t out[24]; h->two(h->user,out,sizeof out);
    h->live=0;
}
static void *open3(uint32_t physical, const void *spec, void (*cb)(void *,void *,int,int), void *user) {
    (void)spec; opens++; opened_physical=physical;
    if (fail_open) return NULL;
    callback3=cb; callback_user=user;
    assert(next_handle<64); unsigned id=next_handle++;
    handles[id]=(FakeHandle){NULL,callback3,callback_user,1};
    return (void *)(uintptr_t)id;
}
static _Bool resume3(void *s) { (void)handle((unsigned)(uintptr_t)s); return !fail_resume; }
static _Bool put3(void *s, const void *data, int len) {
    (void)data; (void)handle((unsigned)(uintptr_t)s); assert(len%12==0); frame_checks++; return 1;
}
static void destroy3(void *s) {
    FakeHandle *h=handle((unsigned)(uintptr_t)s); closes++;
    h->three(h->user,s,24,24);
    h->live=0;
}
static HMODULE load_one(const char *name) { (void)name; return (void *)(uintptr_t)1; }
static FARPROC GetProcAddress(HMODULE m, const char *name) {
    assert(m);
#define SYMBOL(n, fn) if (!strcmp(name,n)) return (FARPROC)fn
    SYMBOL("SDL_GetAudioPlaybackDevices",count3);
    SYMBOL("SDL_GetNumAudioDevices",count2);
    if (!strcmp(name,"SDL_GetAudioDeviceName")) return version==3 ? (FARPROC)name3 : (FARPROC)device_name;
    SYMBOL("SDL_GetCurrentAudioDriver",driver); SYMBOL("SDL_free",release);
    SYMBOL("SDL_CloseAudioDevice",close2); SYMBOL("SDL_DestroyAudioStream",destroy3);
    SYMBOL("SDL_GetAudioDeviceFormat",format3); SYMBOL("SDL_GetAudioDeviceSpec",format2);
    SYMBOL("SDL_GetDefaultAudioInfo",default2); SYMBOL("SDL_GetAudioDeviceStatus",status2);
#undef SYMBOL
    return NULL;
}
static int hos_sdl_load(void) { return version; }
static int hos_sdl_init(uint32_t flags) { assert(flags==HOS_SDL_AUDIO); initializations++; return 1; }
static void hos_sdl_hint(const char *name, const char *value) { (void)name; (void)value; }
static uint64_t GetTickCount64(void) { return clock_ms; }
static struct { void *PutAudioStreamData,*OpenAudioDeviceStream,*ResumeAudioStreamDevice,*OpenAudioDevice,*PauseAudioDevice; } f;
#define CALL(type, fn) ((type)f.fn)
/* PRODUCTION_SOUND */

/* Queue-lock spies: close must not hold the mutex when SDL synchronizes the callback. */
typedef int pthread_mutex_t;
static int pthread_mutex_init(pthread_mutex_t *m, void *attr) { (void)attr; *m=0; return 0; }
static int pthread_mutex_destroy(pthread_mutex_t *m) { assert(!*m); return 0; }
static int pthread_mutex_lock(pthread_mutex_t *m) { assert(!*m); *m=1; return 0; }
static int pthread_mutex_unlock(pthread_mutex_t *m) { assert(*m); *m=0; return 0; }
typedef uint32_t DWORD, UINT;
typedef uintptr_t DWORD_PTR;
typedef UINT MMRESULT;
typedef void *HWAVEOUT;
#define MMSYSERR_NOERROR 0
#define MMSYSERR_ERROR 1
#define MMSYSERR_NODRIVER 6
#define WHDR_DONE 1
#define WHDR_PREPARED 2
#define WHDR_INQUEUE 16
typedef struct { uint16_t wFormatTag,nChannels; uint32_t nSamplesPerSec,nAvgBytesPerSec; uint16_t nBlockAlign,wBitsPerSample,cbSize; } WAVEFORMATEX;
typedef struct { char *lpData; DWORD dwBufferLength,dwBytesRecorded; DWORD_PTR dwUser; DWORD dwFlags,dwLoops; void *lpNext; DWORD_PTR reserved; } WAVEHDR;
/* PRODUCTION_WAVE */

static void drive(HWAVEOUT wave) {
    Pull *p=(Pull *)((WaveOut *)wave)->audio;
    FakeHandle *h=handle(p->stream ? (unsigned)(uintptr_t)p->stream : p->device);
    uint8_t out[24];
    if (version==2) h->two(h->user,out,sizeof out);
    else h->three(h->user,p->stream,sizeof out,sizeof out);
}

int main(int argc, char **argv) {
    assert(argc==2); version=atoi(argv[1]); assert(version==2 || version==3);
    f.PutAudioStreamData=(void *)put3; f.OpenAudioDeviceStream=(void *)open3;
    f.ResumeAudioStreamDevice=(void *)resume3; f.OpenAudioDevice=(void *)open2; f.PauseAudioDevice=(void *)pause2;
    assert(hos_audio_output_count()==2 && !opens);
    char id[2048], name[1024];
    assert(hos_audio_output_info(0,id,sizeof id,name,sizeof name));
    const char *wanted="sdl:pipewire:Headphones";
    int token=hos_audio_output_resolve(wanted); assert(token>=0);
    reversed=1;
    assert(hos_audio_output_resolve(wanted)==token); /* enumeration order must not change identity */
    hos_audio_output_select(wanted);
    assert(hos_sdl_audio_channels()==6 && queried && !opens);
    WAVEFORMATEX format={1,6,48000,576000,12,16,0};
    HWAVEOUT wave=NULL;
    assert(waveOutOpen(&wave,(unsigned)token,&format,0,0,0)==0 && wave);
    if (version==2) assert(!strcmp(opened_name,"Headphones"));
    else assert(opened_physical==10); /* reverse makes index 0 Headphones */
    int16_t samples[12]={1,2,3};
    WAVEHDR header={0}; header.lpData=(char *)samples; header.dwBufferLength=sizeof samples;
    assert(!waveOutPrepareHeader(wave,&header,sizeof header));
    assert(!waveOutWrite(wave,&header,sizeof header));
    drive(wave);
    assert(header.dwFlags & WHDR_DONE);
    /* Remove the selected name even though the SDL callback may still be producing silence. */
    reversed=0; missing=1; clock_ms=2000;
    assert(waveOutWrite(wave,&header,sizeof header)==MMSYSERR_NODRIVER);
    assert(hos_audio_output_resolve(wanted)==-1);
    assert(!waveOutClose(wave) && closes==1);
    unsigned generation=0; char preference[2048];
    hos_audio_output_preference(preference,sizeof preference,&generation); assert(!strcmp(preference,wanted));
    assert(!waveOutOpen(&wave,UINT_MAX,&format,0,0,0));
    assert(version==2 ? !strcmp(opened_name,"Default") : opened_physical==UINT32_MAX);
    assert(!waveOutReset(wave)); assert(!waveOutClose(wave));
    missing=0; assert(hos_audio_output_resolve(wanted)==token);
    assert(!waveOutOpen(&wave,(unsigned)token,&format,0,0,0)); assert(!waveOutClose(wave));
    int old_closes=closes;
    fail_open=1; assert(waveOutOpen(&wave,(unsigned)token,&format,0,0,0)!=0); assert(closes==old_closes);
    fail_open=0;
    if (version==3) {
        fail_resume=1; assert(waveOutOpen(&wave,(unsigned)token,&format,0,0,0)!=0);
        assert(closes==old_closes+1); fail_resume=0;
    }
    duplicate=1; assert(hos_audio_output_count()==0); assert(hos_audio_output_resolve(wanted)==-1);
    assert(waveOutOpen(&wave,(unsigned)token,&format,0,0,0)!=0);
    duplicate=0; assert(hos_audio_output_resolve(wanted)==token);
    /* Retry probing must coexist with a working fallback, including callbacks during either close. */
    HWAVEOUT fallback=NULL, probe=NULL;
    assert(!waveOutOpen(&fallback,UINT_MAX,&format,0,0,0));
    fail_open=1; assert(waveOutOpen(&probe,(unsigned)token,&format,0,0,0)!=0);
    drive(fallback);
    fail_open=0; assert(!waveOutOpen(&probe,(unsigned)token,&format,0,0,0));
    drive(fallback); drive(probe);
    assert(!waveOutClose(fallback)); drive(probe); assert(!waveOutClose(probe));
    for (unsigned i=1;i<next_handle;i++) assert(!handles[i].live);
    assert(!allocations && (version==2 || frame_checks>0) && initializations==1);
    printf("PASS SDL%d: discovery, stable selection/reorder, channels, PCM, removal, default, return, failed open/resume, duplicates, callback-safe close\n",version);
    return 0;
}
