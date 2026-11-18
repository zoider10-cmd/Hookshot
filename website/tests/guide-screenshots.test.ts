import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { repoAssets, repositoryAssets } from '../src/repo-docs/assets.ts';
import { renderPage } from '../src/repo-docs/pages.ts';
import { createMarkdownProcessor } from '@astrojs/markdown-remark';
import { rehypeKeyboardScroll } from '../src/repo-docs/keyboard-scroll.ts';

test('guide tables retain headers and are keyboard reachable without JavaScript', async () => {
  const processor = await createMarkdownProcessor({ rehypePlugins: [rehypeKeyboardScroll] });
  for (const page of ['settings', 'saves/transfer']) {
    const { markdown } = await renderPage(page);
    const { code } = await processor.render(markdown);
    for (const [block] of code.matchAll(/<pre\b[^>]*>/g)) assert.match(block, /tabindex="0"/);
    const tables = [...code.matchAll(/<table\b[^>]*>[\s\S]*?<\/table>/g)];
    assert.ok(tables.length > 0, page);
    for (const [table] of tables) {
      assert.match(table, /^<table tabindex="0" aria-label="[^"]+ — data table" data-scroll-label="[^"]+ — data table">/);
      assert.doesNotMatch(table, /<th>\s*<\/th>/);
      assert.match(table, /<thead>[\s\S]*<th>[^<]+<\/th>/);
    }
  }
});

// A filesystem URL must be decoded: otherwise a checkout under "New Volume"
// writes into a literal New%20Volume directory and serves broken image URLs.
test('guide images copy unchanged into a public directory containing spaces', async () => {
  const dir = await mkdtemp(path.join(tmpdir(), 'hookshot guide assets '));
  try {
    await repoAssets().hooks['astro:config:setup']({ config: { publicDir: pathToFileURL(dir + path.sep) } } as never);
    for (const [source, target] of Object.entries(repositoryAssets)) {
      assert.deepEqual(await readFile(path.join(dir, target)), await readFile(path.resolve('..', source)), source);
    }
  } finally { await rm(dir, { recursive: true, force: true }); }
});

test('canonical guide images resolve to this site, with descriptive alt text', async () => {
  for (const [page, files] of Object.entries({
    install: ['launcher-home.png', 'launcher-game-files.png'],
    'saves/transfer': ['launcher-manage-saves.png', 'launcher-saves.png', 'launcher-import.png', 'launcher-import-confirm.png'],
    settings: ['settings-graphics.png'],
  })) {
    const { markdown } = await renderPage(page);
    const { code } = await (await createMarkdownProcessor()).render(markdown);
    for (const file of files) {
      assert.ok(markdown.includes(`/docs/images/guide/${file}`), `${page}: ${file}`);
      const image = markdown.split('\n').find(line => line.includes(file) && line.trimStart().startsWith('!['));
      assert.match(image ?? '', /^\s*!\[[^\]]{20,}\]\(\/docs\/images\/guide\//);
      assert.ok(!image?.includes('git.magicbean.dev'));
      assert.ok(code.includes(`href="/docs/images/guide/${file}"`), `${file}: full-size link`);
    }
  }
});

test('transfer illustrations remain within the action they explain', async () => {
  const { markdown } = await renderPage('saves/transfer');
  const { code } = await (await createMarkdownProcessor()).render(markdown);
  const items = [...code.matchAll(/<li>([\s\S]*?)<\/li>/g)].map(match => match[1]);
  const chooser = items.find(item => item.includes('launcher-import.png'));
  const confirmation = items.find(item => item.includes('launcher-import-confirm.png'));
  assert.ok(chooser?.includes('Another folder') && chooser?.includes('Continue'));
  assert.ok(confirmation?.includes('FROM') && confirmation?.includes('TO'));
  assert.ok(confirmation?.includes('When the source and destination are correct'));
  assert.ok(!chooser?.includes('launcher-import-confirm.png'));
  assert.ok(!confirmation?.includes('Start Hookshot and load your slot'));
});
