// After `astro build`: every link and asset on the site's own pages resolves, every #anchor exists, and every
// "Edit page" link names a file that exists in the repository.
import { readFile, readdir, stat } from 'node:fs/promises';
import path from 'node:path';
import { editUrl, siteUrl } from '../src/site.ts';
import { readProblemSearchHash } from '../src/lib/problem-search.ts';
import { validateFeed } from '../src/lib/progress.ts';
import { GAME_BRANDING as gameBranding } from '../src/lib/public-copy.ts';

const dist = path.resolve('dist');
const editBase = editUrl('');
const pages = (await readdir(dist, { recursive: true })).filter((file) => file.endsWith('.html'))
  .map((file) => path.join(dist, file));
const html = new Map(await Promise.all(pages.map(async (file) => [file, await readFile(file, 'utf8')] as const)));
const ids = new Map([...html].map(([file, text]) => [file, new Set([...text.matchAll(/\bid="([^"]+)"/g)].map((m) => m[1]))]));

const errors: string[] = [];
let links = 0;
for (const [file, text] of html) {
  const route = '/' + path.relative(dist, file).replaceAll(path.sep, '/').replace(/index\.html$/, '');
  // Audit published prose. Literal code/file paths and link destinations must remain usable and exact.
  const prose = text.replace(/<(script|style|code|pre)\b[^>]*>[\s\S]*?<\/\1>/gi, '')
    .replace(/<!--[^]*?-->/g, '').replace(/<[^>]+>/g, ' ');
  if (gameBranding.test(prose)) errors.push(`${route}: game branding remains in published text`);
  for (const [, url] of text.matchAll(/href="(https:\/\/git\.magicbean\.dev\/[^"]+\/_edit\/[^"]+)"/g)) {
    if (!url.startsWith(editBase)) errors.push(`${route}: edit link to another repository or branch: ${url}`);
    else await stat(path.join('..', url.slice(editBase.length))).catch(() => errors.push(`${route}: edit link to a missing file: ${url}`));
  }
  for (const [, tag, raw] of text.matchAll(/<(a|img|script|link)\b[^>]*?\b(?:href|src)="([^"]+)"/g)) {
    if (/^(?:data:|mailto:|tel:|javascript:)/.test(raw)) continue;
    const url = new URL(raw.replaceAll('&amp;', '&'), siteUrl + route);
    if (url.origin !== siteUrl) continue;
    // The Worker answers /download (worker/index.ts): it isn't a file of the build.
    if (url.pathname === '/download' || url.pathname.startsWith('/download/')) { links++; continue; }
    // Astro emits a /404/ canonical link, but the page is 404.html.
    if (tag === 'link' && url.pathname === '/404/') continue;
    let target = path.join(dist, decodeURIComponent(url.pathname));
    try {
      if ((await stat(target)).isDirectory()) target = path.join(target, 'index.html');
      await stat(target);
      links++;
    } catch { errors.push(`${route}: missing target: ${raw}`); continue; }
    // The problem search keeps its query in the hash (#problem-search?q=...).
    const anchor = url.pathname === '/progress/' && readProblemSearchHash(url.hash) ? 'problem-search' : decodeURIComponent(url.hash.slice(1));
    if (tag === 'a' && anchor && ids.has(target) && !ids.get(target)!.has(anchor)) errors.push(`${route}: missing anchor: ${raw}`);
  }
}
try {
  const feed = validateFeed(JSON.parse(await readFile(path.join(dist, 'progress-feed.json'), 'utf8')));
  for (const item of feed.items) {
    if ([item.title, item.originalTitle, item.summary, item.workaround, ...item.labels]
      .some(value => gameBranding.test(value))) errors.push(`Progress ${item.id}: game branding remains in public copy`);
  }
} catch (error) {
  errors.push(`Progress feed is not publishable: ${error.message} Check the collection log and rebuild before deploying.`);
}
if (!pages.length) errors.push('No pages in dist/: run the build first.');
if (errors.length) {
  console.error([...new Set(errors)].join('\n'));
  process.exitCode = 1;
} else {
  console.log(`Site check passed: ${pages.length} pages, ${links} local links and assets, their anchors and edit links.`);
}
