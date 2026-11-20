// Talks to the dashboard server: every view gets its numbers through here.

// Fetches one set of numbers (JSON) from the dashboard server; a failure comes back as an error with the server's reason.
export async function load(path) {
  const response = await fetch(path, { cache: 'no-store' });
  if (!(response.headers.get('Content-Type') || '').includes('json')) {
    // a page instead of numbers: the server doesn't have this address, so it runs older code than the page
    throw new Error(`the server doesn't know ${path.split('?')[0]} yet: restart it to load its new code`);
  }
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}
