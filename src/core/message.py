# Messages (pure): a load's fuel plan as the driver reads it in Telegram (HTML), one full message per major event.
# Sections, split by a "--------" line: what just happened with the load and its fuel; the road (what is done, then
# what is ahead); the totals; and a link that navigates through what is still ahead.
from html import escape

from core import compare, follow, route
from models import Event, LoadPlan, Outcome, Progress

LINE = "--------"
NEWER = "⤵ Newer update below"
TAGS = {"pickup": "📦 PU", "delivery": "🏁 DEL"}


# The first message of a plan, before anything happened.
def first_text(p: LoadPlan) -> str:
    return plan_text(p, follow.start(p), [], p.truck.fuel_pct / 100 * p.truck.tank_gal, 0.0)


# The full message of plan `p` as `prog` stands, telling the `new` events first. `fuel_gal` is the fuel on board now
# (follow.fuel_gal), `here` how far along the road in force the truck is (route.mile_of).
def plan_text(p: LoadPlan, prog: Progress, new: list[Event], fuel_gal: float, here: float) -> str:
    ahead = route.waypoints(prog.road)[prog.passed:]
    t, end = p.truck, [w for w in route.waypoints(p) if w.kind != "fuel"][-1]
    # once the load is done, its last delivery reads "arrived with ~N gal"
    last = None if ahead else next((e for e in reversed(prog.events) if e.kind == "delivery"), None)
    lines = _headline(p, prog, new, not ahead)
    lines.append(f"Load {_text(p.order.load_id)} · {_text(follow.town(t.place))} → {_text(end.label)} · "
                 f"{p.route_mi:,.0f} mi")
    if ahead:
        lines.append(f"Fuel now {fuel_gal / t.tank_gal * 100:.0f}% · {fuel_gal:.0f} of {t.tank_gal:.0f} gal · "
                     f"{p.mpg:.1f} MPG")
    lines.append(LINE)
    # what is done: pickups, deliveries and every purchase; a stop missed or dropped, or a re-plan, is told in the
    # headline when it happens, and the road ahead already shows what came of it
    lines += [_done(e, e is last, fuel_gal) for e in follow.as_told(prog.events) if e.kind in ("pickup", "delivery", "bought")]
    lines += _ahead(prog, fuel_gal, here)
    lines += [LINE, *_totals(p, prog, fuel_gal, here, not ahead)]
    if ahead:
        lines += [LINE, _link(prog)]
    return "\n".join(lines)


# The same message with its link replaced by "⤵ Newer update below", once a newer one is sent.
def superseded(text: str) -> str:
    return "\n".join(NEWER if _is_link(line) else line for line in text.split("\n"))


# The same message with its link leading through what is still ahead now (the truck passed a stop with nothing to
# tell yet, e.g. its fuel line hasn't come in); unchanged when nothing is left ahead.
def with_link(text: str, prog: Progress) -> str:
    if follow.finished(prog):
        return text
    return "\n".join(_link(prog) if _is_link(line) else line for line in text.split("\n"))


# The first lines: what happened, one line per new event, the first naming the unit.
def _headline(p: LoadPlan, prog: Progress, new: list[Event], finished: bool) -> list[str]:
    unit = f"Unit {_text(p.truck.unit)}"
    told = [_head(e) for e in new if e.kind != "dropped" and not (finished and e.kind == "delivery")]
    if finished:
        went = "plan not followed" if follow.off_plan(follow.as_told(prog.events)) else "plan followed"
        heads = [("🏁 Delivered", went)] + told
    elif told:
        heads = told
    else:
        heads = [("⛽ Fuel plan" if prog.events else "⛽ New fuel plan", "")]
    first, rest = heads[0], heads[1:]
    return ([f"<b>{first[0]} · {unit}</b>" + (f" · {first[1]}" if first[1] else "")]
            + [f"{title} · {detail}" if detail else title for title, detail in rest])


# One event as a headline: a title and a detail.
def _head(e: Event) -> tuple[str, str]:
    label = _text(e.label)
    if e.kind in TAGS:
        return f"✅ {TAGS[e.kind].split()[1]} {label} done", ""
    if e.kind == "bought":
        if e.stop_no:
            return "✅ Stop done", f"bought {e.gallons:.0f} gal at {label}"
        return "⚠️ Off plan", f"bought {e.gallons:.0f} gal at {label}"
    if e.kind == "missed":
        return "⚠️ Stop missed", f"no fuel bought at {label}"
    return "🔁 Rest of the road re-planned", f"from near {label}"


# One thing done, in the road section (a pickup, a delivery or a purchase), in the order it happened; stops done are
# crossed out, except the load's last delivery (`last`), which tells the fuel it arrived with. Stops are named, not
# numbered: the numbers count the stops still ahead, which change as the road is re-planned.
def _done(e: Event, last: bool, fuel_gal: float) -> str:
    label = _text(e.label)
    if e.kind in TAGS:
        return f"{TAGS[e.kind]} {label} ✓ arrived with ~{fuel_gal:.0f} gal" if last else _crossed(f"{TAGS[e.kind]} {label} ✓")
    if e.stop_no:
        return _crossed(f"⛽ {label} ✓ {e.gallons:.0f} gal · ${_pump(e):,.0f}")
    return f"⛽ {label} · {e.gallons:.0f} gal · ${_pump(e) / e.gallons:.2f} (not on plan)"


# The road ahead, in order: each pickup and delivery, each Love's to stop at (numbered 1, 2, ... from the next one)
# with the fuel expected on arrival and what to buy (the name opens Google Maps there), and the fuel expected at the
# end. Distances count from `here`.
def _ahead(prog: Progress, fuel_gal: float, here: float) -> list[str]:
    expected = follow.ahead(prog, fuel_gal, here)
    lines = [] if prog.road.plan else ["⚠️ No safe plan: the Love's on this road are too far apart for the fuel on board."]
    n = 0  # fuel stops ahead so far
    for k, (w, gal, stop) in enumerate(expected):
        into = f"in {max(0.0, w.miles - here):,.0f} mi"
        if stop:
            n += 1
            other = " · no Love's in reach" if stop.store.name else ""  # a station Google found (google_places)
            price = f"${stop.store.retail:.2f}" if stop.store.price_date else "pump price not known"
            lines += [f'⛽ {n}. <a href="{_href(route.place_link(w.lat, w.lng))}">{_text(w.label)}</a>'
                      f" · {into}{other}", f"      arrive ~{max(0.0, gal):.0f} gal → buy {stop.gallons:.0f} gal · {price}"]
        else:
            lines.append(f"{TAGS[w.kind]} {_text(w.label)} · {into}")
            if k == len(expected) - 1 and prog.road.plan:
                lines.append(f"      arrive ~{max(0.0, gal):.0f} gal")
    return lines


# The totals, at pump prices (what the driver sees): the plan's before anything happened; then the plan beside what
# was bought so far; at the end, the plan beside what really happened, with what it cost more or less than the plan.
def _totals(p: LoadPlan, prog: Progress, fuel_gal: float, here: float, finished: bool) -> list[str]:
    planned = _road_totals(p)
    if not prog.events:
        return [f"Total: {planned}"]
    bought = [e for e in prog.events if e.kind == "bought"]
    gallons, pump = sum(e.gallons for e in bought), sum(_pump(e) for e in bought)
    actual = (f"{gallons:.0f} gal · ${pump:,.0f} · {len(bought)} stop{'s' * (len(bought) != 1)}, "
              f"{sum(1 for e in bought if e.stop_no)} on plan") if bought else "nothing yet"
    if not finished:
        return [f"Still to buy: {_still_to_buy(prog, fuel_gal, here)}", f"Bought so far: {actual}"]
    lines = [f"Plan: {planned}" + (f" · ~{p.plan.end_gal:.0f} gal left" if p.plan else ""),
             f"Actual: {actual} · ~{fuel_gal:.0f} gal left"]
    end_pump = p.end_pump or p.end_price  # plans before 2026-10-22 kept only the discounted price
    if p.plan and end_pump:
        real = Outcome(len(bought), gallons, sum(e.billed for e in bought), fuel_gal, pump=pump)
        extra = compare.extra_at_pump(real, compare.from_plan(p.plan), end_pump)
        more = fuel_gal - p.plan.end_gal
        lines.append(f"Extra cost vs plan: {_dollars(extra)} ({abs(more):.0f} gal {'more' if more >= 0 else 'less'} "
                     f"left, counted at ${end_pump:.2f})")
    return lines


# A road's planned buying at pump prices: "120 gal · ~$653 · 2 stops", or why there is nothing to buy.
def _road_totals(road: LoadPlan) -> str:
    if road.plan is None:
        return "no safe plan"
    if not road.plan.stops:
        return "no fuel stop needed"
    n = len(road.plan.stops)
    return (f"{sum(s.gallons for s in road.plan.stops):.0f} gal · ~${compare.from_plan(road.plan).pump:,.0f} · "
            f"{n} stop{'s' * (n != 1)}")


# What the road ahead still plans to buy, at pump prices: "338 gal · ~$2,106 · 2 stops", or why there is nothing.
def _still_to_buy(prog: Progress, fuel_gal: float, here: float) -> str:
    if prog.road.plan is None:
        return "no safe plan"
    stops = [stop for _, _, stop in follow.ahead(prog, fuel_gal, here) if stop]
    if not stops:
        return "nothing more"
    n = len(stops)
    return (f"{sum(s.gallons for s in stops):.0f} gal · ~${sum(s.gallons * s.store.retail for s in stops):,.0f} · "
            f"{n} stop{'s' * (n != 1)}")


# What a purchase came to at the pump; purchases told before pump prices were kept show what was billed.
def _pump(e: Event) -> float:
    return e.pump if e.pump is not None else e.billed


# The navigation link through what is still ahead: "Start" before anything happened, "Continue" after.
def _link(prog: Progress) -> str:
    word = "Continue" if prog.events or prog.passed else "Start"
    return f'<a href="{_href(route.navigate_link(route.waypoints(prog.road)[prog.passed:]))}">▶ {word} the road</a>'


# A link made safe inside an HTML attribute: Telegram reads "&amp;" back as the "&" between the link's values.
def _href(url: str) -> str:
    return escape(url, quote=True)


# True for the message's navigation link line.
def _is_link(line: str) -> bool:
    return line.startswith('<a href="') and "▶" in line


# Whole dollars with a sign: "+$58", "−$12", "$0".
def _dollars(value: float) -> str:
    return f"{'+' if value > 0.5 else '−' if value < -0.5 else ''}${abs(value):,.0f}"


# Text from the data made safe inside Telegram HTML: only <, > and & need it ("Love's" stays as it is).
def _text(value: str) -> str:
    return escape(value, quote=False)


# Text crossed out (Telegram HTML): a stop that is done.
def _crossed(text: str) -> str:
    return f"<s>{text}</s>"
