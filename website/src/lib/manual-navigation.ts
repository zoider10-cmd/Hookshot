export function revealManualTarget(target) {
  if (!target) return;
  for (let parent = target.parentElement; parent; parent = parent.parentElement) {
    if (parent.tagName === 'DETAILS') parent.open = true;
  }
}

export function installManualNavigation(document, window) {
  const guide = document.querySelector('.manual-guide');
  if (!guide) return;
  const revealHash = (hash, scroll = false) => {
    let id;
    try { id = decodeURIComponent(hash.slice(1)); } catch { return; }
    const target = document.getElementById(id);
    if (!target || !guide.contains(target)) return;
    revealManualTarget(target);
    if (scroll) window.requestAnimationFrame(() => target.scrollIntoView());
  };
  revealHash(window.location.hash, true);
  window.addEventListener('hashchange', () => revealHash(window.location.hash, true));
  document.addEventListener('click', event => {
    const link = event.target.closest?.('a[href]');
    if (!link) return;
    const url = new URL(link.href, window.location.href);
    if (url.origin === window.location.origin && url.pathname === window.location.pathname && url.hash) revealHash(url.hash, true);
  });
  let beforePrint;
  window.addEventListener('beforeprint', () => {
    beforePrint = [...guide.querySelectorAll('details')].map(details => [details, details.open]);
    guide.querySelectorAll('details').forEach(details => { details.open = true; });
  });
  window.addEventListener('afterprint', () => beforePrint?.forEach(([details, open]) => { details.open = open; }));
}
