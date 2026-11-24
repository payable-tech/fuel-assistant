// The Cards section: the card agent at work. On top a slim strip with its state (running, eManager, its batch of jobs
// as one square each, the last tag heard); under it the requests it took, newest first, and the picked request as one
// conversation: the chat it read, what it thought, each tool it used with the answer, what went to the driver and the
// office, and what the truck bought since. The picked request is kept in the address (#cards/<id>).
import { load } from './api.js';
import { el } from './dom.js';
import { ago, dayClock, dayTime, fmt, plural, stationName, timeOf } from './format.js';
import { CARD_KINDS, CARD_TOOLS } from './labels.js';

let shown = null;      // the numbers on screen: the agent's state and its requests
let showAll = false;   // false: the requests about a card; true: every tag it took, a thank-you too
let known = null;      // the requests already listed: one that comes in later lights up
let drawn = '';        // the conversation on screen, as text: it is redrawn only when it changed
const CHAT_SHOWN = 3;  // the newest messages of the chat shown; the ones before them are folded

// What became of a request, in words and its tone; one the page doesn't know is shown by its key.
const kindOf = (r) => CARD_KINDS[r.kind] || { label: r.kind, tone: 'off' };

// The request picked in the address, if any ("#cards/-100123_456" -> "-100123_456").
const pickedId = () => (location.hash.startsWith('#cards/') ? location.hash.slice(7) : null);

// The requests the list shows now: all of them, or those about a card.
const listed = () => shown.runs.filter((r) => showAll || r.kind !== 'nothing');

// A span of seconds in words: "18 s", "2 min 5 s", "1 h 3 min".
function span(seconds) {
  if (seconds < 60) return `${seconds} s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ${seconds % 60} s`;
  return `${Math.floor(seconds / 3600)} h ${Math.floor((seconds % 3600) / 60)} min`;
}

// A moment as "07:12" on the company's clock.
const clock = (when) => new Date(when).toLocaleTimeString('en-US', { timeZone: 'America/Chicago', hourCycle: 'h23', hour: '2-digit', minute: '2-digit' });

// A card's short name from its full one: "card …0503 (ALIF, unit 1871, PAUL WISLY)" -> "card …0503".
const shortCard = (card) => (card && card.name ? card.name.split(' (')[0] : null);

// Wires the switch between the card requests and everything heard, once.
export function initCards() {
  document.getElementById('cards-show').addEventListener('click', (e) => {
    const button = e.target.closest('button[data-show]');
    if (!button) return;
    showAll = button.dataset.show === 'all';
    document.querySelectorAll('#cards-show button').forEach((b) => b.setAttribute('aria-pressed', String(b === button)));
    drawList();
    drawTalk();
  });
  window.addEventListener('hashchange', () => { if (shown && location.hash.startsWith('#cards')) { drawList(); drawTalk(); } });
}

// Draws the section from fresh numbers: the strip, the list, and the picked request's conversation.
export function renderCards(d) {
  shown = d;
  document.getElementById('cards-meta').textContent = `Requests in the truck groups where the fuel desk's account is tagged · since ${dayTime(d.from)} CT`;
  drawStrip(d.agent);
  drawList();
  known = new Set(d.runs.map((r) => r.id));
  drawTalk();
}

// Says on the section's top line that it can't be loaded, and why.
export function showCardsError(error) {
  document.getElementById('cards-meta').textContent = `Can't load the card agent: ${error.message}`;
}

// Picks a request: into the address, then the list and the conversation follow; the conversation is brought to its
// top when the page was scrolled past it.
async function pick(id) {
  history.replaceState(null, '', `#cards/${id}`);
  drawList();
  await drawTalk();
  const box = document.getElementById('cards-talk');
  if (box.getBoundingClientRect().top < 0) box.scrollIntoView({ block: 'start' });
}

// One cell of the strip: a state dot in its tone, the state in words, a note under it; `extra` sits beside the words.
function cell(tone, title, note, extra = null) {
  return el('div', { class: `agent-cell ${tone}` }, el('i', { class: 'agent-dot' }),
    el('div', { class: 'agent-words' }, el('div', { class: 'agent-title' }, el('b', {}, title), extra), el('small', {}, note)));
}

// The strip: is the agent running, is eManager logged in, its batch of jobs, the last tag it heard. A stopped agent,
// a logged-out eManager and a batch that is done are the loud ones.
function drawStrip(a) {
  const running = a.running
    ? cell('t-good', 'Agent running', `last sign ${ago(a.beat_at)}`)
    : cell('t-bad loud', 'Agent stopped', `${a.beat_at ? `last sign ${ago(a.beat_at)}` : 'never started'} · start run_agent.bat on the server PC`);
  const since = a.emanager_since ? `since ${dayClock(a.emanager_since)} CT` : '';
  const emanager = a.emanager == null ? cell('t-off', 'eManager not checked yet', 'the agent checks it every few minutes')
    : !a.running ? cell('t-off', `eManager was logged ${a.emanager ? 'in' : 'out'}`, 'as the agent last saw it')
      : a.emanager ? cell('t-good', 'eManager logged in', since)
        : cell('t-bad loud', 'eManager logged out', `${since} · log in in its window on the server PC`);
  const batch = shown.runs.filter((r) => r.in_batch).reverse();  // oldest first, as they were done
  const squares = a.jobs_most == null ? null : el('span', { class: 'job-squares' },
    ...batch.slice(0, a.jobs_most).map(jobSquare),
    ...Array.from({ length: Math.max(a.jobs_most - batch.length, 0) }, () => el('i', { class: 'job-sq empty' })));
  const from = `since ${dayClock(a.jobs_since)} CT`;
  const jobs = a.jobs_most == null ? cell('t-info', `${plural(a.jobs_done, 'job')}, no limit`, from)
    : a.paused ? cell('t-warn loud', `Paused: ${a.jobs_done} of ${a.jobs_most} jobs done`, `card requests go to the office · ${from}`, squares)
      : cell('t-info', `${a.jobs_done} of ${a.jobs_most} jobs`, `${from} · one square = one job`, squares);
  const tag = a.tag_at ? cell('t-off', `Last tag heard ${ago(a.tag_at)}`, a.tag_note || '') : cell('t-off', 'No tag heard yet', 'since the agent last started');
  document.getElementById('agent-strip').replaceChildren(running, emanager, jobs, tag);
}

// One job of the batch as a square in the color of what became of it; a click opens it.
function jobSquare(r) {
  const k = kindOf(r);
  const square = el('button', { type: 'button', class: `job-sq t-${k.tone}`, title: `Unit ${r.unit} · ${k.label} · ${dayClock(r.at)} CT`,
    'aria-label': `Unit ${r.unit}, ${k.label}` });
  square.addEventListener('click', () => pick(r.id));
  return square;
}

// The list of requests, newest first; the picked one marked, one that just came in lit up. Its scroll is kept.
function drawList() {
  const box = document.getElementById('cards-runs');
  const at = box.scrollTop;
  const runs = listed();
  const picked = pickedOf(runs);
  document.getElementById('cards-count').textContent = String(runs.length);
  box.replaceChildren(...(runs.length ? runs.map((r) => item(r, picked && picked.id === r.id))
    : [el('li', { class: 'units-empty' }, shown.runs.length ? 'No card request yet: only tags that asked for nothing.' : 'No request yet.')]));
  box.scrollTop = at;
}

// The request the conversation shows: the one in the address when it is listed, else the newest listed.
function pickedOf(runs) {
  return runs.find((r) => r.id === pickedId()) || runs[0] || null;
}

// One request in the list: the unit and who wrote, when, what they wrote, and what became of it.
function item(r, picked) {
  const k = kindOf(r);
  const head = el('button', { type: 'button', class: 'run-head' },
    el('b', {}, `Unit ${r.unit || '?'}`), el('time', { title: `${dayTime(r.at)} CT` }, dayClock(r.at)),
    el('span', { class: 'run-who' }, r.sender || ''),
    el('span', { class: 'run-text' }, r.text || '(no text)'),
    el('span', { class: 'run-foot' }, el('i', { class: `tone-dot t-${k.tone}` }), k.label,
      r.wait_s != null && el('small', {}, `waited ${span(r.wait_s)}`)));
  head.addEventListener('click', () => pick(r.id));
  const fresh = known && !known.has(r.id);
  return el('li', { class: `run t-${k.tone}${picked ? ' picked' : ''}${r.job ? '' : ' quiet'}${fresh ? ' is-new' : ''}` }, head);
}

// Loads the picked request and draws its conversation; the screen is touched only when something in it changed, so
// reading it is never interrupted by a refresh.
async function drawTalk() {
  const box = document.getElementById('cards-talk');
  const picked = pickedOf(listed());
  if (!picked) {
    drawn = '';
    box.replaceChildren(el('p', { class: 'talk-empty' }, 'A request opens here as one conversation: the chat, what the agent thought and did, and what the truck bought since.'));
    return;
  }
  const [chat, message] = picked.id.split('_');
  let talk;
  try {
    talk = await load(`/api/cards/run?chat=${chat}&message=${message}`);
  } catch (error) {
    drawn = '';
    box.replaceChildren(el('p', { class: 'talk-empty' }, `Can't load this request: ${error.message}`));
    return;
  }
  const picture = JSON.stringify(talk);
  if (picture === drawn || pickedOf(listed())?.id !== talk.id) return;  // nothing new, or another request was picked meanwhile
  drawn = picture;
  box.replaceChildren(...[talkHead(talk), ...remarks(talk), thread(talk), bought(talk), facts(talk)].filter(Boolean));
  box.scrollTop = 0;
}

// The conversation's heading: the unit and who wrote, what became of it, when, how long the driver waited, the card.
function talkHead(t) {
  const k = kindOf(t);
  const facts = [`${dayTime(t.at)} CT`, t.wait_s != null && `waited ${span(t.wait_s)} for the card`, t.card && t.card.name,
    t.cost != null && `Claude ${fmt.exact(t.cost)}`].filter(Boolean);
  return el('header', { class: 'talk-head' },
    el('div', { class: 'talk-title' }, el('h2', {}, `Unit ${t.unit || '?'}${t.sender ? ` · ${t.sender}` : ''}`),
      el('span', { class: `kind-chip t-${k.tone}` }, k.label)),
    el('p', { class: 'meta' }, facts.join(' · ')));
}

// What a person should know about the card: activated, an unusual status, not in his name, a repeat, or why it went
// to a person; and why a request that failed did.
function remarks(t) {
  const c = t.card || {};
  const notes = [
    c.activated && ['warn', 'Was INACTIVE: activated first'],
    c.status && c.status !== 'ACTIVE' && !c.activated && c.did !== 'needs a person' && ['warn', `Status ${c.status}: left as it is, only overridden`],
    c.own === false && ['warn', "Not in the driver's name: the one card in use on the unit"],
    c.again_min != null && ['warn', `Repeat: the agent opened this card ${span(c.again_min * 60)} before`],
    c.why && ['bad', `${c.did === 'failed' ? 'eManager' : 'Needs a person'}: ${c.why}`],
    t.error && ['bad', t.error],
  ].filter(Boolean);
  return notes.length ? [el('div', { class: 'talk-remarks' }, ...notes.map(([tone, text]) => el('span', { class: `remark t-${tone}` }, text)))] : [];
}

// The conversation itself: the chat the agent read (the message that woke it marked), then its steps in order.
function thread(t) {
  const last = t.chat.length - 1;
  const chat = t.chat.length ? t.chat.map((c, i) => bubble(c.ours ? 'ours' : i === last ? 'woke' : '', c.ours ? `${c.sender} (the account)` : c.sender,
    clock(c.at), `${c.text || ''}${c.photo ? ' [photo]' : ''}`))
    : [bubble('woke', t.sender || 'The driver', clock(t.at), t.text)];
  const talk = [...t.talk];  // each use of a tool with its answer, taken in the order the trace names them
  const steps = (t.trace.length ? t.trace : talk.map((u) => ['used', u.tool])).map(([step, text]) => {
    if (step === 'thought') return stepBox('thought', 'Thought', text);
    if (step === 'said') return text === t.said.trim() ? null : stepBox('noted', 'Noted', text);
    const i = talk.findIndex((u) => u.tool === text);
    return i < 0 ? stepBox('tool bad', CARD_TOOLS[text] || text, 'The tool did not run.') : toolStep(talk.splice(i, 1)[0]);
  }).filter(Boolean);
  const none = !steps.length && el('p', { class: 'meta' }, t.kind === 'working' ? 'The agent is working on it now.' : 'Claude was not asked: nothing was done by the agent.');
  const earlier = chat.slice(0, -CHAT_SHOWN);  // the older messages fold away, so the request and the agent are in sight
  return el('div', { class: 'thread' },
    el('div', { class: 'thread-label' }, 'The chat it read'),
    earlier.length > 0 && el('details', { class: 'fold' }, el('summary', {}, `${plural(earlier.length, 'earlier message')}`), ...earlier),
    ...chat.slice(-CHAT_SHOWN),
    el('div', { class: 'thread-label' }, 'The agent'), none, ...steps,
    ...t.office.map((text) => bubble('office', 'Posted to the office chat', '', text)),
    t.said && el('details', { class: 'fold' }, el('summary', {}, 'Its own summary at the end'), el('div', { class: 'step summary' }, ...rich(t.said))));
}

// Text Claude wrote, as paragraphs: a line starting with "- " is a bullet, and **words** are bold. Everything is put
// in as text, never as HTML.
function rich(text) {
  const bold = (line) => line.split(/\*\*(.+?)\*\*/g).map((part, i) => (i % 2 ? el('b', {}, part) : part));
  return text.split('\n').filter((line) => line.trim()).map((line) => (line.trimStart().startsWith('- ')
    ? el('p', { class: 'bullet' }, ...bold(line.trimStart().slice(2))) : el('p', {}, ...bold(line))));
}

// One message as a bubble: who, when, and the text. `tone`: ours (the account's), woke (the message that woke the
// agent), reply (what it sent to the driver), office (what it posted to the office).
function bubble(tone, who, when, text) {
  return el('div', { class: `bub ${tone}` }, el('span', { class: 'bub-who' }, who, when && el('time', {}, when)), text);
}

// One step of the agent that is not a message: its name and its text.
function stepBox(tone, name, text) {
  return el('div', { class: `step ${tone}` }, el('span', { class: 'step-name' }, name), ...rich(text));
}

// One use of a tool: a reply that went out is the message itself; any other is the tool's name, what it was asked
// and what it answered. A use the tool refused is marked.
function toolStep(u) {
  const asked = u.asked && (u.asked.text || u.asked.note);
  if (u.tool === 'reply_to_driver' && !u.refused) return bubble('reply', 'Sent to the driver', '', asked || '');
  return el('div', { class: `step tool${u.refused ? ' bad' : ''}` }, el('span', { class: 'step-name' }, CARD_TOOLS[u.tool] || u.tool),
    asked && el('p', {}, asked), el('p', { class: 'step-answer' }, u.answer));
}

// The truck's purchases since the request, as Datatruck has them.
function bought(t) {
  const rows = t.bought.map((b) => el('li', {},
    el('time', {}, timeOf(b.at)), el('span', {}, `${fmt.wholeGallons(b.gallons)} ${b.product}`),
    el('span', { class: 'bought-where' }, `${stationName(b.station, b.loves ? "Love's" : '')}, ${b.city} ${b.state}`),
    el('span', {}, `${fmt.exact(b.pump_total)} at the pump`),
    el('span', { class: `kind-chip t-${b.loves ? 'good' : 'warn'}` }, b.loves ? "Love's" : "Outside Love's")));
  return el('section', { class: 'talk-part' }, el('div', { class: 'thread-label' }, 'Bought on this truck since, in Datatruck (Central time)'),
    rows.length ? el('ul', { class: 'bought-list' }, ...rows) : el('p', { class: 'meta' }, 'Nothing in Datatruck yet.'));
}

// What the agent was told about the truck before it read the chat; closed until asked for.
function facts(t) {
  return t.facts ? el('details', { class: 'talk-facts' }, el('summary', {}, 'What the agent was told about the truck'), el('pre', {}, t.facts)) : null;
}
