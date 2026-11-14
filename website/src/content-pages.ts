// The pages published from the repository's own documents: the site path, then the file it is made from.
// Only these are published; other notes stay on Forgejo until they are added here.
export const contentPages: Record<string, string> = {
  'install': 'docs/getting-started.md',
  'settings': 'docs/graphics-and-controls.md',
  'tested-configurations': 'docs/tested-configurations.md',
  'saves': 'docs/updates-and-saves.md',
  'saves/transfer': 'docs/saves.md',
  'help': 'docs/common-issues.md',
  'help/report': 'docs/reporting-and-contributing.md',
  'contributing': 'CONTRIBUTING.md',
};

// The other way round, for rewriting a document's links to other published documents. docs/README.md is the docs
// folder's index: a link to it goes to the site's front page.
export const pageForSource = new Map<string, string>([
  ...Object.entries(contentPages).map(([page, source]): [string, string] => [source, page]),
  ['docs/README.md', ''],
]);
