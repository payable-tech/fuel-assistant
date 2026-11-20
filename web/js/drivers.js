// The Drivers view: how each driver usually fuels, from their diesel stops and the Samsara gauge around them:
// every driver as a dot by stop and fill level, every stop by gauge level, and every driver's figures in a table.
import { draw } from './charts.js';
import { el, tooltip } from './dom.js';
import { fmt, personName } from './format.js';
import { token } from './theme.js';

// Love's share groups for the dots: [name, lowest share, color token].
const LOVES_GROUPS = [["90%+ at Love's", 0.9, '--good'], ["50–90% at Love's", 0.5, '--warn'], ["Under 50% at Love's", 0, '--bad']];

// Draws the Drivers view.
export function renderDrivers(d) {
  const gauged = d.habits.filter((h) => h.stop_at_pct != null);
  document.getElementById('drivers-meta').textContent =
    `Last ${d.days} days · ${d.habits.length} drivers · ${fmt.count(d.habits.reduce((s, h) => s + h.stops, 0))} diesel stops, `
    + `${fmt.count(d.stops.length)} with the gauge before and after`;
  drawHabits(gauged, d.low_pct);
  drawStopLevels(d.stops, d.low_pct);
  renderTable(d);
}

// Says on the view's top line that the habits can't be loaded, and why.
export function showDriversError(error) {
  document.getElementById('drivers-meta').textContent = `Can't load the habits: ${error.message}`;
}

// One dot per driver: across, the middle level they stop at; up, the middle level they fill to; size, gallons;
// color, their Love's share. Pilot drivers carry their unit number.
function drawHabits(habits, lowPct) {
  const most = Math.max(...habits.map((h) => h.gallons), 1);
  draw('chart-habits', {
    grid: { left: 36, right: 24, top: 40, bottom: 34, containLabel: true },
    legend: { top: 0, left: 0 },
    tooltip: { trigger: 'item', formatter: (p) => driverTip(p.data.habit) },
    xAxis: { type: 'value', name: 'Gauge when stopping', nameLocation: 'middle', nameGap: 30, min: 0,
      max: (v) => Math.min(100, Math.ceil(v.max / 10) * 10 + 10), axisLabel: { formatter: '{value}%' } },
    yAxis: { type: 'value', name: 'Gauge after filling', nameLocation: 'middle', nameGap: 46,
      min: (v) => Math.max(0, Math.floor(v.min / 10) * 10 - 10), max: 100, axisLabel: { formatter: '{value}%' } },
    labelLayout: { moveOverlap: 'shiftY' },  // pilot unit labels close together move apart instead of overlapping
    series: LOVES_GROUPS.map(([name, lowest, color], i) => ({
      name, type: 'scatter', itemStyle: { color: token(color), opacity: 0.8, borderColor: token('--bg'), borderWidth: 1 },
      data: habits.filter((h) => h.loves_share >= lowest && (i === 0 || h.loves_share < LOVES_GROUPS[i - 1][1]))
        .map((h) => ({
          value: [h.stop_at_pct, h.fill_to_pct], habit: h, symbolSize: 6 + 22 * Math.sqrt(h.gallons / most),
          label: { show: h.pilot, formatter: h.unit, position: 'right', color: token('--text'), fontSize: 11 },
        })),
      markLine: i ? undefined : { symbol: 'none', silent: true, data: [{ xAxis: lowPct }],
        lineStyle: { color: token('--bad'), type: 'dashed' }, label: { formatter: `${lowPct}%`, color: token('--bad') } },
    })),
  });
}

// Every stop by the gauge level just before fueling, in steps of 10%, stacked: at Love's and elsewhere.
function drawStopLevels(stops, lowPct) {
  const bins = Array.from({ length: 10 }, (_, i) => i * 10);
  const count = (loves) => bins.map((b) => stops.filter(([before, , atLoves]) => atLoves === loves
    && Math.min(Math.floor(before / 10) * 10, 90) === b).length);
  draw('chart-stop-levels', {
    grid: { left: 4, right: 12, top: 40, bottom: 4, containLabel: true },
    legend: { top: 0, left: 0 },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    xAxis: { type: 'category', data: bins.map((b) => `${b}–${b + 9}%`), axisLabel: { hideOverlap: true } },
    yAxis: { type: 'value' },
    series: [["At Love's", true, '--s2'], ['Elsewhere', false, '--s6']].map(([name, loves, color], i) => ({
      name, type: 'bar', stack: 'stops', data: count(loves), itemStyle: { color: token(color), borderRadius: i ? [4, 4, 0, 0] : 0 },
      barMaxWidth: 34,
      markArea: i ? undefined : { silent: true, itemStyle: { color: 'rgba(242, 103, 107, 0.07)' },
        data: [[{ xAxis: 0 }, { xAxis: Math.ceil(lowPct / 10) - 1 }]] },
    })),
  });
}

// Every driver's figures, most gallons first; pilot drivers marked.
function renderTable(d) {
  document.getElementById('habits-meta').textContent = `Most gallons first. Levels are the middle of their stops. `
    + `Ran low: stops that began below ${d.low_pct}%. Top-offs: stops under ${d.top_off_gal} gal.`;
  const head = ['Driver', 'Unit', 'Stops', 'Gallons', 'Stops at', 'Ran low', 'Fills to', 'Gal/stop', 'Top-offs', "At Love's",
    'Paid $/gal', 'Outside Love\'s'].map((h, i) => el('th', i < 2 ? { class: 'left' } : {}, h));
  const rows = d.habits.map((h) => el('tr', {},
    el('td', { class: 'left' }, personName(h.name), h.pilot && el('span', { class: 'badge' }, 'pilot')),
    el('td', { class: 'left' }, h.unit || '—'), el('td', {}, h.stops), el('td', {}, fmt.count(h.gallons)),
    el('td', {}, fmt.level(h.stop_at_pct)), el('td', h.ran_low_share > 0.25 ? { class: 'off' } : {}, fmt.percent(h.ran_low_share)),
    el('td', {}, fmt.level(h.fill_to_pct)), el('td', {}, fmt.count(h.gal_per_stop)),
    el('td', h.top_off_share > 0.25 ? { class: 'off' } : {}, fmt.percent(h.top_off_share)),
    el('td', h.loves_share < 0.9 ? { class: 'off' } : {}, fmt.percent(h.loves_share)), el('td', {}, fmt.price(h.paid_per_gal)),
    el('td', {}, h.outside_premium == null ? '—' : `${h.outside_premium >= 0 ? '+' : '−'}${fmt.price(Math.abs(h.outside_premium))}`)));
  document.getElementById('habits-table').replaceChildren(el('thead', {}, el('tr', {}, ...head)), el('tbody', {}, ...rows));
}

// Tooltip for one driver's dot.
function driverTip(h) {
  return tooltip(personName(h.name), [['Unit', h.unit || '—'], ['Stops', h.stops], ['Gallons', fmt.count(h.gallons)],
    ['Stops at', fmt.level(h.stop_at_pct)], ['Fills to', fmt.level(h.fill_to_pct)], ['Ran low', fmt.percent(h.ran_low_share)],
    ['Top-offs', fmt.percent(h.top_off_share)], ["At Love's", fmt.percent(h.loves_share)], ['Paid', `${fmt.price(h.paid_per_gal)}/gal`]]);
}
