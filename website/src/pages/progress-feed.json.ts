// The progress feed the progress board loads, collected from Forgejo when the site is built.
import { buildFeed } from '../lib/progress-feed.ts';

export async function GET() {
  const feed = await buildFeed();
  return new Response(JSON.stringify(feed ?? { error: 'Progress data was unavailable when the site was built.' }), {
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
  });
}
