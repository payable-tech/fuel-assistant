// The Trends view: full weeks only. Figure cards for the last full week, what we paid against the market, related
// numbers stacked over the same weeks so their patterns line up, the discount by who paid, and recent breakdowns.
// It draws numbers; it writes no conclusions (anything worth saying should be visible in the charts).
import { bars, donut, draw, gapChart, hbars, sparkline, stackedRows } from './charts.js';
import { el, ensureCards, setCard } from './dom.js';
import { change, dateOf, fmt, niceName, short, weekLabel } from './format.js';
import { token } from './theme.js';

const DRIVER_TYPES = [['lease', 'Lease', '--s1'], ['company_driver', 'Company driver', '--s2'],
  ['company_owner', 'Company owner', '--s3'], ['other', 'Other', '--s4'], ['unknown', 'Unknown', '--s6']];
const DRIVER_TYPE_NAME = Object.fromEntries(DRIVER_TYPES.map(([key, name]) => [key, name]));
const OWNERSHIP_NAME = { company: 'Company', rental: 'Rental', lease: 'Lease', owner_operator: 'Owner-operator', other: 'Other', unknown: 'Unknown' };
const STATION_COLOR = { "Love's": '--s2', 'Pilot / Flying J / One9': '--s1', 'TA / Petro': '--s3', 'Other stations': '--s6' };

const KPIS = [
  { key: 'gallons', label: 'Diesel bought', format: fmt.gallons, color: '--s1', tip: 'Gallons of diesel bought in the week.' },
  { key: 'spend', label: 'Fuel spend', format: fmt.money, color: '--s1', tip: 'What EFS billed the company for that diesel, after discounts.' },
  { key: 'price_per_gal', label: 'Price per gallon', format: fmt.price, color: '--s1', better: 'down', tip: 'Fuel spend divided by gallons. Lower is better.' },
  { key: 'discount', label: 'Discount kept', format: fmt.money, color: '--s3', better: 'up', tip: "Pump price minus what the company paid. Mostly the Love's discount." },
  { key: 'loves_share', label: "Bought at Love's", format: fmt.share, color: '--s2', better: 'up', points: true,
    tip: "Share of gallons bought at Love's, where the discount is. Higher is better." },
  { key: 'drivers', label: 'Drivers fueling', format: fmt.count, color: '--s4', tip: 'Different drivers who bought diesel in the week.' },
];

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

// Axis labels for shares: whole percents.
const percent = (v) => `${Math.round(v * 100)}%`;

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

// Saved per gallon over the 4 weeks up to each week (all saved ÷ all gallons), so one odd week can't hide the
// trend; none for the first 3 weeks on screen, which have fewer than 4 weeks behind them.
function savedLast4(weeks) {
  return weeks.map((w, i) => {
    if (i < 3) return null;
    const span = weeks.slice(i - 3, i + 1);
    if (span.some((x) => x.saved_vs_market == null)) return null;  // a week with no market price yet
    return span.reduce((s, x) => s + x.saved_vs_market, 0) / span.reduce((s, x) => s + x.gallons, 0);
  });
}

// Each week's diesel priced at the market against what we paid for it; the space between is what our choices
// saved. Below it, that saving per gallon, the number that shows whether fuel decisions get better or worse.
function renderVsMarket(d) {
  const average = savedLast4(d.weeks);
  const rows = d.weeks.map((w, i) => ({ ...w, saved_4w: average[i] }));
  draw('chart-vs-market', gapChart(rows, {
    upper: { name: 'Our diesel at market price', color: token('--s6'), value: (w) => w.market_value },
    lower: { name: 'What we paid', color: token('--s1'), value: (w) => w.spend },
    band: 'Paid below market',
    gap: { name: 'Saved per gallon', averageName: '4-week average', color: token('--s3'), format: fmt.cents,
      value: (w) => w.saved_per_gal, average: (w) => w.saved_4w },
  }, {
    ...WEEK, format: fmt.money,
    tip: (w) => [['Gallons', fmt.gallons(w.gallons)], ['At market price', fmt.money(w.market_value)], ['What we paid', fmt.money(w.spend)],
      ['Paid below market', fmt.money(w.saved_vs_market)], ['Market price per gallon', fmt.price(w.market_per_gal)],
      ['Our price per gallon', fmt.price(w.price_per_gal)], ['Saved per gallon', fmt.cents1(w.saved_per_gal)],
      ['4-week average', fmt.cents1(w.saved_4w)]],
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

// Discount per gallon with the things it is made of: Love's price and discount, and how much is bought at Love's.
function renderDiscountDrivers(d) {
  draw('chart-discount-drivers', stackedRows(d.weeks, [
    { name: "Love's price per gallon", type: 'line', color: token('--s2'), format: fmt.price, value: (w) => w.loves_price_per_gal },
    { name: "Love's discount per gallon", type: 'line', color: token('--s3'), format: fmt.cents, value: (w) => w.loves_discount_per_gal },
    { name: "Share bought at Love's", type: 'line', color: token('--s2'), format: percent, value: (w) => w.loves_share },
    { name: 'Discount per gallon, all diesel', type: 'line', color: token('--s3'), format: fmt.cents, value: (w) => (w.gallons ? w.discount / w.gallons : null) },
  ], WEEK));
}

// Drivers fueling each week, stacked by driver type.
function renderDrivers(d) {
  const types = DRIVER_TYPES.filter(([key]) => d.weeks.some((w) => w.drivers_by_type[key]));
  draw('chart-drivers', bars(d.weeks, types.map(([key, name, color]) => ({ name, color: token(color), value: (w) => w.drivers_by_type[key] || 0 })),
    fmt.count, WEEK));
}

// Weekly discount, split by who paid for the fuel.
function renderDiscount(d) {
  draw('chart-discount', bars(d.weeks, [
    { name: 'Kept from drivers', color: token('--s1'), value: (w) => w.discount_billable },
    { name: 'On company fuel', color: token('--s3'), value: (w) => w.discount_company },
  ], fmt.money, { ...WEEK, extra: (w) => [['Per gallon', fmt.cents(w.discount / w.gallons)]] }));
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
  const td = el('td');
  const wrap = el('span', { class: 'bar-cell' });
  wrap.append(el('span', {}, fmt.gallons(gallons)));
  if (withBar) {
    const track = el('span', { class: 'bar-track' });
    const fill = el('span', { class: 'bar-fill' });
    fill.style.width = `${total ? (gallons / total) * 100 : 0}%`;
    track.append(fill);
    wrap.append(track);
  }
  td.append(wrap);
  return td;
}

// The breakdown table for the selected tab, with a total row; Love's shares clearly below the fleet stand out.
function renderTable(d) {
  const [, title, nameOf] = TABS.find(([key]) => key === currentTab);
  document.querySelectorAll('#tabs button').forEach((b) => b.setAttribute('aria-selected', String(b.dataset.key === currentTab)));
  const total = d.recent.total;
  const row = (name, r, isTotal) => {
    const tr = el('tr');
    tr.append(el('td', {}, name), gallonsCell(r.gallons, total.gallons, !isTotal), ...COLUMNS.map(([key, , format]) => {
      const below = key === 'loves_share' && !isTotal && r.loves_share != null && r.loves_share < total.loves_share - 0.02;
      return el('td', below ? { class: 'below' } : {}, format(r[key]));
    }));
    return tr;
  };
  const head = el('tr');
  head.append(el('th', {}, title), el('th', {}, 'Gallons'), ...COLUMNS.map(([, label]) => el('th', {}, label)));
  const thead = el('thead');
  thead.append(head);
  const tbody = el('tbody');
  tbody.append(...d.recent.breakdowns[currentTab].map((r) => row(nameOf(r.name), r, false)));
  const tfoot = el('tfoot');
  tfoot.append(row('All', total, true));
  document.getElementById('breakdown-table').replaceChildren(thead, tbody, tfoot);
}

// The tab buttons (built once) and the table for the selected tab.
function renderBreakdown(d) {
  const tabs = document.getElementById('tabs');
  if (!tabs.children.length) {
    tabs.append(...TABS.map(([key, label]) => {
      const button = el('button', { type: 'button', role: 'tab', 'data-key': key }, label);
      button.addEventListener('click', () => { currentTab = key; renderTable(current); });
      return button;
    }));
  }
  renderTable(d);
}

// Labels every "recent weeks" panel with the window it covers, e.g. "Last 4 full weeks · Sep 21 – Oct 18".
function labelRecent(d) {
  const text = `Last ${d.recent.weeks} full weeks · ${short(dateOf(d.recent.from))} – ${short(dateOf(d.latest.week, 6))}`;
  document.querySelectorAll('[data-recent]').forEach((p) => { p.textContent = text; });
}

// Draws the whole Trends view; with no fuel data yet, says how to load it.
export function renderTrends(d) {
  current = d;
  if (!d.weeks.length) {
    document.getElementById('trend-meta').textContent = 'No fuel data yet. Load it with: .venv\\Scripts\\python.exe src\\main.py fuel';
    return;
  }
  renderKpis(d);
  renderVsMarket(d);
  renderSpendDrivers(d);
  renderDiscountDrivers(d);
  renderDrivers(d);
  renderDiscount(d);
  renderStations(d);
  renderCompanies(d);
  renderStates(d);
  renderBreakdown(d);
  labelRecent(d);
}
