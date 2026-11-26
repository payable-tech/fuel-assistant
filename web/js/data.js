// The Data view: what the heartbeat finds down, how fresh each source is, when each automatic refresh last ran, and
// what doesn't link up.
import { el } from './dom.js';
import { ago, fmt } from './format.js';

// Each stored table's name in words.
const SOURCE_NAME = {
  fuel_lines: 'Fuel purchases', fuel_cards: 'Fuel cards', dt_trucks: 'Datatruck trucks', dt_drivers: 'Datatruck drivers',
  dt_orders: 'Active loads', dt_stops: 'Load stops', samsara_vehicles: 'Samsara vehicles', trucks: 'Linked trucks',
  tg_groups: 'Telegram groups', stores: "Love's prices",
  samsara_live: 'Truck positions and fuel', tank_estimates: 'Tank estimates', burn_factors: 'Engine fuel factors', fuel_stops: 'Driver fuel stops',
  price_history: "Love's price history", price_files: "Love's price sheets read", efs_cards: 'EFS cards',
  efs_card_pages: 'EFS card pages (cards in use)',
};

// Reads a stored UTC time ("2026-10-19 16:03:33+00:00") as a date.
const stored = (text) => (text ? new Date(text.replace(' ', 'T')) : null);

// A list item with a label on the left and a figure on the right (marked bad when `bad`).
function item(label, value, bad = false) {
  return el('li', {}, el('span', {}, label), el('b', bad ? { class: 'bad' } : {}, value));
}

// Source cards, colored by how long ago each was refreshed.
function renderSources(sources) {
  const now = new Date();
  document.getElementById('sources').replaceChildren(...sources.map((s) => {
    const when = stored(s.refreshed);
    const hours = when ? (now - when) / 3.6e6 : Infinity;
    return el('div', { class: `source ${hours < 12 ? 'fresh' : hours < 48 ? 'stale' : 'old'}` },
      el('b', {}, SOURCE_NAME[s.table] || s.table), el('span', {}, `${fmt.count(s.rows)} rows · ${when ? ago(when) : 'never refreshed'}`));
  }));
}

// The automatic refreshes: when each last started, and whether it is running or crashed.
function renderJobs(jobs) {
  const list = document.getElementById('jobs');
  if (!jobs.length) {
    list.replaceChildren(item('No automatic refresh has run yet', 'start with: main.py serve'));
    return;
  }
  list.replaceChildren(...jobs.map((j) => {
    const state = j.error ? 'failed' : j.finished_at ? `ran ${ago(stored(j.started_at))}` : 'running now';
    const li = item(j.job, state, Boolean(j.error));
    if (j.error) li.title = j.error;
    return li;
  }));
}

// The heartbeat's findings: each part down now (with since when and whether Telegram was told), else that everything
// works; then each other source's last refresh, a failing one first (`refreshes`: how each source's last try went).
// A source already listed as down isn't listed again.
function renderHealth(problems, refreshes) {
  const down = (problems || []).map((p) => {
    const li = item(p.component, `down${p.since ? ` since ${ago(stored(p.since))}` : ''}${p.told ? '' : ' · alert not sent yet'}`, true);
    li.title = p.text;
    return li;
  });
  const listed = new Set((problems || []).map((p) => p.component));
  const others = (refreshes || []).filter((s) => !listed.has(s.name));
  const sources = others.sort((a, b) => Boolean(b.error) - Boolean(a.error)).map((s) => {
    const li = item(s.name, s.error ? `failing · last good ${s.last_ok_at ? ago(stored(s.last_ok_at)) : 'never'}`
      : `ok ${ago(stored(s.last_try_at))}`, Boolean(s.error));
    if (s.error) li.title = s.error;
    return li;
  });
  document.getElementById('health').replaceChildren(
    ...(down.length ? down : [item('Everything is working', 'checked every 5 min')]), ...sources);
}

// Gaps in the fuel lines plus the holes list from the linking.
function renderGaps(baseline) {
  const g = baseline.recent.gaps;
  const weeks = baseline.recent.weeks;
  document.getElementById('gaps').replaceChildren(
    item(`Fuel purchases with no truck (last ${weeks} weeks)`, `${fmt.count(g.without_truck)} of ${fmt.count(g.lines)}`),
    item('Fuel purchases with no driver', `${fmt.count(g.without_driver)} of ${fmt.count(g.lines)}`),
    item("Trucks fueling that Samsara can't see", `${fmt.count(g.trucks_not_in_samsara)} of ${fmt.count(g.trucks)}`),
    ...baseline.holes.map((h) => item(h.hole, fmt.count(h.count))),
  );
}

// Draws the Data view from whatever has loaded so far (live numbers, weekly numbers, or both).
export function renderData(live, baseline) {
  const any = live || baseline;
  if (any) renderSources(any.sources);
  if (live) renderJobs(live.jobs);
  if (live) renderHealth(live.health, live.source_health);
  if (baseline && baseline.weeks.length) renderGaps(baseline);
}
