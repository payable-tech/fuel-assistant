// Dashboard entry: switches between the Live, Trends, Plans, Drivers and Data views, loads their numbers, and keeps
// them current: the live numbers every minute, the weekly ones and the plans every 5 minutes, habits every 30.
import { renderData } from './data.js';
import { renderDrivers } from './drivers.js';
import { ago, timeOf } from './format.js';
import { renderLive } from './live.js';
import { initPlans, plansShown, renderPlanList } from './plans.js';
import { registerTheme } from './theme.js';
import { renderTrends } from './trends.js';

const VIEWS = ['live', 'trends', 'plans', 'drivers', 'data'];
const LIVE_EVERY_MS = 60 * 1000;
const TRENDS_EVERY_MS = 5 * 60 * 1000;
const PLANS_EVERY_MS = 5 * 60 * 1000;
const DRIVERS_EVERY_MS = 30 * 60 * 1000;  // habits are worked out once a day
const state = { live: null, baseline: null, checkedAt: null, failing: false };

// Fetches one set of numbers from the dashboard server.
async function load(path) {
  const response = await fetch(path, { cache: 'no-store' });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}

// Shows the connection state in the top bar: what the data is up to, and when the page last checked.
function showLive() {
  const box = document.getElementById('live');
  const text = document.getElementById('live-text');
  box.classList.toggle('is-error', state.failing);
  if (state.failing) {
    text.textContent = state.checkedAt ? `Can't reach the server · numbers from ${ago(state.checkedAt)}` : "Can't load the numbers";
  } else if (state.live && state.live.latest) {
    text.textContent = `Live · data up to ${timeOf(state.live.latest)} CT · checked ${ago(state.checkedAt)}`;
  }
}

// Shows one view and remembers it in the address (#live, #trends, #plans, #data) so a reload opens the same view.
// Anything after a slash belongs to the view (#plans/5 is plan 5) and is kept.
function showView(name) {
  const base = name.split('/')[0];
  const view = VIEWS.includes(base) ? base : 'live';
  VIEWS.forEach((v) => { document.getElementById(`view-${v}`).hidden = v !== view; });
  document.body.dataset.view = view;  // lets the page styles differ by view (the Plans view uses the full width)
  document.querySelectorAll('.views button').forEach((b) => b.setAttribute('aria-selected', String(b.dataset.view === view)));
  if (location.hash.slice(1).split('/')[0] !== view) history.replaceState(null, '', `#${view}`);
  window.dispatchEvent(new Event('resize'));  // charts in a view that was hidden measure their boxes again
  if (view === 'plans') plansShown();  // the map is drawn only while it can be seen
}

// Loads the live numbers and redraws the Live and Data views; a failure keeps what is on screen and says so.
async function refreshLive() {
  try {
    state.live = await load('/api/live');
    state.checkedAt = new Date();
    state.failing = false;
    renderLive(state.live);
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

// Loads the pilot trucks' plans list and redraws the Plans view (the picked plan is redrawn if the view is open).
async function refreshPlans() {
  try {
    renderPlanList(await load('/api/plans'));
  } catch (error) {
    document.getElementById('plans-meta').textContent = `Can't load the plans: ${error.message}`;
    console.error(error);
  }
}

// Loads every driver's habits and redraws the Drivers view.
async function refreshDrivers() {
  try {
    renderDrivers(await load('/api/drivers'));
  } catch (error) {
    document.getElementById('drivers-meta').textContent = `Can't load the habits: ${error.message}`;
    console.error(error);
  }
}

document.querySelectorAll('.views button').forEach((b) => b.addEventListener('click', () => showView(b.dataset.view)));
window.addEventListener('hashchange', () => showView(location.hash.slice(1)));
showView(location.hash.slice(1));

await document.fonts.ready;  // charts measure text, so the font must be in before the first drawing
registerTheme();
initPlans(load);
await Promise.all([refreshLive(), refreshTrends(), refreshPlans(), refreshDrivers()]);
setInterval(refreshLive, LIVE_EVERY_MS);
setInterval(refreshTrends, TRENDS_EVERY_MS);
setInterval(refreshPlans, PLANS_EVERY_MS);
setInterval(refreshDrivers, DRIVERS_EVERY_MS);
setInterval(showLive, 30 * 1000);  // keeps "checked … ago" current
