import test from 'node:test';
import assert from 'node:assert/strict';
import { progressRequest } from '../src/lib/progress-request.ts';

const url = 'https://git.magicbean.dev/api/v1/repos/MagicBeanDev/Hookshot/issues';
const ok = () => new Response('{"ok":true}');

test('transient HTTP failures back off, honor bounded Retry-After and use fresh timeout signals', async () => {
  const signals = [], waits = [];
  let calls = 0;
  const result = await progressRequest(url, { headers: { Authorization: 'Bearer test-only' },
    wait: async ms => { waits.push(ms); }, fetcher: async (target, options) => {
      assert.equal(target, url);
      assert.equal(options.redirect, 'error');
      assert.equal(options.headers.Authorization, 'Bearer test-only');
      signals.push(options.signal);
      calls++;
      return calls === 1 ? new Response('', { status: 503 }) : calls === 2 ?
        new Response('', { status: 429, headers: { 'Retry-After': '120' } }) : ok();
    } });
  assert.deepEqual(result.data, { ok: true });
  assert.equal(calls, 3);
  assert.equal(new Set(signals).size, 3);
  assert.deepEqual(waits, [1000, 30000]);
});

test('timeouts and connection resets recover, including timeouts while reading the body', async () => {
  for (const failure of ['timeout', 'network', 'body']) {
    let calls = 0;
    const result = await progressRequest(url, { wait: async () => {}, fetcher: async () => {
      if (++calls > 1) return ok();
      if (failure === 'timeout') throw new DOMException('timed out', 'TimeoutError');
      if (failure === 'network') throw new TypeError('fetch failed', { cause: { code: 'ECONNRESET' } });
      return { ok: true, headers: new Headers(), json: async () => { throw new DOMException('body aborted', 'AbortError'); } };
    } });
    assert.deepEqual(result.data, { ok: true });
    assert.equal(calls, 2);
  }
});

test('persistent transient failures stop after three attempts with endpoint diagnostics', async () => {
  let calls = 0;
  await assert.rejects(progressRequest(url, { wait: async () => {}, fetcher: async () => {
    calls++;
    return new Response('not logged', { status: 503 });
  } }), /\/Hookshot\/issues, HTTP 503 \(attempt 3\/3\)/);
  assert.equal(calls, 3);
});

test('authentication, missing resources, redirects, TLS errors and invalid JSON fail without retries', async () => {
  for (const failure of [401, 403, 404, 302, 'tls', 'json']) {
    let calls = 0;
    await assert.rejects(progressRequest(url, { wait: async () => assert.fail('must not retry'), fetcher: async () => {
      calls++;
      if (failure === 'tls') throw new TypeError('fetch failed', { cause: { code: 'CERT_HAS_EXPIRED' } });
      return failure === 'json' ? new Response('invalid json') : new Response('', { status: failure });
    } }));
    assert.equal(calls, 1);
  }
  const result = await progressRequest(url, { allowNotFound: true, fetcher: async () => new Response('', { status: 404 }) });
  assert.equal(result.data, null);
});
