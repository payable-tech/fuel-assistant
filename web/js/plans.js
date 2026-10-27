// The Plans view: each pilot truck's fuel plans, and for the plan picked, a map of it against what the truck really
// did (the road it drove, where it bought diesel), its planned stops beside its fill-ups, and its fuel gauge since.
import { draw } from './charts.js';
import { el } from './dom.js';
import { capitalized, clock, dateOf, dayClock, dayTime, esc, fmt, personName, short, stationName } from './format.js';
import { fade, token } from './theme.js';

const TILES = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
const ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>';
const PICK_KEY = 'fuel.plans.picked';
const DETAIL_EVERY_MS = 5 * 60 * 1000;  // the server rebuilds a trip from Samsara at most this often anyway
const GAUGE_GAP_MS = 2 * 60 * 60 * 1000;  // no gauge reading for this long: the engine was off, the line breaks
const BUBBLE = { w: 40, h: 16, gap: 4 };  // a Love's price bubble on screen, px: bubbles closer than this would overlap
const FIT = { padding: [36, 36] };  // room kept around a plan's road when the map moves to it, px

// trucks: the list as loaded; unitOf: plan id -> its unit; summaries: plan id -> its list entry; busy: the plan being
// loaded; folded: the shown truck's card was closed by hand; bubbles: the Love's marks shown, to keep bubbles apart
const state = { load: null, trucks: [], picked: null, shown: null, shownAt: 0, busy: null, folded: false, reserve: null,
  map: null, layer: null, unitOf: new Map(), summaries: new Map(), bubbles: [] };

// Gives the view the function the page uses to fetch numbers from the server, and wires the search and the keys.
export function initPlans(load) {
  state.load = load;
  const search = document.getElementById('unit-search');
  search.addEventListener('input', filterUnits);
  search.addEventListener('keydown', searchKeys);
  document.getElementById('plan-units').addEventListener('keydown', listKeys);
  document.addEventListener('keydown', slashToSearch);
}

// Draws the truck list, keeps the plan picked before (else the newest), and redraws it if the view is open.
export function renderPlanList(data) {
  const plans = data.trucks.flatMap((t) => t.plans);
  state.trucks = data.trucks;
  state.reserve = data.reserve_pct;
  state.unitOf = new Map(data.trucks.flatMap((t) => t.plans.map((p) => [p.plan_id, t.unit])));
  state.summaries = new Map(plans.map((p) => [p.plan_id, p]));
  document.getElementById('plans-meta').textContent = `${data.trucks.length} pilot trucks · `
    + `${plans.filter((p) => p.active).length} active plans · ${plans.length} plans made in the last ${data.days} days`;
  document.getElementById('plan-units').replaceChildren(...data.trucks.map(unitItem));
  filterUnits();
  const ids = plans.map((p) => p.plan_id);
  const wanted = [linked(), state.picked, remembered()].find((id) => ids.includes(id));
  state.picked = wanted ?? newest(plans);
  markPicked();
  plansShown();
}

// Called when the Plans view opens: draws the picked plan, unless it was drawn in the last few minutes. Redrawing
// the plan already on screen happens quietly, without the loading note. Before the first drawing, the list scrolls
// to the picked truck (it may come from a link or the last visit, further down the list).
export function plansShown() {
  if (document.getElementById('view-plans').hidden || state.picked == null) return;
  if (state.shown == null) keepInSight(document.querySelector('.unit.picked'), 'instant');
  if (state.shown === state.picked && Date.now() - state.shownAt < DETAIL_EVERY_MS) return;
  showPlan(state.picked, { quiet: state.shown === state.picked });
}

// ---------- the truck list ----------

// One truck as a card: "Unit 0226", its fuel now, its driver and where its active plan goes. Pressing the card
// opens the truck's newest plan and unfolds its plans, newest (the active one) on top; pressing it again folds them.
function unitItem(t) {
  const li = el('li', { class: 'unit', 'data-unit': t.unit, 'data-find': findText(t) });
  const head = el('button', { type: 'button', class: 'unit-head', 'aria-expanded': 'false' });
  const fold = el('span', { class: 'unit-fold' });
  fold.append(foldedLine(t));
  head.append(el('b', {}, `Unit ${t.unit}`), fuelLevel(t.fuel_pct), el('span', { class: 'driver' }, personName(t.driver)), fold);
  li.append(head);
  if (!t.plans.length) {
    head.disabled = true;
    return li;
  }
  head.append(el('i', { class: 'chev', 'aria-hidden': 'true' }));
  head.addEventListener('click', () => (li.classList.contains('open') ? foldShown() : openUnit(t.unit)));
  const body = el('div', { class: 'unit-body' });
  const list = el('ol', { class: 'unit-plans' });
  list.append(...t.plans.map(planItem));
  body.append(list);
  // once the plans have unfolded, the whole card is scrolled into sight
  body.addEventListener('transitionend', (e) => { if (e.target === body && li.classList.contains('open')) keepInSight(li); });
  li.append(body);
  return li;
}

// The card's line while folded: where its active plan goes, or that it has none.
function foldedLine(t) {
  const line = el('span');
  const active = t.plans.find((p) => p.active);
  if (active) line.append(el('span', { class: 'badge active' }, 'Active'), el('span', { class: 'to' }, `→ ${active.to}`));
  else line.textContent = t.plans.length ? 'No active plan' : 'No plan yet';
  return line;
}

// One plan in an opened card: where it goes (marked when active), its stops and cost, and when it was made.
function planItem(p) {
  const button = el('button', { type: 'button', class: p.active ? 'active' : '', 'data-plan': p.plan_id, 'aria-pressed': 'false' });
  const to = el('span', { class: 'to' });
  if (p.active) to.append(el('span', { class: 'badge active' }, 'Active'));
  to.append(`→ ${p.to}`);
  button.append(to, el('span', {}, `${planFigures(p)} · ${dayTime(p.made_at)}`));
  button.addEventListener('click', () => pick(p.plan_id));
  const item = el('li');
  item.append(button);
  return item;
}

// What the search looks through for one truck: its unit, driver, and its plans' destinations and load numbers.
function findText(t) {
  return [t.unit, t.driver || '', ...t.plans.flatMap((p) => [p.to, p.load_id])].join(' ').toLowerCase();
}

// The truck's fuel now as a small gauge bar and its percent (red at or below the plans' reserve); nothing when
// there is no reading.
function fuelLevel(pct) {
  const box = el('span', { class: 'level-box' });
  if (pct == null) return box;
  const low = state.reserve != null && pct <= state.reserve ? ' low' : '';
  const bar = el('span', { class: `level${low}` });
  bar.append(el('i', { style: `width: ${Math.max(0, Math.min(100, pct))}%` }));
  box.append(bar, el('em', { class: low.trim() }, `${Math.round(pct)}%`));
  return box;
}

// Shows only the trucks whose unit, driver, destinations or load numbers hold every word typed in the search box
// ("unit" itself is skipped, so "unit 5557" finds Unit 555701).
function filterUnits() {
  const words = document.getElementById('unit-search').value.toLowerCase().replace(/\bunit\b/g, ' ').split(/\s+/).filter(Boolean);
  const cards = [...document.querySelectorAll('.unit')];
  cards.forEach((c) => { c.hidden = !words.every((w) => c.dataset.find.includes(w)); });
  const shown = cards.filter((c) => !c.hidden).length;
  document.getElementById('units-count').textContent = words.length ? `${shown} of ${cards.length}` : String(cards.length);
  document.getElementById('units-empty').hidden = shown > 0;
}

// In the search box: Enter opens the first truck shown, the down arrow moves into the list, Escape empties the box.
function searchKeys(event) {
  const first = document.querySelector('.unit:not([hidden]) .unit-head:not(:disabled)');
  if (event.key === 'Enter' && first) openUnit(first.closest('.unit').dataset.unit);
  else if (event.key === 'ArrowDown' && first) first.focus();
  else if (event.key === 'Escape' && event.target.value) {
    event.target.value = '';
    filterUnits();
  } else return;
  event.preventDefault();
}

// The up and down arrows move between the cards and the opened card's plans; up from the top goes to the search box.
function listKeys(event) {
  if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
  const buttons = [...document.querySelectorAll('.unit:not([hidden]) .unit-head:not(:disabled), .unit.open:not([hidden]) .unit-plans button')];
  const to = buttons.indexOf(document.activeElement) + (event.key === 'ArrowDown' ? 1 : -1);
  (to < 0 ? document.getElementById('unit-search') : buttons[to])?.focus();
  event.preventDefault();
}

// "/" anywhere on the Plans view (outside a text box) jumps to the truck search.
function slashToSearch(event) {
  if (event.key !== '/' || document.getElementById('view-plans').hidden || event.target.matches('input, textarea')) return;
  event.preventDefault();
  document.getElementById('unit-search').focus();
}

// Scrolls the truck list (only the list, never the page) as little as needed to show the whole card, or its top
// when the card is taller than the list.
function keepInSight(card, behavior = 'smooth') {
  if (!card) return;
  const list = card.parentElement, top = card.offsetTop - 6, bottom = card.offsetTop + card.offsetHeight + 6;
  const view = list.scrollTop, height = list.clientHeight;
  if (top < view) list.scrollTo({ top, behavior });
  else if (bottom > view + height) list.scrollTo({ top: Math.min(top, bottom - height), behavior });
}

// A plan in a few words: its stops and cost, "no stop", or "no plan".
function planFigures(p) {
  if (p.stops == null) return 'no plan';
  if (p.stops === 0) return `no stop · ${fmt.count(p.route_mi)} mi`;
  return `${p.stops} stop${p.stops > 1 ? 's' : ''} · ${dollars(p.cost)}`;
}

// Picks a plan: marks it in the list, puts it in the address (#plans/5, a link to this plan), remembers it for the
// next visit, and draws it.
function pick(id) {
  state.picked = id;
  state.folded = false;
  history.replaceState(null, '', `#plans/${id}`);
  remember(id);
  markPicked();
  showPlan(id);
}

// Opens a truck's card: its newest plan, unless one of its plans is already shown, which then just unfolds.
function openUnit(unit) {
  const t = state.trucks.find((x) => x.unit === unit);
  if (!t || !t.plans.length) return;
  if (state.unitOf.get(state.picked) !== unit) {
    pick(t.plans[0].plan_id);
    return;
  }
  state.folded = false;
  markPicked();
}

// Folds the card of the truck shown; its plan stays on screen.
function foldShown() {
  state.folded = true;
  markPicked();
}

// The plan named in the address (#plans/5), or null.
function linked() {
  const [view, id] = location.hash.slice(1).split('/');
  return view === 'plans' ? Number(id) || null : null;
}

// Marks the list: the picked plan's button (with a spinner on the one loading), its truck's card as picked and,
// unless folded by hand, opened; every other card folded. Folded plans can't be reached with Tab.
function markPicked() {
  document.querySelectorAll('[data-plan]').forEach((b) => {
    b.setAttribute('aria-pressed', String(Number(b.dataset.plan) === state.picked));
    b.setAttribute('aria-busy', String(Number(b.dataset.plan) === state.busy));
  });
  const unit = state.unitOf.get(state.picked);
  document.querySelectorAll('.unit').forEach((u) => {
    const open = u.dataset.unit === unit && !state.folded;
    u.classList.toggle('picked', u.dataset.unit === unit);
    u.classList.toggle('open', open);
    u.querySelector('.unit-head').setAttribute('aria-expanded', String(open));
    const body = u.querySelector('.unit-body');
    if (body) body.inert = !open;
  });
}

// The id of the newest plan, or null when there is none.
function newest(plans) {
  return plans.reduce((a, b) => (a && a.made_at > b.made_at ? a : b), null)?.plan_id ?? null;
}

// The plan picked on an earlier visit (this browser only); null when there is none or storage is blocked.
function remembered() {
  try { return Number(localStorage.getItem(PICK_KEY)) || null; } catch { return null; }
}

// Remembers the picked plan for the next visit, when the browser allows it.
function remember(id) {
  try { localStorage.setItem(PICK_KEY, String(id)); } catch { /* the pick just isn't remembered */ }
}

// ---------- one plan ----------

// Loads one plan with its trip and draws it. Unless `quiet`, it shows at once that the plan is coming (see
// `loading`). The map moves only to a plan other than the one on screen, so a refresh keeps where it was zoomed to.
async function showPlan(id, { quiet = false } = {}) {
  if (!quiet) loading(id);
  try {
    const d = await state.load(`/api/plan?id=${id}`);
    if (id !== state.picked) return;  // another plan was picked meanwhile
    const before = state.shown;
    state.shown = id;
    state.shownAt = Date.now();
    renderHead(d);
    drawMap(d, id === before ? null : before == null ? 'jump' : 'fly');
    renderStops(d);
    renderFills(d);
    renderGauge(d);
    renderMoney(d);
    mapNote(null);
  } catch (error) {
    if (id !== state.picked) return;
    if (quiet) console.error(error);  // a background refresh failing keeps the plan on screen as it is
    else failed(id, error);
  } finally {
    if (id === state.picked) loaded();
  }
}

// Shows at once that plan `id` is coming: its title from the list, a note on the map, the plan on screen dimmed,
// and a spinner on its button in the list.
function loading(id) {
  const p = state.summaries.get(id), unit = state.unitOf.get(id);
  document.getElementById('plan-title').textContent = `Unit ${unit} · load ${p.load_id} to ${p.to}`;
  document.getElementById('plan-facts').textContent = `Planned ${dayTime(p.made_at)} · loading…`;
  mapNote(`Loading Unit ${unit}'s road and fuel since the plan…`, 'loading');
  document.querySelector('.plans-main').classList.add('is-loading');
  state.busy = id;
  markPicked();
}

// Ends the loading look: the panels undimmed, the spinner gone.
function loaded() {
  document.querySelector('.plans-main').classList.remove('is-loading');
  state.busy = null;
  markPicked();
}

// Says on the map why plan `id` couldn't load, with a button to try again.
function failed(id, error) {
  document.getElementById('plan-facts').textContent = `Can't load this plan: ${error.message}`;
  const retry = el('button', { type: 'button' }, 'Try again');
  retry.addEventListener('click', () => showPlan(id));
  mapNote(`Can't load this plan: ${error.message}`, 'failed', retry);
}

// The note over the map, of a `kind`: 'loading' (with a spinner; it shows after a moment, so quick loads don't
// flash it) or 'failed'. No text fades it out, its words kept until it is gone.
function mapNote(text, kind, ...extra) {
  const box = document.getElementById('map-note');
  box.className = text ? `map-note ${kind}` : 'map-note';
  if (text) box.replaceChildren(...(kind === 'loading' ? [el('i', { class: 'spin' })] : []), el('span', {}, text), ...extra);
}

// Title and the plan's starting figures: when it was made, fuel, distance, MPG, price sheet; when the load ended,
// and up to when the truck's GPS and gauge were read.
function renderHead(d) {
  const p = d.plan, t = p.truck, end = p.stops_ahead.at(-1);
  document.getElementById('plan-title').textContent = `Unit ${t.unit} · load ${p.order.load_id} to ${end.city}, ${end.state}`;
  const parts = [`Planned ${dayTime(p.made_at)}`,
    `fuel ${Math.round(t.fuel_pct)}% (~${Math.round(t.fuel_pct / 100 * t.tank_gal)} of ${Math.round(t.tank_gal)} gal)`,
    `${fmt.count(p.route_mi)} mi`, `${p.mpg.toFixed(1)} MPG`, `Love's prices of ${short(dateOf(p.price_date))}`];
  if (d.trip.finished_at) parts.push(`last stop reached ${dayTime(d.trip.finished_at)}`);
  parts.push(`GPS and gauge up to ${clock(d.built_at)} CT`);
  document.getElementById('plan-facts').textContent = parts.join(' · ');
}

// The map: planned road, Love's along it by price, the load's stops, the start, the planned stops, then what the
// truck did: the road it drove, its fill-ups, and where it is now while the load isn't finished. `move`: 'fly' glides
// from the plan shown before, 'jump' goes straight there (the first drawing), null keeps the map where it is.
function drawMap(d, move) {
  const { map, layer } = ensureMap();
  layer.clearLayers();
  const p = d.plan, trip = d.trip, stops = p.plan ? p.plan.stops : [];
  const road = L.polyline(p.line, { color: token('--s1'), weight: 4, opacity: 0.85 }).addTo(layer);
  if (trip.track.length > 1) L.polyline(trip.track, { color: token('--brand'), weight: 3 }).addTo(layer);
  drawCandidates(p.candidates, new Set(stops.map((s) => s.store.store_no)), layer);
  p.stops_ahead.forEach((s) => pin(layer, 'pin-load', s.kind === 'pickup' ? 'P' : 'D', [s.lat, s.lng],
    tip(`${s.kind === 'pickup' ? 'Pickup' : 'Delivery'} · ${s.city}, ${s.state}`, [])));
  L.circleMarker(p.line[0], { radius: 6, color: token('--bg'), weight: 2, fillColor: token('--text'), fillOpacity: 1 })
    .bindTooltip(tip('Where the plan started', [['Fuel', `${Math.round(p.truck.fuel_pct)}%`], ['When', dayTime(p.made_at)]]))
    .addTo(layer);
  (d.habit_plan ? d.habit_plan.stops : []).forEach((s, i) => pin(layer, 'pin-habit', `H${i + 1}`, [s.store.lat, s.store.lng],
    tip(`Habit stop ${i + 1} · ${storeName(s.store)}`,
      [['Buy', `${Math.round(s.gallons)} gal`], ['Discounted', fmt.price(s.store.net)], ['Pump', fmt.price(s.store.retail)],
        ['Billed', dollars(s.cost)], ['Arrive with', `${Math.round(s.arrive_gal)} gal`], ['Mile', fmt.count(s.miles)]])));
  stops.forEach((s, i) => pin(layer, 'pin-plan', i + 1, [s.store.lat, s.store.lng], tip(`${i + 1} · ${storeName(s.store)}`,
    [['Buy', `${Math.round(s.gallons)} gal`], ['Discounted', fmt.price(s.store.net)], ['Pump', fmt.price(s.store.retail)],
      ['Arrive with', `${Math.round(s.arrive_gal)} gal`], ['Mile', fmt.count(s.miles)]])));
  trip.fills.filter((f) => f.lat != null).forEach((f) => pin(layer, `pin-fill ${f.plan_stop ? 'on-plan' : 'off-plan'}`, '',
    [f.lat, f.lng], tip(`${dayTime(f.at)} · ${station(f.station)}`, [['Gallons', `${Math.round(f.gallons)} gal`],
      ['Pump', `${fmt.price(f.pump / f.gallons)}/gal`], ['Billed', `${fmt.price(f.billed / f.gallons)}/gal`],
      ['Planned stop', f.plan_stop ? `#${f.plan_stop}` : 'none']]), 'i'));
  if (!trip.finished_at && trip.track.length) pin(layer, 'pin-now', '', trip.track.at(-1), tip(`Unit ${p.truck.unit} now`, fuelNow(d)), 'i');
  const bounds = road.getBounds();
  if (trip.track.length) bounds.extend(L.latLngBounds(trip.track));
  if (move === 'fly' && !matchMedia('(prefers-reduced-motion: reduce)').matches) map.flyToBounds(bounds, { ...FIT, duration: 0.7 });
  else if (move) map.fitBounds(bounds, { ...FIT, animate: false });
  declutter();
}

// The truck's fuel now, from its latest gauge reading since the plan: level, gallons, and when it was read.
function fuelNow(d) {
  const last = d.gauge.at(-1);
  if (!last) return [['Fuel', 'no gauge reading since the plan']];
  return [['Fuel', `${Math.round(last[1])}% (~${Math.round(last[1] / 100 * d.plan.truck.tank_gal)} gal)`], ['Read', dayTime(last[0])]];
}

// A fuel stop's name: "Love's #614 Westfield, MA", or a station that isn't a Love's (sent to when none was in reach)
// by its own name, "Cenex Zip Trip Clarkston, WA".
function storeName(store) {
  return `${store.name || `Love's #${store.store_no}`} ${store.city}, ${store.state}`;
}

// The Love's along the planned road: a dot colored from the cheapest (green) to the dearest (red) on this road, with
// its price in a small bubble above it; hovering shows the rest. `planned` holds the store numbers the plan stops at.
function drawCandidates(candidates, planned, layer) {
  const prices = candidates.map((c) => c.store.net);
  const low = Math.min(...prices), high = Math.max(...prices);
  document.getElementById('price-range').textContent = prices.length ? `${fmt.price(low)} – ${fmt.price(high)}` : '';
  state.bubbles = candidates.map((c) => {
    const color = mix(token('--good'), token('--bad'), high > low ? (c.store.net - low) / (high - low) : 0);
    const icon = L.divIcon({ className: 'loves', iconSize: [12, 12],
      html: `<b style="color: ${color}">${fmt.price(c.store.net)}</b><i style="background: ${color}"></i>` });
    const marker = L.marker([c.store.lat, c.store.lng], { icon, zIndexOffset: -1000, riseOnHover: true })
      .bindTooltip(tip(storeName(c.store),
        [['Discounted', fmt.price(c.store.net)], ['Pump', fmt.price(c.store.retail)], ['Mile', fmt.count(c.miles)],
          ['Off the road', `${c.off_mi.toFixed(1)} mi`]]), { direction: 'top', offset: [0, -34] })
      .addTo(layer);
    return { marker, net: c.store.net, planned: planned.has(c.store.store_no) };
  });
}

// Shows the price bubbles that fit without covering each other: the planned stops' first, then the cheapest; the
// others show on hover only.
function declutter() {
  const kept = [];
  [...state.bubbles].sort((a, b) => b.planned - a.planned || a.net - b.net).forEach((b) => {
    const at = state.map.latLngToContainerPoint(b.marker.getLatLng());
    const free = kept.every((k) => Math.abs(k.x - at.x) > BUBBLE.w + BUBBLE.gap || Math.abs(k.y - at.y) > BUBBLE.h + BUBBLE.gap);
    b.marker.getElement()?.classList.toggle('no-bubble', !free);
    if (free) kept.push(at);
  });
}

// The map, made on first use (the view must be visible by then so it can measure itself), with dark street tiles.
function ensureMap() {
  if (!state.map) {
    state.map = L.map('plan-map', { preferCanvas: true });
    L.tileLayer(TILES, { maxZoom: 18, attribution: ATTRIBUTION }).addTo(state.map);
    state.layer = L.layerGroup().addTo(state.map);
    // the price bubbles hide while the map zooms (or flies to another plan); after, the ones that fit show again:
    // zooming in spreads the Love's out, so more bubbles fit
    const box = state.map.getContainer();
    state.map.on('zoomstart', () => box.classList.add('is-zooming'));
    state.map.on('zoomend', () => {
      box.classList.remove('is-zooming');
      declutter();
    });
    new ResizeObserver(() => state.map.invalidateSize()).observe(document.getElementById('plan-map'));
  }
  return state;
}

// A labelled mark on the map (`tag` holds the shape, so Leaflet can move the outer element) with a tooltip.
function pin(layer, kind, label, latlng, tooltip, tag = 'b') {
  const icon = L.divIcon({ className: `pin ${kind}`, html: `<${tag}>${label}</${tag}>`, iconSize: [26, 26] });
  L.marker(latlng, { icon }).bindTooltip(tooltip, { direction: 'top', offset: [0, -12] }).addTo(layer);
}

// The money of the load. Six figures for what was really bought (so far, until the load is done): at the pump, the
// discount off it, what EFS billed the company, what the drivers' cards charged them; then what the plan saves over
// the driver's usual way and what the real trip cost more than the plan. Below, the plan, the driver's habit simulated
// on the same road and what really happened side by side. Extra cost is company dollars, fuel left at the end counted
// at the price near the destination; the real trip's fuel left and extra cost show once the load is done.
function renderMoney(d) {
  const c = d.compare, a = c.actual, h = d.habit;
  document.getElementById('money-meta').textContent = 'At the pump: the gallons at pump prices. Discount: at the pump '
    + "less what EFS billed the company. Driver paid: what the drivers' cards charged them (pump + fee, pump, or the "
    + `billed amount; nothing on company-paid cards). Extra cost: company dollars, fuel left at the end counted at `
    + `${fmt.price(c.end_price)}/gal.`;
  document.getElementById('habit-line').textContent = h
    ? `Habit of ${personName(h.name)} (${h.stops} stops in the last ${d.habit_days} days): stops at ${level(h.stop_at_pct)}, fills to `
      + `${level(h.fill_to_pct)}, ${share(h.top_off_share)} top-offs, ${share(h.loves_share)} of gallons at Love's`
      + (h.outside_premium == null ? '' : `, ${fmt.price(h.outside_premium)}/gal more outside Love's`)
    : "No recent fuel stops for this truck's driver, so there is no habit to simulate.";
  const bought = a.gallons ? `${gal(a.gallons)} at ${a.stops} stop${a.stops === 1 ? '' : 's'}` : 'nothing bought yet';
  const realized = c.habit_extra != null && c.actual_extra != null ? `vs the habit: ${extra(c.actual_extra - c.habit_extra)}` : '';
  figures('money-stats', [
    ['At the pump', dollars(a.pump), bought],
    ['Discount', dollars(a.pump - a.bought), perGal(a.pump - a.bought, a.gallons)],
    ['Billed to the company', dollars(a.bought), perGal(a.bought, a.gallons)],
    ['Driver paid', dollars(a.driver_paid), perGal(a.driver_paid, a.gallons)],
    ['Plan saves vs the habit', c.habit_extra == null ? '—' : extra(c.habit_extra), 'the same road, the plan followed',
      c.habit_extra == null ? '' : c.habit_extra >= 0 ? 'on' : 'off'],
    ['Extra cost vs the plan', c.actual_extra == null ? 'after the load' : extra(c.actual_extra), realized,
      tone(c.actual_extra)],
  ]);
  const columns = [[c.plan, 'no plan'], [c.habit, 'no habit'], [a, '']];
  const line = (label, value) => row('td', [label, ...columns.map(([o, missing]) => (o ? value(o) : missing))], {}, 1);
  fillTable('plan-compare', row('th', ['', 'Plan', "Driver's habit", c.finished ? 'Actual' : 'Actual so far'], {}, 1), [
    line('Stops', (o) => o.stops),
    line('Gallons bought', (o) => gal(o.gallons)),
    line('At the pump', (o) => dollars(o.pump)),
    line('Discount', (o) => dollars(o.pump - o.bought)),
    line('Billed to the company', (o) => dollars(o.bought)),
    line('Billed per gallon', (o) => (o.gallons ? fmt.price(o.bought / o.gallons) : '—')),
    line('Driver paid', (o) => (o.driver_paid == null ? '—' : dollars(o.driver_paid))),
    line('Fuel left at the end', (o) => (o.end_gal == null ? 'after the load' : gal(o.end_gal))),
    row('td', ['Extra cost vs the plan', '—', extra(c.habit_extra), c.actual_extra == null ? 'after the load' : extra(c.actual_extra)],
      { 2: tone(c.habit_extra), 3: tone(c.actual_extra) }, 1),
  ]);
}

// Figure tiles in the box with this id: each a label, a value (colored by `cls`) and a small note under it.
function figures(id, tiles) {
  document.getElementById(id).replaceChildren(...tiles.map(([label, value, small, cls = '']) => {
    const tile = el('div', { class: 'money-stat' });
    tile.append(el('span', {}, label), el('b', { class: cls }, value), el('small', {}, small || ''));
    return tile;
  }));
}

// "$0.62/gal" for dollars over gallons; nothing without gallons.
const perGal = (value, gallons) => (gallons ? `${fmt.price(value / gallons)}/gal` : '');

// An extra cost in whole dollars with its sign: "+$188", "−$12"; a dash when there is none.
function extra(value) {
  if (value == null) return '—';
  return `${value >= 0 ? '+' : '−'}${dollars(Math.abs(value))}`;
}

// Red when a way of fueling cost more than the plan, green when less.
const tone = (value) => (value == null ? '' : value > 0 ? 'off' : 'on');

// "29%" for a gauge level; a dash when unknown.
const level = (pct) => (pct == null ? '—' : `${Math.round(pct)}%`);

// "45%" for a share from 0 to 1.
const share = (v) => `${Math.round(v * 100)}%`;

// The plan as a journey: the start, each planned stop with what became of it, then the end of the road.
function renderStops(d) {
  const p = d.plan, plan = p.plan, end = p.stops_ahead.at(-1);
  const head = row('th', ['#', "Love's", 'Mile', 'Arrive with', 'Buy', 'Discounted', 'Pump', 'Billed', 'Bought there']);
  const start = row('td', ['Start', town(p.truck.place), 0, gal(p.truck.fuel_pct / 100 * p.truck.tank_gal), '', '', '', '', '']);
  if (!plan) {
    fillTable('plan-stops', head, [start, note(9, `No plan keeps the ${d.reserve_pct}% reserve: the Love's on this road are too far apart for the fuel on board.`)]);
    return;
  }
  const outcomes = plan.stops.map((s, i) => outcome(s, i + 1, d));
  const rows = plan.stops.map((s, i) => row('td', [i + 1, storeName(s.store),
    fmt.count(s.miles), gal(s.arrive_gal), gal(s.gallons), fmt.price(s.store.net), fmt.price(s.store.retail),
    dollars(s.cost), outcomes[i].text], { 8: outcomes[i].cls }));
  const finish = row('td', ['End', `${end.city}, ${end.state}`, fmt.count(p.route_mi), gal(plan.end_gal), '', '', '', '', '']);
  const buy = plan.stops.reduce((s, x) => s + x.gallons, 0);
  const bought = d.trip.fills.filter((f) => f.plan_stop).reduce((s, f) => s + f.gallons, 0);
  fillTable('plan-stops', head, [start, ...rows, finish], plan.stops.length
    ? row('td', ['', 'Total', '', '', gal(buy), '', '', dollars(plan.fuel_cost), gal(bought)]) : null);
}

// What became of planned stop `n`: gallons bought there; "drove past" when the truck went by without buying;
// "skipped" when the load ended without going there; "ahead" while it hasn't got there yet.
function outcome(stop, n, d) {
  const gallons = d.trip.fills.filter((f) => f.plan_stop === n).reduce((s, f) => s + f.gallons, 0);
  if (gallons) return { text: gal(gallons), cls: 'on' };
  const at = [stop.store.lat, stop.store.lng];
  if (d.trip.track.some((p) => miles(p, at) <= d.stop_reached_mi)) return { text: 'drove past', cls: 'off' };
  return d.trip.finished_at ? { text: 'skipped', cls: 'off' } : { text: 'ahead', cls: '' };
}

// Every fill-up since the plan: when, where, how much, at what price, and whether it was a planned stop.
function renderFills(d) {
  const fills = d.trip.fills;
  const head = row('th', ['Time', 'Station', 'Where', 'Gallons', 'Pump $/gal', 'Billed $/gal', 'Planned stop']);
  if (!fills.length) {
    fillTable('plan-fills', head, [note(7, 'No diesel bought since the plan.')]);
    return;
  }
  const rows = fills.map((f) => row('td', [dayTime(f.at), station(f.station), `${capitalized(f.city)}, ${f.state}`, gal(f.gallons),
    fmt.price(f.pump / f.gallons), fmt.price(f.billed / f.gallons), f.plan_stop ? `#${f.plan_stop}` : 'none'],
  { 6: f.plan_stop ? 'on' : 'off' }));
  const sum = (key) => fills.reduce((s, f) => s + f[key], 0);
  const gallons = sum('gallons'), onPlan = fills.filter((f) => f.plan_stop).length;
  fillTable('plan-fills', head, rows, row('td', ['Total', '', '', gal(gallons), fmt.price(sum('pump') / gallons),
    fmt.price(sum('billed') / gallons), `${onPlan} of ${fills.length}`]));
}

// The fuel gauge from the plan to the end of the load (or now), the reserve line, and a line at each fill-up.
function renderGauge(d) {
  const amber = token('--brand'), good = token('--good'), bad = token('--bad');
  const fills = d.trip.fills.map((f) => ({
    xAxis: f.at, lineStyle: { color: f.plan_stop ? good : bad, type: 'solid', width: 1.5 },
    label: { formatter: `${Math.round(f.gallons)} gal`, color: f.plan_stop ? good : bad, position: 'end' },
  }));
  // Samsara only reads the gauge while the engine runs: a gap of over 2 hours breaks the line instead of bridging it.
  const readings = d.gauge.flatMap((r, i) => (i && new Date(r[0]) - new Date(d.gauge[i - 1][0]) > GAUGE_GAP_MS
    ? [[r[0], null], r] : [r]));
  const end = d.trip.finished_at || new Date();
  const days = new Date(end) - new Date(d.plan.made_at) > 24 * 60 * 60 * 1000;  // over a day: ticks name the weekday
  draw('chart-gauge', {
    grid: { left: 4, right: 20, top: 26, bottom: 4, containLabel: true },
    tooltip: {
      trigger: 'axis',
      formatter: (items) => tip(dayTime(items[0].value[0]), [['Fuel gauge', items[0].value[1] == null ? 'no reading' : `${items[0].value[1]}%`]]),
    },
    xAxis: { type: 'time', min: d.plan.made_at, max: end,
      axisLabel: { hideOverlap: true, formatter: (v) => (days ? dayClock(v) : clock(v)) } },  // Central, not this PC's zone
    yAxis: { type: 'value', min: 0, max: 100, interval: 25, axisLabel: { formatter: '{value}%' } },
    series: [{
      name: 'Fuel gauge', type: 'line', data: readings, showSymbol: d.gauge.length < 3, lineStyle: { width: 2, color: amber },
      itemStyle: { color: amber }, areaStyle: { color: fade(amber, 0.12) },
      markLine: {
        symbol: 'none', silent: true,
        data: [{ yAxis: d.reserve_pct, lineStyle: { color: bad, type: 'dashed' },
          label: { formatter: 'reserve', color: bad, position: 'insideEndTop' } }, ...fills],
      },
    }],
  });
}

// ---------- small helpers ----------

// A table row of `tag` cells; the first `left` columns read from the left, `classes` maps a column to a class.
function row(tag, cells, classes = {}, left = 2) {
  const tr = el('tr');
  cells.forEach((c, i) => tr.append(el(tag, { class: `${i < left ? 'left' : ''} ${classes[i] || ''}`.trim() }, c)));
  return tr;
}

// A row with one cell across `cols` columns, for a table that has nothing to list.
function note(cols, text) {
  const tr = el('tr', { class: 'note-row' });
  tr.append(el('td', { colspan: cols }, text));
  return tr;
}

// Puts a head row, body rows and an optional total row into the table with this id.
function fillTable(id, head, rows, foot) {
  const thead = el('thead'), tbody = el('tbody');
  thead.append(head);
  tbody.append(...rows);
  const parts = [thead, tbody];
  if (foot) {
    const tfoot = el('tfoot');
    tfoot.append(foot);
    parts.push(tfoot);
  }
  document.getElementById(id).replaceChildren(...parts);
}

// Tooltip HTML: a title, then label/value rows.
function tip(title, rows) {
  return `<div class="tt-title">${esc(title)}</div>${rows.map(([k, v]) => `<div class="tt-row"><span>${esc(k)}</span><b>${esc(v)}</b></div>`).join('')}`;
}

// Straight-line miles between two [lat, lng] points.
function miles(a, b) {
  const r = Math.PI / 180, dLat = (b[0] - a[0]) * r, dLng = (b[1] - a[1]) * r;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a[0] * r) * Math.cos(b[0] * r) * Math.sin(dLng / 2) ** 2;
  return 2 * 3958.8 * Math.asin(Math.sqrt(h));
}

// A color `share` (0 to 1) of the way from one "#rrggbb" color to another.
function mix(from, to, share) {
  const a = parseInt(from.slice(1), 16), b = parseInt(to.slice(1), 16);
  const channel = (shift) => Math.round(((a >> shift) & 255) * (1 - share) + ((b >> shift) & 255) * share);
  return `rgb(${channel(16)}, ${channel(8)}, ${channel(0)})`;
}

// Whole gallons: "138 gal".
const gal = (v) => `${Math.round(v)} gal`;

// Whole dollars: "$1,222".
const dollars = (v) => `$${Math.round(v).toLocaleString('en-US')}`;

// A station as people say it: "LOVES #614 TRAVEL STOP" -> "Love's #614"; other names shortened.
const station = (location) => stationName(location, /^LOVE'?S\b/i.test(location.trim()) ? "Love's" : 'other');

// The town and state of a Samsara address: "1425 Crooked Hill Road, Harrisburg, PA, 17110" -> "Harrisburg, PA".
function town(place) {
  if (!place) return 'where the truck was';
  return place.split(', ').filter((part) => !/^\d{5}$/.test(part)).slice(-2).join(', ');
}

