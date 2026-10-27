// The Live view: this week so far against the same hours of last week, the newest purchases, who bought outside
// Love's this week, the last days one by one, and today so far.
import { bars, draw } from './charts.js';
import { el, ensureCards, setCard } from './dom.js';
import { change, dateOf, dayLabel, dayTick, fmt, short, stationName, timeOf } from './format.js';
import { token } from './theme.js';

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
const STATION_COLOR = { "Love's": '--s2', 'Pilot / Flying J / One9': '--s1', 'TA / Petro': '--s3', 'Other stations': '--s6' };

let seen = null;  // purchases already on screen, so new arrivals can be highlighted (none on the first draw)

// "This week so far" cards: each figure since Monday, with last week's figure at the same hour.
function renderPace(d) {
  ensureCards(document.getElementById('pace'), 'pace', PACE, false);
  PACE.forEach((p) => setCard(`pace-${p.key}`, p.format(d.this_week[p.key]),
    change(d.this_week[p.key], d.last_week_same[p.key], p), `last week by now ${p.format(d.last_week_same[p.key])}`));
  document.getElementById('live-meta').textContent =
    `Monday ${short(dateOf(d.week_start))} to ${timeOf(d.latest)} Central, against last week up to the same time`;
}

// A table cell holding a station chip: colored dot plus a short station name.
function stationCell(row) {
  const td = el('td', { class: 'station' });
  const chip = el('span', { class: 'chip', title: `${row.location}, ${row.city} ${row.state}` });
  const dot = el('i');
  dot.style.background = token(STATION_COLOR[row.station] || '--s6');
  chip.append(dot, document.createTextNode(stationName(row.location, row.station)));
  td.append(chip);
  return td;
}

// The newest purchases, newest first; stops outside Love's are marked, and rows new since the last refresh light up.
function renderFeed(d) {
  const key = (r) => `${r.fueled_at}|${r.unit}|${r.gallons}`;
  const head = el('tr');
  ['Time', 'Unit', 'Driver', 'Station', 'State', 'Gallons', '$/gal', 'Discount'].forEach((h) =>
    head.append(el('th', h === 'Driver' || h === 'Station' ? { class: 'left' } : {}, h)));  // text columns read from the left
  const rows = d.feed.map((r) => {
    const out = r.station !== "Love's";
    const tr = el('tr', { class: `${out ? 'out' : ''} ${seen && !seen.has(key(r)) ? 'is-new' : ''}`.trim() });
    tr.append(el('td', { class: 'when' }, timeOf(r.fueled_at)), el('td', {}, r.unit || '—'),
      el('td', { class: 'driver', title: r.driver || '' }, r.driver || '—'), stationCell(r), el('td', {}, r.state || '—'),
      el('td', {}, fmt.gallons(r.gallons)), el('td', {}, fmt.price(r.price_per_gal)),
      el('td', out ? { class: 'below' } : {}, fmt.cents(r.discount_per_gal)));
    return tr;
  });
  const thead = el('thead');
  thead.append(head);
  const tbody = el('tbody');
  tbody.append(...rows);
  document.getElementById('feed-table').replaceChildren(thead, tbody);
  seen = new Set(d.feed.map(key));
  document.getElementById('feed-meta').textContent = `Newest ${d.feed.length} · times are Central`;
}

// Drivers who bought outside Love's this week, largest missed discount first.
function renderOutside(d) {
  const list = document.getElementById('outside-list');
  if (!d.outside.length) {
    list.replaceChildren(el('li', { class: 'empty' }, "Nobody has bought outside Love's this week."));
  } else {
    list.replaceChildren(...d.outside.map((o) => {
      const li = el('li');
      const who = el('div');
      who.append(el('div', { class: 'name' }, o.driver), el('div', { class: 'sub' },
        `Unit ${o.unit || '—'} · ${o.fills} fill${o.fills === 1 ? '' : 's'} · ${fmt.gallons(o.gallons)} · last ${timeOf(o.last)}`));
      const missed = el('div', { class: 'missed' });
      missed.append(el('b', {}, fmt.money(o.missed)), el('div', { class: 'sub' }, 'discount missed'));
      li.append(who, missed);
      return li;
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
  document.getElementById('today-stats').replaceChildren(...stats.map(([label, value, alarm]) => {
    const row = el('div', { class: 'stat' });
    row.append(el('span', {}, label), el('b', alarm ? { class: 'bad' } : {}, value));
    return row;
  }));
  document.getElementById('today-meta').textContent = `${dayLabel(d.latest)} · up to ${d.latest.slice(11, 16)} Central`;
}

// Draws the whole Live view; with no fuel data yet, says how to load it.
export function renderLive(d) {
  if (!d.latest) {
    document.getElementById('live-meta').textContent = 'No fuel data yet. Load it with: .venv\\Scripts\\python.exe src\\main.py fuel';
    return;
  }
  renderPace(d);
  renderFeed(d);
  renderOutside(d);
  renderDays(d);
  renderToday(d);
}
