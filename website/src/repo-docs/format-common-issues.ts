import { sectionsAt } from './format-install.ts';

// The Help page (docs/common-issues.md): an introduction with a list of the groups, then one `##` group for each moment
// a problem shows up, each with `###` problems that end with a line of report-search links, then "Still stuck?".
// Presentation labels only: all troubleshooting steps and links live in the document.
const groups = new Map([
  ['Installing and building', 'Before you play'],
  ['Starting the game', 'When you press Play'],
  ['In game: graphics', 'While playing'],
  ['In game: performance and freezes', 'While playing'],
  ['In game: controls, saves and language', 'While playing'],
  ['Downloads and antivirus', 'When you download'],
]);
const stuckTitle = 'Still stuck?';
// The page's topics before it was grouped: old links to them open the problem (or group) that replaced each one.
export const legacyAnchors = new Map([
  ['the-build-rejects-the-game-version', 'the-launcher-says-this-version-isnt-supported'],
  ['the-game-closes-or-shows-a-black-screen', 'the-game-opens-and-closes-shows-a-black-screen-or-the-log-says-device-lost'],
  ['graphics-are-missing-or-corrupted', 'in-game-graphics'],
  ['the-controller-behaves-differently-than-expected', 'a-and-b-are-swapped-or-a-button-does-the-wrong-thing'],
  ['performance-drops-or-stutters', 'in-game-performance-and-freezes'],
  ['an-update-or-save-transfer-failed', 'a-save-is-missing-or-a-save-transfer-or-update-went-wrong'],
  ['a-download-is-flagged', 'windows-defender-or-the-browser-flags-the-download'],
]);
// A problem ends with one line of searches of the reports: [Search ...](.../progress/#problem-search?q=...) · ...
const searchLink = String.raw`\[Search [^\]]+\]\((?:https://hookshot\.magicbean\.dev)?/progress/#problem-search\?q=[^)\s]+\)`;
const searchLine = new RegExp(`^${searchLink}(?: · ${searchLink})*$`);

const escape = text => text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
// A heading's text as shown: straight quotes become curly ones.
const display = title => escape(title.replace(/"([^"]*)"/g, '“$1”').replaceAll("'", '’'));
// A group's name as shown under its label: "In game: graphics" reads "Graphics" under "While playing".
const groupName = title => display(title.replace(/^In game: (.)/, (_, first) => first.toUpperCase()));
/** The anchor Starlight and Forgejo give a heading: lower case, punctuation dropped, spaces as hyphens. */
export const headingId = title => title.toLowerCase().replace(/[^a-z0-9 -]/g, '').replaceAll(' ', '-');
const anchorsFor = id => [...legacyAnchors].filter(([, target]) => target === id)
  .map(([legacy]) => `<span class="issue-anchor" id="${legacy}"></span>`).join('');

export function formatCommonIssues(source) {
  const sections = sectionsAt(source, 2);
  const expected = [...groups.keys(), stuckTitle];
  if (sections.slice(1).map(section => section.title).join('\n') !== expected.join('\n')) {
    throw new Error(`Help page group structure changed: expected ${expected.join(', ')}`);
  }
  // The introduction: its text, then a list linking each group in order (the problem finder replaces it).
  const lead = sections[0].body.trim();
  const listAt = lead.search(/^- /m);
  const jumps = listAt < 0 ? [] : [...lead.slice(listAt).matchAll(/^- \[([^\]]+)\]\(#([^)]+)\)$/gm)];
  if (jumps.map(([, label, id]) => `${label}#${id}`).join('\n') !== expected.map(title => `${title}#${headingId(title)}`).join('\n')
    || lead.slice(listAt).split('\n').length !== jumps.length) {
    throw new Error('Help page group list changed: it must link each group in order');
  }

  const rendered = sections.slice(1, -1).map(group => {
    const id = headingId(group.title);
    const label = escape(groups.get(group.title));
    const problems = sectionsAt(group.body, 3);
    if (problems[0].body.trim() || problems.length < 2) throw new Error(`Help page group structure changed: ${group.title}`);
    const items = problems.slice(1).map(problem => {
      const lines = problem.body.trim().split('\n');
      const search = lines.pop();
      const body = lines.join('\n').trim();
      if (!body || !searchLine.test(search) || /^#{4,} /m.test(body)) {
        throw new Error(`Help page problem structure changed: ${problem.title}`);
      }
      const problemId = headingId(problem.title);
      return { title: problem.title, id: problemId, html: `<details class="issue-card">
<summary>${anchorsFor(problemId)}<h3 id="${problemId}">${display(problem.title)}</h3></summary>
<div class="issue-content">

${body}

<div class="issue-search">

${search}

</div>
</div>
</details>` };
    });
    const finder = `<li class="issue-finder-group">
<a class="issue-finder-head" href="#${id}"><span class="issue-category">${label}</span><strong>${groupName(group.title)}</strong></a>
<ul>
${items.map(item => `<li><a href="#${item.id}">${display(item.title)}</a></li>`).join('\n')}
</ul>
</li>`;
    const section = `<section class="issue-group" aria-labelledby="${id}">
${anchorsFor(id)}<h2 id="${id}"><span class="issue-category">${label}</span>${groupName(group.title)}</h2>
<div class="issue-list">

${items.map(item => item.html).join('\n\n')}

</div>
</section>`;
    return { finder, section };
  });

  const stuck = sections.at(-1).body.trim();
  if ((stuck.match(/^\d+\. /gm) || []).length < 4) throw new Error('Help page "Still stuck?" changed: it must list the steps to take');

  return `<div class="manual-guide issues-guide">

${lead.slice(0, listAt).trim()}

<nav class="issue-finder" aria-label="Find your problem">
<ul>
${rendered.map(group => group.finder).join('\n')}
<li class="issue-finder-group issue-finder-stuck">
<a class="issue-finder-head" href="#still-stuck"><span class="issue-category">Nothing fits?</span><strong>Still stuck?</strong></a>
<p>Find the log, make a bug report, search the reports or ask the team.</p>
</li>
</ul>
</nav>

${rendered.map(group => group.section).join('\n\n')}

<section class="issue-stuck" aria-labelledby="still-stuck">
<h2 id="still-stuck">Still stuck?</h2>

${stuck}

</section>
</div>\n`;
}
