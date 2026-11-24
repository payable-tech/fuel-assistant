// The fleet status on top of the Drivers view. On top, a summary of the fleet, a picture only: one bar of the trucks by
// what they have (Samsara working, a fuel card assigned, both, neither), a grid of driver type against the same, and
// what is missing, biggest first; for the trucks on duty or for all of them. Under it, the units as a table, one row
// per truck, and the table is where the filtering is done: every column's heading sorts by it and opens its filter.
// Several choices in one column are either-or; the columns together narrow the list down.
import { el } from './dom.js';
import { ago, fmt, personName, plural } from './format.js';
import { FLEET, TRUCK_STATUS } from './labels.js';

const HOUR = 3600 * 1000;

// One of the questions asked of every truck, by its key.
const question = (key) => FLEET.find((q) => q.key === key);

// A question's group by its key; a group the page doesn't know is shown by its key.
const group = (key, k) => question(key).parts.find((p) => p.k === k) || { k, label: k, color: '--faint' };

// A truck's place in a question's order of groups, so a column sorts the way its groups are listed.
const place = (key, t) => question(key).parts.findIndex((p) => p.k === t[key]);

// How long ago a time was; a stored time ("2026-10-19 16:03:33+00:00") is read like the others; "never" without one.
const since = (when) => (when ? ago(when.replace(' ', 'T')) : 'never');

// The choices a column of ages is filtered by, and the one a time falls in.
const AGES = [{ k: 'hour', label: 'Under 1 h ago' }, { k: 'day', label: '1 to 24 h ago' }, { k: 'old', label: 'Over 24 h ago' },
  { k: 'never', label: 'Never' }];
function age(when) {
  if (!when) return 'never';
  const hours = (new Date() - new Date(when.replace(' ', 'T'))) / HOUR;
  return hours < 1 ? 'hour' : hours < 24 ? 'day' : 'old';
}

// The choices the gauge is filtered by, and the one a level falls in (10% is the reserve, 25% the level a stop is told at).
const LEVELS = [{ k: 'low', label: 'Under 10%' }, { k: 'quarter', label: '10% to 25%' }, { k: 'half', label: '25% to 50%' },
  { k: 'high', label: 'Over 50%' }, { k: 'none', label: 'No reading' }];
const level = (pct) => (pct == null ? 'none' : pct < 10 ? 'low' : pct < 25 ? 'quarter' : pct < 50 ? 'half' : 'high');

// The choices the diesel bought is filtered by, and the one a truck's gallons fall in.
const BOUGHT = [{ k: 'none', label: 'None' }, { k: 'some', label: 'Under 500 gal' }, { k: 'more', label: '500 to 1,500 gal' },
  { k: 'most', label: 'Over 1,500 gal' }];
const bought = (gallons) => (!gallons ? 'none' : gallons < 500 ? 'some' : gallons < 1500 ? 'more' : 'most');

// A column filtered by one of the questions: its choices are the question's groups.
const asked = (key) => ({ key, name: question(key).name, by: (t) => place(key, t), of: (t) => t[key], choices: question(key).parts });

// The table's columns: the heading, what a truck is sorted by, and how it is filtered: `text` (what is typed must be
// in it), or `choices` with `of` (the choice a truck falls in). A column with neither is not filtered.
const COLUMNS = [
  { key: 'unit', name: 'Unit', by: (t) => t.unit, text: (t) => t.unit },
  { key: 'driver', name: 'Driver', by: (t) => personName(t.driver), text: (t) => t.driver || 'no active driver' },
  asked('status'), asked('duty'), asked('type'), asked('samsara'), asked('card'),
  { key: 'gps', name: 'Last GPS', by: (t) => t.gps_at || '', of: (t) => age(t.gps_at), choices: AGES },
  { key: 'gauge', name: 'Gauge', by: (t) => t.fuel_pct ?? -1, of: (t) => level(t.fuel_pct), choices: LEVELS },
  { key: 'read', name: 'Gauge read', by: (t) => t.fuel_at || '', of: (t) => age(t.fuel_at), choices: AGES },
  { key: 'gallons', name: 'Diesel bought', by: (t) => t.gallons, of: (t) => bought(t.gallons), choices: BOUGHT },
  { key: 'live', name: 'Fuel messages', by: (t) => (t.live ? 1 : 0), of: (t) => (t.live ? 'yes' : 'no'),
    choices: [{ k: 'yes', label: 'Gets them' }, { k: 'no', label: 'Does not' }] },
  { key: 'todo', name: 'What to do', by: (t) => group('samsara', t.samsara).todo || '' },
];

let scope = 'duty';                        // the trucks the summary covers: 'duty' (on duty) or 'all'; kept across refreshes
let sortBy = { column: 0, down: false };   // the table's order: a column, and whether it runs downward
let shown = null;                          // the numbers on screen: redrawn when the filter changes
let open = null;                           // the column whose filter is open, by its key
// the filter: each column's choices picked (none: all), or the words typed for a text column
const picked = Object.fromEntries(COLUMNS.map((c) => [c.key, new Set()]));
const typed = Object.fromEntries(COLUMNS.filter((c) => c.text).map((c) => [c.key, '']));

// True for a truck with Samsara working and a fuel card assigned.
const both = (t) => t.samsara === 'working' && t.card === 'card';

// What a truck has, in four groups that every truck is in exactly one of.
const HAVE = [
  { label: 'Samsara working and a card assigned', color: '--good', has: both },
  { label: 'A card assigned, Samsara not working', color: '--bad', has: (t) => t.card === 'card' && t.samsara !== 'working' },
  { label: 'Samsara working, no card assigned', color: '--warn', has: (t) => t.samsara === 'working' && t.card !== 'card' },
  { label: 'Neither', color: '--s4', has: (t) => t.samsara !== 'working' && t.card !== 'card' },
];

// Orders two trucks by unit number, numbers by their value ("9" before "10").
const byUnit = (a, b) => a.unit.localeCompare(b.unit, 'en', { numeric: true });

// True when a column is filtered.
const filtered = (c) => (c.text ? Boolean(typed[c.key].trim()) : picked[c.key].size > 0);

// True when a truck passes one column's filter.
function passesColumn(t, c) {
  if (c.text) return !typed[c.key].trim() || c.text(t).toLowerCase().includes(typed[c.key].trim().toLowerCase());
  return !picked[c.key].size || picked[c.key].has(c.of(t));
}

// True when a truck passes every column's filter; `but` leaves one column out (for that column's own counts).
const passes = (t, but = null) => COLUMNS.every((c) => c.key === but || (!c.text && !c.choices) || passesColumn(t, c));

// Wires what stays on the page: a click outside an open filter, or Escape, closes it. The click's own path is asked,
// because a click inside the filter redraws it before this is reached.
export function initFleet() {
  const inside = (node) => node.id === 'fleet-pop' || (node.classList && node.classList.contains('col-filter'));
  document.addEventListener('click', (e) => { if (open && !e.composedPath().some(inside)) closeFilter(); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && open) closeFilter(); });
  document.getElementById('fleet-clear').addEventListener('click', () => {
    COLUMNS.forEach((c) => { picked[c.key].clear(); if (c.text) typed[c.key] = ''; });
    closeFilter();
  });
}

// Draws the fleet status from fresh numbers. A truck's duty is given the same shape as its other groups, and a
// status the page has no name for becomes "other".
export function renderFleet(d) {
  shown = { ...d, trucks: d.trucks.map((t) => ({ ...t, duty: t.on_duty ? 'on' : 'off', status: t.status in TRUCK_STATUS ? t.status : 'other' })) };
  document.getElementById('fleet-meta').textContent = `${plural(d.trucks.length, 'truck')} in Datatruck `
    + `· Samsara's newest position ${since(d.samsara_at)} · trucks, drivers and cards synced ${since(d.synced_at)}`;
  drawSummary();
  drawTable();
}

// Says on the fleet status's top line that it can't be loaded, and why.
export function showFleetError(error) {
  document.getElementById('fleet-meta').textContent = `Can't load the fleet status: ${error.message}`;
}

// A row of buttons, one pressed: `choices` as [key, words], `now` the key pressed, `pick(key)` on a click.
function seg(name, choices, now, pick) {
  const buttons = choices.map(([key, words]) => {
    const button = el('button', { type: 'button', 'aria-pressed': String(key === now) }, words);
    button.addEventListener('click', () => pick(key));
    return button;
  });
  return el('div', { class: 'seg', role: 'group', 'aria-label': name }, ...buttons);
}

// The summary on top: which trucks it covers (on duty, or all), then the bar, the grid and what is missing.
function drawSummary() {
  const all = shown.trucks, duty = all.filter((t) => t.on_duty);
  const list = scope === 'duty' ? duty : all;
  document.getElementById('fleet-tools').replaceChildren(
    seg('Which trucks', [['duty', `On duty  ${duty.length}`], ['all', `All trucks  ${all.length}`]], scope, (k) => { scope = k; drawSummary(); }),
    el('p', { class: 'meta' }, `The ${plural(list.length, 'truck')} ${scope === 'duty' ? 'on duty: in transit or available, with an active driver' : 'in Datatruck, driven or not'}.`));
  document.getElementById('fleet-board').replaceChildren(have(list), el('div', { class: 'board-pair' }, grid(list), missing(list)));
}

// The trucks by what they have, as one bar and its key: both Samsara working and a card assigned, one of them, or
// neither.
function have(list) {
  const parts = HAVE.map((p) => ({ ...p, n: list.filter(p.has).length })).filter((p) => p.n);
  return el('div', { class: 'have' },
    el('div', { class: 'have-bar' }, ...parts.map((p) => el('i', { style: `flex: ${p.n}; background: var(${p.color})`, title: `${p.label}: ${p.n}` },
      p.n / list.length > 0.04 ? fmt.count(p.n) : ''))),
    el('div', { class: 'have-key' }, ...parts.map((p) => el('span', {}, mark(p), p.label, el('b', {}, fmt.count(p.n)),
      el('small', {}, fmt.percent(p.n / list.length))))));
}

// One cell of the grid: how many of a row's trucks have something, of how many, as a count, a share and a bar whose
// color runs from red (none) to green (all).
function cover(n, of) {
  const share = of ? n / of : 0;
  return el('td', {}, el('div', { class: 'cover' }, el('b', {}, fmt.count(n)), el('small', {}, `of ${fmt.count(of)} · ${fmt.percent(share)}`),
    el('i', {}, el('u', { style: `width: ${share * 100}%; background: color-mix(in srgb, var(--good) ${share * 100}%, var(--bad))` }))));
}

// The grid: a row per driver type and one for them all; across, the trucks, then how many of them have Samsara
// working, a card assigned, and both.
function grid(list) {
  const line = (name, trucks, cls = '') => el('tr', { class: cls },
    el('th', { class: 'left' }, name),
    el('td', {}, el('div', { class: 'cover' }, el('b', {}, fmt.count(trucks.length)), el('small', {}, `${fmt.percent(trucks.length / list.length)} of these trucks`),
      el('i', {}, el('u', { style: `width: ${(trucks.length / list.length) * 100}%; background: var(--s1)` })))),
    cover(trucks.filter((t) => t.samsara === 'working').length, trucks.length),
    cover(trucks.filter((t) => t.card === 'card').length, trucks.length),
    cover(trucks.filter(both).length, trucks.length));
  const rows = question('type').parts.map((p) => ({ p, trucks: list.filter((t) => t.type === p.k) })).filter(({ trucks }) => trucks.length);
  return el('div', { class: 'board-part' }, el('div', { class: 'thread-label' }, 'By driver type'),
    el('table', { class: 'cover-table' },
      el('thead', {}, el('tr', {}, ...['', 'Trucks', 'Samsara working', 'Fuel card assigned', 'Both'].map((h) => el('th', { class: 'left' }, h)))),
      el('tbody', {}, ...rows.map(({ p, trucks }) => line(el('span', { class: 'msg-kind', title: p.tip }, mark(p, 'msg'), p.tip || p.label), trucks)),
        line('All of them', list, 'total'))));
}

// What is missing: every group of the Samsara and fuel card questions that is not the good one, biggest first, with
// its count, a bar against all the trucks covered, and what to do about it.
function missing(list) {
  const rows = ['samsara', 'card'].flatMap((key) => question(key).parts.slice(1).map((p) => ({ key, p, n: list.filter((t) => t[key] === p.k).length })))
    .filter((r) => r.n).sort((a, b) => b.n - a.n);
  return el('div', { class: 'board-part' }, el('div', { class: 'thread-label' }, 'What is missing'),
    rows.length ? el('ul', { class: 'missing' }, ...rows.map(({ key, p, n }) => el('li', {},
      el('div', { class: 'missing-head' }, mark(p, 'msg'), el('span', {}, `${question(key).name}: ${p.label}`), el('b', {}, fmt.count(n))),
      el('i', {}, el('u', { style: `width: ${(n / list.length) * 100}%; background: var(${p.color})` })),
      el('small', {}, p.todo || p.tip || ''))))
      : el('p', { class: 'meta' }, 'Nothing: every truck has Samsara working and a card assigned.'));
}

// A group's color mark: filled in its color, or hollow for the one drawn as an outline; nothing for a choice with no
// color of its own.
function mark(part, cls = '') {
  if (!part.color) return null;
  const paint = part.hollow ? `box-shadow: inset 0 0 0 2px var(${part.color})` : `background: var(${part.color})`;
  return el('i', { class: cls, style: paint });
}

// The table of the trucks the filter leaves, in the order picked on a heading; over it the count, the filter in
// words (each part with a cross to drop it) and "Clear filters". An open filter is drawn again, so its counts follow.
function drawTable() {
  const d = shown;
  const list = d.trucks.filter((t) => passes(t));
  const column = COLUMNS[sortBy.column];
  const way = sortBy.down ? -1 : 1;
  const compare = (a, b) => {
    const x = column.by(a), y = column.by(b);
    return (typeof x === 'number' ? x - y : String(x).localeCompare(String(y), 'en', { numeric: true })) * way || byUnit(a, b);
  };
  document.getElementById('fleet-count').textContent = `${fmt.count(list.length)} of ${plural(d.trucks.length, 'truck')}`;
  document.getElementById('fleet-chips').replaceChildren(...COLUMNS.filter(filtered).map(chip));
  document.getElementById('fleet-clear').hidden = !COLUMNS.some(filtered);
  document.getElementById('fleet-list').replaceChildren(el('div', { class: 'table-wrap' }, el('table', { class: 'table fleet-table' },
    el('thead', {}, el('tr', {}, ...COLUMNS.map(head))),
    el('tbody', {}, ...(list.length ? [...list].sort(compare).map(row)
      : [el('tr', {}, el('td', { class: 'left', colspan: String(COLUMNS.length) }, 'No truck passes this filter.'))])))));
  document.querySelector('#fleet-list .table-wrap').addEventListener('scroll', () => { if (open) closeFilter(); });
  if (open) drawFilter();
}

// One column's filter in words, as a chip with a cross that drops it.
function chip(c) {
  const said = c.text ? `"${typed[c.key].trim()}"` : c.choices.filter((p) => picked[c.key].has(p.k)).map((p) => p.label).join(' or ');
  const button = el('button', { type: 'button', class: 'fleet-chip', title: 'Drop this filter' }, `${c.name}: ${said}`, el('span', {}, '×'));
  button.addEventListener('click', () => { picked[c.key].clear(); if (c.text) typed[c.key] = ''; closeFilter(); });
  return button;
}

// A column's heading: its name (a click sorts by it; again turns the order) and, when it can be filtered, the button
// that opens its filter, lit while the column is filtered.
function head(c, i) {
  const on = i === sortBy.column;
  const sort = el('button', { type: 'button', class: on ? 'sort on' : 'sort', title: 'Sort by this column' },
    c.name, el('i', { class: 'sort-way' }, on ? (sortBy.down ? '↓' : '↑') : '↕'));
  sort.addEventListener('click', () => { sortBy = { column: i, down: on ? !sortBy.down : false }; drawTable(); });
  const filter = (c.text || c.choices) && el('button', { type: 'button', class: filtered(c) ? 'col-filter on' : 'col-filter',
    'data-col': c.key, 'aria-label': `Filter by ${c.name}`, 'aria-expanded': String(open === c.key), title: `Filter by ${c.name}` });
  if (filter) {
    filter.innerHTML = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2 4h12M4.5 8h7M7 12h2" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>';
    filter.addEventListener('click', () => { open = open === c.key ? null : c.key; drawTable(); if (!open) closeFilter(); });
  }
  return el('th', { class: 'left', 'aria-sort': on ? (sortBy.down ? 'descending' : 'ascending') : null },
    el('div', { class: 'col-head' }, sort, filter));
}

// Closes the open filter and draws the table as the filter now stands.
function closeFilter() {
  open = null;
  document.getElementById('fleet-pop').hidden = true;
  drawTable();
}

// The open column's filter, under its button: for a text column a box to type in; for the others its choices to
// tick, each with the number of trucks it would list with the other columns as they stand.
function drawFilter() {
  const c = COLUMNS.find((col) => col.key === open);
  const pop = document.getElementById('fleet-pop');
  const anchor = document.querySelector(`.col-filter[data-col="${open}"]`);
  const body = c.text ? textFilter(c) : choiceFilter(c);
  const clear = el('button', { type: 'button', class: 'fleet-clear' }, 'Clear');
  clear.addEventListener('click', () => { picked[c.key].clear(); if (c.text) typed[c.key] = ''; drawTable(); });
  const done = el('button', { type: 'button', class: 'fleet-clear' }, 'Done');
  done.addEventListener('click', closeFilter);
  const typing = pop.contains(document.activeElement) && document.activeElement.tagName === 'INPUT' && document.activeElement.type === 'search';
  pop.replaceChildren(el('div', { class: 'pop-head' }, c.name), body, el('div', { class: 'pop-foot' }, clear, done));
  pop.hidden = false;
  const at = anchor.getBoundingClientRect();
  pop.style.top = `${at.bottom + window.scrollY + 6}px`;
  pop.style.left = `${Math.max(8, Math.min(at.left + window.scrollX - 8, window.scrollX + document.documentElement.clientWidth - pop.offsetWidth - 8))}px`;
  const box = pop.querySelector('input[type="search"]');
  if (box && (typing || c.text)) { box.focus(); box.setSelectionRange(box.value.length, box.value.length); }
}

// A text column's filter: what is typed must be in the truck's value.
function textFilter(c) {
  const box = el('input', { type: 'search', class: 'search', placeholder: `${c.name} contains…`, 'aria-label': `${c.name} contains`, autocomplete: 'off' });
  box.value = typed[c.key];
  box.addEventListener('input', () => { typed[c.key] = box.value; drawTable(); });
  box.addEventListener('keydown', (e) => { if (e.key === 'Enter') closeFilter(); });
  return box;
}

// A column's choices to tick; none ticked means all. A choice no truck is in (with the other columns as they
// stand) is dim.
function choiceFilter(c) {
  const others = shown.trucks.filter((t) => passes(t, c.key));
  return el('div', { class: 'pop-list' }, ...c.choices.map((p) => {
    const n = others.filter((t) => c.of(t) === p.k).length;
    const tick = el('input', { type: 'checkbox' });
    tick.checked = picked[c.key].has(p.k);
    tick.addEventListener('change', () => { picked[c.key][tick.checked ? 'add' : 'delete'](p.k); drawTable(); });
    return el('label', { class: n || tick.checked ? 'pop-choice' : 'pop-choice zero', title: p.tip || p.todo || null },
      tick, mark(p), el('span', {}, p.label), el('b', {}, fmt.count(n)));
  }));
}

// A group's color mark and name, for one truck.
const tag = (t, key) => el('span', { class: 'msg-kind' }, mark(group(key, t[key]), 'msg'), group(key, t[key]).label);

// One truck's line in the table, its cells in the columns' order; a reading older than a day, or none, is in red.
function row(t) {
  const old = (when) => (!when || new Date() - new Date(when) > 24 * HOUR ? 'left off' : 'left');
  const cell = (text, cls = 'left') => el('td', { class: cls }, text);
  return el('tr', {}, el('td', {}, el('b', {}, t.unit)), cell(personName(t.driver)), cell(group('status', t.status).label),
    cell(t.on_duty ? 'On duty' : 'Not on duty'), cell(tag(t, 'type')), cell(tag(t, 'samsara')), cell(tag(t, 'card')),
    cell(since(t.gps_at), old(t.gps_at)), cell(fmt.level(t.fuel_pct)), cell(since(t.fuel_at), old(t.fuel_at)),
    cell(fmt.wholeGallons(t.gallons)), cell(t.live ? 'Yes' : ''), cell(group('samsara', t.samsara).todo || '', 'left fleet-todo'));
}
