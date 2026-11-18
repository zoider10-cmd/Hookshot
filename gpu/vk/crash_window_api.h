/* (hookshot) The crash window's pages (vk_crash_window.cpp), for the crash helper (host/hos_crash_dialog.c): the back end's
   module draws them as the Insert menu is drawn (vk_ui.h), in a window of their own through the SDL the helper loaded, with
   SDL's renderer, not Vulkan (the crash may have been the GPU's). Looked up by name, mkwvk_crash_page, so a helper without the
   module, or with one older than this, shows SDL's message box instead. Plain C: the helper is C. */
#pragma once

#ifdef __cplusplus
extern "C" {
#endif

typedef struct MkwCrashSdl {
    int version;                          /* 3 or 2, the SDL loaded */
    void *(*sym)(const char *name);       /* a function of that SDL by name, NULL when it has none */
} MkwCrashSdl;

typedef struct MkwCrashPage {
    const char *title;                    /* the window's title ("Hookshot: report ready") */
    const char *heading;                  /* the banner's ("The game crashed") */
    const char *text;                     /* the page's text: its lines; an empty line between paragraphs */
    const char *block;                    /* NULL, or text shown as it is in a box below (the report that would be sent) */
    const char *const *buttons;           /* left to right: the first is Enter's, the last Escape's */
    int nbuttons;                         /* 1 to 4 */
} MkwCrashPage;

/* The page until a button is pressed: its index; -1 when the window was closed; -2 when it could not be shown (no window,
   no renderer). The window stays open for the next page, so the player sees one window go from page to page; until
   mkwvk_crash_close */
typedef int (*mkwvk_crash_page_fn)(const MkwCrashSdl *sdl, const MkwCrashPage *page);
typedef void (*mkwvk_crash_close_fn)(void);

#ifdef __cplusplus
}
#endif
