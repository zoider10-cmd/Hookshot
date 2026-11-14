export const beanBites = Object.freeze([
  'Slightly emotional beans.',
  'Beans with commit issues.',
  'Full of beans. Mostly.',
  'Small beans. Big feelings.',
  'One bean short of sensible.',
  'Questionable beans.',
  'Beans. Bugs. Breakthroughs.',
  'Spilling beans. Shipping builds.',
  'Big plans. Tiny beans.',
  'Bean there. Debugged that.',
]);

export function chooseBeanBite(previous, random = Math.random) {
  const choices = beanBites.filter(line => line !== previous);
  return choices[Math.floor(random() * choices.length)];
}

export function refreshBeanBite(element, window, random = Math.random) {
  if (!element) return;
  let previous = element.textContent;
  try { previous = window.sessionStorage.getItem('hookshot-bean-bite') || previous; } catch { /* Storage is optional. */ }
  const next = chooseBeanBite(previous, random);
  element.textContent = next;
  try { window.sessionStorage.setItem('hookshot-bean-bite', next); } catch { /* Keep the visible line without storage. */ }
}
