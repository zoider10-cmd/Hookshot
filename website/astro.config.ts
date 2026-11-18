import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import { unified } from '@astrojs/markdown-remark';
import { repository, siteUrl, editUrl } from './src/site.ts';
import { repoAssets } from './src/repo-docs/assets.ts';
import { remarkTestedConfigurations } from './src/repo-docs/tested-configurations.ts';
import { rehypeKeyboardScroll } from './src/repo-docs/keyboard-scroll.ts';

export default defineConfig({
  site: siteUrl,
  trailingSlash: 'always',
  markdown: { processor: unified({ remarkPlugins: [remarkTestedConfigurations], rehypePlugins: [rehypeKeyboardScroll] }) },
  integrations: [repoAssets(), starlight({
    expressiveCode: { plugins: [{
      name: 'Keyboard scroll fallback',
      hooks: {
        // Expressive Code replaces the original pre after the Markdown plugins.
        postprocessRenderedBlock: ({ renderData }) => rehypeKeyboardScroll()(renderData.blockAst),
      },
    }] },
    title: 'Hookshot',
    description: 'Hookshot by Team MagicBean. Guides, project updates, and practical help for your PC adventure.',
    favicon: '/branding/hookshot.png',
    customCss: ['./src/styles/theme.css', './src/styles/content.css'],
    components: {
      Header: './src/components/Header.astro',
      Sidebar: './src/components/Sidebar.astro',
      Hero: './src/components/HookshotHero.astro',
      Footer: './src/components/Footer.astro',
    },
    editLink: { baseUrl: editUrl('website/') },
    tableOfContents: { minHeadingLevel: 2, maxHeadingLevel: 2 },
    sidebar: [
      { label: 'Get started', items: [
        { label: 'Install', slug: 'install' },
        { label: 'Steam Deck', slug: 'install/steam-deck' },
        { label: 'System requirements', slug: 'requirements' },
        { label: 'Settings', slug: 'settings' },
        { label: 'Updates & saves', slug: 'saves' },
        { label: 'Transfer a save', slug: 'saves/transfer' },
        { label: 'Mods', slug: 'mods' },
      ] },
      { label: 'Help', items: [
        { label: 'Common problems', slug: 'help' },
        { label: 'Report a problem', slug: 'help/report' },
        { label: 'Report slow performance', slug: 'help/performance' },
        { label: 'Antivirus warnings', slug: 'help/antivirus' },
      ] },
      { label: 'Development', items: [
        { label: 'Progress', slug: 'progress' },
        { label: 'Contributing', slug: 'contributing' },
        { label: 'Help test (Test Farm) ↗', link: 'https://beanstalk.magicbean.dev/how' },
        { label: 'Scrub a save', slug: 'saves/scrub' },
        { label: 'Source code ↗', link: repository },
      ] },
      { label: 'About', items: [
        { label: 'About Hookshot', slug: 'about' },
        { label: 'Team MagicBean', slug: 'about/team' },
      ] },
    ],
  })],
});
