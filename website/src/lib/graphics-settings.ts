export function matchesSetting(text, query) {
  const normalized = text.toLocaleLowerCase().replace(/\s+/g, ' ');
  return query.trim().toLocaleLowerCase().split(/\s+/).every(word => normalized.includes(word));
}

export function installGraphicsSettings(document, window) {
  const root = document.querySelector('[data-graphics-settings]');
  if (!root) return;
  const form = root.querySelector('form');
  const query = form.elements.namedItem('query');
  const group = form.elements.namedItem('group');
  const groups = [...root.querySelectorAll('[data-settings-group]')];
  const cards = [...root.querySelectorAll('[data-setting]')];
  const text = new Map(cards.map(card => [card, card.textContent]));
  const count = root.querySelector('[data-settings-count]');
  const empty = root.querySelector('[data-settings-empty]');
  // (a row whose choices are short shows them; a longer one folds them into a disclosure)
  const details = card => card.querySelector('details');
  const setOpen = (card, open) => { const d = details(card); if (d) d.open = open; };
  let savedOpen;
  const update = () => {
    const filtering = Boolean(query.value.trim() || group.value);
    if (filtering && !savedOpen) savedOpen = new Map(cards.map(card => [card, Boolean(details(card)?.open)]));
    let visible = 0;
    for (const section of groups) {
      let sectionCount = 0;
      for (const card of section.querySelectorAll('[data-setting]')) {
        card.hidden = Boolean(group.value && group.value !== section.dataset.settingsGroup) || !matchesSetting(text.get(card), query.value);
        if (!card.hidden) { visible++; sectionCount++; }
        if (filtering) setOpen(card, !card.hidden);
        else if (savedOpen) setOpen(card, savedOpen.get(card));
      }
      section.hidden = sectionCount === 0;
    }
    if (!filtering) savedOpen = undefined;
    count.textContent = filtering ? `${visible} of ${cards.length} settings shown.` : `${cards.length} settings.`;
    empty.hidden = visible !== 0;
  };
  form.hidden = false;
  form.addEventListener('submit', event => event.preventDefault());
  form.addEventListener('input', update);
  form.addEventListener('change', update);
  form.addEventListener('reset', () => { query.value = ''; group.value = ''; update(); });
  const revealHash = () => {
    let id;
    try { id = decodeURIComponent(window.location.hash.slice(1)); } catch { return; }
    const target = document.getElementById(id);
    if (!target || !root.contains(target)) return;
    form.reset();
    target.closest('[data-setting]')?.querySelector('details')?.setAttribute('open', '');
    window.requestAnimationFrame(() => target.scrollIntoView());
  };
  window.addEventListener('hashchange', revealHash);
  root.addEventListener('click', event => {
    const link = event.target.closest?.('a[href]');
    if (!link) return;
    const url = new URL(link.href, window.location.href);
    if (url.origin === window.location.origin && url.pathname === window.location.pathname && url.hash === window.location.hash) revealHash();
  });
  update();
  revealHash();
  let printState;
  window.addEventListener('beforeprint', () => {
    printState = { query: query.value, group: group.value, savedOpen, open: cards.map(card => Boolean(details(card)?.open)) };
    form.reset();
    cards.forEach(card => setOpen(card, true));
  });
  window.addEventListener('afterprint', () => {
    if (!printState) return;
    query.value = printState.query; group.value = printState.group;
    update();
    cards.forEach((card, i) => setOpen(card, printState.open[i]));
    savedOpen = printState.savedOpen;
    printState = undefined;
  });
}
