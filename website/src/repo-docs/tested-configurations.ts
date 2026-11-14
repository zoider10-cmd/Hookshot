// The local fragment format also belongs to scripts/tested_configurations.py. Keep both readers in step.
import { readFile, readdir } from 'node:fs/promises';
import path from 'node:path';
import { publicGameText } from '../lib/public-copy.ts';

export const runHeader = '| Date | Build | OS / desktop | GPU / driver | CPU / RAM | Settings | Where | Result |';
export const runSeparator = '|---|---|---|---|---|---|---|---|';
export const fragmentsMarker = '<!-- tested-run-fragments -->';
export const fragmentDirectory = 'docs/tested';
export const publicTestedRunsMarker = '<!-- hookshot-tested-configurations-public-copy -->';

interface RunFragment { name: string; text: string }
type PresentRun = (row: string, source: string) => string;

function rowCells(row: string, source: string): string[] {
  const parts: string[] = [];
  let start = 0, slashes = 0;
  for (let i = 0; i < row.length; i++) {
    if (row[i] === '|' && slashes % 2 === 0) {
      parts.push(row.slice(start, i).trim());
      start = i + 1;
    }
    slashes = row[i] === '\\' ? slashes + 1 : 0;
  }
  parts.push(row.slice(start).trim());
  if (parts.length !== 10 || parts[0] || parts.at(-1) || parts.slice(1, -1).some(cell => !cell)) {
    throw new Error(`${source}: expected eight non-empty cells between pipes (escape a literal pipe as \\|)`);
  }
  return parts.slice(1, -1);
}

const rowKey = (cells: string[]) => JSON.stringify(cells.map(cell => cell.replace(/\s+/g, ' ').trim()));

/** Validate original row text before optional website presentation; the default view keeps it verbatim. */
export function assembleTestedConfigurations(source: string, fragments: readonly RunFragment[], presentRow?: PresentRun): string {
  const parts = source.split(fragmentsMarker);
  if (parts.length !== 2 || (parts[0] && !parts[0].endsWith('\n')) || !parts[1].startsWith('\n')) {
    throw new Error('tested configurations: expected one standalone tested-run-fragments marker');
  }
  const [prefix, frozen] = parts;
  if (!/^\n+## Earlier runs \(frozen\)\n/.test(frozen)) {
    throw new Error('tested configurations: marker must precede Earlier runs (frozen)');
  }
  const lines = frozen.split('\n');
  const header = lines.indexOf(runHeader);
  const limits = lines.flatMap((line, i) => /^## Limits(?:\s|$)/.test(line) ? [i] : []);
  if (header < 0 || header !== lines.lastIndexOf(runHeader) || lines[header + 1] !== runSeparator ||
      lines.filter(line => line === runSeparator).length !== 1 || limits.length !== 1 || limits[0] <= header + 2) {
    throw new Error('tested configurations: expected one standard frozen table followed by its Limits section');
  }
  const tableEnd = lines.findIndex((line, i) => i > header + 1 && !line.trim());
  if (tableEnd < 0 || tableEnd >= limits[0] || lines.slice(tableEnd, limits[0]).some(line => line.trim())) {
    throw new Error('tested configurations: frozen rows must be contiguous, with a blank line before Limits');
  }
  const oldRows = lines.slice(header + 2, tableEnd);
  if (!oldRows.length) throw new Error('tested configurations: frozen table has no rows');
  // Historical duplicates and relative references stay in their original order, without an allowlist.
  const seen = new Set(oldRows.map(row => rowKey(rowCells(row, 'Earlier runs (frozen)'))));
  const rows: string[] = [];
  for (const { name, text } of [...fragments].sort((a, b) => a.name < b.name ? 1 : a.name > b.name ? -1 : 0)) {
    const match = /^(\d{4}-\d{2}-\d{2})-[a-z0-9]+(?:-[a-z0-9]+){2,}\.md$/.exec(name);
    if (!match) throw new Error(`${name}: filename must be YYYY-MM-DD-topic-tester-run.md`);
    const fragmentLines = (text.endsWith('\n') ? text.slice(0, -1) : text).split('\n');
    if (text.includes('\r') || fragmentLines.length !== 3 || fragmentLines[0] !== runHeader || fragmentLines[1] !== runSeparator) {
      throw new Error(`${name}: expected the standard header, separator and exactly one row, with LF line endings`);
    }
    const row = fragmentLines[2];
    const cells = rowCells(row, name);
    const date = /^(\d{4}-\d{2}-\d{2})(?: UTC)?$/.exec(cells[0])?.[1];
    const parsed = date ? new Date(`${date}T00:00:00Z`) : new Date(NaN);
    if (!date || date.startsWith('0000') || !Number.isFinite(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== date) {
      throw new Error(`${name}: date must be an ISO calendar date, optionally followed by UTC`);
    }
    if (date !== match[1]) throw new Error(`${name}: filename must match the row's date`);
    if (cells.some(cell => /\b(?:as\s+above|same\s+host|ditto)\b/i.test(cell))) {
      throw new Error(`${name}: new rows must stand alone, without as above, same host or ditto references`);
    }
    const key = rowKey(cells);
    if (seen.has(key)) throw new Error(`${name}: duplicate row`);
    seen.add(key);
    rows.push(presentRow ? presentRow(row, `${fragmentDirectory}/${name}`) : row);
  }
  const newest = rows.length ? [runHeader, runSeparator, ...rows].join('\n') : 'No new run fragments yet.';
  return prefix + '## New runs\n\n' + newest + frozen;
}

/** Only direct Markdown fragments are data; README.md is the tracked landing page. */
export async function readTestedConfigurations(source: string, directory: string, presentRow?: PresentRun): Promise<string> {
  const names = (await readdir(directory)).filter(name => name.endsWith('.md') && name !== 'README.md');
  const fragments: RunFragment[] = [];
  for (const name of names) fragments.push({ name, text: await readFile(path.join(directory, name), 'utf8') });
  return assembleTestedConfigurations(source, fragments, presentRow);
}

type MarkdownNode = { type: string; value?: string; url?: string; children?: MarkdownNode[] };

/** Page-scoped prose policy, inside Astro's single render so heading metadata is kept. */
export function remarkTestedConfigurations() {
  return (tree: MarkdownNode) => {
    const marker = tree.children?.findIndex(node => node.type === 'html' && node.value === publicTestedRunsMarker) ?? -1;
    if (marker < 0) return;
    tree.children!.splice(marker, 1);
    function neutralize(node: MarkdownNode) {
      // An autolink displays its URL; it is not descriptive prose.
      if (node.type === 'link' && node.children?.length === 1 && node.children[0].value === node.url) return;
      if (node.type === 'text' && node.value) node.value = publicGameText(node.value);
      for (const child of node.children || []) neutralize(child);
    }
    neutralize(tree);
  };
}
