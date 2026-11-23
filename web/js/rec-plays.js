// The Recommend view's list of how it played out: each message we told a driver and what the driver did, the fills no
// message asked for, and what each purchase cost.
import { el } from './dom.js';
import { ago, dayTime, fmt } from './format.js';
import { STATES, storeName } from './labels.js';

// Why a stop was chosen, in words.
const REASONS = {
  range: 'in the fuel zone, saves the most', hard_stop: 'last before the reserve', tight: "under the reserve, nearest Love's",
  last: "last Love's in reach", low: "no Love's in reach", no_load: "no load: nearest Love's ahead",
  heading: "off the load's road: nearest Love's ahead",
};

// How it played out, newest first: each message and what the driver did, and the fills no message asked for. `now` (the
// plan now, or null) puts a row on top saying why nothing is told yet.
export function renderPlays(recommendations, ownFills, now) {
  const rows = [...recommendations.map((r) => [r.made_at, playItem(r)]), ...ownFills.map((p) => [p.at, ownItem(p)])]
    .sort((a, b) => new Date(b[0]) - new Date(a[0])).map(([, row]) => row);
  document.getElementById('rec-plays').replaceChildren(...(now ? [nowItem(now)] : []), ...rows);
}

// What came of a message: [its tone, what the driver did, the small print]. Purchases can come in hours late.
export function messageResult(r) {
  const o = r.outcome;
  if (r.status === 'repeat') return ['dim', 'Sent again by mistake', 'An engine bug, fixed: not counted'];
  if (o && o.there) return ['good', `Fueled there: ${fmt.wholeGallons(o.gallons)}`, `${dayTime(o.at)}${gaugeChange(o)}`];
  if (o) return ['warn', `Fueled elsewhere: ${fmt.wholeGallons(o.gallons)}`, `${o.where} · ${dayTime(o.at)}${gaugeChange(o)}${againstStop(o.saved)}`];
  if (r.status === 'replaced') return ['dim', 'Replaced', 'Changed before reaching it'];
  if (r.status === 'passed') return ['bad', 'Drove past', 'No fuel bought there'];
  if (r.status === 'fueled') return ['warn', 'Fueled', 'Where and how much: purchase not in yet'];
  if (r.status === 'load ended') return ['dim', 'Load ended', 'Before any fuel was bought'];
  return ['open', 'Not yet', 'Still on the way to it'];
}

// The row for now, when no stop is standing: why nothing has been told.
function nowItem(d) {
  return playRow('open', d.looked_at ? `Looked ${ago(new Date(d.looked_at))}` : '',
    part('Now', 'Nothing to tell yet', el('small', {}, nowWords(d))), el('div'));
}

// Why nothing is told yet, in words: no load, enough fuel, no Love's for a while, or the next stop and when it is told.
function nowWords(d) {
  const r = d.road;
  if (!r) return STATES[d.state] || d.state;
  if (r.decision === 'enough') return 'Enough fuel to reach delivery';
  if (r.reason === 'no_loves') return "A long stretch without a Love's, plenty of fuel for now";
  const next = r.loves.find((v) => v.stop.store.store_no === r.chosen);
  return next ? `Next: ${storeName(next.stop.store)}, told once within ${r.look_mi} mi` : 'Watching';
}

// One message and what came of it.
function playItem(r) {
  const [tone, did, small] = messageResult(r);
  const todo = r.then_station ? `Buy about ${fmt.wholeGallons(r.gallons)}, then fill up at ${r.then_station}` : 'Fill up';
  const told = r.sent_at ? `Sent to the driver, ${dayTime(r.sent_at)}` : 'Told (not sent)';
  const said = part(r.kind === 'urgent' ? `${told}: emergency` : told, `${r.station || 'Find a truck stop'}${r.retail ? ` · ${fmt.price(r.retail)}` : ''}`,
    el('small', {}, `${todo}${r.miles_ahead != null ? `, in ${fmt.miles(r.miles_ahead)}` : ''}`),
    el('small', {}, `Gauge ${fmt.level(r.gauge_pct)} then, arrive ${fmt.level(r.arrive_pct)}${REASONS[r.reason] ? ` · ${REASONS[r.reason]}` : ''}`));
  return playRow(tone, dayTime(r.made_at), said, didPart(did, el('small', {}, small), r.outcome && boughtTable(r.outcome)), r.text);
}

// A fill-up no message asked for: the driver's own choice, and what it cost.
function ownItem(p) {
  return playRow('warn', dayTime(p.at), part('Told', 'Nothing', el('small', {}, 'No message asked for this fill')),
    didPart(`Fueled on their own: ${fmt.wholeGallons(p.gallons)}`, el('small', {}, `${p.where}${gaugeChange(p)}`), boughtTable(p)));
}

// One row of the list: when, what we said, and what the driver did; its tone colors its edge; `title` shows on hover.
function playRow(tone, when, said, did, title) {
  return el('li', { class: `play ${tone}`, title }, el('div', { class: 'play-when' }, when), said, did);
}

// What we said in a row: a small heading, a line in bold, and the notes under it.
function part(heading, bold, ...notes) {
  return el('div', { class: 'play-part' }, el('span', {}, heading), el('b', {}, bold), ...notes);
}

// What the driver did in a row, and the notes under it.
function didPart(did, ...notes) {
  return el('div', { class: 'play-part play-did' }, el('span', {}, 'Driver did'), el('b', {}, did), ...notes);
}

// The gauge before and after a fill, once the driver's stops have it (refreshed daily); nothing until then.
function gaugeChange(p) {
  return p.gauge_before != null && p.gauge_after != null ? ` · gauge ${fmt.level(p.gauge_before)} → ${fmt.level(p.gauge_after)}` : '';
}

// What a purchase cost: the pump price, what the company paid, and the discount between them, per gallon and in all.
function boughtTable(o) {
  const row = (name, gal, total, cls = '') => el('tr', { class: cls }, el('th', {}, name), el('td', {}, fmt.price(gal)), el('td', {}, fmt.dollars(total)));
  return el('table', { class: 'bought' },
    el('thead', {}, el('tr', {}, el('th'), el('td', {}, 'Per gal'), el('td', {}, 'Total'))),
    el('tbody', {}, row('Pump price', o.pump, o.pump_total), row('Company paid', o.paid, o.paid_total),
      row('Discount saved', o.discount, o.discount_total, 'saved')));
}

// How a fill elsewhere compares with the stop we told, in whole dollars; nothing when they come out even.
function againstStop(saved) {
  const gap = Math.round(Math.abs(saved));
  if (!gap) return '';
  return saved > 0 ? ` · our stop would have saved ${fmt.dollars(gap)}` : ` · ${fmt.dollars(gap)} cheaper than our stop`;
}
