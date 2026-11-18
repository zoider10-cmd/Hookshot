import test from 'node:test';
import assert from 'node:assert/strict';
import { rehypeKeyboardScroll, updateScrollSurface } from '../src/repo-docs/keyboard-scroll.ts';

test('keyboard stops follow actual overflow and preserve table semantics', () => {
  const attrs = new Map();
  const node = { tagName: 'TABLE', scrollWidth: 600, clientWidth: 320,
    setAttribute: (k, v) => attrs.set(k, v), removeAttribute: k => attrs.delete(k), hasAttribute: k => attrs.has(k), getAttribute: k => attrs.get(k) };
  updateScrollSurface(node);
  assert.equal(attrs.get('tabindex'), '0');
  assert.equal(attrs.get('aria-label'), 'Scrollable data table');
  assert.equal(attrs.has('role'), false);
  node.clientWidth = 800; updateScrollSurface(node);
  assert.equal(attrs.has('tabindex'), false);
  assert.equal(attrs.has('aria-label'), false);
  attrs.set('aria-label', 'Save locations');
  node.clientWidth = 320; updateScrollSurface(node);
  assert.equal(attrs.get('aria-label'), 'Save locations');
  assert.equal(attrs.get('tabindex'), '0');
});


test('generated scroll labels use the section and preserve author labels', () => {
  const table = { type: 'element', tagName: 'table', properties: {}, children: [] };
  const named = { type: 'element', tagName: 'pre', properties: { ariaLabel: 'Copy this command' } };
  const referenced = { type: 'element', tagName: 'table', properties: { ariaLabelledBy: 'save-paths' } };
  const tree = { type: 'root', children: [
    { type: 'element', tagName: 'h2', children: [{ type: 'text', value: 'Save locations' }] }, table, named, referenced,
  ] };
  rehypeKeyboardScroll()(tree);
  assert.equal(table.properties.ariaLabel, 'Save locations — data table');
  assert.equal(table.properties['data-scroll-label'], 'Save locations — data table');
  assert.equal(named.properties.ariaLabel, 'Copy this command');
  assert.equal(named.properties['data-scroll-label'], undefined);
  assert.equal(referenced.properties.ariaLabel, undefined);
});
