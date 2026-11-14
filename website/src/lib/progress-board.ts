import { STATUSES, REFRESH_MS, filterItems, validateFeed } from './progress.ts';
import { currentVersionWatch } from './progress-watch.ts';
import { progressOverview } from './progress-overview.ts';
import { readProblemSearchHash, prioritizeProblemSearch } from './problem-search.ts';

function element(tag: string, text = '', className = '') {
  const node = document.createElement(tag);
  node.textContent = text;
  if (className) node.className = className;
  return node;
}
function link(title: string, url: string) {
  const node = element('a', title) as HTMLAnchorElement;
  node.href = url;
  return node;
}
const date = (value: string) => new Date(value).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });

export class ProgressBoard extends HTMLElement {
  feed: ReturnType<typeof validateFeed> | null = null;
  limit = 20;
  timer?: ReturnType<typeof setInterval>;
  controller?: AbortController;
  events?: AbortController;
  lastAttempt = 0;
  failed = false;

  get form() { return this.querySelector('form')!; }
  region<T extends HTMLElement = HTMLElement>(name: string) { return this.querySelector<T>(`[data-${name}]`)!; }
  connectedCallback() {
    this.events = new AbortController();
    const options = { signal: this.events.signal };
    this.form.addEventListener('submit', e => e.preventDefault(), options);
    this.form.addEventListener('input', () => { this.limit = 20; this.renderResults(); }, options);
    this.form.addEventListener('reset', () => queueMicrotask(() => { this.limit = 20; this.renderResults(); }), options);
    this.region('more').addEventListener('click', () => { this.limit += 20; this.renderResults(); }, options);
    this.region('refresh').addEventListener('click', () => this.refresh(), options);
    window.addEventListener('hashchange', () => this.openProblemSearch(), options);
    // A repeated click on the same fragment does not emit hashchange.
    document.addEventListener('click', event => {
      const target = event.target instanceof Element ? event.target.closest<HTMLAnchorElement>('a[data-problem-search]') : null;
      if (target && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey && event.button === 0 &&
          new URL(target.href).pathname === location.pathname && location.hash === '#problem-search') {
        event.preventDefault();
        this.openProblemSearch();
      }
    }, options);
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden && Date.now() - this.lastAttempt >= REFRESH_MS) void this.refresh();
    }, options);
    this.timer = setInterval(() => { if (!document.hidden) void this.refresh(); }, REFRESH_MS);
    this.openProblemSearch();
    void this.refresh();
  }
  openProblemSearch() {
    const search = readProblemSearchHash(location.hash);
    if (!search) return;
    if (search.query !== null) (this.form.elements.namedItem('query') as HTMLInputElement).value = search.query;
    (this.form.elements.namedItem('view') as RadioNodeList).value = 'reports';
    for (const name of ['status', 'platform', 'area', 'version']) {
      (this.form.elements.namedItem(name) as HTMLSelectElement).value = '';
    }
    this.limit = 20;
    this.renderResults();
    prioritizeProblemSearch(this, window);
  }
  disconnectedCallback() {
    this.events?.abort(); this.controller?.abort(); clearInterval(this.timer);
  }
  async refresh() {
    if (this.controller) return;
    const controller = new AbortController();
    this.controller = controller;
    this.lastAttempt = Date.now();
    const timeout = setTimeout(() => controller.abort(), 20000);
    const button = this.region<HTMLButtonElement>('refresh');
    button.disabled = true;
    button.textContent = 'Checking…';
    try {
      const response = await fetch(this.dataset.endpoint!, { signal: controller.signal, credentials: 'omit', cache: 'no-store' });
      if (!response.ok) throw new Error('Feed unavailable');
      const next = validateFeed(await response.json());
      // Do not regress to an older CDN snapshot on a later refresh.
      const changed = !this.feed || next.generatedAt !== this.feed.generatedAt;
      if (!this.feed || Date.parse(next.generatedAt) >= Date.parse(this.feed.generatedAt)) this.feed = next;
      this.failed = false;
      if (changed) { this.populateVersions(); this.renderOverview(); this.renderWatch(); this.renderResults(); }
    } catch {
      this.failed = true;
      if (!this.feed) {
        this.region('overview').replaceChildren(element('p', 'Development totals are unavailable. Use the linked Forgejo pages for current activity.'));
        this.region('watch').replaceChildren(element('p', 'Current-version reports are unavailable. Open the issue tracker below for the latest information.'));
        this.region('count').textContent = 'Progress data is unavailable. This does not mean there are no reported issues.';
      }
    } finally {
      clearTimeout(timeout); this.controller = undefined;
      button.disabled = false; button.textContent = 'Check for updates';
      this.renderFreshness();
    }
  }
  renderFreshness() {
    const feed = this.feed;
    this.region('freshness').textContent = feed ? `Data checked ${date(feed.generatedAt)}. Checks automatically every 5 minutes while this page is open.` : 'No progress snapshot available.';
    const old = feed && Date.now() - Date.parse(feed.generatedAt) > 2 * 60 * 60 * 1000;
    const warning = this.failed ? feed ? 'Update unavailable. Your previous results are still shown.' : 'Could not load progress data. Use the Forgejo links below or try again.' :
      feed?.warning || (old ? 'This snapshot is over 2 hours old. Check the linked Forgejo pages for newer activity.' : '');
    this.region('warning').textContent = warning;
    this.region('warning').hidden = !warning;
  }
  populateVersions() {
    const select = this.form.elements.namedItem('version') as HTMLSelectElement;
    const previous = select.value;
    select.replaceChildren(new Option('Any version', ''));
    const versions = new Set<string>(this.feed!.items.map(i => i.report.version).filter(Boolean));
    for (const version of [...versions].sort()) select.add(new Option(version, version));
    if (previous && !versions.has(previous)) select.add(new Option(previous, previous));
    select.value = previous;
  }
  renderOverview() {
    const root = this.region('overview');
    root.replaceChildren();
    for (const item of progressOverview(this.feed!)) {
      const card = element('div', '', 'progress-overview-card');
      card.append(element('h3', item.title), element('strong', String(item.count)), element('p', item.text));
      root.append(card);
    }
  }
  renderWatch() {
    const watch = currentVersionWatch(this.feed!);
    const root = this.region('watch');
    const active = root.contains(document.activeElement) ? document.activeElement as HTMLElement : null;
    const activeHref = active?.getAttribute('href');
    const activeGroup = active?.closest<HTMLElement>('[data-group]')?.dataset.group;
    const expanded = new Set([...root.querySelectorAll<HTMLDetailsElement>('details[open]')].map(d => d.dataset.group));
    root.replaceChildren();
    if (!watch.stable || !watch.version) {
      root.append(element('p', watch.stable ? 'The stable release has no exact version number to match. Browse reports below.' : 'No stable Hookshot release is published in this snapshot. Browse reports and proposed changes below.'));
      return;
    }
    const heading = element('p');
    heading.append(link(`Latest stable: ${watch.stable.tag}`, watch.stable.url), document.createTextNode(` · Published ${date(watch.stable.publishedAt)}`));
    root.append(heading, element('p', `${watch.current.length} open reports explicitly name this version. ${watch.other} name other versions; ${watch.unknown} have no exact version.`));
    if (!watch.current.length) root.append(element('p', 'No matching open reports in this snapshot. This is not evidence that the version is free of problems.'));
    if (watch.important.length) {
      root.append(element('h3', 'Reviewed issues to know about'));
      root.append(element('p', 'These summaries were checked against the linked reports. The problems have not been independently reproduced here.', 'progress-note'));
      const list = element('ul');
      for (const i of watch.important) {
        const row = element('li'); row.append(link(i.title, i.url), element('p', i.summary), element('p', `Reported impact: ${i.impact} · Summary reviewed ${date(i.reviewedAt)}`, 'progress-note')); list.append(row);
      }
      root.append(list);
    }
    if (watch.groups.length) {
      root.append(element('h3', 'Most reported areas'));
      const list = element('ul', '', 'watch-groups');
      for (const group of watch.groups) {
        const row = element('li'); const details = element('details') as HTMLDetailsElement;
        details.dataset.group = group.area; details.open = expanded.has(group.area);
        details.append(element('summary', `${group.area} — ${group.items.length} ${group.items.length === 1 ? 'report' : 'reports'}`));
        details.append(element('p', 'Grouped by the reporter’s selected category or a reviewed summary. Reports may overlap; known duplicates and questions are excluded.'));
        const items = element('ul');
        for (const i of group.items) { const entry = element('li'); entry.append(link(`#${i.number}: ${i.title}`, i.url)); items.append(entry); }
        details.append(items); row.append(details); list.append(row);
      }
      root.append(list);
    }
    root.append(element('p', 'Evidence: exact game or installation version fields in open reports. “Latest”, ranges and commit hashes are not matched. Comments and older unresolved reports are not proof of a current-version problem.', 'progress-note'));
    if (activeHref) [...root.querySelectorAll<HTMLAnchorElement>('a')].find(a => a.getAttribute('href') === activeHref)?.focus();
    else if (activeGroup) [...root.querySelectorAll<HTMLDetailsElement>('details')].find(d => d.dataset.group === activeGroup)?.querySelector<HTMLElement>('summary')?.focus();
  }
  renderResults() {
    if (!this.feed) return;
    const values = Object.fromEntries(new FormData(this.form).entries());
    const items = filterItems(this.feed.items, values);
    const results = this.region('results');
    const focusedId = (document.activeElement as HTMLElement)?.closest<HTMLElement>('[data-item]')?.dataset.item;
    const focusedHref = document.activeElement?.getAttribute('href');
    const expanded = new Set([...results.querySelectorAll('details[open]')].map(d => d.closest<HTMLElement>('[data-item]')?.dataset.item));
    const previousCount = results.children.length;
    const moreHadFocus = document.activeElement === this.region('more');
    results.replaceChildren();
    for (const item of items.slice(0, this.limit)) {
      const row = element('li', '', 'progress-card'); row.dataset.item = item.id;
      row.append(element('span', STATUSES[item.status][0], 'progress-status'));
      const title = element('h3'); title.append(link(item.title, item.url)); row.append(title);
      row.append(element('p', item.summary));
      const kind = { issue: 'Report', feature: 'Feature request', pull: 'Proposed change', release: 'Release' }[item.kind];
      row.append(element('p', `${kind}${item.kind === 'release' ? '' : ` #${item.number}`} · Updated ${date(item.updatedAt)}${item.report.version ? ` · Reported on ${item.report.version}` : ''}`, 'progress-meta'));
      if (item.workaround) row.append(element('p', `Reviewed workaround: ${item.workaround}`));
      const details = element('details') as HTMLDetailsElement;
      details.open = expanded.has(item.id);
      details.append(element('summary', 'Evidence and developer details'));
      details.append(element('p', STATUSES[item.status][1]), element('p', `Original Forgejo title: ${item.originalTitle}`));
      if (item.labels.length) details.append(element('p', `Forgejo labels: ${item.labels.join(', ')}`));
      details.append(element('p', `Platform: ${item.platforms.join(', ') || 'Unspecified'} · Area: ${item.area}`));
      if (item.reviewedAt) details.append(element('p', `Plain-language summary reviewed ${date(item.reviewedAt)}.`));
      else details.append(element('p', 'Original title with an automatic status explanation; no reviewed workaround is available here.'));
      for (const url of item.sources) { const p = element('p'); p.append(link('Reviewed source on Forgejo', url)); details.append(p); }
      row.append(details); results.append(row);
    }
    this.region('count').textContent = items.length ? `Showing ${Math.min(this.limit, items.length)} of ${items.length} matching items, most recently updated first.` : 'No matching items. Try fewer filters or search the complete Forgejo tracker below.';
    this.region('more').hidden = this.limit >= items.length;
    if (focusedId) {
      const target = [...results.querySelectorAll<HTMLElement>('[data-item]')].find(row => row.dataset.item === focusedId);
      if (focusedHref) [...target?.querySelectorAll<HTMLAnchorElement>('a') || []].find(a => a.getAttribute('href') === focusedHref)?.focus();
      else target?.querySelector<HTMLElement>('summary')?.focus();
    } else if (moreHadFocus && results.children[previousCount]) {
      results.children[previousCount].querySelector<HTMLElement>('a')?.focus();
    }
  }
}
