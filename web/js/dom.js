// Small page helpers shared by the views: making elements and figure cards.

// Creates an element with attributes and optional text.
export function el(tag, attrs = {}, text) {
  const node = document.createElement(tag);
  Object.entries(attrs).forEach(([k, v]) => node.setAttribute(k, v));
  if (text != null) node.textContent = text;
  return node;
}

// A row of figure cards inside `box`, built once from `defs` ({key, label, tip}); `spark` adds a box for a mini trend.
export function ensureCards(box, prefix, defs, spark) {
  if (box.children.length) return;
  box.append(...defs.map((d) => {
    const card = el('div', { class: spark ? 'kpi with-spark' : 'kpi', id: `${prefix}-${d.key}` });
    const top = el('div', { class: 'kpi-top' });
    top.append(el('span', {}, d.label), el('span', { class: 'info', tabindex: '0', 'data-tip': d.tip }, 'i'));
    const foot = el('div', { class: 'kpi-foot' });
    foot.append(el('span', { class: 'delta' }), el('span', { class: 'note' }));
    card.append(top, el('div', { class: 'kpi-value' }), foot);
    if (spark) card.append(el('div', { class: 'spark', id: `${prefix}-spark-${d.key}` }));
    return card;
  }));
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
