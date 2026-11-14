// Presentation helpers for the repository's documents: every source section, command and link is kept.
// Split actual Markdown headings, never heading-like lines inside fenced code samples.
export function sectionsAt(text, level) {
  const sections = [{ title: '', heading: '', body: '' }];
  let fence = null;
  for (const line of text.match(/[^\n]*\n|[^\n]+$/g) || []) {
    const marker = line.match(/^ {0,3}(`{3,}|~{3,})/);
    if (marker) {
      if (!fence) fence = marker[1];
      else if (marker[1][0] === fence[0] && marker[1].length >= fence.length) fence = null;
      sections.at(-1).body += line;
      continue;
    }
    const heading = !fence && line.match(new RegExp(`^#{${level}} ([^\\n]+)\\n?$`));
    if (heading) sections.push({ title: heading[1], heading: line, body: '' });
    else sections.at(-1).body += line;
  }
  return sections;
}
const wrap = (css, content) => `\n<div class="${css}">\n\n${content.trim()}\n\n</div>\n`;
export function formatInstallHub(source) {
  return wrap('install-hub', sectionsAt(source, 2).map(section => section.title
    ? wrap('install-hub-card', section.heading + '\n' + downloadButtons(section.body)) : section.body).join('\n'));
}

function downloadButtons(body) {
  return body.replace(/^(?:- \[[^\]]+\]\(\/download\/[^)\s]+\)\n)+/m, (list) => {
    const links = [...list.matchAll(/- \[([^\]]+)\]\(([^)\s]+)\)/g)];
    const buttons = `<div class="download-buttons">\n${links.map(([, text, url], i) =>
      `<a class="button${i < 2 ? ' primary' : ''}" href="${url}">${text}</a>`).join('\n')}\n</div>\n`;
    return (links.some(([, , url]) => url.startsWith('/download/launcher/')) ? channelPicker() : '') + buttons;
  });
}

// The launcher's channels (website/worker/index.ts): the buttons' links name one once a script picks it
// (lib/launcher-channel.ts). Hidden until then, so without scripts the buttons keep the best channel there is.
// While there is no stable launcher (v1.0.0 is still a candidate), Stable shows as coming soon and the release
// candidate is picked: once it is out, drop `soon` and move `picked` to Stable.
export const launcherChannels = [
  { value: '', name: 'Stable', note: 'For playing.', soon: true },
  { value: 'rc', name: 'Release candidate', note: 'The next version, to try before it is stable.', picked: true },
  { value: 'nightly', name: 'Nightly', note: 'Every change, untested: it may break your saves or settings, so copy them first.' },
];

function channelPicker() {
  const picked = launcherChannels.find(c => c.picked) || launcherChannels.find(c => !c.soon);
  // (a radiogroup, not a fieldset: a legend can't line up in the row of pills)
  return `<div class="launcher-channel" role="radiogroup" aria-labelledby="launcher-channel-label" data-launcher-channel hidden>\n` +
    `<span id="launcher-channel-label">Channel</span>\n${launcherChannels.map(c =>
    `<label><input type="radio" name="launcher-channel" value="${c.value}" data-note="${c.note}"` +
    `${c === picked ? ' checked' : ''}${c.soon ? ' disabled' : ''}> ${c.name}${c.soon ? ' <small>coming soon</small>' : ''}</label>`).join('\n')}\n` +
    `<p data-launcher-channel-note>${picked.note}</p>\n</div>\n`;
}
