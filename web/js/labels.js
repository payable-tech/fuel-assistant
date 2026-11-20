// Names and colors that more than one part of the dashboard uses, kept in one place so they always match.

// What became of a message sent to a driver, in the Live key's order. The ended ones are filled squares and make the
// follow rate; the others are hollow or dim and aren't counted. Each tip is the rule, shown on hover.
export const BECAME = [
  { key: 'there', label: 'Fueled at our stop', ended: true, tip: 'The purchase is in Datatruck, at the stop we sent.' },
  { key: 'loves', label: "Fueled at another Love's", ended: true,
    tip: "The truck's first diesel purchase after the message (before the next one, within 48 h) was at a different Love's." },
  { key: 'outside', label: "Fueled outside Love's", ended: true,
    tip: "The truck's first diesel purchase after the message (before the next one, within 48 h) was at a station that isn't a Love's." },
  { key: 'passed', label: 'Drove past, no fill', ended: true, tip: 'The truck went past the stop, or could no longer reach it, and bought no diesel.' },
  { key: 'waiting', label: 'Fueled, not in Datatruck yet', tip: 'The gauge rose, so the truck fueled. Where shows once the purchase is in Datatruck, often within an hour.' },
  { key: 'open', label: 'On the way', tip: 'The truck has not reached the stop yet.' },
  { key: 'off', label: 'Called off by us', tip: 'The road was remade without this stop, or the load ended before it.' },
];

// Fuel levels the Recommend view colors by, % of the tank: red at or under the reserve the plans keep (a copy of the
// engine's RESERVE_PCT, which the page's numbers don't carry: change both together), amber at or under a quarter tank.
export const FUEL_RED_PCT = 10;
export const FUEL_AMBER_PCT = 25;

// Why a message was sent (the rule that picked its stop), in the order the Live view lists them: a name and the rule.
export const WHY = [
  { key: 'range', label: 'In the fuel zone, saves the most', rule: "Reached near the driver's usual level; the best price of those." },
  { key: 'last', label: "Last Love's in reach", rule: 'Skipping it means running low.' },
  { key: 'hard_stop', label: "Last Love's before the reserve", rule: 'The next one would put the truck under the 10% reserve.' },
  { key: 'tight', label: "Under the reserve, nearest Love's", rule: 'Already under the 10% reserve in the worst case.' },
  { key: 'detour', label: "Love's a short detour off the road", rule: "No Love's on the road was in reach." },
  { key: 'no_load', label: "No load, nearest Love's ahead", rule: "No load: the nearest Love's in the direction it drives." },
  { key: 'low', label: "No Love's in reach, low fuel", rule: 'A truck stop that is not a Love\'s. Switched off since Nov 13.' },
];

// A test truck's state in words, as the Recommend view shows it.
export const STATES = {
  enough: 'Enough fuel for delivery', watch: 'Watching, nothing to tell yet', stop: 'Would tell now', urgent: 'URGENT: fuel low',
  told: 'Stop told', parked: 'Parked: its stop is told once it moves', 'no fresh gauge': 'No fresh gauge reading',
  'no load': "No load, fuel above the driver's usual level", 'no load, parked': "No load, at the driver's level: told once it moves",
  "no load, no Love's ahead": "No load, at the driver's level: no Love's in reach ahead",
  skipped: "Drove past 2 stops: quiet until the last Love's or low fuel",
};

// How a Love's on a truck's road stands, in words.
export const VERDICTS = { range: 'In the zone', early: 'Before the zone', late: 'Under reserve', out: 'Out of reach', passed: 'Passed' };

// A Love's name: "Love's #412 Dunn, NC".
export function storeName(store) {
  return `${store.name || `Love's #${store.store_no}`} ${store.city}, ${store.state}`;
}

// Each station chain's color (a CSS color token), the same in the Live feed and the Trends ring.
export const STATION_COLOR = { "Love's": '--s2', 'Pilot / Flying J / One9': '--s1', 'TA / Petro': '--s3', 'Other stations': '--s6' };

// What a view says before any fuel purchase is loaded, with the command that loads them.
export const NO_FUEL_DATA = 'No fuel data yet. Load it with: .venv\\Scripts\\python.exe src\\main.py fuel';
