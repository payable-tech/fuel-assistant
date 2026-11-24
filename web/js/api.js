// Talks to the dashboard server: every view gets its numbers through here.

const RETRY_MS = 3000;  // how long to wait before asking once more when the server didn't take the request

// Asks the server for an address; when the request itself didn't get through (the server was too busy to take it, as
// in its first seconds after a restart), waits a moment and asks once more.
async function ask(path) {
  try {
    return await fetch(path, { cache: 'no-store' });
  } catch {
    await new Promise((done) => setTimeout(done, RETRY_MS));
    return fetch(path, { cache: 'no-store' });
  }
}

// Fetches one set of numbers (JSON) from the dashboard server; a failure comes back as an error with the server's reason.
export async function load(path) {
  const response = await ask(path);
  if (!(response.headers.get('Content-Type') || '').includes('json')) {
    // a page instead of numbers: the server doesn't have this address, so it runs older code than the page
    throw new Error(`the server doesn't know ${path.split('?')[0]} yet: restart it to load its new code`);
  }
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}
