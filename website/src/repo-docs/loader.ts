// Starlight's docs collection: the pages in src/content/docs, plus the repository's own documents (content-pages.ts)
// rendered straight from their files. Nothing is written to disk; dev watches edits, additions and removals.
import type { Loader, LoaderContext } from 'astro/loaders';
import { docsLoader } from '@astrojs/starlight/loaders';
import { contentPages } from '../content-pages.ts';
import { isSourceFile, renderPage, sourceFiles, testedFragmentsPath } from './pages.ts';

async function loadRepoPages(context: LoaderContext) {
  for (const slug of Object.keys(contentPages)) {
    const { markdown, ...frontmatter } = await renderPage(slug);
    const data = await context.parseData({ id: slug, data: frontmatter });
    context.store.set({ id: slug, data, body: markdown, rendered: await context.renderMarkdown(markdown),
      digest: context.generateDigest(markdown) });
  }
}

export function hookshotDocsLoader(): Loader {
  const docs = docsLoader();
  return {
    name: 'hookshot-docs',
    async load(context) {
      await docs.load(context);
      await loadRepoPages(context);
      if (!context.watcher) return;
      context.watcher.add([...sourceFiles, testedFragmentsPath]);
      for (const event of ['add', 'change', 'unlink'] as const) {
        context.watcher.on(event, async (file) => {
          if (isSourceFile(file)) await loadRepoPages(context);
        });
      }
    },
  };
}
