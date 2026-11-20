// Small page helpers shared by the views: making elements, figure boxes and cards, and tooltip text.
import { esc } from './format.js';

// Creates an element with attributes and its contents: text and other elements, in order. Missing ones (null, false)
// are skipped, so a part can be left out with `cond && el(...)`; so is an attribute with no value.
export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  Object.entries(attrs).forEach(([k, v]) => { if (v != null) node.setAttribute(k, v); });
  node.append(...children.filter((c) => c != null && c !== false));
  return node;
}

// A figure box: its name, the figure in bold and a small note under it. `cls` sets the box's look; `key` (a color
// token) puts a small color mark before the name, the color of its part in the chart below.
export function figure(cls, name, value, note = '', key = null) {
  const mark = key && el('i', { class: 'key-bar', style: `background: var(${key})` });
  return el('div', { class: cls }, el('span', {}, mark, mark && ' ', name), el('b', {}, value), el('small', {}, note));
}

// A row of figure cards inside `box`, built once from `defs` ({key, label, tip}); `spark` adds a box for a mini trend.
export function ensureCards(box, prefix, defs, spark) {
  if (box.children.length) return;
  box.append(...defs.map((d) => el('div', { class: spark ? 'kpi with-spark' : 'kpi', id: `${prefix}-${d.key}` },
    el('div', { class: 'kpi-top' }, el('span', {}, d.label), el('span', { class: 'info', tabindex: '0', 'data-tip': d.tip }, 'i')),
    el('div', { class: 'kpi-value' }),
    el('div', { class: 'kpi-foot' }, el('span', { class: 'delta' }), el('span', { class: 'note' })),
    spark && el('div', { class: 'spark', id: `${prefix}-spark-${d.key}` }))));
}

// Updates one figure card: its value, its change chip ({text, tone}) and the note after the chip.
export function setCard(id, value, change, note) {
  const card = document.getElementById(id);
  card.querySelector('.kpi-value').textContent = value;
  const delta = card.querySelector('.delta');
  delta.textContent = change.text;
  delta.className = `delta ${change.tone}`;
  card.querySelector('.note').textContent = note;
}

// One tooltip line: an optional color marker (ECharts gives it ready), a label and its value; `total` draws a rule above it.
const tipRow = (label, value, marker = '', total = false) =>
  `<div class="tt-row${total ? ' tt-total' : ''}">${marker}<span>${esc(label)}</span><b>${esc(value)}</b></div>`;

// A tooltip: a title, then its lines: [label, value] (or [label, value, marker, total]); a plain text line is a heading
// over the lines after it.
export function tooltip(title, lines) {
  return `<div class="tt-title">${esc(title)}</div>`
    + lines.map((line) => (typeof line === 'string' ? `<div class="tt-head">${esc(line)}</div>` : tipRow(...line))).join('');
}
