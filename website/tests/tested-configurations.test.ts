import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readFile, rm, unlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { createMarkdownProcessor } from '@astrojs/markdown-remark';
import { contentPages, pageForSource } from '../src/content-pages.ts';
import { editUrl, sourceUrl } from '../src/site.ts';
import { isSourceFile, renderPage, repoRoot, rewriteRepoLinks, sourceFiles, testedFragmentsPath } from '../src/repo-docs/pages.ts';
import { assembleTestedConfigurations, fragmentsMarker, publicTestedRunsMarker, readTestedConfigurations,
  remarkTestedConfigurations, runHeader, runSeparator } from '../src/repo-docs/tested-configurations.ts';

const row = (build = 'new', result = 'observed', date = '2026-11-13') =>
  `| ${date} | ${build} | Linux | GPU / driver | CPU / RAM | settings | scene | ${result} |`;
const fragment = (name = '2026-11-13-topic-tester-run1.md', value = row()) =>
  ({ name, text: `${runHeader}\n${runSeparator}\n${value}\n` });
const prefix = '# Tested configurations\n\nKeep the source instructions and links.\n\n';
const oldRows = [row('old'), row('as above'), row('old')];
const limits = '## Limits of the original RTX 4070 Ti runs\n\n- Original limits → unchanged.\n';
const frozen = `\n\n## Earlier runs (frozen)\n\n${runHeader}\n${runSeparator}\n${oldRows.join('\n')}\n\n${limits}`;
const document = prefix + fragmentsMarker + frozen;

test('new filenames sort descending while old rows, duplicates, instructions and limits stay verbatim', () => {
  const fragments = [fragment('2026-11-13-a-tester-run1.md', row('a')),
    fragment('2026-11-12-older-tester-run1.md', row('older', 'observed', '2026-11-12')),
    fragment('2026-11-13-z-tester-run1.md', row('z'))];
  const expected = [runHeader, runSeparator, row('z'), row('a'), row('older', 'observed', '2026-11-12')].join('\n');
  assert.equal(assembleTestedConfigurations(document, fragments), prefix + '## New runs\n\n' + expected + frozen);
  assert.deepEqual(fragments.map(item => item.name), ['2026-11-13-a-tester-run1.md',
    '2026-11-12-older-tester-run1.md', '2026-11-13-z-tester-run1.md']);
});

test('no fragments has a clear message and retains the frozen catalogue and its only Limits section', () => {
  const combined = assembleTestedConfigurations(document, []);
  assert.equal(combined, prefix + '## New runs\n\nNo new run fragments yet.' + frozen);
  assert.equal(combined.split(limits).length - 1, 1);
});

test('a fenced format example before the marker is not frozen evidence', () => {
  const example = fragment();
  for (const fence of ['```', '~~~']) {
    const source = prefix + fence + 'md\n' + example.text + fence + '\n\n' + fragmentsMarker + frozen;
    assert(assembleTestedConfigurations(source, [example]).endsWith(example.text.trimEnd().split('\n')[2] + frozen));
  }
});

test('new copies of a frozen or new row are refused, ignoring only cell whitespace', () => {
  assert.throws(() => assembleTestedConfigurations(document, [fragment(undefined, row('old'))]), /duplicate row/);
  assert.throws(() => assembleTestedConfigurations(document, [fragment(),
    fragment('2026-11-13-topic-tester-run2.md', row().replace('new', '  new\t ').replaceAll(' | ', '  |  '))]), /duplicate row/);
  const spaced = row('  distinct\t build  ', '→ result  ');
  assert(assembleTestedConfigurations(document, [fragment(undefined, spaced)]).includes(spaced));
});

test('fragments require exactly the standard header, separator and one LF row', () => {
  const good = fragment();
  for (const text of ['', good.text.replace('Build', 'Other'), good.text.replace('|---|', '|--|'),
    good.text + row('extra') + '\n', good.text + '\n', '\n' + good.text,
    good.text.replaceAll('\n', '\r\n'), good.text.replace(row(), '<<<<<<< HEAD'), '\uFEFF' + good.text]) {
    assert.throws(() => assembleTestedConfigurations(document, [{ ...good, text }]), /standard header|eight non-empty cells/);
  }
  assert.equal(assembleTestedConfigurations(document, [{ ...good, text: good.text.slice(0, -1) }]),
    assembleTestedConfigurations(document, [good]));
});

test('missing, empty or extra cells are refused', () => {
  for (const value of [row().slice(1), row().slice(0, -1), row().replace('CPU / RAM', ''),
    row().replace('GPU / driver', 'GPU | driver'), row() + ' trailing', row().replace(/ \|$/, String.raw`\|`)]) {
    assert.throws(() => assembleTestedConfigurations(document, [fragment(undefined, value)]), /eight non-empty cells/);
  }
});

test('odd escaped pipes and even backslashes before delimiters keep their original bytes', () => {
  const escaped = row('escaped', String.raw`one \| and three \\\|, including \| in code`)
    .replace('GPU / driver |', String.raw`GPU / driver\\|`)
    .replace(/ \|$/, String.raw`\\|`);
  const inlineCode = row('code', '`left\\|right` and →');
  for (const value of [escaped, inlineCode]) {
    assert(assembleTestedConfigurations(document, [fragment(undefined, value)]).includes(value));
  }
});

test('dates are real ISO calendar dates, optionally UTC, and match the filename', () => {
  for (const date of ['today', '2026-2-13', '2026-02-30', '2026-11-31', '0000-01-01',
    '1900-02-29', '2026-11-13 utc', '2026-11-13 UTC UTC']) {
    assert.throws(() => assembleTestedConfigurations(document, [fragment(undefined, row('new', 'observed', date))]), /date/);
  }
  assert.throws(() => assembleTestedConfigurations(document, [fragment('2026-11-12-topic-tester-run1.md')]), /filename.*date/);
  for (const date of ['2026-11-13 UTC', '2000-02-29']) {
    const value = row('dated', 'observed', date);
    assert(assembleTestedConfigurations(document, [fragment(`${date.slice(0, 10)}-topic-tester-run1.md`, value)]).includes(value));
  }
});

test('filenames require at least topic, tester and run parts after the date', () => {
  for (const name of ['missing-date.md', '2026-11-13-x.md', '2026-11-13-topic-tester.md',
    '2026-11-13-Topic-tester-run1.md', '2026-11-13-topic_tester-run1.md',
    '2026-11-13-topic-tester-run1-.md', 'nested/2026-11-13-topic-tester-run1.md']) {
    assert.throws(() => assembleTestedConfigurations(document, [fragment(name)]), /filename/);
  }
  assert(assembleTestedConfigurations(document, [fragment('2026-11-13-long-topic-tester-run-1.md')]).includes(row()));
});

test('relative references anywhere in new cells are refused, not in the frozen rows', () => {
  for (const value of ['as above', 'As\tAbove', 'same host, changed renderer', 'the same host again', 'DITTO', 'result: ditto']) {
    assert.throws(() => assembleTestedConfigurations(document, [fragment(undefined, row('new', value))]), /stand alone/);
  }
  assert(assembleTestedConfigurations(document, []).includes(row('as above')));
});

test('missing or malformed frozen boundaries and tables stop assembly', () => {
  for (const source of [document.replace(fragmentsMarker, ''), document + '\n' + fragmentsMarker + '\n',
    document.replace(fragmentsMarker, 'inline ' + fragmentsMarker), document.replace('Earlier runs (frozen)', 'Archive'),
    document.replace(runHeader, runHeader.replace('Build', 'Other')), document.replace(runSeparator, '|--|'),
    document.replace(limits, ''), document + limits, document.replace(oldRows.join('\n'), ''),
    document.replace(oldRows.join('\n'), oldRows.join('\n\n')), document.replace('\n\n' + limits, '\n' + limits),
    document.replace(row('as above'), row('as above').replace('Linux', ''))]) {
    assert.throws(() => assembleTestedConfigurations(source, []), /tested configurations|eight non-empty cells/);
  }
});

test('local discovery excludes README and nested files, and sees creation, edit and deletion', async t => {
  const directory = await mkdtemp(path.join(tmpdir(), 'hookshot-tested-runs-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  await writeFile(path.join(directory, 'README.md'), 'Fragment instructions, not data.\n');
  await writeFile(path.join(directory, 'notes.txt'), 'Not a fragment.\n');
  await mkdir(path.join(directory, 'nested'));
  await writeFile(path.join(directory, 'nested', 'bad.md'), 'Not a direct fragment.\n');
  const empty = await readTestedConfigurations(document, directory);
  assert.match(empty, /No new run fragments yet\./);
  const first = fragment();
  const file = path.join(directory, first.name);
  await writeFile(file, first.text);
  assert.equal(await readTestedConfigurations(document, directory), assembleTestedConfigurations(document, [first]));
  const edited = fragment(first.name, row('edited'));
  await writeFile(file, edited.text);
  assert.equal(await readTestedConfigurations(document, directory), assembleTestedConfigurations(document, [edited]));
  await unlink(file);
  assert.equal(await readTestedConfigurations(document, directory), empty);
});

test('fragment links resolve at their own paths while the frozen document keeps its link base', async t => {
  const directory = await mkdtemp(path.join(tmpdir(), 'hookshot-tested-links-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const links = '[trace](./trace.md) [readme](../../README.md#project-status) ' +
    '[install](../getting-started.md) <a href="./trace.md">trace</a>';
  const entry = fragment(undefined, row('linked', links));
  await writeFile(path.join(directory, entry.name), entry.text);
  const source = document.replace('Keep the source instructions and links.', '[instructions](./trace.md)')
    .replace('Original limits → unchanged.', '[old trace](./trace.md)');
  const assembled = await readTestedConfigurations(source, directory, rewriteRepoLinks);
  const page = rewriteRepoLinks(assembled, 'docs/tested-configurations.md');
  assert(page.includes(`[trace](${sourceUrl('docs/tested/trace.md')})`));
  assert(page.includes(`[readme](${sourceUrl('README.md')}#project-status)`));
  assert(page.includes('[install](/install/)'));
  assert(page.includes(`<a href="${sourceUrl('docs/tested/trace.md')}">trace</a>`));
  assert(page.includes(`[instructions](${sourceUrl('docs/trace.md')})`));
  assert(page.includes(`[old trace](${sourceUrl('docs/trace.md')})`));
  assert(assembleTestedConfigurations(source, [entry]).includes(links));
  assert.equal(await readFile(path.join(directory, entry.name), 'utf8'), entry.text);
});

test('fragment link presentation cannot hide a duplicate of an original frozen row', () => {
  const value = row('linked', '[trace](./trace.md)');
  const source = document.replace(row('as above'), value);
  assert.throws(() => assembleTestedConfigurations(source, [fragment(undefined, value)], rewriteRepoLinks), /duplicate row/);
});

test('only the marked page neutralizes prose, retaining URLs, inline code, fences and heading metadata', async () => {
  const processor = await createMarkdownProcessor({ remarkPlugins: [remarkTestedConfigurations] });
  const source = '## Hyrule\n\n[Zelda](https://example.test/Hyrule/OoT) and `Hyrule_OoT`\n\n' +
    '<https://example.test/Hyrule/OoT>\n\n```text\nHyrule and OoT\n```\n';
  const marked = await processor.render(publicTestedRunsMarker + '\n\n' + source);
  assert.match(marked.code, /href="https:\/\/example\.test\/Hyrule\/OoT"[^>]*>the game<\/a>/);
  assert.match(marked.code, /<code>Hyrule_OoT<\/code>/);
  assert.match(marked.code, />https:\/\/example\.test\/Hyrule\/OoT<\/a>/);
  assert.match(marked.code, /Hyrule and OoT/);
  assert(!marked.code.includes(publicTestedRunsMarker));
  assert.deepEqual(marked.metadata.headings.map(heading => heading.text), ['the game world']);
  assert.match(marked.code, /id="the-game-world"/);
  const unmarked = await processor.render(source);
  assert.match(unmarked.code, />Zelda<\/a>/);
  assert.deepEqual(unmarked.metadata.headings.map(heading => heading.text), ['Hyrule']);
});

test('assembled tables render once as tables and keep both run headings and the Limits heading', async () => {
  const processor = await createMarkdownProcessor({ remarkPlugins: [remarkTestedConfigurations] });
  const combined = assembleTestedConfigurations(document, [fragment(undefined, row('new', 'Hyrule → Kokiri Forest'))]);
  const rendered = await processor.render(publicTestedRunsMarker + '\n\n' + combined);
  assert.equal((rendered.code.match(/<table>/g) || []).length, 2);
  assert.equal((rendered.code.match(/<tbody>/g) || []).length, 2);
  assert.match(rendered.code, /the game world → the starting forest/);
  assert.deepEqual(rendered.metadata.headings.filter(heading => heading.depth === 2).map(heading => heading.text),
    ['New runs', 'Earlier runs (frozen)', 'Limits of the original RTX 4070 Ti runs']);
});

test('the real catalogue maps to the repository loader page with no generated source', async () => {
  assert.equal(contentPages['tested-configurations'], 'docs/tested-configurations.md');
  assert.equal(pageForSource.get('docs/tested-configurations.md'), 'tested-configurations');
  const source = await readFile(path.join(repoRoot, 'docs/tested-configurations.md'), 'utf8');
  const unchanged = source.split(fragmentsMarker)[1];
  assert(unchanged, 'the source catalogue has its assembly marker');
  assert(assembleTestedConfigurations(source, []).endsWith(unchanged));
  const page = await renderPage('tested-configurations');
  assert.equal(page.title, 'Tested configurations');
  assert.equal(page.editUrl, editUrl('docs/tested-configurations.md'));
  assert(page.markdown.startsWith(publicTestedRunsMarker + '\n\n'));
  assert.match(page.markdown, /^## New runs$/m);
  assert.match(page.markdown, /^## Earlier runs \(frozen\)$/m);
  assert(!page.markdown.includes(fragmentsMarker));
});

test('dev watches direct fragment additions, edits and removals as well as the original source files', async () => {
  assert(sourceFiles.includes(path.join(repoRoot, 'docs/tested-configurations.md')));
  for (const name of ['2026-11-13-topic-tester-run1.md', 'invalid-name.md']) {
    assert(isSourceFile(path.join(testedFragmentsPath, name)));
  }
  assert(!isSourceFile(path.join(testedFragmentsPath, 'README.md')));
  assert(!isSourceFile(path.join(testedFragmentsPath, 'notes.txt')));
  assert(!isSourceFile(path.join(testedFragmentsPath, 'nested', 'run.md')));
  const loader = await readFile(new URL('../src/repo-docs/loader.ts', import.meta.url), 'utf8');
  assert.match(loader, /context\.watcher\.add\(\[\.\.\.sourceFiles, testedFragmentsPath\]\)/);
  assert.match(loader, /for \(const event of \['add', 'change', 'unlink'\]/);
  assert.match(loader, /context\.watcher\.on\(event,[\s\S]*isSourceFile\(file\)/);
  assert.equal((loader.match(/context\.renderMarkdown\(markdown\)/g) || []).length, 1);
  const config = await readFile(new URL('../astro.config.ts', import.meta.url), 'utf8');
  assert.match(config, /import \{ unified \} from '@astrojs\/markdown-remark';/);
  assert.match(config, /markdown: \{ processor: unified\(\{ remarkPlugins: \[remarkTestedConfigurations\], rehypePlugins: \[rehypeKeyboardScroll\] \}\) \}/);
});
