// Number, date and text formatting shared by every part of the dashboard.

const compact = new Intl.NumberFormat('en-US', { notation: 'compact', maximumSignificantDigits: 3 });
const ZONE = 'America/Chicago';  // the company's clock: every time on the page is US Central, whatever this PC's zone

// A moment (ISO text, Date or milliseconds) on the company's clock, with the Intl `parts` asked for, 24-hour.
const central = (when, parts) => new Date(when).toLocaleString('en-US', { timeZone: ZONE, hourCycle: 'h23', ...parts });

// "Tue, Oct 20, 07:11" in Central time.
export const dayTime = (when) => central(when, { weekday: 'short', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });

// "13:05" in Central time.
export const clock = (when) => central(when, { hour: '2-digit', minute: '2-digit' });

// "Thu 13:05" in Central time.
export const dayClock = (when) => central(when, { weekday: 'short', hour: '2-digit', minute: '2-digit' });

// Formats values for people; a missing value shows as a dash.
export const fmt = {
  money: (v) => (v == null ? '—' : (v < 0 ? '−$' : '$') + compact.format(Math.abs(v))),
  gallons: (v) => (v == null ? '—' : compact.format(v) + ' gal'),
  price: (v) => (v == null ? '—' : '$' + v.toFixed(2)),
  cents: (v) => (v == null ? '—' : Math.round(v * 100) + '¢'),
  cents1: (v) => (v == null ? '—' : (v * 100).toFixed(1) + '¢'),  // for small changes, where 4.0¢ vs 4.3¢ matters
  share: (v) => (v == null ? '—' : (v * 100).toFixed(1) + '%'),
  count: (v) => (v == null ? '—' : Math.round(v).toLocaleString('en-US')),
};

// A local date from "YYYY-MM-DD", moved by whole calendar days (so clock changes can't shift it).
export function dateOf(iso, plusDays = 0) {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
  return new Date(y, m - 1, d + plusDays);
}

// "Oct 12".
export const short = (date) => date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });

// "Oct 12 – 18" (or "Sep 28 – Oct 4") for the Monday-start week beginning on `iso`.
export function weekLabel(iso) {
  const start = dateOf(iso), end = dateOf(iso, 6);
  return start.getMonth() === end.getMonth() ? `${short(start)} – ${end.getDate()}` : `${short(start)} – ${short(end)}`;
}

// How long ago a time was, in words: "just now", "12 min ago", "3 h ago", "2 days ago".
export function ago(when, now = new Date()) {
  const minutes = Math.round((now - new Date(when)) / 60000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} min ago`;
  if (minutes < 48 * 60) return `${Math.round(minutes / 60)} h ago`;
  return `${Math.round(minutes / 1440)} days ago`;
}

// Average of the numbers in a list, skipping missing ones; null when there are none.
export function avg(values) {
  const known = values.filter((v) => v != null);
  return known.length ? known.reduce((a, b) => a + b, 0) / known.length : null;
}

// "TAYLOR TRANSPORTS LLC" -> "Taylor Transports LLC": readable company names, keeping legal suffixes in capitals.
export function niceName(name) {
  return name.toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase()).replace(/\b(Llc|Inc|Uz|Dt|Vkl|Ttl|Ta|Fj)\b/g, (w) => w.toUpperCase());
}

// "Mon 13": a short day label for chart axes, from "YYYY-MM-DD".
export const dayTick = (iso) => `${dateOf(iso).toLocaleDateString('en-US', { weekday: 'short' })} ${dateOf(iso).getDate()}`;

// "Monday, Oct 13": a day as a tooltip title.
export const dayLabel = (iso) => dateOf(iso).toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' });

// "Sun 09:45" from a local time "YYYY-MM-DD HH:MM".
export const timeOf = (when) => `${dateOf(when).toLocaleDateString('en-US', { weekday: 'short' })} ${when.slice(11, 16)}`;

// How a figure changed against an earlier one, as a chip: "▲ 3.0%" (shares in points), and whether that is
// good or bad news for this figure (`better`: 'up', 'down' or nothing when neither is better).
export function change(now, before, { points = false, better } = {}) {
  if (now == null || before == null || before === 0) return { text: '—', tone: '' };
  const diff = points ? (now - before) * 100 : ((now - before) / Math.abs(before)) * 100;
  const unit = points ? ' pts' : '%';
  if (Math.abs(diff) < 0.05) return { text: `0.0${unit}`, tone: '' };
  const tone = better ? ((better === 'up') === (diff > 0) ? 'good' : 'bad') : '';
  return { text: `${diff > 0 ? '▲' : '▼'} ${Math.abs(diff).toFixed(1)}${unit}`, tone };
}

// "BAYTOWN" -> "Baytown": each word with a capital first letter.
export const capitalized = (text) => text.toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());

// Drivers as people say them: "JACOB BYRON KILMER (CPM-M)" -> "Jacob Byron Kilmer"; a team ("A & B") keeps both.
export function personName(name) {
  if (!name) return 'no active driver';
  return name.split(' & ').map((n) => capitalized(n.replace(/\s*\(.*$/, ''))).join(' & ');
}

// A station as people say it: "LOVES #220 TRAVEL STOP" -> "Love's #220"; other names shortened and readable.
export function stationName(location, station) {
  const number = location.match(/#\s*(\d+)/);
  if (station === "Love's") return number ? `Love's #${number[1]}` : "Love's";
  const name = niceName(location.replace(/#.*$/, '').trim() || location);
  return name.length > 26 ? `${name.slice(0, 25)}…` : name;
}

// Escapes text before it goes into tooltip HTML.
export function esc(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
}
