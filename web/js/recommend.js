// The Recommend view: the test trucks on the left; before one is picked, all of them on the map with their fuel. For the
// one picked (#recommend/0530), its fuel plan at one look: five figures and a map with one fuel zone per tank on the
// road, green to the reserve, red to empty. Below: what we told him and what he did, why each Love's is in or out, and
// his gauge. A past trip of the truck can be picked to see the same for it. The map is in rec-map.js, the list of what
// was told and done in rec-plays.js. Nothing here goes to a driver.
import { load } from './api.js';
import { draw, gauge } from './charts.js';
import { el, figure } from './dom.js';
import { ago, dayTime, esc, fmt, personName, plural } from './format.js';
import { FUEL_RED_PCT, STATES, VERDICTS, storeName } from './labels.js';
import { drawFleet, drawPast, drawPlan, drawTrip, mapNote } from './rec-map.js';
import { renderPlays } from './rec-plays.js';

const TOOLS_KEY = 'fuel.recommend.tools';  // where this browser remembers the map's toggles
const GAUGE_GAP_MS = 2 * 60 * 60 * 1000;  // no gauge reading for this long: the engine was off, the line breaks

// trucks: the list; picked: the truck picked (null: all trucks on the map); past: the past trip picked (its order id), or
// null for the plan now; shown: what is drawn ("fleet", "0530", or "0530/123" for a past trip), so a refresh of the same
// keeps the map where it is;
// data, trip: the plan and what the truck really did, to redraw them when a toggle changes; price: the map's prices,
// "net" (company) or "retail" (pump); nearby: the Love's off the road shown.
const state = { trucks: [], picked: null, past: null, shown: null, data: null, trip: null, price: 'net', nearby: false };

// "8.2": miles per gallon; a dash when unknown.
const mpg = (v) => (v == null ? '—' : v.toFixed(1));

// Wires the view's controls, once: the map's toggles (remembered in this browser), the trip picker and the truck search.
export function initRecommend() {
  try { Object.assign(state, JSON.parse(localStorage.getItem(TOOLS_KEY)) || {}); } catch { /* the defaults, then */ }
  document.getElementById('price-net').addEventListener('click', () => setTools({ price: 'net' }));
  document.getElementById('price-retail').addEventListener('click', () => setTools({ price: 'retail' }));
  document.getElementById('show-nearby').addEventListener('change', (e) => setTools({ nearby: e.target.checked }));
  document.getElementById('rec-trip').addEventListener('change', (e) => {  // a past trip, or back to the plan now
    state.past = e.target.value ? Number(e.target.value) : null;
    if (state.picked) showTruck(state.picked);
  });
  const search = document.getElementById('units-search');
  search.addEventListener('input', filterUnits);
  search.addEventListener('keydown', (e) => {  // Enter opens the first truck found
    const first = document.querySelector('#rec-units .unit:not([hidden])');
    if (e.key === 'Enter' && first) pick(first.dataset.unit);
  });
  markTools();
}

// Applies a toggle and redraws the map where it is.
function setTools(change) {
  Object.assign(state, change);
  try { localStorage.setItem(TOOLS_KEY, JSON.stringify({ price: state.price, nearby: state.nearby })); } catch { /* not remembered */ }
  markTools();
  if (state.data) {
    drawPlan(state.data, false, state);
    if (state.trip) drawTrip(state.trip);
  }
}

// Shows the toggles as they stand.
function markTools() {
  document.getElementById('price-net').setAttribute('aria-pressed', String(state.price === 'net'));
  document.getElementById('price-retail').setAttribute('aria-pressed', String(state.price === 'retail'));
  document.getElementById('show-nearby').checked = state.nearby;
}

// Draws the truck list and the numbers above it, and redraws what the address names if the view is open.
export function renderRecommend(d) {
  state.trucks = d.trucks;
  // a count of the live trucks, not each number (156 of them were a wall); the list below marks which they are
  const sending = d.live.length ? `Sent to the driver on ${plural(d.live.length, 'live truck')}; the others only to the Test fuel group` : 'Not sent to drivers, copies go to the Test fuel group';
  const meta = document.getElementById('recommend-meta');
  meta.title = d.live.length ? `Live: ${d.live.join(', ')}` : '';
  meta.textContent = `${sending} · newest Love's prices ${d.price_date || 'none'} · `
    + `last ${d.days} days: ${d.count} would-be messages, ${d.fueled_there} of ${d.fueled} fueled where we'd have said, `
    + (d.saved < 0 ? `fuel bought elsewhere was ${fmt.money(-d.saved)} cheaper than our stops` : `${fmt.money(d.saved)} going there would have saved`);
  document.getElementById('rec-units').replaceChildren(...d.trucks.map(unitItem));
  filterUnits();  // the search typed stays applied when the list refreshes
  recommendShown();
}

// Says on the view's top line that the recommendations can't be loaded, and why.
export function showRecommendError(error) {
  document.getElementById('recommend-meta').textContent = `Can't load the recommendations: ${error.message}`;
}

// Called when the view opens or its numbers refresh: draws the truck the address names (#recommend/0530), or all trucks
// on the map when it names none (the Recommend tab opens there).
export function recommendShown() {
  if (document.getElementById('view-recommend').hidden) return;
  const named = state.trucks.some((t) => t.unit === linked()) ? linked() : null;
  if (named !== state.picked) state.past = null;  // a past trip belongs to the truck it was picked on
  state.picked = named;
  markPicked();
  if (state.picked) showTruck(state.picked);
  else showFleet();
}

// ---------- the truck list ----------

// One truck as a card: its unit, fuel now, driver, and where it would be told to go or what it is doing.
function unitItem(t) {
  const next = t.told
    ? el('span', { class: 'unit-next told' }, `${t.told_gallons ? `Buy ${fmt.wholeGallons(t.told_gallons)}` : 'Fill up'}: ${t.told}`)
    : el('span', { class: 'unit-next' }, STATES[t.state] || t.state);
  const head = el('button', { type: 'button', class: 'unit-head' }, el('b', {}, `Unit ${t.unit}${t.live ? ' · live' : ''}`),
    fuelLevel(t.fuel_pct), el('span', { class: 'driver' }, personName(t.driver || '')), next);
  head.addEventListener('click', () => pick(t.unit));
  return el('li', { class: 'unit', 'data-unit': t.unit }, head);
}

// Shows only the trucks whose unit or driver holds the search text, says how many are shown, and says so when none is.
function filterUnits() {
  const text = document.getElementById('units-search').value.trim().toLowerCase();
  const drivers = Object.fromEntries(state.trucks.map((t) => [t.unit, (t.driver || '').toLowerCase()]));
  let shown = 0;
  document.querySelectorAll('#rec-units .unit').forEach((li) => {
    const hit = !text || li.dataset.unit.toLowerCase().includes(text) || drivers[li.dataset.unit].includes(text);
    li.hidden = !hit;
    shown += hit ? 1 : 0;
  });
  document.getElementById('units-count').textContent = text ? `${shown} of ${state.trucks.length}` : String(state.trucks.length);
  document.getElementById('units-none')?.remove();
  if (text && !shown) document.getElementById('rec-units').append(el('li', { class: 'units-empty', id: 'units-none' }, 'No truck matches'));
}

// The truck's fuel now as a small gauge bar and its percent, red at or under the reserve; nothing without a reading.
function fuelLevel(value) {
  if (value == null) return el('span', { class: 'level-box' });
  const low = value <= FUEL_RED_PCT ? ' low' : '';
  return el('span', { class: 'level-box' },
    el('span', { class: `level${low}` }, el('i', { style: `width: ${Math.max(0, Math.min(100, value))}%` })),
    el('em', { class: low.trim() }, fmt.level(value)));
}

// Picks a truck (from the list or the map): marks it, puts it in the address, and draws it.
function pick(unit) {
  state.picked = unit;
  state.past = null;
  history.replaceState(null, '', `#recommend/${unit}`);
  markPicked();
  showTruck(unit);
}

// Marks the picked truck's card.
function markPicked() {
  document.querySelectorAll('#rec-units .unit').forEach((u) => u.classList.toggle('picked', u.dataset.unit === state.picked));
}

// The truck named in the address (#recommend/0530), or null.
function linked() {
  const [view, unit] = location.hash.slice(1).split('/');
  return view === 'recommend' ? unit || null : null;
}

// ---------- all trucks ----------

// All test trucks on the map, each with its fuel; a click on one opens its plan. The figures, the map's tools and the
// panels under the map belong to one truck, so they hide.
function showFleet() {
  const moved = state.shown !== 'fleet';
  Object.assign(state, { shown: 'fleet', data: null, trip: null });
  setFleet(true);
  const placed = state.trucks.filter((t) => t.where);
  document.getElementById('rec-title').textContent = 'All test trucks';
  const missing = state.trucks.length - placed.length;
  document.getElementById('rec-facts').textContent = `${plural(placed.length, 'truck')} on the map`
    + (missing ? ` (${missing} more without a position)` : '') + ' · fuel now above each · click one to see its plan';
  document.getElementById('rec-stats').replaceChildren();
  document.getElementById('rec-trip').hidden = true;
  drawFleet(placed, moved, pick);
  mapNote(null);
}

// Switches the panel between all trucks (`on`) and one truck: the legend, the figures, the map's tools, the panels below.
function setFleet(on) {
  document.querySelector('#view-recommend .rec-main').classList.toggle('is-fleet', on);
  document.getElementById('rec-plan-key').hidden = on;
  document.getElementById('rec-fleet-key').hidden = !on;
}

// ---------- one truck: the plan now, or a past trip ----------

// Loads a truck's plan and its list of trips, and shows the plan now or the past trip picked.
async function showTruck(unit) {
  try {
    const d = await load(`/api/recommend/truck?unit=${encodeURIComponent(unit)}`);
    if (unit !== state.picked) return;  // another truck was picked meanwhile
    renderTripPick(d);
    if (state.past) showPast(unit, state.past);
    else showNow(unit, d);
  } catch (error) {
    mapNote(`Can't load this truck: ${error.message}`);
    console.error(error);
  }
}

// Draws the plan now at once, then fetches what the truck really did (Samsara takes seconds). The map moves only to a
// truck other than the one on screen, so a refresh keeps where it was zoomed to.
function showNow(unit, d) {
  const moved = state.shown !== unit;
  Object.assign(state, { shown: unit, data: d, trip: moved ? null : state.trip });
  setMode(false);
  renderHead(d);
  renderStats(d);
  drawPlan(d, moved, state);
  if (state.trip) drawTrip(state.trip);  // the road driven stays until the new one comes
  else renderGauge({ gauge: [], fills: [] });  // another truck: not the last one's gauge meanwhile
  renderPlays(d.recommendations, d.own_fills, d.told ? null : d);  // the "now" row only while no stop is told
  renderLoves(d);
  mapNote(null);
  showTrip(unit);
}

// Draws a past trip: the road planned and the road driven with its fill-ups, the load's messages and what came of them,
// and the gauge over the trip.
async function showPast(unit, order) {
  try {
    const p = await load(`/api/recommend/past?unit=${encodeURIComponent(unit)}&order=${order}`);
    if (unit !== state.picked || order !== state.past) return;  // another truck or trip was picked meanwhile
    const key = `${unit}/${order}`, moved = state.shown !== key;
    Object.assign(state, { shown: key, data: null, trip: p });
    setMode(true);
    renderPastHead(p);
    drawPast(p, moved);
    renderPlays(p.recommendations, p.own_fills, null);
    renderGauge(p);
    mapNote(null);
  } catch (error) {
    mapNote(`Can't load this trip: ${error.message}`);
    console.error(error);
  }
}

// Fits the panels to the plan now or a past trip of one truck: the Love's ahead belong to the plan now only.
function setMode(past) {
  setFleet(false);
  document.getElementById('rec-loves-panel').hidden = past;
  document.getElementById('rec-gauge-title').textContent = past ? 'Fuel gauge on this trip' : 'Fuel gauge since this road';
}

// Fetches what the truck really did on the plan now, and draws it: the road driven, its fill-ups, its gauge.
async function showTrip(unit) {
  try {
    const trip = await load(`/api/recommend/trip?unit=${encodeURIComponent(unit)}`);
    if (unit !== state.picked) return;
    state.trip = trip;
    drawTrip(trip);
    renderGauge(trip);
  } catch (error) {
    console.error(error);  // the plan stays on screen without it
  }
}

// The trip picker: the plan now, then the truck's earlier trips, newest first, each by its days, route and messages.
function renderTripPick(d) {
  const box = document.getElementById('rec-trip');
  const past = (d.trips || []).filter((t) => !t.current);
  box.replaceChildren(el('option', { value: '' }, 'Now: the current plan'), ...past.map((t) => el('option', { value: String(t.order_id) },
    `${dayTime(t.started_at)} to ${dayTime(t.ended_at)} · ${t.from ? `${t.from} → ${t.to}` : `load ${t.load_id}`} · ${plural(t.messages, 'message')}`)));
  box.hidden = !past.length;
  if (state.past && !past.some((t) => t.order_id === state.past)) state.past = null;  // that trip is no longer listed
  box.value = state.past ? String(state.past) : '';
}

// ---------- the head and the figures ----------

// Title and the small print: the MPGs, his level, the prices' date, when it was last looked at.
function renderHead(d) {
  const r = d.road;
  const end = r?.stops.at(-1);
  document.getElementById('rec-title').textContent = r
    ? `Unit ${d.unit} · load ${r.load_id}${end ? ` to ${end.city}, ${end.state}` : ''} · ${fmt.miles(r.route_mi - r.mile)} left`
    : `Unit ${d.unit} · ${STATES[d.state] || d.state}`;
  const parts = [];
  if (r) {
    parts.push(`MPG ${mpg(r.forecast_mpg)}, worst case ${mpg(r.cautious_mpg)}`,
      `live ${mpg(r.live_mpg)}${r.live_mpg != null && !r.live_used ? ' (not used: empty lately)' : ''}`,
      `usual ${fmt.level(r.usual.usual_pct)}${r.usual_known ? '' : ' (not known yet)'}`, `prices of ${r.price_date || '—'}`);
  } else if (d.place) parts.push(d.place);
  if (d.looked_at) parts.push(`looked ${ago(new Date(d.looked_at))}`);
  document.getElementById('rec-facts').textContent = parts.join(' · ');
}

// The plan at one look: fuel now, when the zone starts, when he crosses the reserve, when he runs out, and the stop.
// With no road (no load), fuel now and why there is no zone.
function renderStats(d) {
  const figures = d.road ? [fuelNow(d), zoneStarts(d.road), underReserve(d.road), runsOut(d), stopStat(d)]
    : [fuelNow(d), stat('Fuel zone', '—', STATES[d.state] || d.state)];
  document.getElementById('rec-stats').replaceChildren(...figures);
}

// One figure above the map: a label, a value and a small note; `kind` colors it (safe, risky) or widens it (stop).
const stat = (label, value, note, kind = '') => figure(`rec-stat ${kind}`.trim(), label, value, note);

// How far ahead a point of the road is: "Now" once the truck is there, else "in 120 mi".
const milesTo = (r, mile) => (mile <= r.mile + 0.5 ? 'Now' : `in ${fmt.miles(mile - r.mile)}`);

// Fuel now: the gauge, and the gallons in the tank when its size is known.
function fuelNow(d) {
  const gallons = d.tank_gal && d.fuel_pct != null ? `${Math.round(d.fuel_pct / 100 * d.tank_gal)} of ${fmt.wholeGallons(d.tank_gal)}` : '';
  return stat('Fuel now', fmt.level(d.fuel_pct), gallons);
}

// Where the first fuel zone starts: at the driver's usual level (up to their high level, at most `above_usual` points
// above, as the rules have it; it was a fixed 5 here after the rule went to 1, 2026-11-16).
function zoneStarts(r) {
  const z = r.zones[0];
  if (!z) return stat('Zone starts', '—', 'enough for delivery', 'safe');
  const usualTop = Math.min(Math.max(r.usual.high_pct, r.usual.usual_pct), r.usual.usual_pct + r.above_usual);
  return stat('Zone starts', milesTo(r, z.start_mi), `at the driver's level, ${fmt.level(usualTop)}`, 'safe');
}

// Where the tank goes under the reserve in the worst case, if that is before delivery.
function underReserve(r) {
  const z = r.zones[0];
  if (!z || z.reserve_mi >= r.route_mi) return stat('Under reserve', '—', 'not before delivery', 'risky');
  return stat('Under reserve', milesTo(r, z.reserve_mi), 'in the worst case', 'risky');
}

// Where the tank runs empty, if before delivery, with the last Love's before it (or how far the fuel lasts at normal MPG).
function runsOut(d) {
  const r = d.road, z = r.zones[0];
  if (!z || z.end_mi >= r.route_mi) return stat('Runs out', '—', 'not before delivery', 'risky');
  const last = r.loves.filter((v) => ['early', 'range', 'late'].includes(v.verdict)).at(-1);
  const lasts = d.fuel_pct / 100 * d.tank_gal * r.forecast_mpg;  // miles the fuel now lasts at the usual MPG
  return stat('Runs out', milesTo(r, z.end_mi),
    last ? `last Love's: ${last.stop.store.city}, ${fmt.miles(last.stop.miles - r.mile)}` : `${fmt.miles(lasts)} at normal MPG`, 'risky');
}

// The stop chosen: where, how far, how much, and whether he would have been told yet.
function stopStat(d) {
  const r = d.road, v = r.loves.find((x) => x.stop.store.store_no === r.chosen);
  if (!v) return stat('Stop', 'None needed yet', STATES[d.state] || d.state, 'stop');
  const buy = d.told?.then_station ? `buy about ${fmt.wholeGallons(d.told.gallons)}` : 'fill up';
  return stat('Stop', storeName(v.stop.store), `in ${fmt.miles(v.stop.miles - r.mile)} · ${buy} · ${r.told ? 'told' : `told once within ${r.look_mi} mi`}`, 'stop');
}

// A past trip's title, its days and what came of it, and its figures: messages, followed, fill-ups, Love's share.
function renderPastHead(p) {
  const from = p.stops[0], to = p.stops.at(-1);
  document.getElementById('rec-title').textContent = `Unit ${p.unit} · load ${p.load_id || '—'}`
    + (from && to ? ` · ${from.city}, ${from.state} → ${to.city}, ${to.state}` : '');
  const sent = p.recommendations.filter((r) => r.status !== 'repeat'), followed = sent.filter((r) => r.outcome?.there).length;
  const gallons = p.fills.reduce((n, f) => n + f.gallons, 0);
  const loves = p.fills.filter((f) => /^LOVE/i.test(f.station)).reduce((n, f) => n + f.gallons, 0);
  document.getElementById('rec-facts').textContent = `Past trip, ${dayTime(p.started_at)} to ${dayTime(p.ended_at)} CT`
    + (p.line.length ? '' : ' · the road planned was not kept (trips before Nov 5)');
  document.getElementById('rec-stats').replaceChildren(stat('Messages', String(sent.length), sent.length ? 'on this load' : 'none needed'),
    stat('Followed', sent.length ? `${followed} of ${sent.length}` : '—', 'fueled at the stop told', followed ? 'safe' : ''),
    stat('Fill-ups', String(p.fills.length), fmt.wholeGallons(gallons)),
    stat("At Love's", gallons ? fmt.level(100 * loves / gallons) : '—', fmt.wholeGallons(loves)));
}

// ---------- the panels under the map ----------

// The Love's ahead up to the first out of reach, with how each stands. The stop chosen is marked.
function renderLoves(d) {
  const table = document.getElementById('rec-loves'), r = d.road;
  const head = '<thead><tr><th class="left">Love\'s</th><th>Miles ahead</th><th>Arrive</th><th>Worst case</th><th>Company price</th><th>Pump</th><th class="left">Verdict</th></tr></thead>';
  if (!r) {
    table.innerHTML = `${head}<tbody><tr class="note-row"><td colspan="7">No road: no load right now.</td></tr></tbody>`;
    return;
  }
  const ahead = r.loves.filter((v) => v.verdict !== 'passed');
  const firstOut = ahead.findIndex((v) => v.verdict === 'out');
  const shown = firstOut < 0 ? ahead : ahead.slice(0, firstOut + 1);
  const rows = shown.map((v) => {
    const s = v.stop, no = s.store.store_no;
    const off = s.off_mi > r.corridor_mi ? ` · ${Math.round(s.off_mi)} mi off the road` : '';
    const role = (no === r.chosen ? (r.told ? ' · stop told' : ' · stop chosen') : no === r.then ? ' · fill up here after' : '') + off;
    return `<tr class="${no === r.chosen ? 'is-chosen' : ''}"><td class="left">${esc(storeName(s.store))}</td><td>${fmt.count(s.miles - r.mile)}</td>
      <td>${fmt.level(v.arrive_pct)}</td><td>${fmt.level(v.worst_pct)}</td><td>${fmt.price(s.store.net)}</td><td>${fmt.price(s.store.retail)}</td>
      <td class="left verdict-${v.verdict}">${esc(VERDICTS[v.verdict])}${role}</td></tr>`;
  }).join('');
  table.innerHTML = `${head}<tbody>${rows || '<tr class="note-row"><td colspan="7">No Love\'s ahead on this road.</td></tr>'}</tbody>`;
}

// The gauge since this road was made or the last message, with a line per fill-up; a long gap (engine off) breaks the line.
function renderGauge(trip) {
  const readings = trip.gauge.flatMap((g, i) => (i && new Date(g[0]) - new Date(trip.gauge[i - 1][0]) > GAUGE_GAP_MS ? [[g[0], null], g] : [g]));
  draw('chart-rec-gauge', gauge(readings, trip.fills));
}
