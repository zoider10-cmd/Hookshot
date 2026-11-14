// The artwork the site shows lives in the repository's assets/ (with its provenance); this copies it into public/
// (ignored by Git) when Astro starts, for dev and build alike, unchanged.
import { copyFile, mkdir } from 'node:fs/promises';
import path from 'node:path';
import type { AstroIntegration } from 'astro';
import { repoRoot } from './pages.ts';

const files = {
  'assets/hookshot.png': 'assets/hookshot.png',
  ...Object.fromEntries(['hookshot.png', 'teary-elf-bean.png', 'grappling-hook-bean.png', 'glowing-fairy-bean.png',
    'magicbean-green.png', 'magicbean-red.png', 'magicbean-blue.png', 'magicbean-team-logo.webp', 'PROVENANCE.txt']
    .map((name) => [`assets/branding/${name}`, `branding/${name}`])),
};

export function repoAssets(): AstroIntegration {
  return {
    name: 'hookshot-repo-assets',
    hooks: {
      'astro:config:setup': async ({ config }) => {
        for (const [from, to] of Object.entries(files)) {
          const target = path.join(new URL(config.publicDir).pathname, to);
          await mkdir(path.dirname(target), { recursive: true });
          await copyFile(path.join(repoRoot, from), target);
        }
      },
    },
  };
}
