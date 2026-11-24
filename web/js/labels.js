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

// The fleet status on top of the Drivers view: the questions asked of every truck, each with its groups in the
// order they are drawn. `key` is the truck's field holding its group; a group's `todo` is what to do about it, its
// `tip` what it means, its `color` the color token of its mark, its bar segment and its tiles (`hollow`: drawn as an
// outline). The 24 h in the words is a copy of the server's ACTIVE_HOURS: change both together. A type's `name` is
// its name in full, for where there is room.
const SENDER = 'Check the fuel sender connection to the Samsara device';
export const FLEET = [
  { key: 'type', name: 'Type', note: 'driver type', parts: [
    { k: 'LO', label: 'LO', name: 'Lease operator', color: '--s1', tip: 'Lease operator' },
    { k: 'C', label: 'C', name: 'Company driver', color: '--s2', tip: 'Company driver' },
    { k: 'OO', label: 'OO', name: 'Company owner', color: '--s3', tip: 'Company owner' },
    { k: 'Other', label: 'Other', name: 'Other', color: '--s4', tip: "Datatruck's type 'other' (mostly LP)" },
    { k: 'none', label: 'No driver', name: 'No driver', color: '--line', tip: 'No active driver assigned in Datatruck' }] },
  { key: 'samsara', name: 'Samsara', note: 'working or not', parts: [
    { k: 'working', label: 'Working', color: '--good', tip: 'GPS and fuel gauge both reported in the last 24 h' },
    { k: 'none', label: 'No device', color: '--bad', todo: 'Install a Samsara device, or add the truck to Samsara' },
    { k: 'mismatch', label: 'VIN mismatch', color: '--s4', todo: 'Correct the VIN in Datatruck, or move the device to the truck the driver is in' },
    { k: 'nogps', label: 'No GPS 24 h+', color: '--warn', todo: 'Check the device: unplugged, or the truck is powered off (home time?)' },
    { k: 'never', label: 'Gauge never reports', color: '--s1', todo: SENDER },
    { k: 'silent', label: 'Gauge silent 24 h+', color: '--s1', hollow: true, todo: SENDER }] },
  { key: 'card', name: 'Card in EFS', note: 'on this unit number', parts: [
    { k: 'active', label: 'Active', color: '--good', tip: 'EFS has an ACTIVE card carrying this unit number' },
    { k: 'none', label: 'No card', color: '--bad', todo: 'No EFS card carries this unit number: put a card on the unit' },
    { k: 'inactive', label: 'Inactive only', color: '--s4', todo: 'Every EFS card on this unit number is INACTIVE: activate one, or put another card on the unit' },
    { k: 'held', label: 'On hold', color: '--warn', todo: 'EFS holds the card (HOLD or HOLD FOR FRAUD): the pump refuses it until it is overridden or released' }] },
  { key: 'match', name: 'Cards match', note: 'Datatruck against EFS', parts: [
    { k: 'match', label: 'Match', color: '--good', tip: 'Datatruck and EFS show the same cards for this unit' },
    { k: 'differ', label: 'Differ', color: '--bad', tip: 'Both show cards for this unit, not the same ones' },
    { k: 'datatruck', label: 'Datatruck only', color: '--warn', tip: 'Datatruck shows a card for this unit; EFS has none in use on this unit number' },
    { k: 'efs', label: 'EFS only', color: '--warn', tip: 'EFS has a card in use on this unit number; Datatruck shows none' },
    { k: 'none', label: 'No card', color: '--line', tip: 'Neither Datatruck nor EFS shows a card in use for this unit' }] },
  { key: 'status', name: 'Status', note: 'in Datatruck', parts: [
    { k: 'in_transit', label: 'In transit', color: '--s1', tip: "Datatruck's status: in transit" },
    { k: 'available', label: 'Available', color: '--s3', tip: "Datatruck's status: available" },
    { k: 'shop', label: 'In shop', color: '--warn', tip: "Datatruck's status: in the shop" },
    { k: 'yard', label: 'In yard', color: '--s6', tip: "Datatruck's status: in the yard" },
    { k: 'other', label: 'Other status', color: '--faint', tip: 'A Datatruck status the page has no name for' }] },
  { key: 'duty', name: 'On duty', note: 'working now', parts: [
    { k: 'on', label: 'On duty', color: '--good', tip: 'In transit or available, with an active driver' },
    { k: 'off', label: 'Not on duty', color: '--line', tip: 'Nobody is driving it, or it is in the shop or the yard' }] },
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
  { key: 'heading', label: "Off the load's road, nearest Love's ahead", rule: "Drives away from its load's road: the nearest Love's in the direction it drives." },
  { key: 'low', label: "No Love's in reach, low fuel", rule: 'A truck stop that is not a Love\'s. Switched off since Nov 13.' },
];

// A test truck's state in words, as the Recommend view shows it.
export const STATES = {
  enough: 'Enough fuel for delivery', watch: 'Watching, nothing to tell yet', stop: 'Would tell now', urgent: 'URGENT: fuel low',
  told: 'Stop told', parked: 'Parked: its stop is told once it moves', 'no fresh gauge': 'No fresh gauge reading',
  'no load': "No load, fuel above the driver's usual level", 'no load, parked': "No load, at the driver's level: told once it moves",
  "no load, no Love's ahead": "No load, at the driver's level: no Love's in reach ahead",
  'off its road': "Drives away from its load's road, fuel above the driver's usual level",
  "off its road, no Love's ahead": "Drives away from its load's road, at the driver's level: no Love's in reach ahead",
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

// What became of a request to the card agent (the Cards section): its name, and its tone, which colors its square in
// the batch, its mark in the list and its chip (the colors are in the styles, by tone).
export const CARD_KINDS = {
  opened: { label: 'Card opened', tone: 'good' },
  open_already: { label: 'Card was already open', tone: 'good' },
  office: { label: 'Passed to the office', tone: 'warn' },
  replied: { label: 'Answered, nothing opened', tone: 'info' },
  nothing: { label: 'Nothing asked', tone: 'off' },
  paused: { label: 'Agent paused: left for the office', tone: 'warn' },
  logged_out: { label: 'eManager logged out: left for the office', tone: 'bad' },
  failed: { label: 'Failed: the office was told', tone: 'bad' },
  working: { label: 'Working on it', tone: 'info' },
};

// The card agent's tools in words, as its steps are named.
export const CARD_TOOLS = { declined_card: 'Open the card', reply_to_driver: 'Reply to the driver',
  hand_to_office: 'Pass to the office', look_up_card: 'Look the card up' };
