// The charts' dark theme, built from the CSS color tokens so the page and its charts always match.

// Reads one CSS color or font token, e.g. token('--s1').
export const token = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

// A color with transparency, from a "#rrggbb" token value.
export function fade(hex, alpha) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

// Registers the "fuel" chart theme; call once, after the font has loaded and before any chart is drawn.
export function registerTheme() {
  const muted = token('--muted'), grid = token('--grid'), line = token('--line'), font = token('--font');
  echarts.registerTheme('fuel', {
    color: ['--s1', '--s2', '--s3', '--s4', '--s5', '--s6'].map(token),
    backgroundColor: 'transparent',
    textStyle: { fontFamily: font, color: muted },
    categoryAxis: {
      axisLine: { lineStyle: { color: line } }, axisTick: { show: false },
      axisLabel: { color: muted, fontSize: 11 }, splitLine: { show: false },
    },
    valueAxis: {
      axisLine: { show: false }, axisTick: { show: false },
      axisLabel: { color: muted, fontSize: 11 }, splitLine: { lineStyle: { color: grid } },
    },
    legend: { textStyle: { color: muted, fontSize: 12 }, icon: 'roundRect', itemWidth: 10, itemHeight: 10, itemGap: 16 },
    tooltip: {
      backgroundColor: token('--panel-2'), borderColor: line, borderWidth: 1, padding: [10, 12],
      textStyle: { color: token('--text'), fontFamily: font },
      extraCssText: 'border-radius:10px; box-shadow:0 10px 28px rgba(0,0,0,.45); min-width:180px;',
    },
  });
}
