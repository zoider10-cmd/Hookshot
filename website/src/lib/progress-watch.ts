// Deliberately narrow: “latest”, log build hashes, ranges and prose are not exact version evidence.
export function exactVersion(value) {
  if (typeof value !== 'string') return null;
  const match = value.trim().replace(/^`([^`]+)`$/, '$1').match(/^v?((?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?)$/);
  return match?.[1] || null;
}

function formField(body, name) {
  if (typeof body !== 'string') return '';
  const blocks = body.split(/^### /m);
  const matches = blocks.filter(b => b.split(/\r?\n/, 1)[0].trim() === name);
  return matches.length === 1 ? matches[0].slice(matches[0].indexOf('\n') + 1).split(/^#{1,6} /m)[0].trim() : '';
}

export function reportEvidence(body) {
  const game = exactVersion(formField(body, 'Hookshot version'));
  const builderField = formField(body, 'Builder version');
  const installField = formField(body, 'Version');
  const builder = builderField && installField ? null : exactVersion(builderField || installField);
  const version = (builderField && installField) || (game && builder && game !== builder) ? null : game || builder;
  const kind = formField(body, 'What kind of problem');
  const areas = {
    'Graphics (missing, black or wrong-coloured things, lighting, flicker)': 'Graphics',
    'Crash, freeze or black screen': 'Crashes or startup',
    'Low fps or stutter': 'Performance',
    'Sound': 'Audio',
    'Controls': 'Controls',
    'Sound, controls or saves': 'Sound, controls or saves',
  };
  return { version, versionSource: version ? game ? 'Hookshot version field' : installField ? 'Installation version field' : 'Builder version field' : null,
    reportedArea: areas[kind] || (builder ? 'Setup' : 'Unspecified') };
}

export function currentVersionWatch(feed) {
  const stable = feed.stableRelease;
  const version = exactVersion(stable?.tag);
  const open = feed.items.filter(i => i.kind === 'issue' && ['reported', 'working'].includes(i.status) &&
    !i.labels.some(l => ['duplicate', 'invalid', 'question'].includes(l.toLowerCase())));
  const current = version ? open.filter(i => i.report.version === version) : [];
  const groups = new Map();
  for (const item of current) {
    const area = item.area !== 'Unspecified' ? item.area : item.report.reportedArea;
    if (!groups.has(area)) groups.set(area, []);
    groups.get(area).push(item);
  }
  return { stable, version, current,
    other: version ? open.filter(i => i.report.version && i.report.version !== version).length : 0,
    unknown: open.filter(i => !i.report.version).length,
    groups: [...groups.entries()].map(([area, items]) => ({ area, items })).sort((a, b) => b.items.length - a.items.length || a.area.localeCompare(b.area)),
    important: current.filter(i => i.impact).sort((a, b) => a.number - b.number),
  };
}
