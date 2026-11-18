// Starlight tables and code blocks scroll on narrow screens. Keep those surfaces
// keyboard reachable without JavaScript; the client removes tab stops when they fit.
interface HtmlNode {
  type: string;
  value?: string;
  tagName?: string;
  properties?: Record<string, unknown>;
  children?: HtmlNode[];
}

export function rehypeKeyboardScroll() {
  return (tree: HtmlNode) => {
    let heading = '';
    const text = (node: HtmlNode): string => node.value || node.children?.map(text).join('') || '';
    function visit(node: HtmlNode) {
      if (node.type === 'element' && /^h[1-6]$/.test(node.tagName || '')) heading = text(node).trim();
      if (node.type === 'element' && (node.tagName === 'table' || node.tagName === 'pre')) {
        node.properties = { ...node.properties, tabIndex: 0 };
        if (!node.properties.ariaLabel && !node.properties.ariaLabelledBy) {
          const kind = node.tagName === 'table' ? 'data table' : 'code example';
          const label = heading ? `${heading} — ${kind}` : `Scrollable ${kind}`;
          node.properties.ariaLabel = label;
          node.properties['data-scroll-label'] = label;
        }
      }
      node.children?.forEach(visit);
    }
    visit(tree);
  };
}

/** Keep native table semantics; only overflow creates an additional keyboard stop. */
export function updateScrollSurface(node: HTMLElement) {
  const overflows = node.scrollWidth > node.clientWidth + 1;
  if (overflows) {
    node.setAttribute('tabindex', '0');
    if (!node.hasAttribute('aria-label') && !node.hasAttribute('aria-labelledby')) {
      const label = node.getAttribute('data-scroll-label') || (node.tagName === 'TABLE' ? 'Scrollable data table' : 'Scrollable code example');
      node.setAttribute('aria-label', label);
      node.setAttribute('data-scroll-label', label);
    }
  } else {
    node.removeAttribute('tabindex');
    const generated = node.getAttribute('data-scroll-label');
    if (generated && node.getAttribute('aria-label') === generated) node.removeAttribute('aria-label');
  }
}

export function installKeyboardScroll(document: Document) {
  const surfaces = [...document.querySelectorAll<HTMLElement>('.sl-markdown-content table, .sl-markdown-content pre')];
  const observer = new ResizeObserver(entries => entries.forEach(entry => updateScrollSurface(entry.target as HTMLElement)));
  for (const node of surfaces) { updateScrollSurface(node); observer.observe(node); }
  void document.fonts.ready.then(() => surfaces.forEach(updateScrollSurface));
}
