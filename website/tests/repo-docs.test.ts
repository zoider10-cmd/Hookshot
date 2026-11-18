import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { sectionsAt, formatInstallHub, launcherChannels } from '../src/repo-docs/format-install.ts';
import { launcherHref } from '../src/lib/launcher-channel.ts';
import { formatCommonIssues, headingId, legacyAnchors } from '../src/repo-docs/format-common-issues.ts';
import { revealManualTarget } from '../src/lib/manual-navigation.ts';

test('sections do not split headings inside backtick or tilde code fences', () => {
  const source = 'Introduction\n## First\n```sh\n## A shell comment\n```\n~~~text\n## Another example\n~~~\n## Second\nDone\n';
  const sections = sectionsAt(source, 2);
  assert.deepEqual(sections.map(section => section.title), ['', 'First', 'Second']);
  assert.equal(sections.map(section => section.heading + section.body).join(''), source);
});

test('installation hub retains source sections and links', () => {
  const source = 'Welcome\n\n## Windows\n[Instructions](../README.md#on-windows)\n\n## Linux\nChoose your platform.\n';
  const formatted = formatInstallHub(source);
  for (const line of source.split('\n').filter(Boolean)) assert(formatted.includes(line));
  assert.equal((formatted.match(/class="install-hub-card"/g) || []).length, 2);
});

test('the launcher download buttons get a channel picker, hidden until a script runs it', async () => {
  const source = await readFile(new URL('../../docs/getting-started.md', import.meta.url), 'utf8');
  const page = source.replace(/https:\/\/hookshot\.magicbean\.dev\//g, '/');
  const formatted = formatInstallHub(page);
  assert.equal((formatted.match(/data-launcher-channel /g) || []).length, 1);
  assert.match(formatted, /<div class="launcher-channel" role="radiogroup" aria-labelledby="launcher-channel-label" data-launcher-channel hidden>[\s\S]*<\/p>\n<\/div>\n<p class="launcher-version">[\s\S]*<\/p>\n<div class="download-buttons">/);
  assert.match(formatted, /data-launcher-version role="status"/);
  assert.match(formatted, /This is the launcher's own version\. The game it builds is numbered as a Hookshot version/);
  assert(!formatted.includes('See all versions'));
  for (const c of launcherChannels) assert(formatted.includes(`value="${c.value}"`), `Missing channel: ${c.name}`);
  assert.equal((formatted.match(/ checked>/g) || []).length, 0);
  assert(formatted.includes('The recommended channel is chosen when you download.'));
  assert(formatted.includes('value="stable" data-note="For playing."> Stable <small></small>'));
  // (no blank line inside, so Markdown keeps it one HTML block)
  assert(!/data-launcher-channel[\s\S]*\n\n[\s\S]*class="download-buttons"/.test(formatted));
  assert(!formatInstallHub('## Elsewhere\n- [Other](/download/other)\n').includes('launcher-channel'));
});

test('a channel moves the launcher links, and only them', () => {
  assert.equal(launcherHref('/download/launcher/windows', 'nightly'), '/download/launcher/nightly/windows');
  assert.equal(launcherHref('/download/launcher/nightly/windows-portable', 'rc'), '/download/launcher/rc/windows-portable');
  assert.equal(launcherHref('/download/launcher/rc/linux', ''), '/download/launcher/linux');
  assert.equal(launcherHref('/download', 'rc'), '/download');
  assert.equal(launcherHref('/download/launcher/nightly', 'rc'), '/download/launcher/nightly');
});

test('symptom cards keep every line of the help page, its anchors and the old topic anchors', async () => {
  const source = await readFile(new URL('../../docs/common-issues.md', import.meta.url), 'utf8');
  const page = source.replace(/^# .+\n/m, '');
  const formatted = formatCommonIssues(page);
  const groups = sectionsAt(page, 2).slice(1, -1);
  const problems = groups.flatMap(group => sectionsAt(group.body, 3).slice(1));
  assert.equal(groups.length, 6);
  assert.equal((formatted.match(/class="issue-card"/g) || []).length, problems.length);
  assert.equal((formatted.match(/class="issue-search"/g) || []).length, problems.length);
  // Every group and problem keeps the anchor Forgejo gives its heading, and the finder links to each one.
  for (const section of [...groups, ...problems]) {
    const id = headingId(section.title);
    assert.equal((formatted.match(new RegExp(`id="${id}"`, 'g')) || []).length, 1, `Missing anchor: ${id}`);
    assert(formatted.includes(`href="#${id}"`), `Not in the finder: ${id}`);
  }
  assert(formatted.includes('id="still-stuck"'));
  // Links to the page's topics before it was grouped still land on the problem or group that replaced each one.
  for (const [legacy, target] of legacyAnchors) {
    assert(formatted.includes(`id="${legacy}"`), `Lost old anchor: ${legacy}`);
    assert(formatted.includes(`id="${target}"`), `Old anchor ${legacy} points nowhere: ${target}`);
  }
  // Every line of the problems and of "Still stuck?" is on the page.
  for (const line of sectionsAt(page, 2).slice(1).flatMap(section => section.body.split('\n'))) {
    if (line.trim() && !/^#{3} /.test(line)) assert(formatted.includes(line), `Lost content: ${line}`);
  }
  assert.throws(() => formatCommonIssues(page.replace('## Downloads and antivirus', '## Unknown group')), /structure changed/);
  assert.throws(() => formatCommonIssues(page.replace('- [Starting the game](#starting-the-game)\n', '')), /group list changed/);
  assert.throws(() => formatCommonIssues(page.replace('[Search language reports]', 'Search language reports')),
    /problem structure changed: The game is in the wrong language/);
  assert.throws(() => formatCommonIssues(page.replace(/## Still stuck\?[\s\S]*/, '## Still stuck?\n\nAsk on Discord.\n')), /Still stuck/);
});

test('a legacy symptom link opens its native card, including nested help targets', () => {
  const outer = { tagName: 'DETAILS', open: false, parentElement: null };
  const inner = { tagName: 'DETAILS', open: false, parentElement: outer };
  revealManualTarget({ parentElement: inner, closest: () => null });
  assert.equal(outer.open, true);
  assert.equal(inner.open, true);
});
