// The Live view: the fuel plans (each message sent and what became of it, Love's share and the price and discount per
// gallon of our trucks beside the whole fleet's), this week so far against the same hours of last week, the newest
// purchases, who bought outside Love's this week, the last days one by one, and today so far.
import { bars, draw, lines } from './charts.js';
import { el, ensureCards, figure, setCard } from './dom.js';
import { change, dateOf, dayLabel, dayTick, fmt, plural, short, stationName, timeOf, weekLabel } from './format.js';
import { NO_FUEL_DATA, STATION_COLOR } from './labels.js';
import { initMessages, renderMessages } from './messages.js';
import { token } from './theme.js';

// The "This week so far" cards: each figure, how to show it, which way is better, and its explanation.
const PACE = [
  { key: 'gallons', label: 'Diesel bought', format: fmt.gallons, tip: 'Gallons of diesel bought since Monday.' },
  { key: 'spend', label: 'Fuel spend', format: fmt.money, tip: 'What EFS billed the company since Monday, after discounts.' },
  { key: 'price_per_gal', label: 'Price per gallon', format: fmt.price, better: 'down', tip: 'Fuel spend divided by gallons. Lower is better.' },
  { key: 'loves_share', label: "Bought at Love's", format: fmt.share, better: 'up', points: true,
    tip: "Share of gallons bought at Love's, where the discount is. Higher is better." },
  { key: 'outside_lines', label: "Fills outside Love's", format: fmt.count, better: 'down',
    tip: "Fuel stops at Pilot, TA and other stations, where the discount is a few cents." },
  { key: 'discount', label: 'Discount kept', format: fmt.money, better: 'up', tip: 'Pump price minus what the company paid, since Monday.' },
];

let seen = null;  // purchases already on screen, so new arrivals can be highlighted (none on the first draw)

// "This week so far" cards: each figure since Monday, with last week's figure at the same hour.
function renderPace(d) {
  ensureCards(document.getElementById('pace'), 'pace', PACE, false);
  PACE.forEach((p) => setCard(`pace-${p.key}`, p.format(d.this_week[p.key]),
    change(d.this_week[p.key], d.last_week_same[p.key], p), `last week by now ${p.format(d.last_week_same[p.key])}`));
  document.getElementById('live-meta').textContent =
    `Monday ${short(dateOf(d.week_start))} to ${timeOf(d.latest)} Central, against last week up to the same time`;
}

// One bar row: a name, a figure with an optional chip ({text, tone}), the bar's parts ({share of the bar 0-1, color
// token}), a note under it, and the rule on hover.
function meter(name, value, chip, parts, note, tip) {
  return el('div', { class: 'meter', title: tip },
    el('div', { class: 'meter-head' }, el('span', {}, name), el('b', {}, value), chip && el('span', { class: `delta ${chip.tone}` }, chip.text)),
    el('div', { class: 'meter-bar' }, ...parts.filter((x) => x.share > 0)
      .map((x) => el('i', { style: `width: ${x.share * 100}%; background: var(${x.color})` }))),
    el('div', { class: 'meter-note' }, note));
}

// Love's share of some fills as a bar row: gallons at Love's and elsewhere, and how far from the goal. `scope` starts the
// note: whose fills, from when.
function lovesMeter(name, s, target, tip, scope) {
  if (!s.gallons) return meter(name, '—', null, [], `${scope} · no fills yet`, tip);
  const gap = target - s.loves_share;
  return meter(name, fmt.share(s.loves_share), gap > 0 ? { text: `${(gap * 100).toFixed(1)} pts to goal`, tone: 'bad' } : { text: 'goal met', tone: 'good' },
    [{ share: s.loves_share, color: '--s2' }, { share: 1 - s.loves_share, color: '--s5' }],
    `${scope} · ${fmt.gallons(s.gallons)} · ${fmt.gallons(s.gallons * (1 - s.loves_share))} elsewhere`, tip);
}

// What some fills paid per gallon, or null while unknown (no fills, or a server that doesn't send `paid` yet).
const paidPerGal = (s) => (s.gallons && s.paid != null ? s.paid / s.gallons : null);

// The chip comparing what our stops paid per gallon with the whole fleet; paying less is good news. None while unknown.
function againstFleet(ours, fleet) {
  if (ours == null || fleet == null) return null;
  const cents = Math.round((fleet - ours) * 100);
  if (!cents) return { text: 'same as the fleet', tone: '' };
  return cents > 0 ? { text: `${cents}¢/gal less than the fleet`, tone: 'good' } : { text: `${-cents}¢/gal more than the fleet`, tone: 'bad' };
}

// What the company paid per gallon and the discount per gallon, at the stops we sent beside the whole fleet: a bar per
// discount, the price paid in the note under it, and on our stops a chip saying how their price compares with the fleet's.
function renderPerGallon(p) {
  const discount = (s) => (s.gallons ? s.discount / s.gallons : null);
  const top = Math.max(discount(p.at_stops) || 0, discount(p.fleet) || 0) / 0.9 || 1;  // the bigger bar fills 90%
  const note = (s) => `${paidPerGal(s) == null ? '' : `Paid ${fmt.price(paidPerGal(s))}/gal · `}${fmt.money(s.discount)} off on ${fmt.gallons(s.gallons)}`;
  const row = (name, s, color, chip, tip) => (s.gallons
    ? meter(name, `${fmt.cents(discount(s))}/gal`, chip, [{ share: discount(s) / top, color }], note(s), tip)
    : meter(name, '—', null, [], 'no fills yet', tip));
  document.getElementById('plans-discount').replaceChildren(
    row('At stops we sent', p.at_stops, '--s1', againstFleet(paidPerGal(p.at_stops), paidPerGal(p.fleet)),
      'Fills where the driver fueled at the stop we sent. The chip: what they paid per gallon against the whole fleet.'),
    row('Whole fleet', p.fleet, '--s2', null, "Every diesel fill of every truck, Love's or not."));
}

// The fuel plans since the first message to a driver: the messages, Love's share and the price and discount per gallon
// of our trucks beside the whole fleet's.
function renderPlans(d) {
  const p = d.plans;
  document.getElementById('plans-meta').textContent = `${dayLabel(p.since)}, 00:00 to ${timeOf(d.latest)} Central, the newest purchase`;
  renderMessages(p);
  const messaged = [...new Set(p.messages.map((m) => m.unit))];  // the trucks that got a message, in the order they did
  document.getElementById('plans-goal').textContent = `Share of diesel gallons · goal ${fmt.share(p.target)}`;
  document.getElementById('plans-loves').replaceChildren(
    lovesMeter(messaged.length ? `${plural(messaged.length, 'truck')} we messaged` : 'Trucks we messaged: none yet', p.live, p.target,
      "Their diesel bought after each one's first message. Live trucks with no message yet aren't counted."
        + (messaged.length ? `\nUnits: ${messaged.join(', ')}` : ''), "since each one's first message"),
    lovesMeter('Whole fleet', p.fleet, p.target, 'Diesel of every truck, every company.', `${p.fleet.trucks} trucks`));
  renderPerGallon(p);
}

// A period's name on the axis and in the tooltip: a day, a week from Monday, a month.
const month = (key, style) => new Date(+key.slice(0, 4), +key.slice(5, 7) - 1, 1).toLocaleDateString('en-US', style);
const PERIODS = {
  day: { now: 'Today', tick: (k) => dayTick(k), title: (k) => dayLabel(k) },
  week: { now: 'This week', tick: (k) => short(dateOf(k)), title: (k) => `Week of ${weekLabel(k)}` },
  month: { now: 'This month', tick: (k) => month(k, { month: 'short' }), title: (k) => month(k, { month: 'long', year: 'numeric' }) },
};
let period = 'week';  // the discount chart's period, kept across refreshes
let shown = null;     // the Live data on screen, to redraw when the period changes

// Wires the Live view's buttons, once: the messages' arrangement, and the discount chart's Day / Week / Month (a click
// redraws the chart for that period).
export function initLive() {
  initMessages();
  document.querySelectorAll('#discount-period button').forEach((b) => b.addEventListener('click', () => {
    period = b.dataset.p;
    if (shown) renderDiscount(shown);  // nothing to redraw before the first numbers come
  }));
}

// The discount kept and missed: the period in progress in three figures (the fleet on its own, our stops' part, missed
// outside Love's), then the finished periods as smooth stacked lines of the same three, the top line what each period
// could have kept. The period in progress stays out of the lines: cut short, it would drop like the fall we watch for.
function renderDiscount(d) {
  shown = d;
  const rows = d.discount[period], now = rows[rows.length - 1], kept = now.own + now.ours, names = PERIODS[period];
  document.querySelectorAll('#discount-period button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.p === period)));
  document.getElementById('discount-meta').textContent = `${names.now} so far: ${names.title(now.key)}, up to ${timeOf(d.latest)} Central`;
  document.getElementById('discount-figs').replaceChildren(
    figure('plan-fig', 'Fleet on its own', fmt.money(now.own), `${now.gallons ? fmt.cents(now.own / now.gallons) : '—'}/gal on ${fmt.gallons(now.gallons)}`, '--s2'),
    figure('plan-fig', 'At stops we sent', fmt.money(now.ours), `${kept ? fmt.share(now.ours / kept) : '—'} of the discount kept`, '--s1'),
    figure('plan-fig', "Missed outside Love's", fmt.money(now.missed), `estimated · ${fmt.gallons(now.outside_gallons)} outside Love's`, '--s5'));
  draw('chart-discount', lines(rows.slice(0, -1), [
    { name: 'Fleet on its own', color: token('--s2'), value: (r) => r.own },
    { name: 'At stops we sent', color: token('--s1'), value: (r) => r.ours },
    { name: "Missed outside Love's", color: token('--s5'), value: (r) => r.missed },
  ], fmt.money, {
    tick: (r) => names.tick(r.key), title: (r) => names.title(r.key), min: 0, smooth: true, stack: true, totalLabel: 'Could have kept',
    extra: (r) => [['Kept', fmt.money(r.own + r.ours)], ["Gallons outside Love's", fmt.gallons(r.outside_gallons)]],
  }));
}

// A table cell holding a station chip: colored dot plus a short station name.
function stationCell(row) {
  return el('td', { class: 'station' }, el('span', { class: 'chip', title: `${row.location}, ${row.city} ${row.state}` },
    el('i', { style: `background: ${token(STATION_COLOR[row.station] || '--s6')}` }), stationName(row.location, row.station)));
}

// The newest purchases, newest first: $/gal is what EFS billed (the pump price on hover), Discount the cents off the
// pump price, Saved those cents times the gallons. Stops outside Love's are marked; rows new since the last refresh
// light up.
function renderFeed(d) {
  const key = (r) => `${r.fueled_at}|${r.unit}|${r.gallons}`;
  const head = ['Time', 'Unit', 'Driver', 'Station', 'State', 'Gallons', '$/gal', 'Discount', 'Saved']
    .map((h) => el('th', h === 'Driver' || h === 'Station' ? { class: 'left' } : {}, h));  // text columns read from the left
  const rows = d.feed.map((r) => {
    const out = r.station !== "Love's";
    return el('tr', { class: `${out ? 'out' : ''} ${seen && !seen.has(key(r)) ? 'is-new' : ''}`.trim() },
      el('td', { class: 'when' }, timeOf(r.fueled_at)), el('td', {}, r.unit || '—'),
      el('td', { class: 'driver', title: r.driver || '' }, r.driver || '—'), stationCell(r), el('td', {}, r.state || '—'),
      el('td', {}, fmt.gallons(r.gallons)), el('td', { title: `Pump ${fmt.price(r.pump_per_gal)}/gal` }, fmt.price(r.price_per_gal)),
      el('td', out ? { class: 'below' } : {}, fmt.cents(r.discount_per_gal)),
      el('td', out ? { class: 'below' } : {}, fmt.dollars(r.discount_per_gal * r.gallons)));  // pump total minus billed
  });
  document.getElementById('feed-table').replaceChildren(el('thead', {}, el('tr', {}, ...head)), el('tbody', {}, ...rows));
  seen = new Set(d.feed.map(key));
  document.getElementById('feed-meta').textContent = `Newest ${d.feed.length} · times are Central`;
}

// Drivers who bought outside Love's this week, most paid above the cheapest Love's nearby first. A fill is compared
// once its place is looked up in Samsara and if a Love's is that close.
function renderOutside(d) {
  document.getElementById('outside-meta').textContent = `Drivers by what they paid above the cheapest Love's within `
    + `${d.near_mi} mi of each fill that day (Love's price sheet, the truck's GPS at the fill). The road ahead isn't `
    + 'known, so it is at most this much.';
  const list = document.getElementById('outside-list');
  if (!d.outside.length) {
    list.replaceChildren(el('li', { class: 'empty' }, "Nobody has bought outside Love's this week."));
  } else {
    list.replaceChildren(...d.outside.map((o) => {
      const untold = o.fills - o.told;
      const who = el('div', {}, el('div', { class: 'name' }, o.driver), el('div', { class: 'sub' },
        `Unit ${o.unit || '—'} · ${plural(o.fills, 'fill')} · ${fmt.gallons(o.gallons)} · last ${timeOf(o.last)}`));
      const rule = `A fill is compared once Samsara shows where the truck was (within about 15 min) and if a Love's is `
        + `within ${d.near_mi} mi of it.`;
      const above = el('div', { class: 'missed', title: rule }, el('b', {}, o.told ? fmt.money(o.paid_above) : '—'),
        el('div', { class: 'sub' }, (o.told ? (o.paid_above < 0 ? "below Love's nearby" : "above Love's nearby") : 'not compared')
          + (o.told && untold ? ` · ${untold} not compared` : '')));
      return el('li', {}, who, above);
    }));
  }
}

// Gallons per day for the last days, split into Love's and elsewhere.
function renderDays(d) {
  draw('chart-days', bars(d.daily, [
    { name: "At Love's", color: token('--s2'), value: (r) => r.loves_gallons },
    { name: 'Elsewhere', color: token('--s5'), value: (r) => r.outside_gallons },
  ], fmt.gallons, {
    tick: (r) => dayTick(r.day), title: (r) => dayLabel(r.day),
    extra: (r) => [['Spend', fmt.money(r.spend)], ['Fills', fmt.count(r.fills)], ["Fills outside Love's", fmt.count(r.outside_fills)]],
  }));
}

// Today's figures so far.
function renderToday(d) {
  const t = d.today;
  const stats = [
    ['Fills', fmt.count(t.lines)], ['Diesel bought', fmt.gallons(t.gallons)], ['Fuel spend', fmt.money(t.spend)],
    ['Drivers', fmt.count(t.drivers)], ["Fills outside Love's", fmt.count(t.outside_lines), t.outside_lines > 0],
  ];
  document.getElementById('today-stats').replaceChildren(...stats.map(([label, value, alarm]) =>
    el('div', { class: 'stat' }, el('span', {}, label), el('b', alarm ? { class: 'bad' } : {}, value))));
  document.getElementById('today-meta').textContent = `${dayLabel(d.latest)} · up to ${d.latest.slice(11, 16)} Central`;
}

// Draws the whole Live view; with no fuel data yet, says how to load it.
export function renderLive(d) {
  if (!d.latest) {
    document.getElementById('live-meta').textContent = NO_FUEL_DATA;
    return;
  }
  renderPlans(d);
  renderDiscount(d);
  renderPace(d);
  renderFeed(d);
  renderOutside(d);
  renderDays(d);
  renderToday(d);
}
