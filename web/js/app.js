// Dashboard entry: switches between the sections (Fuel, Accounting) and their views (Fuel: Live, Trends, Recommend,
// Drivers, Data; Accounting: the EFS statements as a tree), loads their numbers and hands
// them to each view to draw, and keeps them current: the live numbers and the recommendations every minute, the weekly
// ones every 5 minutes, habits every 30. The bell in the top bar tells when a message goes to a driver.
import { accountingPath, initAccounting, renderAccounting, showAccountingError } from './accounting.js';
import { load } from './api.js';
import { renderData } from './data.js';
import { renderDrivers, showDriversError } from './drivers.js';
import { ago, timeOf } from './format.js';
import { initLive, renderLive } from './live.js';
import { initNotes, renderNotes } from './notes.js';
import { initRecommend, recommendShown, renderRecommend, showRecommendError } from './recommend.js';
import { registerTheme } from './theme.js';
import { initTrends, renderTrends } from './trends.js';

// each section's views, in the order of its tabs; picking a section opens its first view
const SECTIONS = {
  fuel: ['live', 'trends', 'recommend', 'drivers', 'data'],
  accounting: ['accounting'],
};
const VIEWS = Object.values(SECTIONS).flat();
// how often each set of numbers is fetched again
const LIVE_EVERY_MS = 60 * 1000;
const TRENDS_EVERY_MS = 5 * 60 * 1000;
const DRIVERS_EVERY_MS = 30 * 60 * 1000;  // habits are worked out once a day
const ACCOUNTING_EVERY_MS = 30 * 60 * 1000;  // a new statement comes once a week; this picks it up the same half hour
const VERSION_EVERY_MS = 60 * 1000;
// live, baseline: the numbers last loaded; checkedAt: when; failing: the last load failed; version: the page's files
const state = { live: null, baseline: null, checkedAt: null, failing: false, version: null };

// Shows the connection state in the top bar: what the data is up to, and when the page last checked.
function showLive() {
  const box = document.getElementById('live');
  const text = document.getElementById('live-text');
  const down = (state.live && state.live.health) || [];  // parts the heartbeat found down: named on hover, listed on Data
  box.classList.toggle('is-error', state.failing);
  box.classList.toggle('is-warn', !state.failing && down.length > 0);
  box.title = down.map((p) => `${p.component}: ${p.text}`).join('\n');
  if (state.failing) {
    text.textContent = state.checkedAt ? `Can't reach the server · numbers from ${ago(state.checkedAt)}` : "Can't load the numbers";
  } else if (state.live && state.live.latest) {
    const warn = down.length ? `${down.length} part${down.length > 1 ? 's' : ''} down (see Data) · ` : '';
    text.textContent = `${warn}Live · data up to ${timeOf(state.live.latest)} CT · checked ${ago(state.checkedAt)}`;
  }
}

// Shows one view, its section and that section's tabs, and remembers the view in the address (#live, #trends,
// #accounting…) so a reload opens it again. Anything after a slash belongs to the view (#recommend/0530 is that truck).
function showView(name) {
  const base = name.split('/')[0];
  const view = VIEWS.includes(base) ? base : 'live';
  const section = Object.keys(SECTIONS).find((s) => SECTIONS[s].includes(view));
  document.querySelectorAll('.sections button').forEach((b) => b.setAttribute('aria-selected', String(b.dataset.section === section)));
  document.querySelectorAll('.views').forEach((n) => { n.hidden = n.dataset.section !== section; });  // a section with one view has no tabs
  VIEWS.forEach((v) => { document.getElementById(`view-${v}`).hidden = v !== view; });
  document.body.dataset.view = view;  // lets the page styles differ by view (the Recommend view uses the full width)
  document.querySelectorAll('.views button').forEach((b) => b.setAttribute('aria-selected', String(b.dataset.view === view)));
  if (location.hash.slice(1).split('/')[0] !== view) history.replaceState(null, '', `#${view}`);
  window.dispatchEvent(new Event('resize'));  // charts in a view that was hidden measure their boxes again
  if (view === 'recommend') recommendShown();  // the map is drawn only while it can be seen
}

// Loads the live numbers and redraws the Live and Data views and the bell; a failure keeps what is on screen and says so.
async function refreshLive() {
  try {
    state.live = await load('/api/live');
    state.checkedAt = new Date();
    state.failing = false;
    renderLive(state.live);
    renderNotes(state.live.plans?.messages);
    renderData(state.live, state.baseline);
  } catch (error) {
    state.failing = true;
    console.error(error);
  }
  showLive();
}

// Loads the weekly numbers and redraws the Trends and Data views.
async function refreshTrends() {
  try {
    state.baseline = await load('/api/baseline');
    renderTrends(state.baseline);
    renderData(state.live, state.baseline);
  } catch (error) {
    state.failing = true;
    console.error(error);
    showLive();
  }
}

// Loads the fuel recommendations and redraws the Recommend view.
async function refreshRecommend() {
  try {
    renderRecommend(await load('/api/recommend'));
  } catch (error) {
    showRecommendError(error);
    console.error(error);
  }
}

// Loads every driver's habits and redraws the Drivers view.
async function refreshDrivers() {
  try {
    renderDrivers(await load('/api/drivers'));
  } catch (error) {
    showDriversError(error);
    console.error(error);
  }
}

// Loads the picked EFS statement's tree and redraws the Accounting view.
async function refreshAccounting() {
  try {
    renderAccounting(await load(accountingPath()));
  } catch (error) {
    showAccountingError(error);
    console.error(error);
  }
}

// Reloads the page once its files changed on the server since it was opened (an update), so a dashboard left open
// all day never runs old code against new numbers. The first look only notes the version.
async function checkVersion() {
  try {
    const { version } = await load('/api/version');
    state.version = state.version ?? version;
    if (version !== state.version) location.reload();
  } catch (error) {
    console.error(error);
  }
}

document.querySelectorAll('.views button').forEach((b) => b.addEventListener('click', () => {
  history.replaceState(null, '', `#${b.dataset.view}`);  // a tab opens its view's front: Recommend shows all trucks, none picked
  showView(b.dataset.view);
}));
document.querySelectorAll('.sections button').forEach((b) => b.addEventListener('click', () => {
  const first = SECTIONS[b.dataset.section][0];
  history.replaceState(null, '', `#${first}`);
  showView(first);
}));
window.addEventListener('hashchange', () => showView(location.hash.slice(1)));
showView(location.hash.slice(1));

await document.fonts.ready;  // charts measure text, so the font must be in before the first drawing
registerTheme();
initLive();
initTrends();
initRecommend();
initNotes();
initAccounting(refreshAccounting);
checkVersion();
setInterval(checkVersion, VERSION_EVERY_MS);
await Promise.all([refreshLive(), refreshTrends(), refreshRecommend(), refreshDrivers(), refreshAccounting()]);
setInterval(refreshAccounting, ACCOUNTING_EVERY_MS);
setInterval(refreshLive, LIVE_EVERY_MS);
setInterval(refreshRecommend, LIVE_EVERY_MS);
setInterval(refreshTrends, TRENDS_EVERY_MS);
setInterval(refreshDrivers, DRIVERS_EVERY_MS);
setInterval(showLive, 30 * 1000);  // keeps "checked … ago" current
