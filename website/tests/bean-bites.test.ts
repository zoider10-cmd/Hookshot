import test from 'node:test';
import assert from 'node:assert/strict';
import { beanBites, chooseBeanBite, refreshBeanBite } from '../src/lib/bean-bites.ts';

test('ten short bean lines are reachable and never immediately repeat the previous one', () => {
  assert.equal(new Set(beanBites).size, 10);
  assert(beanBites.every(line => /bean/i.test(line) && line.length <= 34));
  for (const previous of beanBites) {
    const choices = Array.from({ length: 9 }, (_, i) => chooseBeanBite(previous, () => (i + .5) / 9));
    assert.equal(new Set(choices).size, 9);
    assert(!choices.includes(previous));
  }
});

test('reloads use the stored previous line, not the static fallback', () => {
  let stored = null;
  const window = { sessionStorage: { getItem: () => stored, setItem: (_, value) => { stored = value; } } };
  const element = { textContent: beanBites[0] };
  refreshBeanBite(element, window, () => 0);
  const first = element.textContent;
  assert.equal(stored, first);
  element.textContent = beanBites[0]; // Static HTML on the next page load.
  refreshBeanBite(element, window, () => 0);
  assert.notEqual(element.textContent, first);
});

test('blocked storage does not throw during hero initialization', () => {
  const window = { get sessionStorage() { throw new Error('Storage blocked'); } };
  const element = { textContent: beanBites[0] };
  assert.doesNotThrow(() => refreshBeanBite(element, window, () => 0));
  assert(beanBites.includes(element.textContent));
  assert.doesNotThrow(() => refreshBeanBite(null, window));
});
