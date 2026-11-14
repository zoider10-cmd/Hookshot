import { defineCollection } from 'astro:content';
import { docsSchema, i18nSchema } from '@astrojs/starlight/schema';
import { i18nLoader } from '@astrojs/starlight/loaders';
import { hookshotDocsLoader } from './repo-docs/loader.ts';

export const collections = {
  docs: defineCollection({ loader: hookshotDocsLoader(), schema: docsSchema() }),
  // Starlight's interface wording, where ours differs from its default.
  i18n: defineCollection({ loader: i18nLoader(), schema: i18nSchema() }),
};
