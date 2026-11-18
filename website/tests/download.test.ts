// The download links' channel rules (worker/index.ts), the same cases as the launcher's scripts/release.py tests
// (tests/test_release.py, Channels). No network.
import assert from "node:assert/strict";
import test from "node:test";
import worker, { assetOf, best, newest, versionKey, launcherVersions } from "../worker/index.ts";

const rel = (tag_name, draft, prerelease, files = ["windows-x64-setup.exe", "windows-x64-portable.zip", "x86_64.AppImage"]) => ({
  tag_name, draft, prerelease, html_url: `https://git.example.invalid/${tag_name}`,
  assets: [...files.map((f) => ({ name: `HookshotLauncher-${tag_name}-${f}`, browser_download_url: `https://f/${tag_name}/${f}` })),
           { name: "SHA256SUMS" }, { name: "SHA256SUMS.sig" }],
});

test("the version order", () => {
  const order = ["v1.0.0-rc.1", "v1.0.0-rc.2", "v1.0.0-rc.10", "v1.0.0", "v1.0.1-rc.1", "v1.0.1", "v1.1.0", "v10.0.0"];
  const cmp = (a, b) => { const x = versionKey(a), y = versionKey(b); for (let i = 0; i < 5; i++) if (x[i] !== y[i]) return x[i] - y[i]; return 0; };
  assert.deepEqual([...order].reverse().sort(cmp), order);
  assert.equal(versionKey("nightly-1-aaaaaaaa"), null);
});

test("what each channel offers", () => {
  const rels = [rel("v1.0.0", false, false), rel("v1.1.0-rc.1", false, true), rel("v1.1.0-rc.2", true, true), rel("v1.2.0", true, false),
                rel("nightly-9-aaaaaaaa", false, true), rel("nightly-12-bbbbbbbb", false, true), rel("nightly-100-cccccccc", true, true),
                rel("tools", false, true), rel("v0.9.0", false, false)];
  assert.equal(newest(rels, "stable").tag_name, "v1.0.0");                 // (drafts never)
  assert.equal(newest(rels, "rc").tag_name, "v1.1.0-rc.1");
  assert.equal(newest(rels, "nightly").tag_name, "nightly-12-bbbbbbbb");   // (by count, not by text)
  rels.push(rel("v1.1.0", false, false));
  assert.equal(newest(rels, "rc").tag_name, "v1.1.0");                     // (rc offers the stable once it is out)
  rels.push(rel("v1.2.0", false, true));                                   // (a vX.Y.Z marked pre-release is no stable)
  assert.equal(newest(rels, "stable").tag_name, "v1.1.0");
});

test("the best channel: stable, else rc, else nightly", () => {
  const rels = [rel("nightly-10-968b7963", false, true)];
  assert.deepEqual(best(rels).map((x) => x && (x.tag_name || x)), ["nightly", "nightly-10-968b7963"]);
  rels.push(rel("v1.0.0-rc.1", false, true));
  assert.equal(best(rels)[0], "rc");
  rels.push(rel("v1.0.0", false, false));
  assert.equal(best(rels)[0], "stable");
  assert.deepEqual(best([]), [null, null]);
});

test("each file by its kind", () => {
  const r = rel("v1.0.0", false, false, ["windows-x64-setup.exe", "x86_64.AppImage"]);
  assert.equal(assetOf(r, "windows").name, "HookshotLauncher-v1.0.0-windows-x64-setup.exe");
  assert.equal(assetOf(r, "linux").name, "HookshotLauncher-v1.0.0-x86_64.AppImage");
  assert.equal(assetOf(r, "windows-portable"), null);
  // (Hookshot's builder is never a launcher file)
  assert.equal(assetOf({ assets: [{ name: "Hookshot-v3.0.0-x86_64.AppImage" }] }, "linux"), null);
});

test("version metadata uses the redirect channel rules and only that release's available files", () => {
  const releases = [rel('v1.0.0', false, false, ['windows-x64-setup.exe']),
    rel('v1.1.0-rc.2', false, true), rel('v9.0.0', true, false), rel('nightly-12-aaaaaaaa', false, true)];
  const result = launcherVersions(releases);
  assert.equal(result.bestChannel, best(releases)[0]);
  for (const channel of ['stable', 'rc', 'nightly']) {
    assert.equal(result.channels[channel].tag, newest(releases, channel).tag_name);
    assert.equal(result.channels[channel].downloads.windows, assetOf(newest(releases, channel), 'windows').browser_download_url);
  }
  assert.equal(result.channels.stable.downloads.linux, undefined);
  assert.deepEqual(launcherVersions([]), { bestChannel: null, channels: { stable: null, rc: null, nightly: null } });
});

test("version endpoint uses the cached list, returns CDN files and reports upstream errors as JSON", async (t) => {
  const release = rel('v1.0.0-rc.1', false, true);
  release.assets[0].browser_download_url = 'https://git.magicbean.dev/attachments/windows';
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'caches');
  Object.defineProperty(globalThis, 'caches', { configurable: true, value: { default: { match: async () => Response.json([release]) } } });
  t.after(() => { if (previous) Object.defineProperty(globalThis, 'caches', previous); else delete globalThis.caches; });
  const request = new Request('https://hookshot.magicbean.dev/download/launcher/versions.json');
  const env = { ASSETS: { fetch: () => { throw new Error('Metadata must not use static assets'); } } };
  const ctx = { waitUntil: () => {} };
  const response = await worker.fetch(request, env, ctx);
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('Cache-Control'), 'no-store');
  const data = await response.json();
  assert.equal(data.channels.rc.tag, 'v1.0.0-rc.1');
  assert.equal(data.channels.rc.downloads.windows, 'https://git-cdn.magicbean.dev/attachments/windows');
  t.mock.method(globalThis.caches.default, 'match', async () => { throw new Error('offline'); });
  const failed = await worker.fetch(request, env, ctx);
  assert.equal(failed.status, 502);
  assert.equal((await failed.json()).error, 'Launcher versions unavailable');
});

test('download responses use the shared built shell, including error status and escaped titles', async () => {
  const { withSiteShell } = await import('../worker/index.ts');
  const shell = '<html><head><title>Download | Hookshot</title><link rel="canonical" href="https://hookshot.magicbean.dev/download/"><meta property="og:title" content="Download the Hookshot Launcher"><meta property="og:url" content="https://hookshot.magicbean.dev/download/"><meta name="description" content="Download the launcher"></head><body><header>Shared navigation</header><h1 id="_top">Download</h1><launcher-download-content>Fallback</launcher-download-content><footer>Shared footer</footer></body></html>';
  const request = new Request('https://preview.example/download/launcher/missing');
  const response = new Response('<html><main><h1>No &lt;release&gt;</h1><p>Try another channel.</p></main></html>', { status: 404, headers: { 'Content-Type': 'text/html', 'Cache-Control': 'no-store' } });
  const result = await withSiteShell(response, request, { ASSETS: { fetch: async r => {
    assert.equal(r.url, 'https://preview.example/download/');
    return new Response(shell);
  } } });
  assert.equal(result.status, 404);
  assert.equal(result.headers.get('Cache-Control'), 'no-store');
  const html = await result.text();
  assert.match(html, /Shared navigation/);
  assert.match(html, /Shared footer/);
  assert.match(html, /<h1 id="_top">No &lt;release&gt;<\/h1>/);
  assert.match(html, /<title>No &lt;release&gt; \| Hookshot<\/title>/);
  assert.equal((html.match(/<h1/g) || []).length, 1);
  assert.match(html, /Try another channel/);
  assert(!html.includes('Fallback'));
  assert(!html.includes('rel="canonical"'));
  assert(!html.includes('property="og:url"'));
  assert.match(html, /name="robots" content="noindex"/);
  assert.match(html, /property="og:title" content="No &lt;release&gt;"/);
});

test('a missing or malformed shell retains a working standalone download page', async () => {
  const { withSiteShell } = await import('../worker/index.ts');
  for (const fetch of [async () => new Response('Missing', { status: 404 }), async () => new Response('<html>No slot</html>'), async () => { throw new Error('offline'); }]) {
    const response = new Response('<main><h1>Download</h1><a href="/download/launcher/linux">Linux</a></main>', { status: 502 });
    const result = await withSiteShell(response, new Request('https://preview.example/download'), { ASSETS: { fetch } });
    assert.equal(result.status, 502);
    assert.match(await result.text(), /href="\/download\/launcher\/linux"/);
  }
});

test('launcher metadata carries the displayed file size from the same release', () => {
  const release = rel('v1.0.0', false, false);
  release.assets[0].size = 40 * 1048576;
  const metadata = launcherVersions([release]);
  assert.equal(metadata.channels.stable.sizes.windows, 40 * 1048576);
  assert.equal(metadata.channels.stable.downloads.windows, release.assets[0].browser_download_url);
  assert.equal(metadata.channels.stable.url, release.html_url);
});


test('download HTML pins files and release notes to its displayed release and preserves the CDN', async t => {
  const release = rel('v1.0.0', false, false);
  release.html_url = 'https://git.magicbean.dev/MagicBeanDev/HookshotLauncher/releases/tag/v1.0.0';
  release.assets[0].browser_download_url = 'https://git.magicbean.dev/attachments/windows';
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'caches');
  Object.defineProperty(globalThis, 'caches', { configurable: true, value: { default: { match: async () => Response.json([release]) } } });
  t.after(() => { if (previous) Object.defineProperty(globalThis, 'caches', previous); else delete globalThis.caches; });
  const result = await worker.fetch(new Request('https://preview.example/download', { headers: { 'User-Agent': 'Windows NT 10.0' } }), {}, { waitUntil() {} });
  const html = await result.text();
  assert.match(html, /href="https:\/\/git-cdn.magicbean.dev\/attachments\/windows"/);
  assert(html.includes('href="' + release.html_url + '"'));
  assert(!html.includes('href="/download/launcher/windows"'));
  // (the launcher's version is named as the launcher's, apart from the game's Hookshot version)
  assert.match(html, /Launcher v1\.0\.0<\/small>/);
  assert.match(html, /The versions on this page are the launcher's/);
});
