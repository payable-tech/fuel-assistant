// Chart shapes: each function returns the settings for one kind of chart; `draw` puts them into a box on the page.
// Time charts take rows (weeks or days) plus `tick(row)` for the axis label and `title(row)` for the tooltip title.
import { tooltip } from './dom.js';
import { dayClock, dayTime, fmt } from './format.js';
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

// Tooltip for one row: its title, each series, an optional total, then extra lines for that row.
function rowTooltip(rows, title, format, { total = false, totalLabel = 'Total', extra, pointer = 'shadow' } = {}) {
  return {
    trigger: 'axis',
    axisPointer: pointer === 'shadow'
      ? { type: 'shadow', shadowStyle: { color: fade(token('--text'), 0.04) } }
      : { type: 'line', lineStyle: { color: token('--faint'), type: 'dashed' } },
    formatter: (items) => {
      const row = rows[items[0].dataIndex];
      const sum = items.reduce((s, i) => s + (i.value || 0), 0);
      return tooltip(title(row), [...items.map((i) => [i.seriesName, format(i.value), i.marker]),
        ...(total ? [[totalLabel, format(sum), '', true]] : []), ...(extra ? extra(row) : [])]);
    },
  };
}

// Bars over time: one series, or several stacked (`totalLabel` names their sum in the tooltip). `series` items:
// {name, color, value(row)}.
export function bars(rows, series, format, { tick, title, extra, totalLabel }) {
  const stacked = series.length > 1;
  return {
    grid: { left: 4, right: 12, top: stacked ? 40 : 14, bottom: 4, containLabel: true },
    legend: stacked ? { top: 0, left: 0 } : undefined,
    tooltip: rowTooltip(rows, title, format, { total: stacked, totalLabel, extra }),
    xAxis: rowAxis(rows, tick),
    yAxis: { type: 'value', axisLabel: { formatter: format } },
    series: series.map((s, i) => ({
      name: s.name, type: 'bar', stack: stacked ? 'all' : undefined, data: rows.map(s.value), barMaxWidth: 30,
      itemStyle: { color: s.color, borderRadius: i === series.length - 1 ? [5, 5, 0, 0] : 0 },
      emphasis: { focus: 'series' },
    })),
  };
}

// Lines over time on one shared axis. Options as `bars`, plus `min` where the axis starts (else it fits the lines);
// `smooth` rounds the lines; `stack` piles each series on the ones before it (parts of one whole, each band filled) and
// `totalLabel` names their sum in the tooltip.
export function lines(rows, series, format, { tick, title, extra, min, smooth = false, stack = false, totalLabel } = {}) {
  return {
    grid: { left: 4, right: 12, top: series.length > 1 ? 40 : 14, bottom: 4, containLabel: true },
    legend: series.length > 1 ? { top: 0, left: 0 } : undefined,
    tooltip: rowTooltip(rows, title, format, { extra, pointer: 'line', total: Boolean(totalLabel), totalLabel }),
    xAxis: rowAxis(rows, tick, false),
    yAxis: { type: 'value', min, scale: min == null, axisLabel: { formatter: format } },
    series: series.map((s) => ({
      name: s.name, type: 'line', data: rows.map(s.value), symbol: 'circle', symbolSize: 7, showSymbol: false, smooth,
      stack: stack ? 'all' : undefined, lineStyle: { width: 2.5, color: s.color }, itemStyle: { color: s.color },
      areaStyle: stack ? { color: fade(s.color, 0.3) } : undefined,
    })),
  };
}

// The frame of small charts stacked over the same rows: each part's heading, its box (an equal slice of the height)
// and its axis of rows, labelled only under the bottom part.
function stackFrame(rows, names, tick) {
  const band = 100 / names.length;  // each part's slice of the box's height, in percent
  return {
    band,
    title: names.map((text, i) => ({ text, left: 0, top: `${i * band}%`,
      textStyle: { color: token('--muted'), fontSize: 12, fontWeight: 500, fontFamily: token('--font') } })),
    grid: names.map((_, i) => ({ left: 4, right: 12, top: `${i * band + 6}%`, height: `${band - (i === names.length - 1 ? 10.5 : 9)}%`, containLabel: true })),
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    xAxis: names.map((_, i) => ({ ...rowAxis(rows, tick, true), gridIndex: i,
      axisLabel: { show: i === names.length - 1, hideOverlap: true } })),
  };
}

// Several small charts stacked over the same rows, each with its own axis, so you can see which ones rise and fall
// together. Hovering a week shows every row's value for it. parts: {name, color, value(row), format, type: 'line'|'bar'}.
export function stackedRows(rows, parts, { tick, title }) {
  const { band, ...frame } = stackFrame(rows, parts.map((p) => p.name), tick);
  return {
    ...frame,
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'line', lineStyle: { color: token('--faint'), type: 'dashed' } },
      formatter: (items) => tooltip(title(rows[items[0].dataIndex]),
        items.map((i) => [i.seriesName, parts[i.seriesIndex].format(i.value), i.marker])),
    },
    // a line may zoom in on its range; bars always start at zero so their heights stay honest
    yAxis: parts.map((p, i) => ({ type: 'value', gridIndex: i, scale: p.type === 'line', splitNumber: 2, axisLabel: { formatter: p.format } })),
    series: parts.map((p, i) => ({
      name: p.name, type: p.type, xAxisIndex: i, yAxisIndex: i, data: rows.map(p.value), barMaxWidth: 22,
      symbol: 'circle', symbolSize: 6, showSymbol: false, lineStyle: { width: 2.5, color: p.color },
      itemStyle: { color: p.color, borderRadius: p.type === 'bar' ? [4, 4, 0, 0] : 0 },
    })),
  };
}

// Small line charts stacked over the same rows, where a part can shade a range around its line (e.g. an average with
// where the middle of the gallons were) and can hold more than one line (named at its top right).
// parts: {name, format, lines: [{name, color, value(row)}], range: {low(row), high(row)} or none, shaded in the first
// line's color}. `tip(row)` lists the tooltip: [label, text] lines, and plain text for a heading over the next lines.
export function rangeRows(rows, parts, { tick, title, tip }) {
  const { band, ...frame } = stackFrame(rows, parts.map((p) => p.name), tick);
  const series = parts.flatMap((p, i) => {
    const axes = { xAxisIndex: i, yAxisIndex: i };
    // the shaded range: an invisible line along `low`, with high minus low stacked on top of it and filled
    const shade = { ...axes, type: 'line', stack: `range-${i}`, symbol: 'none', silent: true, lineStyle: { opacity: 0 } };
    const width = (r) => (p.range.low(r) == null || p.range.high(r) == null ? null : p.range.high(r) - p.range.low(r));
    return [
      ...(p.range ? [{ ...shade, data: rows.map(p.range.low) },
        { ...shade, data: rows.map(width), areaStyle: { color: fade(p.lines[0].color, 0.2) } }] : []),
      ...p.lines.map((s) => ({ ...axes, name: s.name, type: 'line', data: rows.map(s.value), symbol: 'circle', symbolSize: 6,
        showSymbol: false, lineStyle: { width: 2.5, color: s.color }, itemStyle: { color: s.color } })),
    ];
  });
  return {
    ...frame,
    legend: parts.map((p, i) => (p.lines.length > 1 ? { top: `${i * band}%`, right: 0, data: p.lines.map((s) => s.name) } : null))
      .filter(Boolean),
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'line', lineStyle: { color: token('--faint'), type: 'dashed' } },
      formatter: (items) => tooltip(title(rows[items[0].dataIndex]), tip(rows[items[0].dataIndex])),
    },
    yAxis: parts.map((p, i) => ({ type: 'value', gridIndex: i, scale: true, splitNumber: 2, axisLabel: { formatter: p.format } })),
    series,
  };
}

// A truck's fuel gauge over time, 0 to 100%, with an upright line at each fill-up labelled with its gallons (green where
// we told the driver, amber elsewhere). readings: [time, percent], a null percent breaks the line; fills: {at, told, gallons}.
export function gauge(readings, fills) {
  const brand = token('--brand'), good = token('--good'), warn = token('--warn');
  return {
    grid: { left: 4, right: 20, top: 26, bottom: 4, containLabel: true },
    tooltip: { trigger: 'axis', formatter: (items) => tooltip(dayTime(items[0].value[0]),
      [['Fuel gauge', items[0].value[1] == null ? 'no reading' : fmt.level(items[0].value[1])]]) },
    xAxis: { type: 'time', axisLabel: { hideOverlap: true, formatter: (v) => dayClock(v) } },
    yAxis: { type: 'value', min: 0, max: 100, interval: 25, axisLabel: { formatter: '{value}%' } },
    series: [{
      name: 'Fuel gauge', type: 'line', data: readings, showSymbol: readings.filter(([, v]) => v != null).length < 3,  // dots only when too few for a line
      lineStyle: { width: 2, color: brand }, itemStyle: { color: brand }, areaStyle: { color: fade(brand, 0.12) },
      markLine: { symbol: 'none', silent: true, data: fills.map((f) => ({ xAxis: f.at, lineStyle: { color: f.told ? good : warn, type: 'solid', width: 1.5 },
        label: { formatter: fmt.wholeGallons(f.gallons), color: f.told ? good : warn, position: 'end' } })) },
    }],
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
    tooltip: { trigger: 'item', formatter: (p) => tooltip(p.name, [[format(p.value), pct(p.value)]]) },
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
    tooltip: { trigger: 'item', formatter: (p) => tooltip(p.name, tip(rows[p.dataIndex])) },
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
