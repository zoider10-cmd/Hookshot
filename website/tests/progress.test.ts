import test from 'node:test';
import assert from 'node:assert/strict';
import { ROOT, REPOSITORY, normalizeItem, validateCuration, validateFeed, filterItems } from '../src/lib/progress.ts';
import { exactVersion, reportEvidence, currentVersionWatch } from '../src/lib/progress-watch.ts';
import { progressOverview } from '../src/lib/progress-overview.ts';
import { collectFeed } from '../src/lib/progress-feed.ts';

const time = '2026-11-11T12:00:00Z';
const raw = (n = 1, extra = {}) => ({ number: n, title: 'Controller stops responding', state: 'open', updated_at: time, labels: [], ...extra });
const release = { id: 100, name: 'Version 2.1.0', tag_name: 'v2.1.0', updated_at: time, published_at: time, draft: false, prerelease: false };
const body = (version, area = 'Low fps or stutter') => `### Hookshot version\n\n${version}\n\n### What kind of problem\n\n${area}\n\n### Description\n\nprivate log excerpts are not published`;
function feed(items = [normalizeItem(raw(), 'issue')]) {
  return { version: 1, repository: REPOSITORY, generatedAt: time, collectionStartedAt: time, closedSince: '2026-08-13T12:00:00Z', warning: '',
    stableRelease: { tag: 'v2.1.0', url: `${ROOT}/releases/tag/v2.1.0`, publishedAt: time }, items };
}
const response = (data, status = 200, headers = {}) => new Response(JSON.stringify(data), { status, headers });
const repository = { id: 1446962520, full_name: REPOSITORY, private: false };

test('statuses distinguish proposals, accepted work, releases and closure reasons', () => {
  assert.equal(normalizeItem(raw(1, { assignees: [{}] }), 'issue').status, 'reported');
  assert.equal(normalizeItem(raw(1, { labels: [{ name: 'enhancement' }] }), 'issue').status, 'suggested');
  assert.equal(normalizeItem(raw(1, { labels: [{ name: 'in progress' }] }), 'issue').status, 'working');
  assert.equal(normalizeItem(raw(), 'pull').status, 'proposed');
  assert.equal(normalizeItem(raw(1, { draft: true }), 'pull').status, 'draft');
  assert.equal(normalizeItem(raw(1, { title: 'WIP: renderer change' }), 'pull').status, 'draft');
  assert.equal(normalizeItem(raw(1), 'pull').url, `${ROOT}/pulls/1`);
  assert.equal(normalizeItem(raw(1, { state: 'closed', merged_at: time }), 'pull').status, 'merged');
  assert.equal(normalizeItem(raw(1, { state: 'closed' }), 'pull').status, 'withdrawn');
  assert.equal(normalizeItem(raw(1, { state: 'closed', state_reason: 'completed' }), 'issue').status, 'closed');
  assert.equal(normalizeItem(raw(1, { state: 'closed', state_reason: 'not_planned' }), 'issue').status, 'declined');
  assert.equal(normalizeItem(raw(1, { state: 'closed', labels: ['duplicate'] }), 'issue').status, 'duplicate');
  assert.equal(normalizeItem(release, 'release').status, 'released');
  assert.equal(normalizeItem({ ...release, prerelease: true }, 'release').status, 'preview');
  assert.equal(normalizeItem({ ...release, draft: true }, 'release'), null);
});

test('curation expires when source changes and rejects unsafe evidence', () => {
  const curation = { 'issue:1': { title: 'Controller help', summary: 'A reviewed description.', reviewedAt: time, sourceUpdatedAt: time, sources: [`${ROOT}/issues/1`], impact: 'Cannot start', platforms: ['Linux'], workaround: 'Reviewed advice.' } };
  validateCuration(curation);
  const curated = normalizeItem(raw(), 'issue', curation);
  assert.equal(curated.title, 'Controller help');
  assert.equal(curated.workaround, 'Reviewed advice.');
  assert.equal(curated.impact, 'Cannot start');
  const expired = normalizeItem(raw(1, { updated_at: '2026-11-12T00:00:00Z' }), 'issue', curation);
  assert.equal(expired.title, raw().title);
  assert.equal(expired.workaround, '');
  assert.equal(expired.impact, null);
  curation['issue:1'].sources = ['javascript:alert(1)'];
  assert.throws(() => validateCuration(curation));
});

test('version matching uses only exact report fields, not text guesses', () => {
  assert.equal(exactVersion('`v2.1.0`'), '2.1.0');
  for (const text of ['latest', '2.1.0 or 2.0.9', 'hookshot abc123', '02.1.0', 'v2.1.0 Windows', '']) assert.equal(exactVersion(text), null);
  assert.equal(reportEvidence(body('v2.1.0')).version, '2.1.0');
  assert.equal(reportEvidence(body('v2.1.0', 'Sound')).reportedArea, 'Audio');
  assert.equal(reportEvidence(body('v2.1.0', 'Controls')).reportedArea, 'Controls');
  assert.equal(reportEvidence(body('v2.1.0-rc.1')).version, '2.1.0-rc.1');
  assert.equal(reportEvidence('Mentioned v2.1.0 in a comment').version, null);
  assert.equal(reportEvidence(body('latest')).version, null);
  assert.equal(reportEvidence(body('v2.1.0') + '\n### Hookshot version\n\nv2.0.9').version, null);
  assert.equal(reportEvidence(body('v2.1.0') + '\n### Builder version\n\nv2.0.9').version, null);
  assert.equal(reportEvidence('### Builder version\n\nv2.1.0').reportedArea, 'Setup');
  assert.equal(reportEvidence('### Version\n\nv2.1.0').versionSource, 'Installation version field');
  assert.equal(reportEvidence('### Version\n\nLauncher v1.0.0, game v2.1.0').version, null);
});

test('current watch excludes older, preview, closed and duplicate reports and all PRs', () => {
  const items = [
    normalizeItem(raw(1, { body: body('v2.1.0') }), 'issue'),
    normalizeItem(raw(2, { body: body('v2.0.9') }), 'issue'),
    normalizeItem(raw(3, { body: body('v2.1.0-rc.1') }), 'issue'),
    normalizeItem(raw(4, { body: body('latest') }), 'issue'),
    normalizeItem(raw(5, { body: body('v2.1.0'), state: 'closed' }), 'issue'),
    normalizeItem(raw(6, { body: body('v2.1.0'), labels: ['duplicate'] }), 'issue'),
    normalizeItem(raw(7, { body: body('v2.1.0') }), 'pull'),
    normalizeItem(raw(8, { body: body('v2.1.0'), labels: ['enhancement'] }), 'issue'),
  ];
  const watch = currentVersionWatch(feed(items));
  assert.deepEqual(watch.current.map(i => i.number), [1]);
  assert.equal(watch.other, 2); assert.equal(watch.unknown, 1);
  assert.equal(watch.groups[0].area, 'Performance');
  assert.equal(watch.important.length, 0);
  assert.equal(currentVersionWatch({ ...feed(items), stableRelease: null }).current.length, 0);
});

test('search combines query terms and every filter, including source numbers and exact versions', () => {
  const items = [normalizeItem(raw(123, { body: body('v2.1.0'), labels: ['os:linux', 'documentation'] }), 'issue'), normalizeItem(release, 'release')];
  assert.equal(filterItems(items, { query: 'controller responding', platform: 'Linux', area: 'Documentation', version: '2.1.0' }).length, 1);
  assert.equal(filterItems(items, { query: '#123' })[0].number, 123);
  assert.equal(filterItems(items, { view: 'releases' }).length, 1);
  assert.equal(filterItems(items, { query: 'controller', status: 'released' }).length, 0);
});

test('feed validation rejects unsafe URLs, duplicate IDs and malformed records', () => {
  validateFeed(feed());
  for (const url of ['javascript:alert(1)', 'https://git.magicbean.dev.evil/MagicBeanDev/Hookshot/issues/1', `${ROOT}/issues/2`, 'https://git.magicbean.dev/MagicBeanDev/Hookshot/pull/1']) {
    const data = feed(); data.items[0].url = url;
    assert.throws(() => validateFeed(data));
  }
  assert.throws(() => validateFeed(feed([normalizeItem(raw(), 'issue'), normalizeItem(raw(), 'issue')])));
  assert.throws(() => validateFeed({ ...feed(), items: [{}] }));
});

test('collector paginates open items, stops old closed history and keeps PRs separate', async () => {
  const calls = [];
  const fetcher = async (url, options) => {
    assert.equal(options.redirect, 'error');
    assert.equal(options.headers.Authorization, 'Bearer test-only');
    const u = new URL(url); calls.push(u);
    if (u.pathname === `/api/v1/repos/${REPOSITORY}`) return response(repository);
    if (u.pathname.endsWith('/releases/latest')) return response(release);
    if (u.pathname.endsWith('/releases')) return response([{ ...release, id: 101, draft: true }, release]);
    const page = Number(u.searchParams.get('page') || 1);
    if (u.searchParams.get('state') === 'closed') return response([raw(999, { state: 'closed', updated_at: '2020-01-01T00:00:00Z' })]);
    if (u.pathname.endsWith('/pulls')) return response([raw(500, { merged_at: null })]);
    if (page === 1) return response(Array.from({ length: 100 }, (_, i) => raw(i + 1, { body: body('v2.1.0'), ...(i === 0 ? { pull_request: {} } : {}) })), 200,
      { link: '<https://git.magicbean.dev/api/v1/repos/MagicBeanDev/Hookshot/issues?state=open&page=2>; rel="next"' });
    return response([raw(123, { html_url: 'https://evil.invalid', user: { login: 'not-published' }, body: 'not-published' })]);
  };
  const data = await collectFeed({ fetcher, token: 'test-only', now: Date.parse(time) });
  assert.equal(data.items.length, 102);
  assert(!data.items.some(i => i.id === 'issue:1' || i.number === 999 || i.id === 'release:101'));
  assert.equal(data.stableRelease.tag, 'v2.1.0');
  assert(!JSON.stringify(data).includes('not-published'));
  assert(!JSON.stringify(data).includes('test-only'));
  assert(calls.some(u => u.searchParams.get('page') === '2'));
});

test('failed or truncated collection never returns a partial feed', async () => {
  await assert.rejects(collectFeed({ wait: async () => {}, fetcher: async url => url.endsWith('/latest') ? response(release) : response({}, 503) }));
  await assert.rejects(collectFeed({ maxPages: 1, now: Date.parse(time), fetcher: async url => url.endsWith(REPOSITORY) ? response(repository) : url.endsWith('/latest') ? response(release) : response(Array.from({ length: 100 }, (_, i) => raw(i + 1)), 200,
    { link: '<https://git.magicbean.dev/api/v1/repos/MagicBeanDev/Hookshot/issues?state=closed&after=cursor>; rel="next"' }) }), /pagination limit/);
});

test('pagination never forwards the token to another host or endpoint', async () => {
  let calls = 0;
  await assert.rejects(collectFeed({ token: 'test-only', now: Date.parse(time), fetcher: async url => {
    calls++;
    if (url.endsWith(REPOSITORY)) return response(repository);
    if (url.endsWith('/latest')) return response(release);
    return response([raw()], 200, { link: '<https://evil.invalid/steal>; rel="next"' });
  } }), /Unsafe Forgejo/);
  assert.equal(calls, 3);
});

test('overview counts actual merge and publish dates, not recent comments', () => {
  const items = [
    normalizeItem(raw(1, { state: 'closed', merged_at: '2026-01-01T00:00:00Z' }), 'pull'),
    normalizeItem(raw(2, { state: 'closed', merged_at: time }), 'pull'),
    normalizeItem(raw(3), 'pull'), normalizeItem(raw(4, { draft: true }), 'pull'),
    normalizeItem(release, 'release'), normalizeItem({ ...release, id: 101, prerelease: true }, 'release'),
  ];
  assert.deepEqual(progressOverview(feed(items)).map(i => i.count), [0, 1, 1, 1]);
});

test('a private repository cannot be exposed through the public feed', async () => {
  await assert.rejects(collectFeed({ fetcher: async () => response({ ...repository, private: true }) }), /public repository/);
});

test('Forgejo collection uses its query contract and supports no published releases', async () => {
  const data = await collectFeed({ fetcher: async (url, options) => {
    assert.equal(options.headers.Accept, 'application/json');
    const u = new URL(url);
    if (u.pathname === `/api/v1/repos/${REPOSITORY}`) return response(repository);
    if (u.pathname.endsWith('/latest')) return response({}, 404);
    assert.equal(u.searchParams.get('limit'), '100');
    assert.equal(u.searchParams.has('per_page'), false);
    if (!u.pathname.endsWith('/releases')) assert.equal(u.searchParams.get('sort'), 'recentupdate');
    if (u.pathname.endsWith('/issues')) assert.equal(u.searchParams.get('type'), 'issues');
    return response([]);
  } });
  assert.equal(data.stableRelease, null);
  assert.deepEqual(data.items, []);
});

test('pagination rejects another endpoint even on the trusted Forgejo host', async () => {
  await assert.rejects(collectFeed({ fetcher: async url => {
    if (url.endsWith(REPOSITORY)) return response(repository);
    if (url.endsWith('/latest')) return response({}, 404);
    return response([raw()], 200, { link: '<https://git.magicbean.dev/api/v1/user>; rel="next"' });
  }, now: Date.parse(time) }), /Unsafe Forgejo/);
});
