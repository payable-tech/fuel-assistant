// The Trends view: full weeks only. Figure cards for the last full week, Love's prices and discount with how they
// spread, related numbers stacked over the same weeks so their patterns line up, the discount by who paid, and recent
// breakdowns. It draws numbers; it writes no conclusions (anything worth saying should be visible in the charts).
import { bars, donut, draw, hbars, rangeRows, sparkline, stackedRows } from './charts.js';
import { el, ensureCards, setCard } from './dom.js';
import { change, dateOf, fmt, niceName, short, weekLabel } from './format.js';
import { NO_FUEL_DATA, STATION_COLOR } from './labels.js';
import { token } from './theme.js';

// Driver types: [key, name, color]; and the names of driver types and truck ownership as people say them.
const DRIVER_TYPES = [['lease', 'Lease', '--s1'], ['company_driver', 'Company driver', '--s2'],
  ['company_owner', 'Company owner', '--s3'], ['other', 'Other', '--s4'], ['unknown', 'Unknown', '--s6']];
const DRIVER_TYPE_NAME = Object.fromEntries(DRIVER_TYPES.map(([key, name]) => [key, name]));
const OWNERSHIP_NAME = { company: 'Company', rental: 'Rental', lease: 'Lease', owner_operator: 'Owner-operator', other: 'Other', unknown: 'Unknown' };

// The last full week's cards: each figure, how to show it, its mini trend's color, which way is better, its explanation.
const KPIS = [
  { key: 'gallons', label: 'Diesel bought', format: fmt.gallons, color: '--s1', tip: 'Gallons of diesel bought in the week.' },
  { key: 'spend', label: 'Fuel spend', format: fmt.money, color: '--s1', tip: 'What EFS billed the company for that diesel, after discounts.' },
  { key: 'price_per_gal', label: 'Price per gallon', format: fmt.price, color: '--s1', better: 'down', tip: 'Fuel spend divided by gallons. Lower is better.' },
  { key: 'discount', label: 'Discount kept', format: fmt.money, color: '--s3', better: 'up', tip: "Pump price minus what the company paid. Mostly the Love's discount." },
  { key: 'loves_share', label: "Bought at Love's", format: fmt.share, color: '--s2', better: 'up', points: true,
    tip: "Share of gallons bought at Love's, where the discount is. Higher is better." },
  { key: 'drivers', label: 'Drivers fueling', format: fmt.count, color: '--s4', tip: 'Different drivers who bought diesel in the week.' },
];

// The breakdown table: its tabs [key, name, how a row's name reads], and its columns [key, name, format].
const TABS = [
  ['company', 'Company', niceName], ['driver_type', 'Driver type', (n) => DRIVER_TYPE_NAME[n] || n],
  ['truck_ownership', 'Truck ownership', (n) => OWNERSHIP_NAME[n] || n], ['station', 'Station', (n) => n], ['state', 'State', (n) => n],
];
const COLUMNS = [
  ['spend', 'Spend', fmt.money], ['price_per_gal', '$/gal', fmt.price], ['loves_share', "At Love's", fmt.share],
  ['discount', 'Discount', fmt.money], ['billable_share', 'Billed to drivers', fmt.share], ['drivers', 'Drivers', fmt.count], ['trucks', 'Trucks', fmt.count],
];

let current = null;           // the numbers on screen, so a tab click can redraw the table
let currentTab = 'company';   // the breakdown tab being shown; kept across refreshes

// Axis label and tooltip title for weekly rows.
const WEEK = { tick: (w) => short(dateOf(w.week)), title: (w) => `Week of ${weekLabel(w.week)}` };

// A company name short enough for a chart label: "TAYLOR TRANSPORTS LLC" -> "Taylor Transports".
const shortCompany = (name) => niceName(name).replace(/\s+(LLC|INC|Corp)\.?$/i, '');

// The last full week's figure cards, each with its change against the 4 weeks before and a 12-week mini trend.
function renderKpis(d) {
  ensureCards(document.getElementById('kpis'), 'kpi', KPIS, true);
  KPIS.forEach((k) => {
    setCard(`kpi-${k.key}`, k.format(d.latest[k.key]), change(d.latest[k.key], d.before[k.key], k), 'vs 4-week average');
    draw(`kpi-spark-${k.key}`, sparkline(d.weeks.slice(-12).map((w) => w[k.key]), token(k.color)));
  });
  document.getElementById('trend-meta').textContent = `${d.weeks.length} full weeks, up to ${weekLabel(d.latest.week)}. `
    + 'Cards: the last full week against the average of the 4 before it.';
}

// Tooltip lines for a spread of Love's fills: average, where the middle 80% of the gallons were, the single extremes.
const spreadTip = (average, s, format) => [[average, format(s?.average)],
  ['Middle 80% of gallons', s ? `${format(s.low)} – ${format(s.high)}` : '—'],
  ['Lowest – highest fill', s ? `${format(s.lowest)} – ${format(s.highest)}` : '—']];

// Discount per gallon over all of a week's diesel, Love's or not.
const allDiscount = (w) => (w.gallons ? w.discount / w.gallons : null);

// Love's pump price and the discount per gallon, each an average line with where the middle 80% of the Love's gallons
// were shaded around it; the discount also over all our diesel and across all Love's stores. Under them, what we paid
// per gallon for all diesel, at Love's and outside Love's. Each line keeps its color in every row.
function renderLovesPrices(d) {
  draw('chart-loves', rangeRows(d.weeks, [
    { name: "Love's pump price per gallon", format: fmt.price, range: { low: (w) => w.loves_pump?.low, high: (w) => w.loves_pump?.high },
      lines: [{ name: "Love's pump price", color: token('--s2'), value: (w) => w.loves_pump?.average }] },
    { name: 'Discount per gallon', format: fmt.cents, range: { low: (w) => w.loves_discount?.low, high: (w) => w.loves_discount?.high },
      lines: [{ name: "At Love's", color: token('--s2'), value: (w) => w.loves_discount?.average },
        { name: 'All diesel', color: token('--s1'), value: allDiscount },
        { name: "Love's network average", color: token('--s4'), value: (w) => w.network_discount }] },
    { name: 'What we paid per gallon', format: fmt.price, lines: [
      { name: 'All diesel', color: token('--s1'), value: (w) => w.price_per_gal },
      { name: "At Love's", color: token('--s2'), value: (w) => w.loves_price_per_gal },
      { name: "Outside Love's", color: token('--s6'), value: (w) => w.outside_price_per_gal }] },
  ], {
    ...WEEK,
    tip: (w) => ["Love's pump price", ...spreadTip('Average', w.loves_pump, fmt.price),
      'Discount per gallon', ...spreadTip("At Love's", w.loves_discount, fmt.cents), ['All diesel', fmt.cents(allDiscount(w))],
      ["Love's network average", fmt.cents(w.network_discount)],
      'What we paid per gallon', ['All diesel', fmt.price(w.price_per_gal)], ["At Love's", fmt.price(w.loves_price_per_gal)],
      ["Outside Love's", fmt.price(w.outside_price_per_gal)],
      ["All diesel above Love's", w.price_per_gal == null || w.loves_price_per_gal == null ? '—' : fmt.cents1(w.price_per_gal - w.loves_price_per_gal)]],
  }));
}

// Spend with the things it is made of, one under another: gallons, drivers fueling, and price per gallon.
function renderSpendDrivers(d) {
  draw('chart-spend-drivers', stackedRows(d.weeks, [
    { name: 'Fuel spend', type: 'bar', color: token('--s1'), format: fmt.money, value: (w) => w.spend },
    { name: 'Diesel gallons', type: 'bar', color: token('--s1'), format: fmt.gallons, value: (w) => w.gallons },
    { name: 'Drivers fueling', type: 'bar', color: token('--s4'), format: fmt.count, value: (w) => w.drivers },
    { name: 'Price per gallon', type: 'line', color: token('--s2'), format: fmt.price, value: (w) => w.price_per_gal },
  ], WEEK));
}

// How much is bought at Love's, and what the rest cost above Love's price.
function renderOutsideWeekly(d) {
  draw('chart-outside', stackedRows(d.weeks, [
    { name: "Share bought at Love's", type: 'line', color: token('--s2'), format: fmt.percent, value: (w) => w.loves_share },
    { name: "Paid extra outside Love's", type: 'bar', color: token('--s6'), format: fmt.money, value: (w) => w.outside_extra },
  ], WEEK));
}

// Drivers fueling each week, stacked by driver type.
function renderDriverTypes(d) {
  const types = DRIVER_TYPES.filter(([key]) => d.weeks.some((w) => w.drivers_by_type[key]));
  draw('chart-drivers', bars(d.weeks, types.map(([key, name, color]) => ({ name, color: token(color), value: (w) => w.drivers_by_type[key] || 0 })),
    fmt.count, WEEK));
}

// Weekly discount, split by who paid for the fuel.
function renderDiscountWeekly(d) {
  draw('chart-discount-weekly', bars(d.weeks, [
    { name: 'Kept from drivers', color: token('--s1'), value: (w) => w.discount_billable },
    { name: 'On company fuel', color: token('--s3'), value: (w) => w.discount_company },
  ], fmt.money, { ...WEEK, extra: (w) => [['Per gallon', fmt.cents(allDiscount(w))]] }));  // a dash for a week with no gallons
}

// How the recent gallons split between station chains.
function renderStations(d) {
  draw('chart-stations', donut(d.recent.breakdowns.station.map((r) => ({ name: r.name, value: r.gallons, color: token(STATION_COLOR[r.name] || '--s6') })),
    fmt.gallons, { value: fmt.share(d.recent.total.loves_share), label: "at Love's" }));
}

// Love's share for each company against the whole fleet; companies clearly below the fleet are red.
function renderCompanies(d) {
  const fleet = d.recent.total.loves_share;
  const rows = d.recent.breakdowns.company.filter((r) => r.gallons >= 1000)  // tiny companies swing to 0% or 100% on a few fills
    .map((r) => ({ ...r, label: shortCompany(r.name) }));
  draw('chart-companies', hbars(rows, {
    value: (r) => r.loves_share, format: fmt.share, max: 1, color: (r) => token(r.loves_share < fleet - 0.02 ? '--bad' : '--s1'),
    tip: (r) => [['Gallons', fmt.gallons(r.gallons)], ["At Love's", fmt.share(r.loves_share)], ['Drivers', fmt.count(r.drivers)]],
    reference: { value: fleet, label: `Fleet ${fmt.share(fleet)}` },
  }));
}

// The 10 states where the most diesel was bought recently, with price and Love's share in the tooltip.
function renderStates(d) {
  const rows = d.recent.breakdowns.state.slice(0, 10).map((r) => ({ ...r, label: r.name }));
  draw('chart-states', hbars(rows, {
    value: (r) => r.gallons, format: fmt.gallons, color: () => token('--s1'),
    tip: (r) => [['Gallons', fmt.gallons(r.gallons)], ['Price per gallon', fmt.price(r.price_per_gal)], ["At Love's", fmt.share(r.loves_share)]],
  }));
}

// A gallons cell with a small bar showing the row's share of all gallons.
function gallonsCell(gallons, total, withBar) {
  const bar = withBar && el('span', { class: 'bar-track' },
    el('span', { class: 'bar-fill', style: `width: ${total ? (gallons / total) * 100 : 0}%` }));
  return el('td', {}, el('span', { class: 'bar-cell' }, el('span', {}, fmt.gallons(gallons)), bar));
}

// The breakdown table for the selected tab, with a total row; Love's shares clearly below the fleet stand out.
function renderBreakdownTable(d) {
  const [, title, nameOf] = TABS.find(([key]) => key === currentTab);
  document.querySelectorAll('#tabs button').forEach((b) => b.setAttribute('aria-selected', String(b.dataset.key === currentTab)));
  const total = d.recent.total;
  const row = (name, r, isTotal) => el('tr', {}, el('td', {}, name), gallonsCell(r.gallons, total.gallons, !isTotal),
    ...COLUMNS.map(([key, , format]) => {
      const below = key === 'loves_share' && !isTotal && r.loves_share != null && r.loves_share < total.loves_share - 0.02;
      return el('td', below ? { class: 'below' } : {}, format(r[key]));
    }));
  const head = el('tr', {}, el('th', {}, title), el('th', {}, 'Gallons'), ...COLUMNS.map(([, label]) => el('th', {}, label)));
  document.getElementById('breakdown-table').replaceChildren(el('thead', {}, head),
    el('tbody', {}, ...d.recent.breakdowns[currentTab].map((r) => row(nameOf(r.name), r, false))),
    el('tfoot', {}, row('All', total, true)));
}

// Builds the breakdown table's tab buttons, once: a click shows that tab's table.
export function initTrends() {
  document.getElementById('tabs').append(...TABS.map(([key, label]) => {
    const button = el('button', { type: 'button', role: 'tab', 'data-key': key }, label);
    button.addEventListener('click', () => {
      currentTab = key;
      if (current) renderBreakdownTable(current);  // nothing to redraw before the first numbers come
    });
    return button;
  }));
}

// Labels every "recent weeks" panel with the window it covers, e.g. "Last 4 full weeks · Sep 21 – Oct 18".
function labelRecent(d) {
  const text = `Last ${d.recent.weeks} full weeks · ${short(dateOf(d.recent.from))} – ${short(dateOf(d.latest.week, 6))}`;
  document.querySelectorAll('[data-recent]').forEach((p) => { p.textContent = text; });
}

// Draws the whole Trends view; with no fuel data yet, says how to load it.
export function renderTrends(d) {
  if (!d.weeks.length) {
    document.getElementById('trend-meta').textContent = NO_FUEL_DATA;
    return;
  }
  current = d;
  renderKpis(d);
  renderLovesPrices(d);
  renderSpendDrivers(d);
  renderOutsideWeekly(d);
  renderDriverTypes(d);
  renderDiscountWeekly(d);
  renderStations(d);
  renderCompanies(d);
  renderStates(d);
  renderBreakdownTable(d);
  labelRecent(d);
}
