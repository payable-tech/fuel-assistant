// The All cards view of the Cards section: every EFS card, one row each, as the copy of EFS's list has it. On top, a
// summary, a picture only: each account's cards by status, how their checks stand against the status, and the cards in
// use by the day EFS last saw them used. Under it, the cards as a table filtered and sorted from its column headings
// (table.js).
import { el } from './dom.js';
import { ago, dayClock, fmt, personName, plural, until } from './format.js';
import { filterTable, mark } from './table.js';

// A card's state: its status in EFS, with the inactive cards the cleanup parked apart.
const STATES = [
  { k: 'ACTIVE', label: 'Active', color: '--good', tip: 'EFS: ACTIVE, the pump takes it' },
  { k: 'HOLD', label: 'Hold', color: '--warn', tip: 'EFS: HOLD, the pump refuses it until it is released or overridden' },
  { k: 'HOLD FOR FRAUD', label: 'Fraud hold', color: '--bad', tip: 'EFS: HOLD FOR FRAUD, the pump refuses it until it is overridden; a new card is due' },
  { k: 'INACTIVE', label: 'Inactive', color: '--s6', tip: 'EFS: INACTIVE' },
  { k: 'parked', label: 'Parked', color: '--s6', hollow: true, tip: 'INACTIVE, on unit 99999 / ALIF UZ CORP (the card cleanup)' },
  { k: 'other', label: 'Other status', color: '--faint', tip: 'An EFS status the page has no name for' },
];
// When EFS last saw a card used, as its own page says; only the pages of cards in use are read.
const USES = [
  { k: 'day', label: 'Today or yesterday', color: '--good' },
  { k: 'week', label: '2 to 7 days ago', color: '--s3' },
  { k: 'month', label: '8 to 30 days ago', color: '--warn' },
  { k: 'old', label: 'Over 30 days ago', color: '--bad' },
  { k: 'never', label: 'Never used', color: '--s4' },
  { k: 'unread', label: 'Not read', color: '--line', tip: 'Only the pages of cards in use (any status but INACTIVE) are read' },
];
// Whom Datatruck assigns the same card to (found in EFS by its full number), as the server names it.
const DATATRUCK = [
  { k: 'driver', label: 'Active driver', color: '--good', tip: 'Datatruck assigns this card to a driver who is active' },
  { k: 'left', label: 'Driver not active', color: '--bad', tip: 'Datatruck assigns this card to a driver who is no longer active' },
  { k: 'truck', label: 'On a truck', color: '--s1', tip: 'Datatruck assigns this card to a truck, not a driver' },
  { k: 'nobody', label: 'Not assigned', color: '--warn', tip: 'Datatruck has this card but assigns it to nobody' },
  { k: 'none', label: 'Not in Datatruck', color: '--line', tip: 'Datatruck has no card with this number (or it is not looked up yet)' },
];
// How a card's latest check stands against its status (the server's verdict), and how sure the check was.
const VERDICTS = [
  { k: 'agree', label: 'Agrees', mark: '✓', color: '--good', tip: 'What the card should be is what it is' },
  { k: 'off', label: 'Should be off', mark: '✗', color: '--bad', tip: 'The card is on, and the check says it should be off' },
  { k: 'on', label: 'Should be on', mark: '✗', color: '--warn', tip: 'The card is not on, and the check says it should be' },
  { k: 'unsure', label: 'Unsure', mark: '?', color: '--s4', tip: 'The check could not tell' },
  { k: 'unchecked', label: 'Not checked', color: '--s6', hollow: true, tip: 'No check of this card yet' },
];
const SURE = [
  { k: 'high', label: 'High', tone: 'good', tip: 'The group and the data say the same' },
  { k: 'medium', label: 'Medium', tone: 'warn', tip: 'Only the group, or only the data, says it' },
  { k: 'low', label: 'Low', tone: '', tip: 'Nothing recent to go on' },
  { k: 'none', label: 'Not checked', tone: '' },
];
const ACCOUNTS = [{ k: 'ALIF', label: 'ALIF' }, { k: 'DT', label: 'DT' }];

// A card's group in one of those lists, by its key.
const state = (c) => (c.parked && c.status === 'INACTIVE' ? 'parked' : STATES.some((s) => s.k === c.status) ? c.status : 'other');
const use = (c) => (!c.read ? 'unread' : c.days == null ? 'never' : c.days <= 1 ? 'day' : c.days <= 7 ? 'week' : c.days <= 30 ? 'month' : 'old');
const part = (list, k) => list.find((p) => p.k === k);
const place = (list, k) => list.findIndex((p) => p.k === k);

// How long ago EFS last saw the card used, in a few letters: "Today", "Yesterday", "12 d ago"; "Never"; a dash when
// its page isn't read.
function used(c) {
  if (!c.read) return '—';
  if (c.days == null) return 'Never';
  return c.days === 0 ? 'Today' : c.days === 1 ? 'Yesterday' : `${fmt.count(c.days)} d ago`;
}

// The table's columns: the heading, what a card is sorted by, and how it is filtered (see table.js).
const COLUMNS = [
  { key: 'account', name: 'Account', by: (c) => c.account, of: (c) => c.account, choices: ACCOUNTS },
  { key: 'card', name: 'Card', by: (c) => c.last4, text: (c) => `…${c.last4} ${c.number || ''}` },
  { key: 'driver', name: 'Driver on card', by: (c) => c.driver || '', text: (c) => c.driver || '' },
  { key: 'unit', name: 'Unit on card', by: (c) => c.unit || '', text: (c) => c.unit || '' },
  { key: 'id', name: 'Driver ID', by: (c) => c.driver_id || '', text: (c) => c.driver_id || '' },
  { key: 'xref', name: 'X-Ref', by: (c) => c.xref || '', text: (c) => c.xref || '' },
  { key: 'state', name: 'Status', by: (c) => place(STATES, state(c)), of: state, choices: STATES },
  { key: 'use', name: 'Last used', by: (c) => (c.read ? c.days ?? 1e6 : 2e6), of: use, choices: USES },
  { key: 'datatruck', name: 'Driver in Datatruck', by: (c) => `${place(DATATRUCK, c.datatruck)} ${c.dt_driver || ''}`,
    of: (c) => c.datatruck, choices: DATATRUCK },
  { key: 'dtunit', name: 'Unit in Datatruck', by: (c) => c.dt_unit || '', text: (c) => c.dt_unit || '' },
  { key: 'verdict', name: 'Should be', by: (c) => place(VERDICTS, c.verdict), of: (c) => c.verdict, choices: VERDICTS },
  { key: 'why', name: 'Why', by: (c) => c.why || '', text: (c) => c.why || '' },
  { key: 'sure', name: 'Sure', by: (c) => place(SURE, c.sure || 'none'), of: (c) => c.sure || 'none', choices: SURE },
];
const STATUS_COLUMN = COLUMNS.findIndex((c) => c.key === 'state');

let drawTable = null;  // the cards' table (table.js), made once the page is there

// Orders two cards by the unit on them, numbers by their value ("9" before "10"), then by their last four digits.
const byUnit = (a, b) => (a.unit || '').localeCompare(b.unit || '', 'en', { numeric: true }) || a.last4.localeCompare(b.last4);

// How long ago a stored time was ("2026-11-26 13:27:50+00:00"); "never" without one.
const since = (when) => (when ? ago(when.replace(' ', 'T')) : 'never');

// Makes the cards' table, sorted by status at first (active cards on top).
export function initAllCards() {
  drawTable = filterTable({ columns: COLUMNS, row, tie: byUnit, noun: 'card', start: STATUS_COLUMN, cls: 'card-table',
    ids: { list: 'allcards-list', count: 'allcards-count', chips: 'allcards-chips', clear: 'allcards-clear', pop: 'allcards-pop' } });
}

// Draws the view from fresh numbers.
export function renderAllCards(d) {
  const linking = d.links.done < d.links.of ? ` · Datatruck's cards found in EFS: ${fmt.count(d.links.done)} of ${fmt.count(d.links.of)}` : '';
  document.getElementById('allcards-meta').textContent = `${plural(d.cards.length, 'card')} · one row per EFS card · `
    + `EFS's list copied ${since(d.efs_at)}, card pages read ${since(d.pages_at)}${linking}`;
  showChecker(d.check);
  const inUse = d.cards.filter((c) => c.status !== 'INACTIVE');
  document.getElementById('allcards-board').replaceChildren(el('div', { class: 'board-pair even' },
    bars('By account · every card', d.cards, STATES, state),
    bars('Status against its check · every card', d.cards, VERDICTS, (c) => c.verdict),
    bars('Cards in use · by when EFS last saw them used', inUse, USES.filter((u) => u.k !== 'unread'), use)));
  drawTable(d.cards);
}

// The card checker's chip on top: running now, or when it runs next (US Central) and when it last checked; red when
// Windows' Task Scheduler has it off or doesn't have it.
function showChecker(check) {
  const chip = document.getElementById('allcards-check');
  const last = `last ${since(check.last_at)}`;
  const [tone, text] = check.state === 'Running' ? ['--warn', 'Card check running now']
    : check.next_at ? ['--good', `Next card check ${dayClock(check.next_at)} (${until(check.next_at)}) · ${last}`]
      : ['--bad', `Card check ${check.state ? 'off in Task Scheduler' : 'not scheduled'} · ${last}`];
  chip.replaceChildren(el('i', { style: `background: var(${tone})` }), text);
  chip.title = "Windows' Task Scheduler runs the card checker; it reads each active card's group and changes no card";
  chip.hidden = false;
}

// Says on the view's top line that it can't be loaded, and why.
export function showAllCardsError(error) {
  document.getElementById('allcards-meta').textContent = `Can't load the cards: ${error.message}`;
}

// A bar segment's paint: filled in its group's color, or an outline in it.
const paint = (g) => (g.hollow ? `box-shadow: inset 0 0 0 2px var(${g.color}); color: var(--muted)` : `background: var(${g.color})`);

// One part of the summary: a bar per account and one for all, each split into `groups` by `of`, with the key and the
// counts of all under them. A group drawn hollow (parked) is an outline with its count in grey.
function bars(title, cards, groups, of) {
  const line = (name, list, cls = '') => {
    const parts = groups.map((g) => ({ ...g, n: list.filter((c) => of(c) === g.k).length })).filter((g) => g.n);
    return el('div', { class: `card-bar ${cls}` }, el('span', {}, name), el('b', {}, fmt.count(list.length)),
      el('div', { class: 'have-bar' }, ...parts.map((g) => el('i', { style: `flex: ${g.n}; ${paint(g)}`, title: `${g.label}: ${g.n}` },
        g.n / list.length > 0.06 ? fmt.count(g.n) : ''))));
  };
  const all = groups.map((g) => ({ ...g, n: cards.filter((c) => of(c) === g.k).length })).filter((g) => g.n);
  return el('div', { class: 'board-part' }, el('div', { class: 'thread-label' }, title),
    ...ACCOUNTS.map((a) => line(a.label, cards.filter((c) => c.account === a.k))), line('All', cards, 'total'),
    el('div', { class: 'have-key' }, ...all.map((g) => el('span', { title: g.tip || null }, mark(g), g.label, el('b', {}, fmt.count(g.n)),
      el('small', {}, fmt.percent(g.n / cards.length))))));
}

// A group's color mark and name, for one card; what it means shows when pointed at.
function tag(group, extra = null) {
  return el('span', { class: 'msg-kind', title: group.tip || null }, mark(group, 'msg'), group.label, extra);
}

// One card's line in the table, its cells in the columns' order. A card in override mode says so by its status; the
// Datatruck driver is named, or the group says why there is none.
function row(c) {
  const cell = (content, cls = '') => el('td', { class: `left ${cls}` }, content);
  const none = () => el('span', { class: 'meta' }, '—');
  const assigned = part(DATATRUCK, c.datatruck) || { label: c.datatruck };
  const named = (name) => el('span', { title: name }, personName(name));  // the whole name on hover, when clipped
  return el('tr', {}, cell(c.account), cell(copyButton(c)), cell(c.driver ? named(c.driver) : none(), 'clip'),
    cell(c.unit || none()), cell(c.driver_id || none()), cell(c.xref ? el('span', { title: c.xref }, c.xref) : none(), 'clip'), cell(tag(part(STATES, state(c)), c.override && el('small', {}, 'override'))),
    cell(el('span', { class: 'msg-kind', title: c.last_used ? `EFS: last used ${c.last_used}` : part(USES, use(c)).tip || null },
      mark(part(USES, use(c)), 'msg'), used(c))),
    cell(el('span', { class: 'msg-kind', title: [c.dt_driver, assigned.tip].filter(Boolean).join(' · ') || null }, mark(assigned, 'msg'),
      c.dt_driver ? personName(c.dt_driver) : assigned.label), 'clip'),
    cell(c.dt_unit || none()), cell(shouldBe(c)), cell(c.why ? el('span', { title: [c.why, checkTip(c)].filter(Boolean).join(' · ') }, c.why) : none(), 'clip why'),
    cell(c.sure ? el('span', { class: `badge ${part(SURE, c.sure)?.tone || ''}`, title: part(SURE, c.sure)?.tip || null },
      part(SURE, c.sure)?.label || c.sure) : none()));
}

// A card's last four digits as a button that copies its full number (from Datatruck; EFS shows only the last four),
// saying "Copied" for a moment. A card Datatruck doesn't have has no full number to copy.
function copyButton(c) {
  const button = el('button', { type: 'button', class: 'copy-card',
    title: c.number ? 'Copy the full card number' : "No full number: Datatruck doesn't have this card" }, `…${c.last4}`);
  button.addEventListener('click', async () => {
    const done = c.number && await copied(c.number);
    button.textContent = done ? 'Copied' : c.number ? "Can't copy" : 'No number';
    button.classList.toggle('done', Boolean(done));
    setTimeout(() => { button.textContent = `…${c.last4}`; button.classList.remove('done'); }, 1500);
  });
  return button;
}

// Puts text on the clipboard; true when it worked. Browsers allow the clipboard only on this PC's own address, so
// from another office PC the page's older copy command is used.
async function copied(text) {
  try {
    if (window.isSecureContext && navigator.clipboard) {
      await navigator.clipboard.writeText(text);
      return true;
    }
    const box = el('textarea', { readonly: '', style: 'position: fixed; opacity: 0' });
    box.value = text;
    document.body.append(box);
    box.select();
    const ok = document.execCommand('copy');
    box.remove();
    return ok;
  } catch {
    return false;
  }
}

// What the card should be, against what it is: a green tick when they agree ("✓ Active"), a cross with the change
// when they don't ("✗ Off"), a question mark when the check couldn't tell; a dash before any check.
function shouldBe(c) {
  const v = part(VERDICTS, c.verdict) || { label: c.verdict };
  if (c.verdict === 'unchecked') return el('span', { class: 'meta', title: v.tip }, '—');
  const words = c.verdict === 'agree' ? part(STATES, state(c)).label : c.verdict === 'off' ? 'Off' : c.verdict === 'on' ? 'On' : 'Unsure';
  return el('span', { class: 'msg-kind', title: v.tip }, el('b', { class: 'verdict', style: `color: var(${v.color}-ink, var(${v.color}))` }, v.mark), words);
}

// What a check read, and when, shown on pointing at its why.
const checkTip = (c) => [c.evidence, c.checked_at && `Checked ${since(c.checked_at)}`].filter(Boolean).join(' · ') || null;
