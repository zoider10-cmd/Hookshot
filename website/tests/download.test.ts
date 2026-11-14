// The download links' channel rules (worker/index.ts), the same cases as the launcher's scripts/release.py tests
// (tests/test_release.py, Channels). No network.
import assert from "node:assert/strict";
import test from "node:test";
import { assetOf, best, newest, versionKey } from "../worker/index.ts";

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
