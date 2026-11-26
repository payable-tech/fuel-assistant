// The fleet status on top of the Drivers view, built on the unit master: one row per Datatruck truck with what each
// source says of it (Datatruck, Samsara, EFS). On top, a summary, a picture only: one bar of the trucks by what they
// have (Samsara working, an active card in EFS, both, neither), a grid of driver type against the same, and what is
// missing, biggest first; for the trucks on duty or for all of them. Under it, the units as a table, and the table is
// where the filtering is done: every column's heading sorts by it and opens its filter (table.js).
import { el } from './dom.js';
import { ago, fmt, personName, plural } from './format.js';
import { FLEET } from './labels.js';
import { filterTable, mark } from './table.js';

const HOUR = 3600 * 1000;
const EFS_COLOR = { ACTIVE: '--good', HOLD: '--warn', 'HOLD FOR FRAUD': '--bad' };  // an EFS card's mark, by its status

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

// Cards as people name them, by their last four digits: "…7539, …0482".
const numbers = (list) => list.map((n) => `…${n}`).join(', ');

// The unit's EFS cards that are in use (any status but INACTIVE), the active ones first.
const inUse = (t) => t.efs.filter((c) => c.status !== 'INACTIVE').sort((a, b) => (a.status !== 'ACTIVE') - (b.status !== 'ACTIVE'));

// A column filtered by one of the questions: its choices are the question's groups.
const asked = (key) => ({ key, name: question(key).name, by: (t) => place(key, t), of: (t) => t[key], choices: question(key).parts });

// The table's columns, each from one source: the heading, what a truck is sorted by, and how it is filtered: `text`
// (what is typed must be in it), or `choices` with `of` (the choice a truck falls in).
const COLUMNS = [
  { key: 'unit', name: 'Unit', by: (t) => t.unit, text: (t) => t.unit },
  asked('type'),
  { key: 'driver', name: 'Drivers', by: (t) => personName(t.driver), text: (t) => t.driver || 'no active driver' },
  asked('status'), asked('duty'),
  { key: 'cards', name: 'Card in Datatruck', by: (t) => numbers(t.cards), text: (t) => numbers(t.cards) },
  { key: 'efs', name: 'Card in EFS', by: (t) => numbers(inUse(t).map((c) => c.last4)),
    text: (t) => t.efs.map((c) => `…${c.last4} ${c.status} ${c.name || ''}`).join(' ') },
  asked('match'), asked('samsara'),
  { key: 'gps', name: 'Last GPS', by: (t) => t.gps_at || '', of: (t) => age(t.gps_at), choices: AGES },
];

let scope = 'duty';   // the trucks the summary covers: 'duty' (on duty) or 'all'; kept across refreshes
let shown = null;     // the numbers on screen
let drawTable = null; // the units' table (table.js), made once the page is there

// True for a truck with Samsara working and an active card in EFS.
const both = (t) => t.samsara === 'working' && t.card === 'active';

// What a truck has, in four groups that every truck is in exactly one of.
const HAVE = [
  { label: 'Samsara + active card', color: '--good', has: both },
  { label: 'Card, no Samsara', color: '--bad', has: (t) => t.card === 'active' && t.samsara !== 'working' },
  { label: 'Samsara, no active card', color: '--warn', has: (t) => t.samsara === 'working' && t.card !== 'active' },
  { label: 'Neither', color: '--s4', has: (t) => t.samsara !== 'working' && t.card !== 'active' },
];

// Orders two trucks by unit number, numbers by their value ("9" before "10").
const byUnit = (a, b) => a.unit.localeCompare(b.unit, 'en', { numeric: true });

// Makes the units' table, filtered from its headings (table.js).
export function initFleet() {
  drawTable = filterTable({ columns: COLUMNS, row, tie: byUnit, noun: 'truck',
    ids: { list: 'fleet-list', count: 'fleet-count', chips: 'fleet-chips', clear: 'fleet-clear', pop: 'fleet-pop' } });
}

// Draws the fleet status from fresh numbers. A truck's duty is given the same shape as its other groups, and a
// status the page has no name for becomes "other".
export function renderFleet(d) {
  const known = question('status').parts.map((p) => p.k);
  shown = { ...d, trucks: d.trucks.map((t) => ({ ...t, duty: t.on_duty ? 'on' : 'off', status: known.includes(t.status) ? t.status : 'other' })) };
  document.getElementById('fleet-meta').textContent = `${plural(d.trucks.length, 'truck')} · one row per unit · read from Datatruck ${since(d.synced_at)}, `
    + `Samsara ${since(d.samsara_at)}, EFS ${since(d.efs_at)}`;
  drawSummary();
  drawTable(shown.trucks);
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
    seg('Which trucks', [['duty', `On duty  ${duty.length}`], ['all', `All trucks  ${all.length}`]], scope, (k) => { scope = k; drawSummary(); }));
  document.getElementById('fleet-board').replaceChildren(have(list), el('div', { class: 'board-pair' }, grid(list), missing(list)));
}

// The trucks by what they have, as one bar and its key: both Samsara working and an active card, one of them, or
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
  return el('td', {}, el('div', { class: 'cover' }, el('b', {}, fmt.count(n)), el('small', {}, fmt.percent(share)),
    el('i', {}, el('u', { style: `width: ${share * 100}%; background: color-mix(in srgb, var(--good) ${share * 100}%, var(--bad))` }))));
}

// The grid: a row per driver type and one for them all; across, the trucks, then how many of them have Samsara
// working, an active card in EFS, and both.
function grid(list) {
  const line = (name, trucks, cls = '') => el('tr', { class: cls },
    el('th', { class: 'left' }, name),
    el('td', {}, el('div', { class: 'cover' }, el('b', {}, fmt.count(trucks.length)), el('small', {}, fmt.percent(trucks.length / list.length)),
      el('i', {}, el('u', { style: `width: ${(trucks.length / list.length) * 100}%; background: var(--s1)` })))),
    cover(trucks.filter((t) => t.samsara === 'working').length, trucks.length),
    cover(trucks.filter((t) => t.card === 'active').length, trucks.length),
    cover(trucks.filter(both).length, trucks.length));
  const rows = question('type').parts.map((p) => ({ p, trucks: list.filter((t) => t.type === p.k) })).filter(({ trucks }) => trucks.length);
  return el('div', { class: 'board-part' }, el('div', { class: 'thread-label' }, 'By driver type'),
    el('table', { class: 'cover-table' },
      el('thead', {}, el('tr', {}, ...['', 'Trucks', 'Samsara working', 'Active card in EFS', 'Both'].map((h) => el('th', { class: 'left' }, h)))),
      el('tbody', {}, ...rows.map(({ p, trucks }) => line(el('span', { class: 'msg-kind', title: p.tip }, mark(p, 'msg'), p.name || p.label), trucks)),
        line('All', list, 'total'))));
}

// What is missing: every group of the Samsara and card questions that is not the good one, biggest first, with its
// count and a bar against all the trucks covered. What to do about it shows when it is pointed at.
function missing(list) {
  const rows = ['samsara', 'card'].flatMap((key) => question(key).parts.slice(1).map((p) => ({ key, p, n: list.filter((t) => t[key] === p.k).length })))
    .filter((r) => r.n).sort((a, b) => b.n - a.n);
  return el('div', { class: 'board-part' }, el('div', { class: 'thread-label' }, 'What is missing'),
    rows.length ? el('ul', { class: 'missing' }, ...rows.map(({ key, p, n }) => el('li', { title: p.todo || p.tip },
      el('div', { class: 'missing-head' }, mark(p, 'msg'), el('span', {}, `${question(key).name}: ${p.label}`), el('b', {}, fmt.count(n))),
      el('i', {}, el('u', { style: `width: ${(n / list.length) * 100}%; background: var(${p.color})` })))))
      : el('p', { class: 'meta' }, 'Nothing: every truck has Samsara working and an active card.'));
}

// A group's color mark and name, for one truck; what the group means, or what to do about it, shows when pointed at.
function tag(t, key) {
  const part = group(key, t[key]);
  return el('span', { class: 'msg-kind', title: part.todo || part.tip }, mark(part, 'msg'), part.label);
}

// A unit's cards in EFS: each card in use by its last four digits with a mark in the color of its status (and the
// status in words when it is not ACTIVE); the name on the card and its account show when pointed at. With only
// inactive cards, how many; a dash with none.
function efsCell(t) {
  const cards = inUse(t), idle = t.efs.length - cards.length;
  if (!cards.length) return el('span', { class: 'meta' }, idle ? `${idle} inactive` : '—');
  return el('span', { class: 'efs-cards' }, ...cards.map((c) => el('span', { class: 'msg-kind', title: `${c.name || 'no name on the card'} · ${c.account}` },
    el('i', { class: 'msg', style: `background: var(${EFS_COLOR[c.status] || '--s4'})` }), `…${c.last4}`,
    c.status !== 'ACTIVE' && el('small', {}, c.status.toLowerCase()))));
}

// One truck's line in the table, its cells in the columns' order; a position older than a day, or none, is in red.
function row(t) {
  const old = !t.gps_at || new Date() - new Date(t.gps_at) > 24 * HOUR;
  const cell = (text, cls = 'left') => el('td', { class: cls }, text);
  return el('tr', {}, el('td', {}, el('b', {}, t.unit)), cell(tag(t, 'type')), cell(personName(t.driver)), cell(group('status', t.status).label),
    cell(t.on_duty ? 'Yes' : 'No'), cell(t.cards.length ? numbers(t.cards) : el('span', { class: 'meta' }, '—')), cell(efsCell(t)),
    cell(tag(t, 'match')), cell(tag(t, 'samsara')), cell(since(t.gps_at), old ? 'left off' : 'left'));
}
