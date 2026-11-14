import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { REPOSITORY, normalizeItem, validateCuration, validateFeed } from './progress.ts';
import { publicProgressItem } from './public-copy.ts';
import { progressRequest } from './progress-request.ts';

// Collects the public progress feed from Forgejo. The site's build calls buildFeed() once, and publishes the result
// as /progress-feed.json and on the front page: the data is as fresh as the last build.
const API = `https://git.magicbean.dev/api/v1/repos/${REPOSITORY}`;
// Astro bundles this module into dist/ when it builds, so the file is found from website/, where the build runs.
const curationPath = path.resolve('progress-curation.json');

export async function collectFeed({ fetcher = fetch, token = '', curation = {}, now = Date.now(), maxPages = 100, wait } = {}) {
  validateCuration(curation);
  const closedSince = new Date(now - 90 * 86400000).toISOString();
  const headers = { Accept: 'application/json', 'User-Agent': 'Hookshot-docs-progress' };
  if (token) headers.Authorization = `Bearer ${token}`;
  const request = (url, allowNotFound = false) => progressRequest(url, { fetcher, headers, allowNotFound, wait });
  const { data: repository } = await request(API);
  if (repository.private !== false || !Number.isSafeInteger(repository.id) || repository.id <= 0 ||
      repository.full_name?.toLowerCase() !== REPOSITORY.toLowerCase()) throw new Error('Progress source must be the expected public repository.');
  async function page(endpoint, query, next) {
    const url = new URL(next || `${API}/${endpoint}`);
    if (!next) url.search = new URLSearchParams(query).toString();
    // Only follow Forgejo's same-endpoint pagination links, never forward credentials elsewhere.
    if (url.origin !== 'https://git.magicbean.dev' || url.pathname !== `/api/v1/repos/${REPOSITORY}/${endpoint}` || url.username || url.password) {
      throw new Error('Unsafe Forgejo pagination link.');
    }
    const { data, headers: responseHeaders } = await request(url.href);
    if (!Array.isArray(data)) throw new Error('Unexpected Forgejo response.');
    const link = responseHeaders.get('link') || '';
    const nextPage = link.split(',').map(part => part.match(/<([^>]+)>;\s*rel="next"/)).find(Boolean)?.[1] || null;
    return { data, next: nextPage };
  }
  const { data: latest } = await request(`${API}/releases/latest`, true);
  if (latest && (latest.draft !== false || latest.prerelease !== false)) throw new Error('Invalid latest stable release.');
  const latestItem = latest ? normalizeItem(latest, 'release', curation) : null;
  if (latest && !latestItem) throw new Error('Invalid latest stable release.');
  async function list(endpoint, state) {
    const result = [];
    let next;
    const visited = new Set();
    for (let n = 1; n <= maxPages; n++) {
      const batch = await page(endpoint, { state, sort: 'recentupdate', limit: '100', page: '1', ...(endpoint === 'issues' ? { type: 'issues' } : {}) }, next);
      const { data } = batch;
      if (data.some(i => !Number.isFinite(Date.parse(i.updated_at)))) throw new Error('Missing Forgejo update date.');
      result.push(...data.filter(i => state === 'open' || Date.parse(i.updated_at) >= Date.parse(closedSince)));
      if (!batch.next || !data.length || (state === 'closed' && Date.parse(data.at(-1).updated_at) < Date.parse(closedSince))) return result;
      if (visited.has(batch.next)) throw new Error('Repeated Forgejo pagination cursor.');
      visited.add(batch.next);
      next = batch.next;
    }
    throw new Error('Progress pagination limit reached; previous snapshot retained.');
  }
  // Sequential pagination limits burst traffic. Do not publish any part until every list succeeds.
  const items = new Map();
  if (latestItem) items.set(latestItem.id, latestItem);
  for (const [endpoint, kind] of [['issues', 'issue'], ['pulls', 'pull']]) {
    for (const state of ['closed', 'open']) {
      for (const raw of await list(endpoint, state)) {
        if (kind === 'issue' && raw.pull_request) continue;
        const item = normalizeItem(raw, kind, curation);
        items.set(item.id, item);
      }
    }
  }
  // Token access must not leak draft releases. Walk pages until 20 published releases are found.
  let releases = 0;
  let nextRelease;
  for (let n = 1; n <= maxPages; n++) {
    const batch = await page('releases', { limit: '100', page: '1' }, nextRelease);
    const { data } = batch;
    for (const raw of data) {
      if (raw.draft !== false) continue;
      const item = normalizeItem(raw, 'release', curation);
      if (item) { items.set(item.id, item); releases++; }
      if (releases === 20) break;
    }
    if (releases === 20 || !batch.next) break;
    nextRelease = batch.next;
    if (n === maxPages) throw new Error('Release pagination limit reached.');
  }
  return validateFeed({ version: 1, repository: REPOSITORY, collectionStartedAt: new Date(now).toISOString(),
    generatedAt: new Date().toISOString(), closedSince, warning: '',
    stableRelease: latestItem ? { tag: latest.tag_name, url: latestItem.url, publishedAt: latest.published_at } : null,
    items: [...items.values()].map(publicProgressItem).sort((a, b) => b.updatedAt.localeCompare(a.updatedAt) || a.id.localeCompare(b.id)) });
}

let built;
// One collection per build (or dev server), shared by every page that shows progress. A failure leaves the pages
// saying the data is unavailable for local previews. The publication check rejects that fallback before deployment.
export function buildFeed() {
  built ??= (async () => {
    const curation = JSON.parse(await readFile(curationPath, 'utf8'));
    return collectFeed({ token: process.env.FORGEJO_TOKEN || '', curation });
  })().catch((error) => {
    console.warn(`Progress feed unavailable for this build: ${error.message}`);
    return null;
  });
  return built;
}
