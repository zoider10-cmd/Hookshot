import { reportEvidence } from './progress-watch.ts';
export const REPOSITORY = 'MagicBeanDev/Hookshot';
export const ROOT = `https://git.magicbean.dev/${REPOSITORY}`;
export const REFRESH_MS = 5 * 60 * 1000;
export const AREAS = ['Graphics', 'Performance', 'Crashes or startup', 'Sound, controls or saves', 'Controls', 'Audio', 'Setup', 'Documentation'];
export const PLATFORMS = ['Windows', 'Linux', 'Steam Deck', 'Other'];
export const IMPACTS = ['Crashes', 'Save integrity', 'Cannot start', 'Blocked progression'];
export const STATUSES = {
  reported: ['Reported', 'Someone has reported a problem or asked a question. This does not yet confirm a bug or active work.'],
  suggested: ['Suggested', 'A feature has been requested. It has not necessarily been accepted or scheduled.'],
  working: ['Work underway', 'This item has an explicit “in progress” label on Forgejo. Check its discussion for the latest details.'],
  proposed: ['Change proposed', 'A contributor has submitted a change for review. It may still change or be declined.'],
  draft: ['Draft change', 'This proposal is marked as a draft and is not ready for final review.'],
  merged: ['Merged', 'The change was accepted into its target branch. Release availability has not been verified here.'],
  closed: ['Closed report', 'This report was closed. Read the discussion to see why; closure alone does not establish a released fix.'],
  declined: ['Closed without completion', 'Forgejo records this report as not planned. Read the discussion for the reason.'],
  duplicate: ['Duplicate report', 'This closed report is labelled as a duplicate. Follow the linked discussion to the original report.'],
  withdrawn: ['Closed proposal', 'This proposed change was closed without being merged.'],
  released: ['Stable release', 'A published stable version is available. Open the release notes to see what it includes.'],
  preview: ['Preview release', 'A published prerelease is available for testing; it is separate from the stable version.'],
};

const clean = (value, limit = 400) => typeof value === 'string' ? value.trim().slice(0, limit) : '';
const validDate = (value) => typeof value === 'string' && Number.isFinite(Date.parse(value));
const validId = (value) => Number.isSafeInteger(value) && value > 0;
const isSource = (value) => {
  try { const u = new URL(value); return u.origin === 'https://git.magicbean.dev' && u.pathname.startsWith(`/${REPOSITORY}/`) && !u.username && !u.password; }
  catch { return false; }
};

export function validateCuration(curation) {
  if (!curation || typeof curation !== 'object' || Array.isArray(curation)) throw new Error('Invalid progress curation.');
  for (const [key, value] of Object.entries(curation)) {
    if (!/^(issue|pull|release):[1-9]\d*$/.test(key) || !value ||
        !clean(value.title) || !clean(value.summary) || !validDate(value.reviewedAt) || !validDate(value.sourceUpdatedAt) ||
        !Array.isArray(value.sources) || !value.sources.length || !value.sources.every(isSource) ||
        (value.area !== undefined && !AREAS.includes(value.area)) ||
        (value.impact !== undefined && !IMPACTS.includes(value.impact)) ||
        (value.platforms !== undefined && (!Array.isArray(value.platforms) || !value.platforms.every(p => PLATFORMS.includes(p)))) ||
        (value.workaround !== undefined && typeof value.workaround !== 'string')) throw new Error(`Invalid progress curation: ${key}`);
  }
}

export function normalizeItem(raw, kind, curation = {}) {
  const release = kind === 'release';
  const number = release ? raw.id : raw.number;
  const updatedAt = raw.updated_at || raw.published_at;
  if (!validId(number) || !validDate(updatedAt) || (!release && !['open', 'closed'].includes(raw.state))) {
    throw new Error('Invalid Forgejo progress item.');
  }
  if (release && (raw.draft !== false || !validDate(raw.published_at) || !clean(raw.tag_name))) return null;
  const labels = (raw.labels || []).map(l => clean(typeof l === 'string' ? l : l.name, 80)).filter(Boolean);
  const lower = labels.map(l => l.toLowerCase());
  const feature = kind === 'issue' && lower.some(l => ['enhancement', 'feature', 'feature request'].includes(l));
  let status;
  if (release) status = raw.prerelease ? 'preview' : 'released';
  else if (kind === 'pull') status = raw.merged_at ? 'merged' : raw.state === 'closed' ? 'withdrawn' : (raw.draft || /^(?:WIP:|\[WIP\]|Draft:)/i.test(raw.title || '')) ? 'draft' : 'proposed';
  else if (raw.state === 'closed') status = lower.includes('duplicate') ? 'duplicate' : raw.state_reason === 'not_planned' ? 'declined' : 'closed';
  else status = lower.includes('in progress') ? 'working' : feature ? 'suggested' : 'reported';
  const id = `${kind}:${number}`;
  const review = curation[id];
  const curated = review?.sourceUpdatedAt === updatedAt ? review : null;
  const originalTitle = clean(release ? raw.name || raw.tag_name : raw.title);
  if (!originalTitle) throw new Error('Missing Forgejo title.');
  const platforms = curated?.platforms || PLATFORMS.filter(p => lower.includes(`os:${p.toLowerCase().replace(' ', '')}`));
  const report = kind === 'issue' ? reportEvidence(raw.body) : { version: null, versionSource: null, reportedArea: 'Unspecified' };
  const area = curated?.area || (lower.includes('documentation') ? 'Documentation' : report.reportedArea);
  return {
    id, kind: feature ? 'feature' : kind, number, title: clean(curated?.title || originalTitle), originalTitle,
    summary: clean(curated?.summary, 1200) || STATUSES[status][1], status, updatedAt,
    publishedAt: release ? raw.published_at : null,
    mergedAt: kind === 'pull' ? raw.merged_at || null : null,
    url: release ? `${ROOT}/releases/tag/${encodeURIComponent(raw.tag_name)}` : `${ROOT}/${kind === 'pull' ? 'pulls' : 'issues'}/${number}`,
    labels, platforms, area, reviewedAt: curated?.reviewedAt || null,
    sources: curated?.sources || [], workaround: clean(curated?.workaround, 1200),
    impact: curated?.impact || null,
    report,
  };
}

export function validateFeed(feed) {
  if (!feed || feed.version !== 1 || feed.repository !== REPOSITORY || !validDate(feed.generatedAt) ||
      !validDate(feed.collectionStartedAt) || !validDate(feed.closedSince) || !Array.isArray(feed.items) ||
      typeof feed.warning !== 'string' || (feed.stableRelease !== null &&
        (!feed.stableRelease || typeof feed.stableRelease.tag !== 'string' || !validDate(feed.stableRelease.publishedAt) ||
         feed.stableRelease.url !== `${ROOT}/releases/tag/${encodeURIComponent(feed.stableRelease.tag)}`))) throw new Error('Invalid progress feed.');
  const ids = new Set();
  for (const i of feed.items) {
    if (!i || !['issue', 'feature', 'pull', 'release'].includes(i.kind) || !validId(i.number) ||
        i.id !== `${i.kind === 'feature' ? 'issue' : i.kind}:${i.number}` || ids.has(i.id) ||
        !Object.hasOwn(STATUSES, i.status) || !validDate(i.updatedAt) || !clean(i.title) ||
        typeof i.originalTitle !== 'string' || typeof i.summary !== 'string' || typeof i.workaround !== 'string' ||
        !Array.isArray(i.labels) || !i.labels.every(l => typeof l === 'string') ||
        !Array.isArray(i.platforms) || !i.platforms.every(p => PLATFORMS.includes(p)) ||
        ![...AREAS, 'Unspecified'].includes(i.area) || !Array.isArray(i.sources) || !i.sources.every(isSource) ||
        (i.reviewedAt !== null && !validDate(i.reviewedAt)) ||
        (i.kind === 'release' && !validDate(i.publishedAt)) ||
        (i.mergedAt !== null && !validDate(i.mergedAt)) ||
        (i.impact !== null && !IMPACTS.includes(i.impact)) || !i.report ||
        (i.report.version !== null && typeof i.report.version !== 'string') ||
        (i.report.versionSource !== null && !['Hookshot version field', 'Builder version field', 'Installation version field'].includes(i.report.versionSource)) ||
        typeof i.report.reportedArea !== 'string') throw new Error('Invalid progress feed item.');
    const prefix = i.kind === 'release' ? `${ROOT}/releases/tag/` : `${ROOT}/${i.kind === 'pull' ? 'pulls' : 'issues'}/`;
    if (typeof i.url !== 'string' || !isSource(i.url) || !i.url.startsWith(prefix) ||
        (i.kind !== 'release' && i.url !== prefix + i.number)) throw new Error('Invalid progress link.');
    ids.add(i.id);
  }
  return feed;
}

export function filterItems(items, { query = '', view = 'all', status = '', platform = '', area = '', version = '' } = {}) {
  const words = query.toLowerCase().trim().replace(/^#(?=\d)/, '').split(/\s+/).filter(Boolean);
  return items.filter(i => {
    if (view === 'reports' && i.kind !== 'issue') return false;
    if (view === 'features' && i.kind !== 'feature') return false;
    if (view === 'changes' && i.kind !== 'pull' && i.status !== 'working') return false;
    if (view === 'releases' && i.kind !== 'release') return false;
    if (status && i.status !== status) return false;
    if (platform && !(platform === 'Unspecified' ? !i.platforms.length : i.platforms.includes(platform))) return false;
    if (area && i.area !== area) return false;
    if (version && i.report.version !== version) return false;
    const haystack = [i.title, i.originalTitle, i.summary, i.workaround, i.number, ...i.labels, ...i.platforms, i.area, i.report.version, i.report.reportedArea].join(' ').toLowerCase();
    return words.every(word => haystack.includes(word));
  });
}
