import { setTimeout as delay } from 'node:timers/promises';

const retryStatuses = new Set([408, 429, 500, 502, 503, 504]);
const retryCodes = new Set(['ECONNRESET', 'ECONNREFUSED', 'ETIMEDOUT', 'EAI_AGAIN',
  'UND_ERR_CONNECT_TIMEOUT', 'UND_ERR_HEADERS_TIMEOUT', 'UND_ERR_BODY_TIMEOUT', 'UND_ERR_SOCKET']);

// Build-time GETs only. Read the body inside the timeout/retry boundary too: receiving headers is not success.
export async function progressRequest(url, { fetcher = fetch, headers = {}, allowNotFound = false,
  wait = delay } = {}) {
  const endpoint = new URL(url).pathname;
  for (let attempt = 1; attempt <= 3; attempt++) {
    let response;
    let failure;
    let retry = false;
    try {
      response = await fetcher(url, { headers, signal: AbortSignal.timeout(30000), redirect: 'error' });
      if (allowNotFound && response.status === 404) {
        await response.body?.cancel();
        return { data: null, headers: response.headers };
      }
      if (response.ok) return { data: await response.json(), headers: response.headers };
      failure = `HTTP ${response.status}`;
      retry = retryStatuses.has(response.status);
      await response.body?.cancel();
    } catch (error) {
      retry = error.name === 'TimeoutError' || error.name === 'AbortError' ||
        retryCodes.has(error.code) || retryCodes.has(error.cause?.code);
      // Do not log response bodies, headers or credentials from an upstream error.
      failure = error.name === 'SyntaxError' ? 'invalid JSON' : error.name || 'request failed';
    }
    if (!retry || attempt === 3) {
      throw new Error(`Forgejo progress request failed: ${endpoint}, ${failure} (attempt ${attempt}/3).`);
    }
    const retryAfter = response?.headers.get('retry-after');
    const requested = retryAfter && (/^\d+$/.test(retryAfter) ? Number(retryAfter) * 1000 : Date.parse(retryAfter) - Date.now());
    const pause = Math.min(30000, Math.max(attempt * 1000, Number.isFinite(requested) ? requested : 0));
    console.warn(`Retrying Forgejo progress request: ${endpoint}, ${failure} (attempt ${attempt}/3).`);
    await wait(pause);
  }
}
