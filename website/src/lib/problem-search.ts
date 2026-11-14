export function problemSearchHash(query = '') {
  const value = String(query).trim().slice(0, 300);
  return value ? `#problem-search?${new URLSearchParams({ q: value })}` : '#problem-search';
}

export function readProblemSearchHash(hash) {
  const [anchor, ...rest] = hash.split('?');
  if (anchor !== '#problem-search') return null;
  const params = new URLSearchParams(rest.join('?'));
  return { query: params.has('q') ? params.get('q').slice(0, 300) : null };
}

export function prioritizeProblemSearch(board, window) {
  // Move the whole search experience, not just the input. Overview/watch updates
  // must stay below it so asynchronous feed rendering cannot push results away.
  const panel = board.querySelector('[data-search-panel]');
  if (board.firstElementChild !== panel) board.prepend(panel);
  const input = panel.querySelector('input[name="query"]');
  window.requestAnimationFrame(() => {
    if (!board.isConnected) return;
    input.focus({ preventScroll: true });
    input.scrollIntoView({ block: 'start', behavior: 'instant' });
  });
}
