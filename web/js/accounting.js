// Accounting view: one EFS statement as a tree of boxes (the top box is everything it charged; a click on a box opens
// what it is made of under it, and so on down, like a skill tree; open boxes stay open across refreshes), then the
// checks on its fills: the statement in numbers and Love's promised price against what was charged.
import { el, figure } from './dom.js';
import { dateOf, fmt, personName, stationName } from './format.js';

// The statement picked (null: the newest), the open boxes by their path of names (null: just the top one, on a new
// statement) and the numbers last loaded.
const state = { picked: null, open: null, data: null };

// A box's color, by what it is: EFS's row, where it was bought, or who pays. Any other box takes its parent's color.
const TONES = {
  what: { Diesel: '--s2', DEF: '--s1', 'Money codes': '--s4', Credits: '--s5', Scales: '--s6', 'Unleaded gas': '--s6',
    Merchandise: '--s6', Other: '--s6', 'Transaction fees': '--s6' },
  where: { "Love's": '--s2', Elsewhere: '--s5', 'Not in Datatruck': '--bad' },
  payer: { 'Charged back to drivers': '--s3', Company: '--text', 'Not in Datatruck': '--bad' },
};
// The color of each verdict on a Love's fill.
const VERDICT_TONES = {
  'As promised': '--good', 'Charged more than the sheet': '--bad', 'Charged less than the sheet': '--s1',
  'No deal: store not on the sheet': '--warn', 'No sheet that day': '--faint',
  'Gauge rose, truck at the station': '--good', 'Gauge rose less than the gallons': '--warn', "Gauge didn't rise": '--bad',
  'Truck elsewhere at the fill': '--bad', 'No gauge readings': '--faint', 'Truck not in Samsara': '--faint',
  'Not looked up yet': '--faint',
};
const UNEXPLAINED_WARN_GAL = 50;  // a truck's unexplained diesel from this much shows amber, from twice it red

// Wires the statement picker (a new pick opens only the top box and loads it through `reload`) and the clicks on boxes.
export function initAccounting(reload) {
  const pick = document.getElementById('acct-statement');
  pick.addEventListener('change', () => {
    state.picked = pick.value;
    state.open = null;
    reload();
  });
  document.getElementById('acct-tree').addEventListener('click', (event) => {
    const box = event.target.closest('.cube[aria-expanded]');
    if (!box) return;
    const path = box.dataset.path;
    if (state.open.has(path)) state.open.delete(path); else state.open.add(path);
    drawTree();
    // the tree re-centers as it grows: bring the box clicked back to the middle, so it stays under the eye
    const again = document.querySelector(`#acct-tree [data-path="${CSS.escape(path)}"]`);
    again.scrollIntoView({ block: 'nearest', inline: 'center' });
  });
}

// Where the numbers for the picked statement are read from.
export function accountingPath() {
  return state.picked ? `/api/accounting?statement=${encodeURIComponent(state.picked)}` : '/api/accounting';
}

// Draws the picker, the statement's line under the title and its tree.
export function renderAccounting(data) {
  state.data = data;
  const pick = document.getElementById('acct-statement');
  pick.hidden = !data.statement;
  pick.replaceChildren(...data.statements.map((s) => el('option', { value: s.statement_no },
    `${longDate(s.statement_day)} · ${s.account} · ${fmt.exact(s.charges)}`)));
  const s = data.statement;
  if (s) {
    pick.value = s.statement_no;
    document.getElementById('acct-meta').textContent = `Statement ${s.statement_no} · ${s.account} · purchases `
      + `${longDate(s.first_day)} to ${longDate(s.last_day)}`;
    state.open = state.open || new Set([data.tree.label]);
  }
  drawTree();
  drawChecks(data.checks);
}

// Draws the checks under the tree: the statement in numbers, the Love's verdicts and the fills not as promised.
function drawChecks(checks) {
  const head = checks && checks.headline;
  document.getElementById('acct-headline').replaceChildren(...(head ? [
    figure('plan-fig', 'Card swipes', fmt.count(head.swipes), 'one swipe can buy diesel and DEF'),
    figure('plan-fig', 'Diesel fills', fmt.count(head.diesel_fills), `${fmt.count(head.diesel_gallons)} gal`),
    figure('plan-fig', 'Trucks', fmt.count(head.units), 'Datatruck units on the purchases'),
    figure('plan-fig', 'Drivers', fmt.count(head.drivers), 'Datatruck drivers on the purchases'),
    figure('plan-fig', 'Money codes', fmt.count(head.money_codes), 'who got them is not on the statement'),
  ] : []));
  const loves = checks ? checks.loves : { groups: [], odd: [] };
  document.getElementById('acct-loves').replaceChildren(
    el('thead', {}, el('tr', {}, ...['Love\'s diesel fills', 'Fills', 'Gallons', 'Charged', 'Off the promise'].map((h) => el('th', {}, h)))),
    el('tbody', {}, ...loves.groups.map((g) => el('tr', {},
      el('td', {}, verdictMark(g.verdict), g.verdict),
      el('td', {}, fmt.count(g.fills)),
      el('td', {}, fmt.count(g.gallons)),
      el('td', {}, fmt.exact(g.charged)),
      el('td', {}, offText(g.verdict, g.off))))));
  document.getElementById('acct-odd-title').hidden = !loves.odd.length;
  document.getElementById('acct-odd').replaceChildren(...(loves.odd.length ? [
    el('thead', {}, el('tr', {}, ...['Day', 'Store', 'Unit', 'Driver', 'Gallons', 'Charged/gal', 'Sheet/gal', 'Off', 'Verdict']
      .map((h, i) => el('th', { class: i < 4 ? 'left' : null }, h)))),
    el('tbody', {}, ...loves.odd.map((f) => el('tr', {},
      el('td', { class: 'left' }, shortDay(f.day)),
      el('td', { class: 'left' }, `#${f.store} ${f.place}`),
      el('td', { class: 'left' }, f.unit || '—'),
      el('td', { class: 'left' }, personName(f.driver)),
      el('td', {}, fmt.count(f.gallons)),
      el('td', {}, fmt.price(f.per_gal)),
      el('td', {}, f.sheet_per_gal == null ? 'not on it' : fmt.price(f.sheet_per_gal)),
      el('td', {}, offText(f.verdict, f.off)),
      el('td', {}, verdictMark(f.verdict), f.verdict)))),
  ] : []));
  drawBurn(checks && checks.burn);
  drawFills(checks && checks.fills);
}

// Draws bought vs burned per truck: a line on what was looked up, then one row per truck, biggest unexplained first.
function drawBurn(burn) {
  const rows = burn ? burn.trucks : [];
  const known = rows.filter((t) => t.burned != null);
  document.getElementById('acct-burn-meta').textContent = !burn ? '' : !burn.looked_up
    ? 'Fuel used not looked up in Samsara yet: it is, within the next quarter hour.'
    : `${rows.length} trucks bought diesel: ${known.length} in Samsara (${fmt.count(sumOf(known, 'bought'))} gal bought, `
      + `${fmt.count(sumOf(known, 'burned'))} gal burned), ${rows.length - known.length} not in Samsara (bought only).`;
  fillTable('acct-burn', ['Unit', 'Driver', 'Fills', 'Bought', 'Burned', 'Miles', 'MPG', 'Gauge first → last day', 'Tank',
    'Into the tank', 'Unexplained'], 2, rows.map((t) => [
    t.unit, t.drivers.map(personName).join(', ') || '—', fmt.count(t.fills), gal(t.bought), gal(t.burned),
    t.miles == null ? '—' : fmt.count(t.miles), t.miles && t.burned ? (t.miles / t.burned).toFixed(1) : '—',
    t.gauge_start == null || t.gauge_end == null ? '—' : `${fmt.level(t.gauge_start)} → ${fmt.level(t.gauge_end)}`,
    t.tank == null ? '—' : gal(t.tank), t.into_tank == null ? '—' : gal(t.into_tank, true), unexplained(t.unexplained)]));
}

// Draws each fill's evidence: fills per verdict, the units keyed differently, and the doubtful fills.
function drawFills(fills) {
  const groups = fills ? fills.groups : [];
  fillTable('acct-fills', ['Diesel fills', 'Fills', 'Gallons'], 1,
    groups.map((g) => [el('span', {}, verdictMark(g.verdict), g.verdict), fmt.count(g.fills), fmt.count(g.gallons)]));
  document.getElementById('acct-fills-meta').textContent = fills
    ? `Unit keyed at the pump other than the Datatruck truck: ${fmt.count(fills.unit_differs)} of ${fmt.count(fills.fills)} fills.` : '';
  const doubtful = fills ? fills.doubtful : [];
  document.getElementById('acct-doubt-title').hidden = !doubtful.length;
  fillTable('acct-doubt', ['Day', 'Station', 'Unit', 'Keyed', 'Driver', 'Gallons', 'Gauge', 'Tank it implies', 'Truck was', 'Verdict'], 5,
    doubtful.map((f) => [shortDay(f.day), `${stationName(f.station, f.station.startsWith('LOVES') ? "Love's" : '')} · ${f.efs_place}`,
      f.unit || '—', f.keyed || '—', personName(f.driver), fmt.count(f.gallons),
      f.gauge_from == null ? '—' : `${fmt.level(f.gauge_from)} → ${fmt.level(f.gauge_to)}`,
      f.tank == null ? '—' : gal(f.tank), truckWas(f), el('span', {}, verdictMark(f.verdict), f.verdict)]));
}

// Where the truck was as the doubtful list shows it: miles from the Love's store, or Samsara's address.
function truckWas(f) {
  if (f.miles_off != null) return `${f.miles_off} mi from the store`;
  return f.truck_place ? f.truck_place.split(',').slice(-3, -1).join(',').trim() : '—';
}

// A truck's unexplained gallons, amber or red when big.
function unexplained(v) {
  if (v == null) return '—';
  const tone = v >= 2 * UNEXPLAINED_WARN_GAL ? 'bad' : v >= UNEXPLAINED_WARN_GAL ? 'warn' : null;
  return el('span', { class: tone ? `acct-${tone}` : null }, gal(v, true));
}

// Gallons as a table cell: "1,234 gal"; `signed` puts a + on gains.
function gal(v, signed = false) {
  return v == null ? '—' : `${signed && v > 0 ? '+' : ''}${fmt.count(v)} gal`;
}

// The sum of one field over rows.
function sumOf(rows, key) {
  return rows.reduce((total, r) => total + (r[key] || 0), 0);
}

// Fills a table: its headings (the first `left` columns left-aligned) and its rows of cells (text or elements).
// No rows: the table is emptied.
function fillTable(id, heads, left, rows) {
  document.getElementById(id).replaceChildren(...(rows.length ? [
    el('thead', {}, el('tr', {}, ...heads.map((h, i) => el('th', { class: i < left ? 'left' : null }, h)))),
    el('tbody', {}, ...rows.map((cells) => el('tr', {}, ...cells.map((c, i) => el('td', { class: i < left ? 'left' : null }, c))))),
  ] : []));
}

// A small mark in a verdict's color.
function verdictMark(verdict) {
  return el('i', { class: 'key-bar', style: `background: var(${VERDICT_TONES[verdict]}); margin-right: 8px` });
}

// Dollars off the promise as a table shows them: above the sheet with a sign, a missed discount marked estimated,
// a dash when it can't be checked.
function offText(verdict, off) {
  if (off == null) return verdict === 'No sheet that day' ? "can't check" : '—';
  const dollars = `${off > 0 ? '+' : ''}${fmt.exact(off)}`;
  return verdict.startsWith('No deal') ? `${dollars} missed (est.)` : dollars;
}

// "Wed, Nov 11" from "2026-11-11".
function shortDay(iso) {
  return dateOf(iso).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
}

// Says why the numbers didn't load, in place of the tree.
export function showAccountingError(error) {
  document.getElementById('acct-statement').hidden = !(state.data && state.data.statement);  // no empty picker
  document.getElementById('acct-tree').replaceChildren(el('p', { class: 'meta' }, `Couldn't load the statement: ${error.message}`));
}

// Draws the tree from the numbers last loaded, with the boxes open that were open.
function drawTree() {
  const box = document.getElementById('acct-tree');
  const tree = state.data && state.data.tree;
  if (!tree) {
    box.replaceChildren(el('p', { class: 'meta' }, 'No EFS statement read yet. Save the statement PDF from EFS into the '
      + 'data\\efs folder: it is read within 30 minutes.'));
    return;
  }
  box.replaceChildren(el('ul', {}, branch(tree, tree.label, null, '--muted')));
}

// One box and, when it is open, the boxes it is made of under it. `path` names it by its parents' names and its own.
function branch(node, path, parent, tone) {
  const own = (TONES[node.dim] && TONES[node.dim][node.label]) || tone;
  const open = node.children.length > 0 && state.open.has(path);
  return el('li', {}, cube(node, path, parent, own, open),
    open && el('ul', {}, ...node.children.map((child) => branch(child, `${path} › ${child.label}`, node, own))));
}

// A box: its name, its dollars to the cent, its share of the box above, its gallons and price per gallon (fuel) or its
// statement lines, the pump price and discount per gallon (fuel), a mark when its lines don't add up to EFS's figure,
// and its Datatruck badge. One with boxes under it is a button.
function cube(node, path, parent, tone, open) {
  const kids = node.children.length;
  const share = parent && parent.amount ? `${fmt.share(node.amount / parent.amount)} of ${parent.label}` : null;
  const note = node.gallons ? `${fmt.count(node.gallons)} gal · ${fmt.price(node.amount / node.gallons)}/gal`
    : `${fmt.count(node.lines)} line${node.lines === 1 ? '' : 's'}`;
  const parts = [
    el('span', { class: 'cube-label' }, node.label),
    el('b', { class: 'cube-amount' }, fmt.exact(node.amount)),
    share && el('span', { class: 'cube-share' }, share),
    el('small', { class: 'cube-note' }, note),
    node.pump_per_gal != null && el('small', { class: 'cube-note' },
      `Pump ${fmt.price(node.pump_per_gal)} · discount ${fmt.cents(node.discount_per_gal)}/gal`),
    node.check != null && el('small', { class: 'cube-check' }, `Its lines add to ${fmt.exact(node.amount + node.check)}`),
    badge(node),
    kids > 0 && el('span', { class: 'cube-more', 'aria-hidden': 'true' }, open ? '−' : `+${kids}`),
  ];
  const attrs = { class: `cube${open ? ' is-open' : ''}${parent ? '' : ' is-root'}`, style: `--tone: var(${tone})`, 'data-path': path };
  return kids ? el('button', { type: 'button', 'aria-expanded': String(open), ...attrs }, ...parts) : el('div', attrs, ...parts);
}

// A box's badge: how its card purchases compare with Datatruck (worst first: lines not found, dollars that differ,
// then on the top box Datatruck lines on no statement line), or "EFS only" for what Datatruck never has. Hover: figures.
function badge(node) {
  const d = node.datatruck;
  if (!d) {
    return el('span', { class: 'badge', title: 'Money codes, credits and fees are only on the EFS statement: Datatruck has no line for them.' }, 'EFS only');
  }
  const all = d.found + d.missing;
  const tip = [
    `${fmt.count(d.found)} of ${fmt.count(all)} card purchase${all === 1 ? '' : 's'} found in Datatruck.`,
    d.off ? `Datatruck has ${fmt.exact(Math.abs(d.off))} ${d.off < 0 ? 'less' : 'more'} for them than the statement.`
      : 'Their dollars agree to the cent.',
    d.extra === null && 'Datatruck lines on no statement line: not checked (this EFS account\'s companies are not set).',
    d.extra > 0 && `${d.extra} Datatruck line${d.extra === 1 ? ' is' : 's are'} on no statement line: ${fmt.exact(d.extra_dollars)} `
      + `(${Object.entries(d.extra_items).map(([item, n]) => `${n} ${item}`).join(', ')}).`,
  ].filter(Boolean).join(' ');
  if (d.missing) return el('span', { class: 'badge bad', title: tip }, `✗ ${fmt.count(d.missing)} not in Datatruck`);
  if (d.off) return el('span', { class: 'badge warn', title: tip }, `≠ Datatruck ${fmt.exact(Math.abs(d.off))} ${d.off < 0 ? 'less' : 'more'}`);
  if (d.extra) return el('span', { class: 'badge warn', title: tip }, `+${d.extra} only in Datatruck`);
  return el('span', { class: 'badge good', title: tip }, '✓ Matches Datatruck');
}

// "Sun, Nov 15, 2026" from "2026-11-15".
function longDate(iso) {
  return dateOf(iso).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' });
}
