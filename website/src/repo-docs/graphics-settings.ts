import { sectionsAt } from './format-install.ts';
import { publicGameText } from '../lib/public-copy.ts';

const escape = value => value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
const slug = value => value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');

// The tabs a player sees, as README names them; the Controls page's rows (TAB_PAGE) are listed with the Controls tab's,
// and the Motion page's (TAB_MOTION) on README's Motion line. The Debug tab is for testing, not here.
const TAB_NAMES = { GRAPHICS: 'Graphics', AUDIO: 'Audio', GAMEPLAY: 'Gameplay', CONTROLS: 'Controls', PAGE: 'Controls' };
const ACTIONS = new Set(['Restart', 'Quit']);   // (rows that do a thing, with no choice to list)
export const RESTART_BADGE = 'After a restart';

// What a row's README cells say about when it shows or what sets it, as small badges on its card. A row the menu hides on
// some PCs (row_shown) must match a `shown` rule, so a new condition in the menu fails the build until README names it.
export const BADGES = [
  { test: /shown only on NVIDIA GPUs/i, label: 'NVIDIA GPUs only', shown: true },
  { test: /shown only on AMD GPUs/i, label: 'AMD GPUs only', shown: true },
  { test: /shown where DLSS runs/i, label: 'Where DLSS runs', shown: true },
  { test: /\bshown while Frame generation is on\b/i, label: 'While Frame generation is on', shown: true },
  { test: /\bshown with a CRT filter on\b/i, label: 'With a CRT filter on', shown: true },
  { test: /while HDR is on/i, label: 'While HDR is on', shown: true },
  { test: /\bwith HDR set to Native\b/i, label: 'With HDR on Native', shown: true },
  { test: /only in builds with/i, label: 'Depends on GPU and build', shown: true },
  { test: /(?:quality )?preset (?:sets|turns) it/i, label: 'Set by quality presets', both: true },
  { test: /on the Controls page/i, label: 'On the Controls page' },
];

/// The C string literals of a field, joined ("a" "b" is "ab"), their escapes read; null when it has none
function cString(field) {
  const parts = [...field.matchAll(/"((?:[^"\\]|\\.)*)"/g)].map(match => match[1].replace(/\\(.)/g, (_, c) => c === 'n' ? '\n' : c));
  return parts.length ? parts.join('') : null;
}

/// The menu's row table (gpu/vk/vk_menu.cpp `Row rows[]`), read without evaluating C++: each `{TAB_..., ...}` entry split at
/// its top-level commas, strings and comments skipped. The fields are Row's: tab, name, value, lo, hi, step, text, help, hint,
/// restart, preset_exempt, cheat, heading. `shown` is false for a row row_shown can hide.
export function readMenuRows(menu) {
  const body = menu.match(/Row rows\[\]\s*=\s*\{([\s\S]*?)\n\};/)?.[1];
  if (!body) throw new Error('Missing menu row table');
  const rows = [];
  let depth = 0, field = '', fields = [];
  for (let i = 0; i < body.length; i++) {
    const c = body[i];
    if (c === '/' && body[i + 1] === '/') { while (i < body.length && body[i] !== '\n') i++; continue; }
    if (c === '/' && body[i + 1] === '*') {
      i = body.indexOf('*/', i + 2) + 1;
      if (i === 0) throw new Error('Unreadable menu row table');
      continue;
    }
    if (c === '"') {
      let j = i + 1;
      while (j < body.length && body[j] !== '"') j += body[j] === '\\' ? 2 : 1;
      if (depth > 0) field += body.slice(i, j + 1);
      i = j;
      continue;
    }
    if (c === '{') {
      if (depth++ === 0) { field = ''; fields = []; continue; }
    } else if (c === '}') {
      if (--depth === 0) {
        fields.push(field.trim());
        const tab = fields[0].match(/^TAB_(\w+)$/)?.[1];
        const name = cString(fields[1] || '');
        if (!tab || name === null) throw new Error(`Unrecognized menu row: ${fields.slice(0, 2).join(', ')}`);
        rows.push({ tab, name, value: fields[2], help: cString(fields[7] || '') || '', restart: fields[9] === 'true',
          heading: fields[12] === 'true', shown: true,
          // This registered selector stores an opaque display identity rather than an Options integer.
          monitorSelector: tab === 'GRAPHICS' && name === 'Fullscreen monitor' && fields[2] === '&monitor_pick'
            && fields[6] === 'tx_fullscreen_monitor' && fields[8] === 'hn_fullscreen_monitor' });
        continue;
      }
      if (depth < 0) throw new Error('Unreadable menu row table');
    } else if (c === ',' && depth === 1) {
      fields.push(field.trim());
      field = '';
      continue;
    }
    if (depth > 0) field += c;
  }
  if (depth !== 0 || !rows.length) throw new Error('Unreadable menu row table');
  // Text fields have no integer option pointer. Their maintained registration and help
  // identify them; keep rejecting arbitrary null-valued Graphics actions.
  const fieldTable = menu.match(/const FieldRow field_rows\[\]\s*=\s*\{([\s\S]*?)\};/)?.[1] || '';
  const textFields = new Set([...fieldTable.matchAll(/\{\s*"([^"]+)"\s*,\s*&\w+\s*,\s*\w+\s*\}/g)].map(match => match[1]));
  for (const row of rows) {
    row.textField = row.value === 'nullptr' && textFields.has(row.name);
    if (row.textField) row.restart = /Applies after (?:a )?restart\./.test(row.help);
  }
  const shown = menu.match(/bool row_shown\(int i\) \{([\s\S]*?)\n\}/)?.[1];
  if (!shown) throw new Error('Missing menu row_shown');
  const conditional = new Set([...shown.matchAll(/&opts\.\w+/g)].map(match => match[0]));
  for (const row of rows) if (conditional.has(row.value)) row.shown = false;
  if (!rows.some(row => !row.shown)) throw new Error('Unrecognized menu row_shown');
  return rows;
}

/// The menu's own help for a card: what the row is. Its restart sentence is the card's badge instead.
const summaryOf = help => help.replace(/\s*Applies after (?:a )?restart\.?/g, '').trim();

// Choices and defaults have one maintained source, README's table; names, order, sections, help and restarts come from the
// menu's. Fail on drift between them instead of publishing a wrong or partial list. Escaped table pipes remain cell content.
export function readGraphicsSettings(readme, menu) {
  const section = sectionsAt(readme, 2).find(section => section.title === 'In-game menu');
  const table = section?.body.match(/^\| Tab \| Option \| Choices \| Default \|\r?\n\|[-| :]+\|\r?\n((?:\|[^\n]+\r?\n?)+)/m);
  if (!table) throw new Error('Missing README in-game menu table');
  let tab = '';
  const settings = [];
  const otherTabs = new Map();
  for (const line of table[1].trim().split('\n')) {
    const cells = line.trim().slice(1, -1).split(/(?<!\\)\|/).map(cell => cell.trim().replaceAll('\\|', '|'));
    if (cells.length !== 4) throw new Error('Changed README menu table structure');
    tab = cells[0] || tab;
    const [, name, choices, defaultValue] = cells;
    if (tab !== 'Graphics') {
      if (tab === 'Debug' || !name) continue;
      if (!otherTabs.has(tab)) otherTabs.set(tab, []);
      otherTabs.get(tab).push({ name, choices, defaultValue: defaultValue || '—', id: `setting-${slug(tab)}-${slug(name)}` });
      continue;
    }
    if (!name || !choices || !defaultValue) throw new Error('Incomplete README graphics setting');
    settings.push({ name, choices, defaultValue });
  }
  if (!settings.length) throw new Error('No Graphics settings in README');
  if ([...otherTabs.keys()].some(name => !Object.values(TAB_NAMES).includes(name))) throw new Error('README menu table has an unknown tab');

  const rows = readMenuRows(menu);
  const withSource = (setting, tabName) => {
    const row = rows.find(row => !row.heading && TAB_NAMES[row.tab] === tabName && row.name === setting.name);
    if (!row) throw new Error(`README/menu ${tabName} coverage mismatch at ${setting.name}`);
    // (README says "after a restart" exactly where the menu's row takes one)
    if (/after a restart/i.test(setting.choices) !== row.restart) throw new Error(`README/menu restart mismatch at ${setting.name}`);
    const badges = BADGES.filter(badge => badge.test.test(badge.both ? `${setting.choices} ${setting.defaultValue}` : setting.choices));
    if (!row.shown && !badges.some(badge => badge.shown)) {
      throw new Error(`README names no condition for ${setting.name}, which the menu shows only on some PCs`);
    }
    return { ...setting, summary: summaryOf(row.help), restart: row.restart, badges: badges.map(badge => badge.label) };
  };

  // The Graphics tab: README's lines in the menu's order, under the menu's section titles
  const groups = [{ name: 'Quality preset', settings: [] }];
  let at = 0;
  for (const row of rows.filter(row => row.tab === 'GRAPHICS')) {
    if (row.heading) {
      if (row.value !== 'nullptr') throw new Error(`README/menu graphics coverage mismatch: unrecognized heading ${row.name}`);
      groups.push({ name: row.name, settings: [] });
      continue;
    }
    if (!row.value.startsWith('&opts.') && !row.textField && !row.monitorSelector) throw new Error(`README/menu graphics coverage mismatch at ${row.name}`);
    const setting = settings[at++];
    if (setting?.name !== row.name) throw new Error(`README/menu graphics order mismatch at ${row.name}`);
    groups.at(-1).settings.push({ ...withSource(setting, 'Graphics'), id: `setting-${slug(row.name)}` });
  }
  if (at !== settings.length || groups.some(group => !group.settings.length)) throw new Error('README/menu graphics coverage mismatch');

  // The other tabs: every row the menu has there, and nothing it has not
  for (const tabName of ['Audio', 'Gameplay', 'Controls']) {
    const listed = (otherTabs.get(tabName) || []).map(setting => setting.name).sort();
    const source = rows.filter(row => !row.heading && TAB_NAMES[row.tab] === tabName && !ACTIONS.has(row.name)).map(row => row.name).sort();
    if (listed.join('\n') !== source.join('\n')) throw new Error(`README/menu ${tabName} coverage mismatch`);
  }
  return [
    ...groups.map(group => ({ ...group, tab: 'Graphics', id: `settings-${slug(group.name)}` })),
    ...[...otherTabs].map(([name, tabSettings]) => ({ name, tab: name, id: `settings-${slug(name)}`,
      settings: tabSettings.map(setting => withSource(setting, name)) })),
  ];
}

// (choices this short show on their row; longer ones fold away)
export const SHORT_CHOICES = 120;

export async function formatGraphicsSettings(text, readme, menu, processor) {
  const marker = '<!-- graphics-settings -->';
  if (text.split(marker).length !== 2) throw new Error('Expected one graphics-settings insertion marker');
  const groups = readGraphicsSettings(readme, menu);
  const count = groups.reduce((sum, group) => sum + group.settings.length, 0);
  const inline = async value => (await processor.render(publicGameText(value))).code.trim().replace(/^<p>([\s\S]*)<\/p>$/, '$1');
  const rendered = [];
  for (const group of groups) {
    const cards = [];
    for (const setting of group.settings) {
      const badges = [...(setting.restart ? [RESTART_BADGE] : []), ...setting.badges];
      const choices = await inline(setting.choices);
      const short = setting.choices.length <= SHORT_CHOICES;
      // (one row a setting: its name and badges, what it does with its choices, then its default)
      cards.push(`<article class="graphics-row" data-setting>
<div class="graphics-name"><h4 id="${setting.id}"><a href="#${setting.id}">${escape(publicGameText(setting.name))}</a></h4>
${badges.length ? `<ul class="graphics-badges" aria-label="Conditions">${badges.map(badge => `<li${badge === RESTART_BADGE ? ' class="graphics-badge-restart"' : ''}>${escape(badge)}</li>`).join('')}</ul>` : ''}</div>
<div class="graphics-about">${setting.summary ? `<p class="graphics-summary">${escape(publicGameText(setting.summary))}</p>` : ''}
${short ? `<p class="graphics-choices"><span>Choices</span> ${choices}</p>` : `<details><summary>Choices and requirements</summary><p>${choices}</p></details>`}</div>
<p class="graphics-default"><span>Default</span> ${await inline(setting.defaultValue)}</p>
</article>`);
    }
    rendered.push(`<section class="graphics-group" data-settings-group="${group.id}">
<p class="graphics-tab">${escape(group.tab.toUpperCase())} TAB</p>
<h3 id="${group.id}">${escape(group.name)}</h3>
<div class="graphics-head" aria-hidden="true"><span>Setting</span><span>What it does</span><span>Default</span></div>
<div class="graphics-list">${cards.join('\n')}</div>
</section>`);
  }
  // (a jump list: each tab, and the Graphics tab's sections, with how many settings each has)
  const tabs = [];
  for (const group of groups) {
    if (tabs.at(-1)?.name !== group.tab) tabs.push({ name: group.tab, groups: [] });
    tabs.at(-1).groups.push(group);
  }
  const jump = `<nav class="graphics-jump" aria-label="Jump to a tab or section">${tabs.map(tab => `<div>
<p>${escape(tab.name)} tab</p>
<ul>${tab.groups.map(group => `<li><a href="#${group.id}">${escape(tab.groups.length > 1 ? group.name : `${group.settings.length} settings`)}</a>${tab.groups.length > 1 ? ` <span>${group.settings.length}</span>` : ''}</li>`).join('')}</ul>
</div>`).join('\n')}</nav>`;
  return text.replace(marker, `<div class="graphics-settings" data-graphics-settings>
${jump}
<form class="graphics-filters" data-settings-filters hidden role="search" aria-label="Settings">
<label>Find a setting<input type="search" name="query" placeholder="Try DLSS, HDR, rumble or restart" aria-controls="graphics-results" /></label>
<label>Section<select name="group" aria-controls="graphics-results"><option value="">Everything</option>${groups.map(group => `<option value="${group.id}">${escape(group.tab === group.name ? group.name : `${group.tab}: ${group.name}`)}</option>`).join('')}</select></label>
<button type="reset">Clear filters</button>
</form>
<p class="graphics-count" data-settings-count role="status" aria-live="polite">${count} settings.</p>
<p data-settings-empty hidden>No settings match. Try another term or clear the filters.</p>
<div id="graphics-results">${rendered.join('\n')}</div>
</div>`);
}
