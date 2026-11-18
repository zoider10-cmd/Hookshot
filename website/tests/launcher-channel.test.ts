import assert from 'node:assert/strict';
import test from 'node:test';
import { installLauncherChannel, installLauncherStatus, validateLauncherVersions } from '../src/lib/launcher-channel.ts';

const versions = {
  bestChannel: 'rc',
  channels: {
    stable: null,
    rc: { tag: 'v1.0.0-rc.5', downloads: {
      windows: 'https://git-cdn.magicbean.dev/attachments/rc-windows',
      linux: 'https://git-cdn.magicbean.dev/attachments/rc-linux',
    } },
    nightly: { tag: 'nightly-42-abcdef12', downloads: {
      windows: 'https://git-cdn.magicbean.dev/attachments/nightly-windows',
    } },
  },
};

function fixture() {
  const links = ['windows', 'linux', 'windows-portable'].map(kind => {
    const attrs = new Map([['href', '/download/launcher/' + kind]]);
    return { textContent: kind, classList: { toggle() {} }, getAttribute: (name) => attrs.get(name) ?? null,
      setAttribute: (name, value) => attrs.set(name, value), removeAttribute: name => attrs.delete(name) };
  });
  const picked = { value: 'rc', dataset: { note: 'Release candidate' } };
  const note = { textContent: '' }, version = { textContent: '' };
  let change = () => {};
  const root = { hidden: true,
    parentElement: { querySelectorAll: () => links, querySelector: () => version },
    querySelectorAll: () => [],
    querySelector: selector => selector === 'input:checked' ? picked : note,
    addEventListener: (_, fn) => { change = fn; },
  };
  return { document: { querySelector: () => root } as unknown as Document, links, picked, note, version, root, change: () => change() };
}

test('shows the selected launcher version and pins links to its files, including channel changes', async () => {
  const f = fixture();
  await installLauncherChannel(f.document, async url => {
    assert.equal(url, '/download/launcher/versions.json');
    return Response.json(versions);
  });
  assert.equal(f.root.hidden, false);
  assert.match(f.version.textContent, /Hookshot Launcher v1\.0\.0-rc\.5/);
  assert.equal(f.links[0].getAttribute('href'), versions.channels.rc.downloads.windows);
  assert.equal(f.links[2].getAttribute('href'), null);
  assert.equal(f.links[2].getAttribute('aria-disabled'), 'true');
  assert.equal(f.links[2].getAttribute('role'), 'link');
  assert.equal(f.links[2].getAttribute('tabindex'), '-1');
  f.picked.value = 'nightly'; f.change();
  assert.match(f.version.textContent, /nightly-42-abcdef12/);
  assert.equal(f.links[0].getAttribute('href'), versions.channels.nightly.downloads.windows);
  assert.equal(f.links[1].getAttribute('href'), null);
  f.picked.value = 'rc'; f.change();
  assert.equal(f.links[1].getAttribute('href'), versions.channels.rc.downloads.linux);
  assert.equal(f.links[1].getAttribute('aria-disabled'), null);
  assert.equal(f.links[1].textContent, 'linux');
  f.picked.value = ''; f.change();
  assert.match(f.version.textContent, /v1\.0\.0-rc\.5/);
});

test('no published releases is different from a lookup failure', async () => {
  const empty = fixture();
  await installLauncherChannel(empty.document, async () => Response.json({ bestChannel: null, channels: { stable: null, rc: null, nightly: null } }));
  assert.match(empty.version.textContent, /No launcher release/);
  assert(empty.links.every(link => link.getAttribute('href') === null));
  const failed = fixture();
  await installLauncherChannel(failed.document, async () => new Response('offline', { status: 502 }));
  assert.match(failed.version.textContent, /Version information is unavailable/);
  assert.equal(failed.root.hidden, false);
  assert.equal(failed.links[0].getAttribute('href'), '/download/launcher/windows');
  failed.picked.value = 'nightly'; failed.change();
  assert.equal(failed.links[0].getAttribute('href'), '/download/launcher/nightly/windows');
});

test('a channel changed during lookup uses its own version when the response arrives', async () => {
  const f = fixture();
  let resolve;
  const ready = installLauncherChannel(f.document, () => new Promise(done => { resolve = done; }));
  f.picked.value = 'nightly'; f.change();
  resolve(Response.json(versions));
  await ready;
  assert.match(f.version.textContent, /nightly-42-abcdef12/);
  assert.equal(f.links[0].getAttribute('href'), versions.channels.nightly.downloads.windows);
});

test('invalid download metadata cannot replace the existing links', async () => {
  for (const href of ['javascript:alert(1)', 'https://example.com/file', 'https://secret@git.magicbean.dev/file']) {
    const bad = structuredClone(versions);
    bad.channels.rc.downloads.windows = href;
    assert.throws(() => validateLauncherVersions(bad));
    const f = fixture();
    await installLauncherChannel(f.document, async () => Response.json(bad));
    assert.match(f.version.textContent, /Version information is unavailable/);
    assert.equal(f.links[0].getAttribute('href'), '/download/launcher/windows');
  }
});

test('platform hints never recommend a desktop Linux build to Android or ChromeOS', async () => {
  const { preferredPlatform } = await import('../src/lib/launcher-channel.ts');
  for (const ua of ['Android Linux', 'CrOS Linux', 'iPhone', 'iPad', 'Macintosh', '']) assert.equal(preferredPlatform(ua), null);
  assert.equal(preferredPlatform('Mozilla Windows NT 10.0'), 'windows');
  assert.equal(preferredPlatform('Mozilla X11 Linux x86_64'), 'linux');
});

test('availability follows the release catalogue, including the first stable release and an empty catalogue', async () => {
  for (const available of [true, false]) {
    const f = fixture();
    const radios = ['stable', 'rc', 'nightly'].map(value => ({ value, checked: value === 'rc', disabled: false, dataset: { note: value } }));
    f.root.querySelectorAll = () => radios;
    f.root.querySelector = selector => selector === 'input:checked' ? radios.find(r => r.checked) : f.note;
    const catalog = available ? { bestChannel: 'stable', channels: { ...versions.channels, stable: versions.channels.rc } }
      : { bestChannel: null, channels: { stable: null, rc: null, nightly: null } };
    await installLauncherChannel(f.document, async () => Response.json(catalog));
    assert.equal(f.root.hidden, false);
    if (available) {
      assert.equal(radios[0].checked, true);
      assert.equal(radios[0].disabled, false);
      assert.equal(f.links[0].getAttribute('href'), versions.channels.rc.downloads.windows);
    } else {
      assert(radios.every(r => r.disabled));
      assert(f.links.every(link => link.getAttribute('href') === null));
      assert.match(f.version.textContent, /No launcher release/);
    }
  }
});

test('untrusted sizes and release-note URLs are rejected', () => {
  for (const extra of [{ sizes: { windows: -1 } }, { sizes: { windows: NaN } }, { url: 'https://example.com/release' }, { url: 'https://git.magicbean.dev/MagicBeanDev/Other/releases/1' }]) {
    const catalog = structuredClone(versions);
    Object.assign(catalog.channels.rc, extra);
    assert.throws(() => validateLauncherVersions(catalog));
  }
});


test('timeout and invalid release metadata keep every channel reachable', async () => {
  for (const fetcher of [async () => { throw new DOMException('Timeout', 'TimeoutError'); }, async () => {
    const bad = structuredClone(versions); bad.channels.rc.url = 'https://example.com/release'; return Response.json(bad);
  }]) {
    const f = fixture();
    const radios = ['stable', 'rc', 'nightly'].map(value => ({ value, disabled: true }));
    f.root.querySelectorAll = () => radios;
    await installLauncherChannel(f.document, fetcher);
    assert.equal(f.root.hidden, false);
    assert(radios.every(r => !r.disabled));
    f.picked.value = 'stable'; f.change();
    assert.equal(f.links[0].getAttribute('href'), '/download/launcher/stable/windows');
    f.picked.value = 'nightly'; f.change();
    assert.equal(f.links[0].getAttribute('href'), '/download/launcher/nightly/windows');
  }
});


test('pending metadata keeps best-channel routes until the user explicitly chooses a channel', async () => {
  const f = fixture();
  let resolve;
  const ready = installLauncherChannel(f.document, () => new Promise(done => { resolve = done; }));
  assert.equal(f.links[0].getAttribute('href'), '/download/launcher/windows');
  assert.equal(f.links[1].getAttribute('href'), '/download/launcher/linux');
  f.picked.value = 'rc'; f.change();
  assert.equal(f.links[0].getAttribute('href'), '/download/launcher/rc/windows');
  resolve(new Response('offline', { status: 502 }));
  await ready;
  assert.equal(f.links[0].getAttribute('href'), '/download/launcher/rc/windows');
});

test('the front page names the launcher and its channel beside its version, not as the game\'s', async () => {
  const statuses = [{ textContent: '' }, { textContent: '' }];
  const document = { querySelectorAll: selector => selector === '[data-launcher-status]' ? statuses : [] };
  await installLauncherStatus(document as any, async () => Response.json(versions));
  for (const status of statuses) assert.equal(status.textContent, 'Hookshot Launcher v1.0.0-rc.5 · release candidate');
});
