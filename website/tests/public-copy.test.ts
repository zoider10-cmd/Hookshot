import test from 'node:test';
import assert from 'node:assert/strict';
import { GAME_BRANDING, publicGameText, publicProgressItem } from '../src/lib/public-copy.ts';

test('public descriptions use neutral game, platform, place and character wording', () => {
  for (const text of ['The Legend of Zelda: Ocarina of Time', 'Nintendo Switch 2', 'OoT',
    'Kokiri Forest', 'the Great Deku Tree', 'Deku Stick', 'Deku Sticks', 'Hyrule Field', 'Kakariko Village',
    'Navi waking Link', 'Navi', 'Kokiri camera turns', 'adult Link', 'Nintendo (Def)', 'Switch Pro controllers', 'the Switch', 'Auto, Switch, Xbox']) {
    assert.doesNotMatch(publicGameText(text), /zelda|ocarina|nintendo|\boot\b|kokiri|deku|hyrule|kakariko|navi|\bLink\b|\bSwitch\b/i);
  }
  assert.equal(publicGameText('Nintendo (Def)'), 'Default (A on right)');
  assert.equal(publicGameText('Windows, Linux, Vulkan, NVIDIA DLSS and AMD FSR; switch tabs.'),
    'Windows, Linux, Vulkan, NVIDIA DLSS and AMD FSR; switch tabs.');
});

test('archived world-name shorthand stays neutral without changing the specific place descriptions', () => {
  assert.equal(publicGameText('Hyrule, then Hyrule Field and Hyrule Castle'),
    'the game world, then the main outdoor area and the castle');
  assert.equal(publicGameText('hyrule'), 'the game world');
  assert.equal(publicGameText('Hyrulean'), 'Hyrulean');
});

test('activity exports neutralize title and search copy without altering source records or identifiers', () => {
  const item = { title: 'fix: OoT crashes in Kokiri Forest', originalTitle: 'fix: OoT crashes in Kokiri Forest',
    summary: 'Zelda on Nintendo Switch 2', workaround: 'Try outside Hyrule Field', labels: ['Ocarina of Time', 'Graphics'],
    id: 'pull:12', url: 'https://git.magicbean.dev/MagicBeanDev/Hookshot/pulls/12', report: { version: '3.0.0' } };
  const result = publicProgressItem(item);
  for (const text of [result.title, result.originalTitle, result.summary, result.workaround, ...result.labels]) {
    assert.doesNotMatch(text, /\boot\b|kokiri|zelda|nintendo|switch|hyrule|ocarina/i);
  }
  assert.equal(result.id, item.id);
  assert.equal(result.url, item.url);
  assert.equal(result.report, item.report);
  assert.match(item.originalTitle, /OoT/);
});

test('players\' issue titles come out with no name the site check rejects', () => {
  assert.equal(publicGameText('[AMD/Linux] Blocky shadow/light artifacts around Link when entering Zora River water'),
    '[AMD/Linux] Blocky shadow/light artifacts around Link when entering the water region water');
  assert.equal(publicGameText('Watefall to zora rivers missing textures'), 'Watefall to the water region missing textures');
  for (const text of ['Zora River', "Zora's Domain", 'Zoras', 'Goron', 'Gorons', 'Ganon', 'Ganondorf', 'Deku Nut',
    'navi', 'EPONA', 'Triforce', 'Joy-Con', 'nintendo switch 2']) {
    assert.doesNotMatch(publicGameText(text), GAME_BRANDING, text);
  }
});


test('new report titles neutralize alternate location spelling and item names', () => {
  assert.equal(publicGameText('Zora River water; Zora’s Domain'), 'the water region water; the water region');
  assert.equal(publicGameText('Deku Stick preview'), 'wooden stick preview');
});
