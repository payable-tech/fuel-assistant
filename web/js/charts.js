// Chart shapes: each function returns the settings for one kind of chart; `draw` puts them into a box on the page.
// Time charts take rows (weeks or days) plus `tick(row)` for the axis label and `title(row)` for the tooltip title.
import { esc } from './format.js';
import { fade, token } from './theme.js';

const charts = new Map();  // element id -> its chart, so a live refresh redraws instead of stacking new charts

// Draws (or redraws) a chart into the element with this id and keeps it sized to its box.
export function draw(id, option) {
  let chart = charts.get(id);
  if (!chart) {
    const box = document.getElementById(id);
    chart = echarts.init(box, 'fuel');
    charts.set(id, chart);
    new ResizeObserver(() => chart.resize()).observe(box);
  }
  chart.setOption(option, { notMerge: true });
}

// A soft vertical fade under a line, from its color to nothing.
const areaFill = (color) => ({
  color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: fade(color, 0.28) }, { offset: 1, color: fade(color, 0) }]),
});

// A category axis over rows, labelled by `tick(row)`; labels thin out on their own so they never overlap.
const rowAxis = (rows, tick, boundaryGap = true) => ({
  type: 'category', boundaryGap, data: rows.map(tick), axisLabel: { hideOverlap: true },
});

// One tooltip line: color marker, label, value.
const tipRow = (marker, label, value) => `<div class="tt-row">${marker || ''}<span>${esc(label)}</span><b>${esc(value)}</b></div>`;

// Tooltip for one row: its title, each series, an optional total, then extra lines for that row.
function rowTooltip(rows, title, format, { total = false, extra, pointer = 'shadow' } = {}) {
  return {
    trigger: 'axis',
    axisPointer: pointer === 'shadow'
      ? { type: 'shadow', shadowStyle: { color: 'rgba(255,255,255,0.04)' } }
      : { type: 'line', lineStyle: { color: token('--faint'), type: 'dashed' } },
    formatter: (items) => {
      const row = rows[items[0].dataIndex];
      const lines = items.map((i) => tipRow(i.marker, i.seriesName, format(i.value)));
      if (total) lines.push(`<div class="tt-row tt-total"><span>Total</span><b>${esc(format(items.reduce((s, i) => s + (i.value || 0), 0)))}</b></div>`);
      (extra ? extra(row) : []).forEach(([label, value]) => lines.push(tipRow('', label, value)));
      return `<div class="tt-title">${esc(title(row))}</div>${lines.join('')}`;
    },
  };
}

// Bars over time: one series, or several stacked. `series` items: {name, color, value(row)}.
export function bars(rows, series, format, { tick, title, extra }) {
  const stacked = series.length > 1;
  return {
    grid: { left: 4, right: 12, top: stacked ? 40 : 14, bottom: 4, containLabel: true },
    legend: stacked ? { top: 0, left: 0 } : undefined,
    tooltip: rowTooltip(rows, title, format, { total: stacked, extra }),
    xAxis: rowAxis(rows, tick),
    yAxis: { type: 'value', axisLabel: { formatter: format } },
    series: series.map((s, i) => ({
      name: s.name, type: 'bar', stack: stacked ? 'all' : undefined, data: rows.map(s.value), barMaxWidth: 30,
      itemStyle: { color: s.color, borderRadius: i === series.length - 1 ? [5, 5, 0, 0] : 0 },
      emphasis: { focus: 'series' },
    })),
  };
}

// Lines over time on one shared axis. Options as `bars`, plus axisFormat, min, max and interval for the axis.
export function lines(rows, series, format, { tick, title, extra, axisFormat = format, min, max, interval }) {
  return {
    grid: { left: 4, right: 12, top: series.length > 1 ? 40 : 14, bottom: 4, containLabel: true },
    legend: series.length > 1 ? { top: 0, left: 0 } : undefined,
    tooltip: rowTooltip(rows, title, format, { extra, pointer: 'line' }),
    xAxis: rowAxis(rows, tick, false),
    yAxis: { type: 'value', min, max, interval, scale: min == null, axisLabel: { formatter: axisFormat } },
    series: series.map((s) => ({
      name: s.name, type: 'line', data: rows.map(s.value), symbol: 'circle', symbolSize: 7, showSymbol: false,
      lineStyle: { width: 2.5, color: s.color }, itemStyle: { color: s.color }, areaStyle: s.area ? areaFill(s.color) : undefined,
    })),
  };
}

// Several small charts stacked over the same rows, each with its own axis, so you can see which ones rise and fall
// together. Hovering a week shows every row's value for it. parts: {name, color, value(row), format, type: 'line'|'bar'}.
export function stackedRows(rows, parts, { tick, title }) {
  const band = 100 / parts.length;  // each part gets an equal slice of the box's height, in percent
  const heading = (text, i) => ({ text, left: 0, top: `${i * band}%`,
    textStyle: { color: token('--muted'), fontSize: 12, fontWeight: 500, fontFamily: token('--font') } });
  return {
    title: parts.map((p, i) => heading(p.name, i)),
    grid: parts.map((p, i) => ({ left: 4, right: 12, top: `${i * band + 6}%`, height: `${band - (i === parts.length - 1 ? 10.5 : 9)}%`, containLabel: true })),
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'line', lineStyle: { color: token('--faint'), type: 'dashed' } },
      formatter: (items) => `<div class="tt-title">${esc(title(rows[items[0].dataIndex]))}</div>`
        + items.map((i) => tipRow(i.marker, i.seriesName, parts[i.seriesIndex].format(i.value))).join(''),
    },
    xAxis: parts.map((p, i) => ({ ...rowAxis(rows, tick, true), gridIndex: i,
      axisLabel: { show: i === parts.length - 1, hideOverlap: true } })),  // dates only under the bottom part
    // a line may zoom in on its range; bars always start at zero so their heights stay honest
    yAxis: parts.map((p, i) => ({ type: 'value', gridIndex: i, scale: p.type === 'line', splitNumber: 2, axisLabel: { formatter: p.format } })),
    series: parts.map((p, i) => ({
      name: p.name, type: p.type, xAxisIndex: i, yAxisIndex: i, data: rows.map(p.value), barMaxWidth: 22,
      symbol: 'circle', symbolSize: 6, showSymbol: false, lineStyle: { width: 2.5, color: p.color },
      itemStyle: { color: p.color, borderRadius: p.type === 'bar' ? [4, 4, 0, 0] : 0 },
    })),
  };
}

// Two lines over time with the space between them shaded (e.g. "at market price" above "what we paid"), and under
// them that space per unit as bars with a rolling-average line, all over the same rows.
// upper/lower: {name, color, value(row)}; band: the shaded space's name; gap: {name, averageName, color, value(row),
// average(row), format}. `format` is for the top lines; `tip(row)` lists the tooltip's [label, text] lines.
export function gapChart(rows, { upper, lower, band, gap }, { format, tick, title, tip }) {
  // the space between the lines; unknown when either line is (a plain subtraction would treat a missing value as 0)
  const space = (r) => (upper.value(r) == null || lower.value(r) == null ? null : upper.value(r) - lower.value(r));
  const line = (s, axis) => ({ name: s.name, type: 'line', xAxisIndex: axis, yAxisIndex: axis, symbol: 'circle', symbolSize: 6,
    showSymbol: false, lineStyle: { width: 2.5, color: s.color }, itemStyle: { color: s.color } });
  // the shaded band: an invisible line along `lower`, with the space stacked on top of it and filled
  const stacked = { type: 'line', stack: 'band', stackStrategy: 'all', symbol: 'none', silent: true, lineStyle: { opacity: 0 } };
  return {
    legend: [
      { top: 0, left: 0, data: [upper.name, lower.name, { name: band, icon: 'rect' }] },
      { top: '64%', left: 0, data: [gap.name, gap.averageName] },
    ],
    grid: [
      { left: 4, right: 12, top: 36, bottom: '40%', containLabel: true },
      { left: 4, right: 12, top: '71%', bottom: 4, containLabel: true },
    ],
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'line', lineStyle: { color: token('--faint'), type: 'dashed' } },
      formatter: (items) => {
        const row = rows[items[0].dataIndex];
        return `<div class="tt-title">${esc(title(row))}</div>${tip(row).map(([l, v]) => tipRow('', l, v)).join('')}`;
      },
    },
    xAxis: [0, 1].map((i) => ({ ...rowAxis(rows, tick, true), gridIndex: i, axisLabel: { show: i === 1, hideOverlap: true } })),
    yAxis: [
      { type: 'value', gridIndex: 0, scale: true, axisLabel: { formatter: format } },
      // bars start at zero so their heights stay honest; a week paid above market goes below the line
      { type: 'value', gridIndex: 1, splitNumber: 2, axisLabel: { formatter: gap.format } },
    ],
    series: [
      { ...stacked, data: rows.map(lower.value) },
      { ...stacked, name: band, data: rows.map(space), areaStyle: { color: fade(gap.color, 0.2) }, itemStyle: { color: fade(gap.color, 0.5) } },
      { ...line(upper, 0), data: rows.map(upper.value) },
      { ...line(lower, 0), data: rows.map(lower.value) },
      { name: gap.name, type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: rows.map(gap.value), barMaxWidth: 22,
        itemStyle: { color: fade(gap.color, 0.45), borderRadius: [4, 4, 0, 0] } },
      { ...line({ name: gap.averageName, color: gap.color }, 1), data: rows.map(gap.average) },
    ],
  };
}

// A tiny trend line with no axes, for the figure cards.
export function sparkline(values, color) {
  return {
    animation: false,
    grid: { left: 0, right: 0, top: 6, bottom: 0 },
    xAxis: { type: 'category', show: false, boundaryGap: false, data: values.map((_, i) => i) },
    yAxis: { type: 'value', show: false, scale: true },
    tooltip: { show: false },
    series: [{ type: 'line', data: values, symbol: 'none', lineStyle: { width: 1.6, color }, areaStyle: areaFill(color) }],
  };
}

// A ring showing how a total splits into a few parts, with a figure in the middle. Items: {name, value, color}.
export function donut(items, format, center) {
  const total = items.reduce((s, i) => s + i.value, 0);
  const pct = (v) => (total ? ((v / total) * 100).toFixed(1) + '%' : '—');
  return {
    tooltip: { trigger: 'item', formatter: (p) => `<div class="tt-title">${esc(p.name)}</div>${tipRow('', format(p.value), pct(p.value))}` },
    legend: { orient: 'vertical', right: 0, top: 'middle', itemGap: 12, formatter: (name) => `${name}  ${pct(items.find((i) => i.name === name).value)}` },
    title: {
      text: center.value, subtext: center.label, left: '29%', top: '40%', textAlign: 'center',
      textStyle: { color: token('--text'), fontSize: 22, fontWeight: 600, fontFamily: token('--font') },
      subtextStyle: { color: token('--muted'), fontSize: 12, fontFamily: token('--font') },
    },
    series: [{
      type: 'pie', radius: ['56%', '80%'], center: ['30%', '50%'], label: { show: false },
      itemStyle: { borderColor: token('--panel'), borderWidth: 3, borderRadius: 6 },
      data: items.map((i) => ({ name: i.name, value: i.value, itemStyle: { color: i.color } })),
    }],
  };
}

// Horizontal bars, one per row, labelled with their value, with an optional dashed reference line.
// Options: value(row), format, color(row), tip(row) -> [[label, text]], reference {value, label}, max.
export function hbars(rows, { value, format, color, tip, reference, max }) {
  return {
    grid: { left: 4, right: 64, top: reference ? 22 : 6, bottom: 4, containLabel: true },
    tooltip: {
      trigger: 'item',
      formatter: (p) => `<div class="tt-title">${esc(p.name)}</div>${tip(rows[p.dataIndex]).map(([l, v]) => tipRow('', l, v)).join('')}`,
    },
    xAxis: { type: 'value', show: false, max },
    yAxis: { type: 'category', inverse: true, data: rows.map((r) => r.label), axisLine: { show: false }, axisLabel: { color: token('--text'), fontSize: 12 } },
    series: [{
      type: 'bar', barMaxWidth: 18, data: rows.map((r) => ({ value: value(r), itemStyle: { color: color(r) } })),
      itemStyle: { borderRadius: [0, 5, 5, 0] },
      label: { show: true, position: 'right', color: token('--text'), formatter: (p) => format(p.value) },
      markLine: reference ? {
        symbol: 'none', silent: true, data: [{ xAxis: reference.value }], lineStyle: { type: 'dashed', color: token('--muted') },
        label: { formatter: reference.label, color: token('--muted'), position: 'end', fontSize: 11 },
      } : undefined,
    }],
  };
}
