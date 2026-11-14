export function progressOverview(feed) {
  // Anchor the window to the collection time so stale data never looks like a live weekly counter.
  const since = Date.parse(feed.generatedAt) - 7 * 86400000;
  const recent = value => value && Date.parse(value) >= since && Date.parse(value) <= Date.parse(feed.generatedAt);
  return [
    { title: 'Open reports', count: feed.items.filter(i => i.kind === 'issue' && ['reported', 'working'].includes(i.status)).length,
      text: 'Problems and questions still open. They may overlap or need confirmation.' },
    { title: 'Changes awaiting review', count: feed.items.filter(i => i.kind === 'pull' && i.status === 'proposed').length,
      text: 'Submitted proposals that are not drafts. Review may not have started yet.' },
    { title: 'Accepted in the past 7 days', count: feed.items.filter(i => i.kind === 'pull' && i.status === 'merged' && recent(i.mergedAt)).length,
      text: 'Merged into their target branches. This does not establish release availability.' },
    { title: 'Stable releases in the past 7 days', count: feed.items.filter(i => i.status === 'released' && recent(i.publishedAt)).length,
      text: 'Published stable versions in this feed. Preview releases are listed separately below.' },
  ];
}
