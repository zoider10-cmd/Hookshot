import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { REPOSITORY } from '../src/lib/progress.ts';

test('publication check rejects the deployed error-only feed and malformed feeds, but accepts a valid empty snapshot', async () => {
  const root = await mkdtemp(path.join(tmpdir(), 'hookshot-publication-'));
  const script = fileURLToPath(new URL('../scripts/check-site.ts', import.meta.url));
  const date = '2026-11-13T00:00:00Z';
  const valid = { version: 1, repository: REPOSITORY, collectionStartedAt: date, generatedAt: date,
    closedSince: date, warning: '', stableRelease: null, items: [] };
  try {
    await mkdir(path.join(root, 'dist'));
    await writeFile(path.join(root, 'dist/index.html'), '<html><body>Hookshot</body></html>');
    for (const data of [{ error: 'Progress data was unavailable when the site was built.' }, { ...valid, items: [{}] }, null, '{bad JSON', valid]) {
      await writeFile(path.join(root, 'dist/progress-feed.json'), typeof data === 'string' ? data : JSON.stringify(data));
      const result = spawnSync(process.execPath, [script], { cwd: root, encoding: 'utf8' });
      assert.ifError(result.error);
      assert.equal(result.status, data === valid ? 0 : 1, result.stderr);
      if (data !== valid) assert.match(result.stderr, /Progress feed is not publishable/);
    }
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
