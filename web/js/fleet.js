// The fleet status on top of the Drivers view: every Datatruck truck as one square, in clusters by status, colored by
// one of three questions (type, Samsara, fuel card). Each question is a bar with its groups and counts; a group picked
// lists its trucks under the squares, and the square under the pointer (or keyboard focus) shows that truck in words.
import { el } from './dom.js';
import { ago, fmt, personName, plural } from './format.js';
import { FLEET, TRUCK_STATUS } from './labels.js';

// The clusters of squares: the on-duty trucks first, then the ones nobody is driving. Every truck is in exactly one.
const CLUSTERS = [
  { name: 'In transit', duty: true, has: (t) => t.status === 'in_transit' && t.on_duty },
  { name: 'Available, with a driver', duty: true, has: (t) => t.status === 'available' && t.on_duty },
  { name: 'In transit, no driver', duty: false, has: (t) => t.status === 'in_transit' && !t.on_duty },
  { name: 'Available, no driver', duty: false, has: (t) => t.status === 'available' && !t.on_duty },
  { name: 'In shop', duty: false, has: (t) => t.status === 'shop' },
  { name: 'In yard', duty: false, has: (t) => t.status === 'yard' },
  { name: 'Other status', duty: false, has: (t) => !(t.status in TRUCK_STATUS) },
];
const COLUMNS = ['Unit', 'Driver', 'Status', 'Type', 'Samsara', 'What to do', 'Last GPS', 'Gauge', 'Gauge read', 'Fuel card', 'Fuel messages'];

let colorBy = 'samsara';  // the question that colors the squares, kept across refreshes
let picked = null;        // the group listed under the squares: { key, k }; kept across refreshes
let shown = null;         // the numbers on screen: redrawn on a click, and where a pointed square is looked up

// One of the three questions, by its key.
const question = (key) => FLEET.find((q) => q.key === key);

// A question's group by its key; a group the page doesn't know is shown by its key.
const group = (key, k) => question(key).parts.find((p) => p.k === k) || { k, label: k };

// Orders two trucks by unit number, numbers by their value ("9" before "10").
const byUnit = (a, b) => a.unit.localeCompare(b.unit, 'en', { numeric: true });

// How long ago a time was; a stored time ("2026-10-19 16:03:33+00:00") is read like the others; "never" without one.
const since = (when) => (when ? ago(when.replace(' ', 'T')) : 'never');

// Wires the square pointed at, once.
export function initFleet() {
  const board = document.getElementById('fleet-board');
  const point = (e) => {
    const square = e.target.closest('.msg[data-i]');
    if (square && shown) showPick(shown.trucks[+square.dataset.i]);
  };
  board.addEventListener('mouseover', point);
  board.addEventListener('focusin', point);
}

// Draws the fleet status: its scope, the three bars with their groups, the squares and the picked group's list.
export function renderFleet(d) {
  shown = d;
  const duty = d.trucks.filter((t) => t.on_duty).length;
  document.getElementById('fleet-meta').textContent = `${plural(d.trucks.length, 'truck')} in Datatruck · ${duty} on duty `
    + `· one square = one truck · Samsara's newest position ${since(d.samsara_at)} · trucks, drivers and cards synced ${since(d.synced_at)}`;
  document.getElementById('fleet-bars').replaceChildren(...FLEET.map((q) => bar(q, d.trucks)));
  document.getElementById('fleet-board').replaceChildren(...[true, false].map((on) => dutyGroup(on, d.trucks)));
  showPick(null);
  renderList(d.trucks);
}

// Says on the fleet status's top line that it can't be loaded, and why.
export function showFleetError(error) {
  document.getElementById('fleet-meta').textContent = `Can't load the fleet status: ${error.message}`;
}

// Colors the squares by a question and lists a group (or none), then redraws.
function choose(key, pick) {
  colorBy = key;
  picked = pick;
  renderFleet(shown);
}

// One question as a bar: its name (click: color the squares by it), a segment per group, and each group with its
// count among all trucks and among those on duty (click: list its trucks; again: clear).
function bar(q, trucks) {
  const count = (k, list) => list.filter((t) => t[q.key] === k).length;
  const duty = trucks.filter((t) => t.on_duty);
  const name = el('button', { type: 'button', class: 'fleet-name', title: 'Color the squares by this' }, q.name, el('small', {}, q.note));
  name.addEventListener('click', () => choose(q.key, picked && picked.key === q.key ? picked : null));
  const groups = q.parts.map((p) => {
    const all = count(p.k, trucks), on = !!picked && picked.key === q.key && picked.k === p.k;
    const chip = el('button', { type: 'button', class: all ? 'fleet-group' : 'fleet-group zero', 'aria-pressed': String(on),
      title: `${p.tip || p.todo} · click to list these trucks` },
    el('i', { class: `f-${q.key}-${p.k}` }), p.label, el('b', {}, fmt.count(all)), el('small', {}, `${count(p.k, duty)} on duty`));
    chip.addEventListener('click', () => choose(q.key, on ? null : { key: q.key, k: p.k }));
    return chip;
  });
  return el('div', { class: q.key === colorBy ? 'fleet-bar on' : 'fleet-bar' }, name, el('div', { class: 'fleet-bar-body' },
    el('div', { class: 'fleet-segs' }, ...q.parts.filter((p) => count(p.k, trucks)).map((p) =>
      el('i', { class: `f-${q.key}-${p.k}`, style: `flex: ${count(p.k, trucks)}`, title: `${p.label}: ${count(p.k, trucks)}` }))),
    el('div', { class: 'fleet-groups' }, ...groups)));
}

// The on-duty trucks, or the rest: a heading with the count, then their clusters of squares.
function dutyGroup(on, trucks) {
  const items = trucks.map((t, i) => ({ t, i }));  // each truck with its place in the list, for the pointer
  const clusters = CLUSTERS.filter((c) => c.duty === on).map((c) => ({ c, list: items.filter(({ t }) => c.has(t)) }))
    .filter(({ list }) => list.length);
  const total = clusters.reduce((n, { list }) => n + list.length, 0);
  return el('div', { class: 'fleet-duty' },
    el('div', { class: 'fleet-duty-head' }, on ? 'On duty ' : 'Not on duty ', el('b', {}, fmt.count(total))),
    el('div', { class: 'fleet-clusters' }, ...clusters.map(({ c, list }) => el('div', { class: 'fleet-cluster' },
      el('div', { class: 'fleet-cluster-head' }, c.name, el('b', {}, fmt.count(list.length))),
      el('div', { class: 'fleet-squares', style: `--cols: ${columns(list.length)}` }, ...sorted(list).map(square))))));
}

// How many squares wide a cluster of `n` is: wider than tall, between 4 and 24.
const columns = (n) => Math.min(Math.max(Math.ceil(Math.sqrt(n * 2.6)), 4), 24);

// A cluster's trucks in the order of the question that colors them, so each color sits together; then by unit.
function sorted(list) {
  const order = question(colorBy).parts.map((p) => p.k);
  return [...list].sort((a, b) => order.indexOf(a.t[colorBy]) - order.indexOf(b.t[colorBy]) || byUnit(a.t, b.t));
}

// One truck as a square: a button, so the keyboard reaches it too, named for screen readers; dim when a group is
// picked and the truck isn't in it.
function square({ t, i }) {
  const off = picked && t[picked.key] !== picked.k;
  return el('button', { type: 'button', class: `msg f-${colorBy}-${t[colorBy]}${off ? ' dim' : ''}`, 'data-i': i,
    'aria-label': `Unit ${t.unit}, ${group(colorBy, t[colorBy]).label}` });
}

// A group's color mark and name, for one truck.
const tag = (t, key) => el('span', { class: 'msg-kind' }, el('i', { class: `msg f-${key}-${t[key]}` }), group(key, t[key]).label);

// The line above the squares: the truck pointed at, in words; a hint before any is.
function showPick(t) {
  const box = document.getElementById('fleet-pick');
  if (!t) {
    box.replaceChildren(el('span', { class: 'meta' },
      'Point at a square to see that truck. Click a bar\'s name to color the squares by it; click a group to list its trucks.'));
    return;
  }
  const linked = t.samsara !== 'none' && t.samsara !== 'mismatch';  // only a linked truck has readings to show
  const todo = group('samsara', t.samsara).todo;
  const parts = [el('b', {}, `Unit ${t.unit}`), el('span', {}, personName(t.driver)), el('span', {}, TRUCK_STATUS[t.status] || t.status),
    tag(t, 'type'), tag(t, 'samsara'), todo && el('span', { class: 'meta' }, todo),
    linked && el('span', { class: 'meta' }, `GPS ${since(t.gps_at)} · gauge ${t.fuel_pct == null ? 'none' : `${fmt.level(t.fuel_pct)}, read ${since(t.fuel_at)}`}`),
    tag(t, 'card'), t.live && el('span', { class: 'meta' }, 'gets fuel messages')];
  box.replaceChildren(...parts.filter(Boolean));  // the parts a truck doesn't have are left out
}

// The picked group's trucks under the squares: on duty first (in transit before available), then by unit.
function renderList(trucks) {
  const box = document.getElementById('fleet-list');
  box.hidden = !picked;
  if (!picked) return;
  const list = trucks.filter((t) => t[picked.key] === picked.k)
    .sort((a, b) => b.on_duty - a.on_duty || (a.status !== 'in_transit') - (b.status !== 'in_transit') || byUnit(a, b));
  const clear = el('button', { type: 'button', class: 'fleet-clear' }, 'Clear');
  clear.addEventListener('click', () => choose(colorBy, null));
  box.replaceChildren(
    el('div', { class: 'fleet-list-head' }, el('h2', {}, `${question(picked.key).name}: ${group(picked.key, picked.k).label}`),
      el('span', { class: 'meta' }, `${plural(list.length, 'truck')}, ${list.filter((t) => t.on_duty).length} on duty`), clear),
    el('div', { class: 'table-wrap' }, el('table', { class: 'table fleet-table' },
      el('thead', {}, el('tr', {}, ...COLUMNS.map((c) => el('th', { class: 'left' }, c)))),
      el('tbody', {}, ...list.map(row)))));
}

// One truck's line in the list; a reading older than a day, or none, is in red.
function row(t) {
  const old = (when) => (!when || new Date() - new Date(when) > 24 * 3600 * 1000 ? 'left off' : 'left');
  const cell = (text, cls = 'left') => el('td', { class: cls }, text);
  return el('tr', {}, el('td', {}, el('b', {}, t.unit)), cell(personName(t.driver)), cell(TRUCK_STATUS[t.status] || t.status),
    cell(group('type', t.type).label), cell(group('samsara', t.samsara).label), cell(group('samsara', t.samsara).todo || '', 'left fleet-todo'),
    cell(since(t.gps_at), old(t.gps_at)), cell(fmt.level(t.fuel_pct)), cell(since(t.fuel_at), old(t.fuel_at)),
    cell(group('card', t.card).label), cell(t.live ? 'Yes' : ''));
}
