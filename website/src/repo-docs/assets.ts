// The artwork the site shows lives in the repository's assets/ (with its provenance); this copies it into public/
// (ignored by Git) when Astro starts, for dev and build alike, unchanged.
import { copyFile, mkdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import type { AstroIntegration } from 'astro';
import guideManifest from '../../../docs/images/guide/manifest.json' with { type: 'json' };

const repoRoot = path.resolve('..');

export const repositoryAssets = {
  'assets/hookshot.png': 'assets/hookshot.png',
  ...Object.fromEntries(guideManifest.screenshots.map(({ file }) => {
    const source = `docs/images/guide/${file}`;
    return [source, source];
  })),
  ...Object.fromEntries(['hookshot.png', 'teary-elf-bean.png', 'grappling-hook-bean.png', 'glowing-fairy-bean.png',
    'magicbean-green.png', 'magicbean-red.png', 'magicbean-blue.png', 'magicbean-team-logo.webp', 'PROVENANCE.txt']
    .map((name) => [`assets/branding/${name}`, `branding/${name}`])),
};

export function repoAssets(): AstroIntegration {
  return {
    name: 'hookshot-repo-assets',
    hooks: {
      'astro:config:setup': async ({ config }) => {
        for (const [from, to] of Object.entries(repositoryAssets)) {
          const target = path.join(fileURLToPath(config.publicDir), to);
          await mkdir(path.dirname(target), { recursive: true });
          await copyFile(path.join(repoRoot, from), target);
        }
      },
    },
  };
}
