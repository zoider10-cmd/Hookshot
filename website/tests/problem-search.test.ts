import test from 'node:test';
import assert from 'node:assert/strict';
import { problemSearchHash, readProblemSearchHash, prioritizeProblemSearch } from '../src/lib/problem-search.ts';
import { readFile } from 'node:fs/promises';
test('front-page search round trips special characters inside the fragment', () => {
  const query = 'black screen & controller #123 / café?';
  const url = new URL('https://example.com/Hookshot/progress/');
  url.hash = problemSearchHash(query);
  assert.equal(url.search, '');
  assert.equal(readProblemSearchHash(url.hash).query, query);
});
test('plain header links preserve the existing query; other anchors do not activate search', () => {
  assert.deepEqual(readProblemSearchHash('#problem-search'), { query: null });
  assert.equal(readProblemSearchHash('#development'), null);
  assert.equal(problemSearchHash('  '), '#problem-search');
});
test('shared queries are bounded and treat markup as plain text', () => {
  assert.equal(readProblemSearchHash(problemSearchHash('x'.repeat(400))).query.length, 300);
  assert.equal(readProblemSearchHash(problemSearchHash('<script>')).query, '<script>');
});

test('search navigation puts input and results before asynchronously growing overview content', () => {
  const actions = [];
  const input = { focus: options => actions.push(['focus', options]), scrollIntoView: options => actions.push(['scroll', options]) };
  const panel = { querySelector: () => input };
  const overview = {}, watch = {};
  const board = {
    isConnected: true,
    children: [overview, watch, panel],
    get firstElementChild() { return this.children[0]; },
    querySelector: () => panel,
    prepend(node) { this.children = [node, ...this.children.filter(child => child !== node)]; },
  };
  const frames = [];
  const window = { requestAnimationFrame: fn => frames.push(fn) };
  prioritizeProblemSearch(board, window);
  assert.equal(board.firstElementChild, panel);
  assert.equal(actions.length, 0, 'wait for the new layout before positioning');
  // Loading the feed can now expand these sections only below the search panel.
  overview.content = 'Loaded development totals';
  watch.content = 'Loaded version reports';
  frames.shift()();
  assert.deepEqual(actions, [['focus', { preventScroll: true }], ['scroll', { block: 'start', behavior: 'instant' }]]);
  prioritizeProblemSearch(board, window);
  assert.deepEqual(board.children, [panel, overview, watch], 'repeat navigation must not duplicate or reorder other sections');
  board.isConnected = false;
  frames.shift()();
  assert.equal(actions.length, 2, 'do not move focus after leaving the page');
});

test('the movable search panel contains its form, feedback, results and pagination', async () => {
  const source = await readFile(new URL('../src/components/ProgressBoard.astro', import.meta.url), 'utf8');
  const panel = source.match(/<section data-search-panel\b[\s\S]*?<\/section>/)?.[0];
  assert(panel);
  for (const marker of ['id="problem-search"', 'data-results', 'data-count', 'data-more', 'data-warning', 'data-freshness']) {
    assert(panel.includes(marker), `Search panel must include ${marker}`);
  }
});
