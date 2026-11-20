// The Recommend view's map: every test truck with its fuel (before one is picked), or one truck's road with its fuel
// zones, the Love's on it with their prices, the load's stops, the stop told, the truck now, and what it really did (the
// road driven and its fill-ups). It owns the map and its marks.
import { el, tooltip } from './dom.js';
import { dayTime, fmt, personName } from './format.js';
import { FUEL_AMBER_PCT, FUEL_RED_PCT, STATES, VERDICTS, storeName } from './labels.js';
import { messageResult } from './rec-plays.js';
import { token } from './theme.js';

// the street map pictures under the marks, and the credit they need
const TILES = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
const ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>';
const BUBBLE = { w: 40, h: 16, gap: 4 };  // a Love's price bubble on screen, px: bubbles closer than this would overlap
const FIT = { padding: [36, 36] };  // room kept around a road when the map moves to it, px
const ZONE_WIDTH = 14;  // px: a fuel zone on the map, far wider than the road

let map = null;        // the Leaflet map, made on first use
let layer = null;      // the plan's marks: road, zones, Love's, stops, truck now
let tripLayer = null;  // what the truck really did: road driven and fill-ups
let bubbles = [];      // the Love's marks with their price bubbles, to keep the bubbles apart

// The plan now: the road, one wide fuel zone per tank (green to the reserve, red to empty), every Love's on it with its
// price (`price`: "net" or "retail"), those close to it but off it (`nearby`), the load's stops, the stop told, and the
// truck now. The map moves to it only when `moved` (another truck), so a refresh keeps where it was zoomed to.
export function drawPlan(d, moved, { price, nearby }) {
  clearMap();
  const r = d.road;
  if (r) {
    drawRoad(r.line);
    drawZones(r);
    drawLoves(r, price);
    if (nearby) drawNearby(r, price);
    drawLoadStops(r.stops);
    drawStopPins(r);
  }
  drawNow(d);
  if (moved) fitTo([...(r ? r.line : []), ...(d.at ? [d.at] : [])]);
  declutter();
}

// Every test truck where it is now (`trucks`: those with a place), its fuel above it in a small bubble: red at the
// reserve or under, amber at a quarter tank or under, grey while its gauge is silent. Where bubbles would overlap, the
// lowest fuel keeps its own. A click on a truck calls `onPick` with its unit. The map moves to them all only when `moved`.
export function drawFleet(trucks, moved, onPick) {
  clearMap();
  bubbles = trucks.map((t) => {
    const icon = L.divIcon({ className: `truck-fuel ${fuelTone(t)}`.trim(), iconSize: [12, 12], html: `<b>${fmt.level(t.fuel_pct)}</b><i></i>` });
    const rows = [['Fuel', fmt.level(t.fuel_pct)], ['Driver', personName(t.driver)], ['Now', STATES[t.state] || t.state],
      ...(t.told ? [['Stop told', t.told]] : []), ['Where', t.place || '—']];
    const marker = L.marker(t.where, { icon, riseOnHover: true, zIndexOffset: Math.round(100 - (t.fuel_pct ?? 100)) * 100 })
      .bindTooltip(tooltip(`Unit ${t.unit}${t.live ? ' · live' : ''}`, rows), { direction: 'top', offset: [0, -32] })
      .on('click', () => onPick(t.unit)).addTo(layer);
    return { marker, net: t.fuel_pct ?? 101, first: 0 };  // declutter keeps the lowest fuel's bubble first
  });
  if (moved) fitTo(trucks.map((t) => t.where));
  declutter();
}

// How a truck's fuel bubble is colored: "stale" while its gauge is silent, "low" at the reserve or under, "mid" at a
// quarter tank or under, else plain.
function fuelTone(t) {
  if (t.fuel_pct == null || t.state === 'no fresh gauge') return 'stale';
  return t.fuel_pct <= FUEL_RED_PCT ? 'low' : t.fuel_pct <= FUEL_AMBER_PCT ? 'mid' : '';
}

// A past trip: the road planned, the load's stops, a pin at each stop told, then the road driven and its fill-ups.
export function drawPast(p, moved) {
  clearMap();
  drawRoad(p.line);
  drawLoadStops(p.stops);
  p.recommendations.filter((r) => r.where && r.status !== 'repeat').forEach((r) => pin(layer, 'pin-plan', '⛽', r.where,
    tooltip(`${r.sent_at ? 'Sent' : 'Told'} ${dayTime(r.made_at)} · ${r.station || 'truck stop'}`,
      [['Driver did', messageResult(r)[1]], ['Arrive', fmt.level(r.arrive_pct)]])));
  drawTrip(p);
  if (moved) fitTo([...p.line, ...p.track]);
  declutter();
}

// What really happened: the road driven and where it fueled, green where we told the driver, amber elsewhere.
export function drawTrip(trip) {
  ensureMap();
  tripLayer.clearLayers();
  if (trip.track.length > 1) L.polyline(trip.track, { color: token('--brand'), weight: 3 }).addTo(tripLayer);
  trip.fills.forEach((f) => pin(tripLayer, `pin-fill ${f.told ? 'on-plan' : 'own'}`, '', [f.lat, f.lng], tooltip(`${dayTime(f.at)} · ${f.station}`, [
    ['Fill', f.told ? 'Where we told the driver' : 'Somewhere else'], ['Where', `${f.city}, ${f.state}`], ['Gallons', fmt.wholeGallons(f.gallons)],
    ['Paid', `${fmt.price(f.paid)}/gal`]]), 'i'));
}

// The note over the top of the map, saying why a truck or trip didn't load; no text hides it.
export function mapNote(text) {
  const box = document.getElementById('rec-note');
  box.className = text ? 'map-note failed' : 'map-note';
  if (text) box.replaceChildren(el('span', {}, text));
}

// ---------- the parts ----------

// The map, made on first use (the view must be visible by then so it can measure itself), with dark street tiles.
function ensureMap() {
  if (map) return;
  map = L.map('rec-map', { preferCanvas: true }).setView([37, -96], 4);
  L.tileLayer(TILES, { maxZoom: 18, attribution: ATTRIBUTION }).addTo(map);
  layer = L.layerGroup().addTo(map);
  tripLayer = L.layerGroup().addTo(map);
  const box = map.getContainer();
  map.on('zoomstart', () => box.classList.add('is-zooming'));  // the price bubbles hide while zooming
  map.on('zoomend', () => {
    box.classList.remove('is-zooming');
    declutter();
  });
  new ResizeObserver(() => map.invalidateSize()).observe(document.getElementById('rec-map'));
}

// Takes every mark off the map, before drawing a plan or a trip.
function clearMap() {
  ensureMap();
  layer.clearLayers();
  tripLayer.clearLayers();
  bubbles = [];
}

// Moves the map to show these points: a single point up close, several all in view; none leaves it where it is.
function fitTo(points) {
  if (points.length === 1) map.setView(points[0], 7, { animate: false });
  else if (points.length) map.fitBounds(L.latLngBounds(points), { ...FIT, animate: false });
}

// A labelled mark on the map (`tag` holds the shape, so Leaflet can move the outer element) with a tooltip.
function pin(target, kind, label, latlng, tip, tag = 'b') {
  const icon = L.divIcon({ className: `pin ${kind}`, html: `<${tag}>${label}</${tag}>`, iconSize: [26, 26] });
  return L.marker(latlng, { icon }).bindTooltip(tip, { direction: 'top', offset: [0, -12] }).addTo(target);
}

// The road planned, as a thin blue line (nothing when it wasn't kept).
function drawRoad(line) {
  if (line.length > 1) L.polyline(line, { color: token('--s1'), weight: 3, opacity: 0.55 }).addTo(layer);
}

// One fuel zone per tank: green from where to fuel to the reserve, red from the reserve to empty.
function drawZones(r) {
  r.zones.forEach((z) => {
    band(z.safe, '--good', tooltip('Fuel zone', [['Starts in', fmt.miles(Math.max(z.start_mi - r.mile, 0))], ['Reserve in', fmt.miles(z.reserve_mi - r.mile)]]));
    band(z.risky, '--bad', tooltip('Under reserve, then empty', [['Reserve in', fmt.miles(z.reserve_mi - r.mile)], ['Runs out in', fmt.miles(z.end_mi - r.mile)]]));
  });
}

// A stretch of a fuel zone: wide, square-ended, so the green meets the red exactly where the reserve is.
function band(line, color, tip) {
  if (line.length < 2) return;
  L.polyline(line, { color: token(color), weight: ZONE_WIDTH, opacity: 0.4, lineCap: 'butt', lineJoin: 'round' }).addTo(layer).bindTooltip(tip, { sticky: true });
}

// The load's pickups (P) and deliveries (D).
function drawLoadStops(stops) {
  stops.forEach((s) => pin(layer, 'pin-load', s.kind === 'pickup' ? 'P' : 'D', [s.lat, s.lng],
    tooltip(`${s.kind === 'pickup' ? 'Pickup' : 'Delivery'} · ${s.city}, ${s.state}`, [])));
}

// The stop told (or chosen), and where to fill up after a part fill.
function drawStopPins(r) {
  r.loves.forEach((v) => {
    const no = v.stop.store.store_no, at = [v.stop.store.lat, v.stop.store.lng];
    if (no === r.chosen) pin(layer, 'pin-plan', '⛽', at, tooltip(`${r.told ? 'Stop told' : 'Stop chosen'} · ${storeName(v.stop.store)}`, stopRows(v, r)));
    if (no === r.then) pin(layer, 'pin-then', '⛽', at, tooltip(`Fill up here after the part fill · ${storeName(v.stop.store)}`, stopRows(v, r)));
  });
}

// The truck now, a pulsing dot, when its place is known.
function drawNow(d) {
  if (d.at) pin(layer, 'pin-now', '', d.at, tooltip(`Unit ${d.unit} now`, [['Fuel', fmt.level(d.fuel_pct)], ['Where', d.place || '—']]), 'i');
}

// Every Love's on the road with its price on the map (company or pump, by the toggle). Those already driven past are
// dimmed; when the bubbles don't all fit, the stop and the zones' ones go first, those behind the truck last.
function drawLoves(r, price) {
  bubbles = r.loves.map((v) => {
    const s = v.stop.store, ahead = v.verdict !== 'passed';
    const icon = L.divIcon({ className: `loves${ahead ? '' : ' dim'}`, iconSize: [12, 12], html: `<b>${fmt.price(s[price])}</b><i></i>` });
    const marker = L.marker([s.lat, s.lng], { icon, zIndexOffset: ahead ? -1000 : -2000, riseOnHover: true })
      .bindTooltip(tooltip(storeName(s), stopRows(v, r)), { direction: 'top', offset: [0, -34] }).addTo(layer);
    const inZone = r.zones.some((z) => z.start_mi <= v.stop.miles && v.stop.miles <= z.end_mi);
    const first = ahead ? (s.store_no === r.chosen || s.store_no === r.then ? 2 : 0) + (inZone ? 1 : 0) : -1;
    return { marker, net: s[price], first };
  });
}

// The Love's close to the road but off it, by the toggle (the rules take one only when none on the road is in reach;
// one chosen or told has its stop pin instead).
function drawNearby(r, price) {
  bubbles.push(...r.nearby.filter((c) => c.store.store_no !== r.chosen).map((c) => {
    const s = c.store;
    const icon = L.divIcon({ className: 'loves off', iconSize: [12, 12], html: `<b>${fmt.price(s[price])}</b><i></i>` });
    const marker = L.marker([s.lat, s.lng], { icon, zIndexOffset: -1000, riseOnHover: true })
      .bindTooltip(tooltip(storeName(s), [['Off the road', `${c.off_mi.toFixed(1)} mi`], ['Company price', fmt.price(s.net)], ['Pump', fmt.price(s.retail)],
        ['Miles ahead', fmt.count(c.miles - r.mile)], ['Arrive', fmt.level(c.arrive_pct)], ['Worst case', fmt.level(c.worst_pct)]]), { direction: 'top', offset: [0, -34] }).addTo(layer);
    return { marker, net: s[price], first: 0 };
  }));
}

// One Love's in figures, for its tooltip; one already driven past shows how far back it is instead of arrival levels.
function stopRows(v, r) {
  const prices = [['Company price', fmt.price(v.stop.store.net)], ['Pump', fmt.price(v.stop.store.retail)]];
  if (v.verdict === 'passed') return [['Verdict', VERDICTS[v.verdict]], ...prices, ['Miles back', fmt.count(r.mile - v.stop.miles)]];
  return [['Verdict', VERDICTS[v.verdict]], ...prices, ['Miles ahead', fmt.count(v.stop.miles - r.mile)], ['Arrive', fmt.level(v.arrive_pct)], ['Worst case', fmt.level(v.worst_pct)]];
}

// Shows the bubbles that fit without covering each other, zooming in fits more: on a plan the stop chosen first, then
// the zones', then the cheapest price; on the map of all trucks the lowest fuel first. The others show on hover.
function declutter() {
  const kept = [];
  [...bubbles].sort((a, b) => b.first - a.first || a.net - b.net).forEach((b) => {
    const at = map.latLngToContainerPoint(b.marker.getLatLng());
    const free = kept.every((k) => Math.abs(k.x - at.x) > BUBBLE.w + BUBBLE.gap || Math.abs(k.y - at.y) > BUBBLE.h + BUBBLE.gap);
    b.marker.getElement()?.classList.toggle('no-bubble', !free);
    if (free) kept.push(at);
  });
}
