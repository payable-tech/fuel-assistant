// A table filtered from its own column headings, like Datatruck's tables: a click on a heading's name sorts by that
// column (again turns the order) and the button beside it opens the column's filter. Several choices in one column
// are either-or; the columns together narrow the list down. Over the table: the count, the filter in words (each part
// with a cross to drop it) and "Clear filters". The fleet status and the card list use it.
import { el } from './dom.js';
import { fmt, plural } from './format.js';

// A group's color mark: filled in its color, or hollow for the one drawn as an outline; nothing for a choice with no
// color of its own.
export function mark(part, cls = '') {
  if (!part.color) return null;
  const paint = part.hollow ? `box-shadow: inset 0 0 0 2px var(${part.color})` : `background: var(${part.color})`;
  return el('i', { class: cls, style: paint });
}

// Makes a table. `columns`: each with its heading `name`, what a row sorts by (`by`), and how it is filtered: `text`
// (what is typed must be in it), or `choices` with `of` (the choice a row falls in). `row` draws one row's <tr>, `tie`
// orders rows the column leaves equal, `noun` names a row ("truck"), `start` is the column sorted by at first, `cls`
// a class of its own for the table. `ids` are the page's parts: list, count, chips, clear, pop. Returns `draw(rows)`,
// which shows fresh rows, the filter and the order kept as they were.
export function filterTable({ columns, row, tie, noun, ids, start = 0, cls = '' }) {
  const part = (name) => document.getElementById(ids[name]);
  let rows = [];
  let sortBy = { column: start, down: false };  // a column, and whether it runs downward
  let open = null;                          // the column whose filter is open, by its key
  // the filter: each column's choices picked (none: all), or the words typed for a text column
  const picked = Object.fromEntries(columns.map((c) => [c.key, new Set()]));
  const typed = Object.fromEntries(columns.filter((c) => c.text).map((c) => [c.key, '']));

  // True when a column is filtered.
  const filtered = (c) => (c.text ? Boolean(typed[c.key].trim()) : picked[c.key].size > 0);

  // Drops one column's filter.
  const clearColumn = (c) => { picked[c.key].clear(); if (c.text) typed[c.key] = ''; };

  // True when a row passes one column's filter.
  function passesColumn(r, c) {
    if (c.text) return !typed[c.key].trim() || c.text(r).toLowerCase().includes(typed[c.key].trim().toLowerCase());
    return !picked[c.key].size || picked[c.key].has(c.of(r));
  }

  // True when a row passes every column's filter; `but` leaves one column out (for that column's own counts).
  const passes = (r, but = null) => columns.every((c) => c.key === but || passesColumn(r, c));

  // The rows the filter leaves, in the order picked on a heading; over them the count, the filter in words and "Clear
  // filters". An open filter is drawn again, so its counts follow.
  function draw() {
    const list = rows.filter((r) => passes(r));
    const column = columns[sortBy.column];
    const way = sortBy.down ? -1 : 1;
    const compare = (a, b) => {
      const x = column.by(a), y = column.by(b);
      return (typeof x === 'number' ? x - y : String(x).localeCompare(String(y), 'en', { numeric: true })) * way || tie(a, b);
    };
    part('count').textContent = `${fmt.count(list.length)} of ${plural(rows.length, noun)}`;
    part('chips').replaceChildren(...columns.filter(filtered).map(chip));
    part('clear').hidden = !columns.some(filtered);
    part('list').replaceChildren(el('div', { class: 'table-wrap' }, el('table', { class: `table fleet-table ${cls}` },
      el('thead', {}, el('tr', {}, ...columns.map(head))),
      el('tbody', {}, ...(list.length ? [...list].sort(compare).map(row)
        : [el('tr', {}, el('td', { class: 'left', colspan: String(columns.length) }, `No ${noun} passes this filter.`))])))));
    part('list').querySelector('.table-wrap').addEventListener('scroll', () => { if (open) closeFilter(); });
    if (open) drawFilter();
  }

  // One column's filter in words, as a chip with a cross that drops it.
  function chip(c) {
    const said = c.text ? `"${typed[c.key].trim()}"` : c.choices.filter((p) => picked[c.key].has(p.k)).map((p) => p.label).join(' or ');
    const button = el('button', { type: 'button', class: 'fleet-chip', title: 'Drop this filter' }, `${c.name}: ${said}`, el('span', {}, '×'));
    button.addEventListener('click', () => { clearColumn(c); closeFilter(); });
    return button;
  }

  // A column's heading: its name (a click sorts by it; again turns the order) and the button that opens its filter,
  // lit while the column is filtered.
  function head(c, i) {
    const on = i === sortBy.column;
    const sort = el('button', { type: 'button', class: on ? 'sort on' : 'sort', title: 'Sort by this column' },
      c.name, el('i', { class: 'sort-way' }, on ? (sortBy.down ? '↓' : '↑') : '↕'));
    sort.addEventListener('click', () => { sortBy = { column: i, down: on ? !sortBy.down : false }; draw(); });
    const filter = el('button', { type: 'button', class: filtered(c) ? 'col-filter on' : 'col-filter',
      'data-col': c.key, 'aria-label': `Filter by ${c.name}`, 'aria-expanded': String(open === c.key), title: `Filter by ${c.name}` });
    filter.innerHTML = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2 4h12M4.5 8h7M7 12h2" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>';
    filter.addEventListener('click', () => { open = open === c.key ? null : c.key; draw(); if (!open) closeFilter(); });
    return el('th', { class: 'left', 'aria-sort': on ? (sortBy.down ? 'descending' : 'ascending') : null },
      el('div', { class: 'col-head' }, sort, filter));
  }

  // Closes the open filter and draws the table as the filter now stands.
  function closeFilter() {
    open = null;
    part('pop').hidden = true;
    draw();
  }

  // The open column's filter, under its button: for a text column a box to type in; for the others its choices to
  // tick, each with the number of rows it would list with the other columns as they stand.
  function drawFilter() {
    const c = columns.find((col) => col.key === open);
    const pop = part('pop');
    const anchor = part('list').querySelector(`.col-filter[data-col="${open}"]`);
    const body = c.text ? textFilter(c) : choiceFilter(c);
    const clear = el('button', { type: 'button', class: 'fleet-clear' }, 'Clear');
    clear.addEventListener('click', () => { clearColumn(c); draw(); });
    const done = el('button', { type: 'button', class: 'fleet-clear' }, 'Done');
    done.addEventListener('click', closeFilter);
    pop.replaceChildren(el('div', { class: 'pop-head' }, c.name), body, el('div', { class: 'pop-foot' }, clear, done));
    pop.hidden = false;
    const at = anchor.getBoundingClientRect();
    pop.style.top = `${at.bottom + window.scrollY + 6}px`;
    pop.style.left = `${Math.max(8, Math.min(at.left + window.scrollX - 8, window.scrollX + document.documentElement.clientWidth - pop.offsetWidth - 8))}px`;
    const box = pop.querySelector('input[type="search"]');
    if (box) { box.focus(); box.setSelectionRange(box.value.length, box.value.length); }
  }

  // A text column's filter: what is typed must be in the row's value.
  function textFilter(c) {
    const box = el('input', { type: 'search', class: 'search', placeholder: `${c.name} contains…`, 'aria-label': `${c.name} contains`, autocomplete: 'off' });
    box.value = typed[c.key];
    box.addEventListener('input', () => { typed[c.key] = box.value; draw(); });
    box.addEventListener('keydown', (e) => { if (e.key === 'Enter') closeFilter(); });
    return box;
  }

  // A column's choices to tick; none ticked means all. A choice no row is in (with the other columns as they stand)
  // is dim.
  function choiceFilter(c) {
    const others = rows.filter((r) => passes(r, c.key));
    return el('div', { class: 'pop-list' }, ...c.choices.map((p) => {
      const n = others.filter((r) => c.of(r) === p.k).length;
      const tick = el('input', { type: 'checkbox' });
      tick.checked = picked[c.key].has(p.k);
      tick.addEventListener('change', () => { picked[c.key][tick.checked ? 'add' : 'delete'](p.k); draw(); });
      return el('label', { class: n || tick.checked ? 'pop-choice' : 'pop-choice zero', title: p.tip || p.todo || null },
        tick, mark(p), el('span', {}, p.label), el('b', {}, fmt.count(n)));
    }));
  }

  // A click outside the open filter, or Escape, closes it. The click's own path is asked, because a click inside the
  // filter redraws it before this is reached.
  const inside = (node) => node === part('pop') || (node.classList && node.classList.contains('col-filter'));
  document.addEventListener('click', (e) => { if (open && !e.composedPath().some(inside)) closeFilter(); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && open) closeFilter(); });
  part('clear').addEventListener('click', () => { columns.forEach(clearColumn); closeFilter(); });
  return (fresh) => { rows = fresh; draw(); };
}
