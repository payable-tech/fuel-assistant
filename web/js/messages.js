// The Live view's "Messages sent to drivers": one square per message, colored by what became of it, arranged by the day
// it was sent (with the trucks that got their first message that day) or by why it was sent. The square under the
// pointer (or keyboard focus) shows that message in words.
import { el } from './dom.js';
import { dateOf, dayTime, fmt, personName, plural, short } from './format.js';
import { BECAME, WHY } from './labels.js';

const ORDER = BECAME.map((b) => b.key);  // each stack and row runs in the key's order: our stop first
const LABEL = Object.fromEntries(BECAME.map((b) => [b.key, b.label]));
const ENDED = new Set(BECAME.filter((b) => b.ended).map((b) => b.key));
const PER_ROW = 4;      // a day's stack is this many squares wide
const SQUARE_PX = 16;   // one square and the gap after it

let by = 'day';     // how the squares are arranged, kept across refreshes
let shown = null;   // the messages on screen: redrawn on a switch, and where a pointed square is looked up

// The company's day (US Central) of a moment, as "YYYY-MM-DD".
const centralDay = (when) => new Date(when).toLocaleDateString('en-CA', { timeZone: 'America/Chicago' });

// Wires the "By day / By why we sent it" buttons and the square pointed at, once.
export function initMessages() {
  const buttons = document.querySelectorAll('#plans-by button');
  buttons.forEach((b) => b.addEventListener('click', () => {
    by = b.dataset.by;
    buttons.forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
    if (shown) drawBoard(shown);
  }));
  const board = document.getElementById('plans-msgs');
  const point = (e) => {
    const square = e.target.closest('.msg[data-i]');
    if (square && shown) showPick(shown.messages[+square.dataset.i]);
  };
  board.addEventListener('mouseover', point);
  board.addEventListener('focusin', point);
}

// Draws the panel: its scope (the live trucks on hover), the key with each kind's count and the follow rate, the line
// where a message pointed at shows, and the squares.
export function renderMessages(p) {
  shown = p;
  const count = Object.fromEntries(ORDER.map((k) => [k, p.messages.filter((m) => m.became === k).length]));
  const ended = BECAME.filter((b) => b.ended).reduce((n, b) => n + count[b.key], 0);
  const trucks = new Set(p.messages.map((m) => m.unit)).size;
  const scope = document.getElementById('plans-scope');
  scope.textContent = `${short(dateOf(p.since))} to now · ${plural(p.messages.length, 'message')} to ${plural(trucks, 'truck')}`
    + ' · one square = one message';
  scope.title = `${plural(p.units.length, 'live truck')}: ${p.units.join(', ')}`;
  document.getElementById('plans-key').replaceChildren(
    ...BECAME.map((b) => el('span', { class: count[b.key] ? 'msg-kind' : 'msg-kind zero', title: b.tip },
      el('i', { class: `msg ${b.key}` }), b.label, el('b', {}, fmt.count(count[b.key])))),
    el('span', { class: 'msg-rate', title: "Fueled at our stop, out of the messages that ended: at our stop, at another Love's, "
      + "outside Love's, or drove past. The others aren't counted yet." },
    'Followed', el('b', {}, ended ? fmt.percent(count.there / ended) : '—'), el('small', {}, `${count.there} of ${ended} ended`)));
  showPick(null);
  drawBoard(p);
}

// The line above the squares: the message pointed at, in words; a hint before any is.
function showPick(m) {
  const box = document.getElementById('plans-pick');
  if (!m) {
    box.replaceChildren(el('span', { class: 'meta' },
      'Point at a square to see that message: when, which truck, where we sent it, why, and what the driver did.'));
    return;
  }
  const why = WHY.find((w) => w.key === m.reason);
  box.replaceChildren(el('b', {}, `${dayTime(m.sent_at)} CT`),
    el('span', {}, `Unit ${m.unit}${m.driver ? ` · ${personName(m.driver)}` : ''}`), el('span', {}, m.station || 'Find a truck stop'),
    el('span', { class: 'meta' }, `Why: ${why ? why.label : m.reason}`),
    el('span', { class: 'msg-kind' }, el('i', { class: `msg ${m.became}` }), LABEL[m.became] || m.became));
}

// Puts the squares in, arranged the chosen way; by day, the newest days come into view when they don't all fit.
function drawBoard(p) {
  const board = document.getElementById('plans-msgs');
  board.className = `msg-board by-${by}`;
  const items = p.messages.map((m, i) => ({ m, i }));  // each message with its place in the list, for the pointer
  board.replaceChildren(...(!items.length ? [el('span', { class: 'meta' }, 'No messages sent yet')]
    : by === 'day' ? byDay(items, p.since) : byWhy(items)));
  if (by === 'day') board.scrollLeft = board.scrollWidth;
}

// One column per day from the first message's day to today: on top how many trucks got their first message that day,
// then the day's squares stacked from the bottom in the key's order, under them the day, its count and its follow rate.
function byDay(items, since) {
  const dayOf = items.map(({ m }) => centralDay(m.sent_at));
  const first = {};  // each truck's first message day
  items.forEach(({ m }, k) => { if (!first[m.unit] || dayOf[k] < first[m.unit]) first[m.unit] = dayOf[k]; });
  const days = [];
  for (let n = 0, today = centralDay(new Date()); ; n++) {
    const day = dateOf(since, n).toLocaleDateString('en-CA');
    if (day > today) break;
    days.push(day);
  }
  const lists = days.map((day) => items.filter((x, k) => dayOf[k] === day));
  const height = Math.ceil(Math.max(...lists.map((l) => l.length), 1) / PER_ROW) * SQUARE_PX;  // the busiest day fills it
  return days.map((day, k) => {
    const list = lists[k], added = Object.values(first).filter((f) => f === day).length;
    return el('div', { class: 'msg-day' },
      el('span', { class: 'msg-added', title: 'Trucks that got their first message this day' }, added ? `+${added}` : ''),
      el('div', { class: 'msg-stack', style: `height: ${height}px` }, ...sorted(list).map(square)),
      el('div', { class: 'msg-day-foot' }, el('span', {}, dateOf(day).toLocaleDateString('en-US', { weekday: 'short' })),
        el('b', {}, short(dateOf(day))), el('strong', {}, String(list.length)), el('small', {}, list.length ? `${followed(list)} followed` : '')));
  });
}

// One row per reason a message was sent (the rule, then its squares in the key's order), with its count and follow rate.
function byWhy(items) {
  const known = new Set(WHY.map((w) => w.key));
  const other = [...new Set(items.map(({ m }) => m.reason))].filter((r) => !known.has(r)).map((r) => ({ key: r, label: r, rule: '' }));
  return [...WHY, ...other].map((w) => ({ w, list: items.filter(({ m }) => m.reason === w.key) })).filter(({ list }) => list.length)
    .map(({ w, list }) => el('div', { class: 'msg-why' },
      el('div', { class: 'msg-why-name' }, el('b', {}, w.label), el('small', {}, w.rule)),
      el('div', { class: 'msg-row' }, ...sorted(list).map(square)),
      el('strong', {}, String(list.length)), el('span', { class: 'msg-why-rate' }, `${followed(list)} followed`)));
}

// Messages in the key's order: fueled at our stop first.
const sorted = (list) => [...list].sort((a, b) => ORDER.indexOf(a.m.became) - ORDER.indexOf(b.m.became));

// The follow rate of some messages: at our stop out of those ended; a dash before any ended.
function followed(list) {
  const ended = list.filter(({ m }) => ENDED.has(m.became)).length;
  return ended ? fmt.percent(list.filter(({ m }) => m.became === 'there').length / ended) : '—';
}

// One message as a square: a button, so the keyboard reaches it too, named for screen readers.
const square = ({ m, i }) => el('button', { type: 'button', class: `msg ${m.became}`, 'data-i': i,
  'aria-label': `${dayTime(m.sent_at)}, unit ${m.unit}, ${m.station || 'a truck stop'}: ${LABEL[m.became] || m.became}` });
