// hookshot.magicbean.dev's Worker: the built site (dist/), and permanent download links for the Hookshot Launcher.
//
//   /download                                   a page: the launcher for this computer, from the best channel there is
//   /download/launcher/<os>                     302 to that file of the best channel (stable, else rc, else nightly)
//   /download/launcher/<channel>                302 to that channel's newest release page
//   /download/launcher/<channel>/<os>           302 to that file of the channel's newest release
//
// <channel> is stable, rc or nightly; <os> is windows (the setup), windows-portable (the zip) or linux (the AppImage).
// The channels follow the launcher's rules (Core/ReleaseManifest.cs, Newest; scripts/release.py, newest): drafts never;
// stable the newest vX.Y.Z that is not a pre-release; rc the newest vX.Y.Z-rc.N or vX.Y.Z; nightly the newest
// nightly-<count>-<8 hex> by its count. The release list is read from git.magicbean.dev and kept 60 seconds.

const FORGE = "https://git.magicbean.dev";
const REPO = "MagicBeanDev/HookshotLauncher";
const FIRST_MAJOR = 1;
const CACHE_SECONDS = 60;
const CHANNELS = ["stable", "rc", "nightly"];
const FILES = {
  windows: { suffix: "-windows-x64-setup.exe", label: "Windows installer", note: "setup.exe" },
  "windows-portable": { suffix: "-windows-x64-portable.zip", label: "Windows portable", note: "zip, no install" },
  linux: { suffix: "-x86_64.AppImage", label: "Linux", note: "AppImage" },
};
const CHANNEL_NAME = { stable: "Stable", rc: "Release candidate", nightly: "Nightly" };
const CHANNEL_NOTE = {
  stable: "for playing",
  rc: "the next version, to try before it is stable",
  nightly: "every change, untested",
};

const STABLE = /^v(\d+)\.(\d+)\.(\d+)$/;
const VERSION = /^v(\d+)\.(\d+)\.(\d+)(?:-rc\.(\d+))?$/;
const NIGHTLY = /^nightly-([0-9]{1,9})-([0-9a-f]{8})$/;

export function versionKey(tag) {
  const m = VERSION.exec(tag || "");
  if (!m) return null;
  return [+m[1], +m[2], +m[3], m[4] ? 0 : 1, +(m[4] || 0)];
}

function compareKeys(a, b) {
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return a[i] - b[i];
  return 0;
}

/** The release a channel offers, from Forgejo's release list, or null */
export function newest(releases, channel) {
  const published = releases.filter((r) => !r.draft);
  if (channel === "nightly") {
    let best = null;
    for (const r of published) {
      const m = NIGHTLY.exec(r.tag_name);
      if (m && (!best || +m[1] > +NIGHTLY.exec(best.tag_name)[1])) best = r;
    }
    return best;
  }
  let best = null;
  for (const r of published) {
    const k = versionKey(r.tag_name);
    if (!k || k[0] < FIRST_MAJOR) continue;
    if (channel === "stable" && (!STABLE.test(r.tag_name) || r.prerelease)) continue;
    if (!best || compareKeys(k, versionKey(best.tag_name)) > 0) best = r;
  }
  return best;
}

/** The release asset of a kind (windows, windows-portable, linux), or null */
export function assetOf(release, kind) {
  const suffix = FILES[kind].suffix;
  return (release.assets || []).find((a) => a.name.startsWith("HookshotLauncher-") && a.name.endsWith(suffix)) || null;
}

/** The best channel there is: stable, else rc, else nightly; [channel, release] or [null, null] */
export function best(releases) {
  for (const c of CHANNELS) {
    const r = newest(releases, c);
    if (r) return [c, r];
  }
  return [null, null];
}

// ---- the release list, cached ----

async function fetchReleases(ctx) {
  const cache = caches.default;
  const key = new Request(`${FORGE}/api/v1/repos/${REPO}/releases?magicbean-site-cache=1`);
  const hit = await cache.match(key);
  if (hit) return hit.json();
  const all = [];
  for (let page = 1; page <= 5; page++) {
    const r = await fetch(`${FORGE}/api/v1/repos/${REPO}/releases?limit=50&page=${page}`, {
      // (Cloudflare refuses requests with no browser or tool User-Agent)
      headers: { "User-Agent": "hookshot-website (+https://hookshot.magicbean.dev)", Accept: "application/json" },
    });
    if (!r.ok) throw new Error(`git.magicbean.dev answered ${r.status}`);
    const items = await r.json();
    if (!Array.isArray(items)) throw new Error("git.magicbean.dev answered no release list");
    all.push(...items);
    if (items.length < 50) break;
  }
  const slim = all.map((r) => ({
    tag_name: r.tag_name, draft: !!r.draft, prerelease: !!r.prerelease, html_url: r.html_url, published_at: r.published_at,
    assets: (r.assets || []).map((a) => ({ name: a.name, size: a.size, browser_download_url: viaCdn(a.browser_download_url) })),
  }));
  const stored = new Response(JSON.stringify(slim), {
    headers: { "Content-Type": "application/json", "Cache-Control": `public, max-age=${CACHE_SECONDS}` },
  });
  ctx.waitUntil(cache.put(key, stored));
  return slim;
}

// ---- pages ----

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const mb = (n) => (n ? `${Math.round(n / 1048576)} MB` : "");

// The site's own pages (src/content-pages.ts, src/content/docs/), linked from the download pages.
const NAV = [["Get started", "/install/"], ["Requirements", "/requirements/"], ["Help", "/help/"], ["About", "/about/"]];

// The same look as the rest of the site (src/styles/theme.css): its colours, its light and dark themes (and the
// theme the visitor picked there, which Starlight keeps in localStorage), its header and its logo.
function page(title, body, status = 200) {
  return new Response(`<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${esc(title)}</title>
  <meta name="description" content="Download the Hookshot Launcher for Windows or Linux: it builds the game from your own copy.">
  <link rel="icon" type="image/png" href="/branding/hookshot.png">
  <meta name="theme-color" content="#0e100f">
  <script>try { const t = localStorage.getItem("starlight-theme"); if (t === "light" || t === "dark") document.documentElement.dataset.theme = t; } catch {}</script>
  <style>
    :root {
      --bg: #0e100f; --fg: #f5f7f3; --muted: #c0c6c1; --faint: #949b96; --border: #2f3431; --panel: #161917;
      --panel-hover: #1f2320; --accent: #c2ed83; --button: #c2ed83; --button-hover: #daf5b2; --button-text: #13210d;
      --warn-bg: #2a2412; --warn-line: #a88a3a;
      color-scheme: dark;
    }
    @media (prefers-color-scheme: light) {
      :root:not([data-theme="dark"]) {
        --bg: #f6f7f4; --fg: #121712; --muted: #434a41; --faint: #5f665c; --border: #cfd3cb; --panel: #eef0ea;
        --panel-hover: #e5e8e1; --accent: #365e1b; --button: #3c651e; --button-hover: #254415; --button-text: #f6f7f4;
        --warn-bg: #f6efd8; --warn-line: #b8953a;
        color-scheme: light;
      }
    }
    :root[data-theme="light"] {
      --bg: #f6f7f4; --fg: #121712; --muted: #434a41; --faint: #5f665c; --border: #cfd3cb; --panel: #eef0ea;
      --panel-hover: #e5e8e1; --accent: #365e1b; --button: #3c651e; --button-hover: #254415; --button-text: #f6f7f4;
      --warn-bg: #f6efd8; --warn-line: #b8953a;
      color-scheme: light;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0; background: var(--bg); color: var(--fg); line-height: 1.6; font-size: 1.0625rem;
      font-family: "Atkinson Hyperlegible Next", "Segoe UI", ui-sans-serif, system-ui, sans-serif;
    }
    a { color: var(--accent); text-underline-offset: .15em; }
    a:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; border-radius: 4px; }
    header {
      display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: .5rem 1.5rem;
      max-width: 60rem; margin: 0 auto; padding: 1rem 16px; border-bottom: 1px solid var(--border);
    }
    .home { display: inline-flex; align-items: center; gap: .6rem; color: var(--fg); text-decoration: none; font-weight: 700; font-size: 1.2rem; }
    .home img { width: 36px; height: 36px; }
    nav { display: flex; flex-wrap: wrap; gap: .25rem 1.25rem; }
    nav a { color: var(--muted); text-decoration: none; font-weight: 600; }
    nav a:hover { color: var(--fg); }
    main { max-width: 44rem; margin: 0 auto; padding: 2.5rem 16px 3rem; }
    h1 {
      font-family: "Libertinus Serif", Georgia, "Times New Roman", serif; font-weight: 600;
      font-size: clamp(2rem, 1.5rem + 2vw, 2.75rem); line-height: 1.1; margin: 0 0 .75rem;
    }
    h2 { font-size: 1.25rem; margin: 2.5rem 0 .75rem; }
    p { color: var(--muted); margin: .5rem 0; }
    strong { color: var(--fg); }
    .lead { font-size: 1.15rem; }
    .warn { background: var(--warn-bg); border-left: 4px solid var(--warn-line); border-radius: 8px; padding: .75rem 1rem; margin: 1.25rem 0; color: var(--fg); }
    .bigs { display: flex; flex-wrap: wrap; gap: .75rem; margin: 1.5rem 0 .75rem; }
    .big {
      display: inline-flex; flex-direction: column; padding: .85rem 1.5rem; border-radius: 12px; background: var(--button);
      color: var(--button-text); text-decoration: none; font-weight: 700; font-size: 1.15rem;
    }
    .big small { font-weight: 500; font-size: .85rem; opacity: .85; }
    .big:hover { background: var(--button-hover); }
    .others { display: flex; flex-wrap: wrap; gap: .5rem; margin: .5rem 0; }
    .pill {
      display: inline-block; padding: .35rem .9rem; border-radius: 999px; border: 1px solid var(--border); background: var(--panel);
      color: var(--fg); font-weight: 600; font-size: .95rem; text-decoration: none;
    }
    .pill:hover { background: var(--panel-hover); border-color: var(--faint); }
    .steps { margin: 0; padding-left: 1.25rem; color: var(--muted); }
    .steps li { margin: .35rem 0; }
    .channels { display: grid; gap: .75rem; }
    .channel { border: 1px solid var(--border); background: var(--panel); border-radius: 12px; padding: .9rem 1rem; }
    .channel h3 { margin: 0; font-size: 1.05rem; }
    .channel h3 small { font-weight: 500; color: var(--faint); font-size: .9rem; margin-left: .35rem; }
    .channel p { font-size: .95rem; }
    footer { max-width: 44rem; margin: 0 auto; padding: 1.5rem 16px 2.5rem; border-top: 1px solid var(--border); font-size: .9rem; }
  </style>
</head>
<body>
  <header>
    <a class="home" href="/"><img src="/branding/hookshot.png" alt="" width="512" height="512">Hookshot</a>
    <nav aria-label="Main navigation">${NAV.map(([label, href]) => `<a href="${href}">${label}</a>`).join("")}</nav>
  </header>
  <main>
${body}
  </main>
  <footer><p>Bring your own copy of the game: Hookshot never includes the game, its keys or an executable.
    All launcher releases: <a href="${FORGE}/${REPO}/releases">git.magicbean.dev</a>.</p></footer>
</body>
</html>
`, {
    status,
    headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store", Vary: "User-Agent" },
  });
}

function osOf(request) {
  const ua = request.headers.get("User-Agent") || "";
  if (/Windows/i.test(ua)) return "windows";
  if (/Android|iPhone|iPad|CrOS/i.test(ua)) return null;
  if (/Linux|X11/i.test(ua)) return "linux";
  return null;
}

function channelTable(releases) {
  const rows = CHANNELS.map((c) => {
    const r = newest(releases, c);
    const head = `<h3>${CHANNEL_NAME[c]} <small>${esc(CHANNEL_NOTE[c])}</small></h3>`;
    if (!r) return `<div class="channel">${head}<p>None yet.</p></div>`;
    const links = Object.keys(FILES).filter((k) => assetOf(r, k))
      .map((k) => `<a class="pill" href="/download/launcher/${c}/${k}">${esc(FILES[k].label)}</a>`).join("");
    return `<div class="channel">${head}<div class="others">${links}</div>` +
      `<p><a href="/download/launcher/${c}">${esc(r.tag_name)}</a>, its release page</p></div>`;
  });
  return `<div class="channels">${rows.join("")}</div>`;
}

const NOT_THE_BUILDER = `<p class="lead">The launcher installs the builder and builds the game on your PC, from your own copy.</p>
    <p>The <em>HookshotBuilder</em> files on Hookshot's releases are for the launcher, not for you to run.</p>`;

const NEXT_STEPS = `<h2>Then</h2>
    <ol class="steps">
      <li>Check your PC can build and run it: <a href="/requirements/">Requirements</a>.</li>
      <li>Install, point it at your copy of the game, and play: <a href="/install/">Get started</a>.</li>
      <li>Windows or your browser warns about the download? <a href="/help/antivirus/">Antivirus and SmartScreen</a>.</li>
      <li>Something else goes wrong: <a href="/help/">Help</a>.</li>
    </ol>`;

function downloadPage(request, releases) {
  const [channel, r] = best(releases);
  if (!r) {
    return page("Download the Hookshot Launcher", `    <h1>Download the Hookshot Launcher</h1>
    <p>There is no release yet. Watch <a href="${FORGE}/${REPO}/releases">the release page</a>.</p>`, 404);
  }
  const os = osOf(request);
  const primary = os && assetOf(r, os) ? os : null;
  const bigs = (primary ? [primary] : ["windows", "linux"]).filter((k) => assetOf(r, k)).map((k) => {
    const a = assetOf(r, k);
    return `<a class="big" href="/download/launcher/${k}">Download for ${k === "windows" ? "Windows" : "Linux"}` +
      `<small>${esc(FILES[k].note)} · ${esc(mb(a.size))} · ${esc(r.tag_name)}</small></a>`;
  }).join(" ");
  const others = Object.keys(FILES).filter((k) => k !== primary && assetOf(r, k))
    .map((k) => `<a class="pill" href="/download/launcher/${k}">${esc(FILES[k].label)} (${esc(FILES[k].note)})</a>`).join("");
  const warn = channel === "stable" ? "" :
    `<div class="warn">There is no stable launcher yet: this is the newest <strong>${channel}</strong> (${esc(CHANNEL_NOTE[channel])}).</div>`;
  return page("Download the Hookshot Launcher", `    <h1>Download the Hookshot Launcher</h1>
    ${NOT_THE_BUILDER}
    ${warn}
    <div class="bigs">${bigs}</div>
    <div class="others">${others}</div>
    ${NEXT_STEPS}
    <h2>Every channel</h2>
    ${channelTable(releases)}`);
}

function notFound(releases, what, kind) {
  const [channel, r] = best(releases);
  let offer = r ? `<p>The newest launcher there is: <strong>${esc(r.tag_name)}</strong> (${channel}).</p>` : "";
  if (r && kind && FILES[kind] && assetOf(r, kind)) {
    offer += `<a class="big" href="/download/launcher/${channel}/${kind}">Get ${esc(r.tag_name)} instead` +
      `<small>${esc(FILES[kind].label)} · ${esc(FILES[kind].note)} · ${esc(CHANNEL_NOTE[channel])}</small></a>`;
  }
  return page("Not found: Hookshot Launcher", `    <h1>${esc(what)}</h1>
    ${offer}
    ${channelTable(releases)}
    <p><a class="pill" href="/download">Back to the download page</a></p>`, 404);
}

// Release files are served by git-cdn.magicbean.dev, from Cloudflare's edge: the same path on its own host.
function viaCdn(url) {
  return typeof url === "string" ? url.replace(/^https:\/\/git\.magicbean\.dev\//, "https://git-cdn.magicbean.dev/") : url;
}

function redirect(url) {
  return new Response(null, { status: 302, headers: { Location: url, "Cache-Control": `public, max-age=${CACHE_SECONDS}` } });
}

async function download(request, ctx, parts) {
  let releases;
  try {
    releases = await fetchReleases(ctx);
  } catch (e) {
    return page("Hookshot Launcher", `    <h1>Can't reach git.magicbean.dev</h1>
    <p>${esc(e.message)}. Try again in a minute, or download from <a href="${FORGE}/${REPO}/releases">the release page</a>.</p>`, 502);
  }
  // /download
  if (parts.length === 0) return downloadPage(request, releases);
  if (parts[0] !== "launcher") return notFound(releases, "No such download");
  // /download/launcher
  if (parts.length === 1) return redirect("/download");
  let [channel, kind] = parts.slice(1);
  if (parts.length === 2 && FILES[channel]) {
    // /download/launcher/<os>: the best channel there is
    [kind, channel] = [channel, best(releases)[0]];
    if (!channel) return notFound(releases, "No launcher release yet");
  }
  if (!CHANNELS.includes(channel) || parts.length > 3 || (kind !== undefined && !FILES[kind])) {
    return notFound(releases, "No such download");
  }
  const r = newest(releases, channel);
  if (!r) return notFound(releases, `No ${channel} launcher yet`, kind);
  if (kind === undefined) return redirect(r.html_url);
  const a = assetOf(r, kind);
  if (!a) return notFound(releases, `${r.tag_name} has no ${FILES[kind].label} file`, kind);
  return redirect(a.browser_download_url);
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "");
    if (path === "/download" || path.startsWith("/download/")) {
      if (request.method !== "GET" && request.method !== "HEAD") return new Response("Method not allowed", { status: 405, headers: { Allow: "GET, HEAD" } });
      const parts = path.split("/").slice(2).filter(Boolean).map((p) => p.toLowerCase());
      return download(request, ctx, parts);
    }
    return env.ASSETS.fetch(request);
  },
};
