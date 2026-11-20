// Notifications of the messages sent to drivers (the user's ask, 2026-11-04): a bell in the top bar with how many you
// haven't marked checked (also in the tab's title), the latest ones in a list, and a popup for each one that comes in
// while the page is open. Each shows how long ago it went out, opens that truck's plan, and can be marked checked.
import { el } from './dom.js';
import { ago, dayTime, personName } from './format.js';
import { BECAME } from './labels.js';

const CHECKED_KEY = 'notes-checked';  // the messages you marked checked, in this browser
const LIST_SIZE = 20;                 // latest messages in the list
const MAX_POPUPS = 3;                 // popups on screen at once; the bell keeps the rest
const TITLE = document.title;         // the tab's title, before the count is put in front
const LABEL = Object.fromEntries(BECAME.map((b) => [b.key, b.label]));  // what became of a message, in words

let messages = [];  // the messages sent so far, oldest first
let known = null;  // messages already shown on this page: only ones that come in after the first load pop up

// A message's id: its truck and when it was sent.
const idOf = (m) => `${m.unit}|${m.sent_at}`;

// The ids of the messages marked checked.
function checked() {
  try { return new Set(JSON.parse(localStorage.getItem(CHECKED_KEY)) || []); } catch { return new Set(); }
}

// Marks messages checked (only ids still in the list are kept, so it never grows) and redraws.
function markChecked(ids) {
  const keep = new Set(messages.map(idOf));
  const all = [...checked(), ...ids].filter((id) => keep.has(id));
  try { localStorage.setItem(CHECKED_KEY, JSON.stringify([...new Set(all)])); } catch { /* not remembered */ }
  drawCount();
  if (!document.getElementById('notes-panel').hidden) drawList();
}

// Opens a truck's plan on the Recommend tab and closes the list.
function openPlan(m) {
  showList(false);
  location.hash = `#recommend/${m.unit}`;
}

// One message as the list and the popups show it: the truck and driver, where to and how far, how long ago it went out,
// what came of it, and its buttons: open the plan, mark it checked (or that it is).
function card(m, cls, done, onCheck) {
  const what = `${m.kind === 'urgent' ? '⚠️ Low fuel: ' : ''}${m.station || 'nearest truck stop'}`
    + (m.miles != null ? ` · in ${Math.round(Math.max(m.miles, 0))} mi` : '');
  const text = el('div', { class: 'note-text' }, el('b', {}, `Unit ${m.unit}${m.driver ? ` · ${personName(m.driver)}` : ''}`),
    el('span', {}, what), el('small', {}, `Sent ${ago(m.sent_at)} · ${dayTime(m.sent_at)} CT · ${LABEL[m.became] || m.became}`));
  const open = el('button', { type: 'button', class: 'open-plan' }, 'Open plan');
  open.addEventListener('click', () => openPlan(m));
  const check = done ? el('span', { class: 'checked' }, '✓ Checked') : el('button', { type: 'button', class: 'mark-checked' }, 'Mark checked');
  if (!done) check.addEventListener('click', () => { markChecked([idOf(m)]); if (onCheck) onCheck(); });
  return el('div', { class: `${cls}${done ? '' : ' is-new'}` }, text, el('div', { class: 'note-buttons' }, open, check));
}

// The count of unchecked messages on the bell and in the tab's title.
function drawCount() {
  const done = checked();
  const open = messages.filter((m) => !done.has(idOf(m))).length;
  const count = document.getElementById('bell-count');
  count.hidden = !open;
  count.textContent = String(open);
  document.title = open ? `(${open}) ${TITLE}` : TITLE;
  document.getElementById('check-all').hidden = !open;
}

// The list of the latest messages, newest first, the unchecked ones marked.
function drawList() {
  const done = checked();
  const items = messages.slice(-LIST_SIZE).reverse().map((m) => el('li', {}, card(m, 'note-card', done.has(idOf(m)))));
  document.getElementById('notes-list').replaceChildren(...(items.length ? items : [el('li', { class: 'notes-empty' }, 'No messages sent yet')]));
}

// Opens or closes the list. Opening it clears the popups: they would cover it, and their messages are in it.
function showList(open) {
  document.getElementById('notes-panel').hidden = !open;
  document.getElementById('bell').setAttribute('aria-expanded', String(open));
  if (open) {
    document.getElementById('toasts').replaceChildren();
    drawList();
  }
}

// A popup for a message that just went out; it stays until closed, checked, or its plan is opened.
function popup(m) {
  const box = document.getElementById('toasts');
  const toast = card(m, 'toast', false, () => toast.remove());
  const close = el('button', { type: 'button', class: 'toast-close', 'aria-label': 'Close' }, '×');
  close.addEventListener('click', () => toast.remove());
  toast.querySelector('.open-plan').addEventListener('click', () => toast.remove());
  toast.prepend(close);
  box.prepend(toast);
  [...box.children].slice(MAX_POPUPS).forEach((old) => old.remove());
}

// Takes the messages sent so far (oldest first), from each refresh of the live numbers: pops up the new ones and
// redraws the count, and the list if it is open (so "how long ago" stays current).
export function renderNotes(sent) {
  messages = sent || [];
  const ids = messages.map(idOf);
  if (known) messages.filter((m, i) => !known.has(ids[i])).forEach(popup);
  known = new Set(ids);
  drawCount();
  if (!document.getElementById('notes-panel').hidden) drawList();
}

// Wires the bell (opens and closes the list; a click elsewhere or Escape closes it) and "Check all".
export function initNotes() {
  document.getElementById('bell').addEventListener('click', (e) => {
    e.stopPropagation();
    showList(document.getElementById('notes-panel').hidden);
  });
  document.getElementById('notes-panel').addEventListener('click', (e) => e.stopPropagation());
  document.getElementById('check-all').addEventListener('click', () => markChecked(messages.map(idOf)));
  document.addEventListener('click', () => showList(false));
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') showList(false); });
}
