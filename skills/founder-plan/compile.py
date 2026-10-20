#!/usr/bin/env python3
"""Compiles the business plan for founder-plan. Standard library only, no network.

Reads everything the other ten skills wrote into founder/ and assembles one
document, founder/business-plan.md, with a verdict at the top. The verdict is
computed from the numbers, never written by hand:

    Profitable   every check that has data passes
    Not yet      at least one check fails (each failure is listed with its number)
    Incomplete   there are no numbers yet (run founder-cfo first)

The checks:
    1. each unit earns money before fixed costs        (founder/numbers.json)
    2. year 1 makes an operating profit                 (founder/numbers.json)
    3. break-even fits inside capacity, if capacity is given
    4. enough of the buyer panel buys                   (founder/panel/results.json, --min-buy-rate, default 25%)
    5. there is a buyer panel at all                    (founder/panel/results.json)
    6. the outside view has a source for every number   (founder/rcf.json, founder-rcf's rcf.py check)
    7. no plan number is above its reference class high without evidence  (founder/rcf.json)

Amounts are shown in numbers.json's "currency" (default USD). A numbers.json
that cannot be read stops the tool with one "error: ..." line and exit code 2.

    python3 compile.py                      # reads ./founder, writes ./founder/business-plan.md
    python3 compile.py --dir path/to/founder --min-buy-rate 0.3
    python3 compile.py --check              # print the verdict and exit 0 (Profitable) or 1
"""

import argparse
import importlib.util
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SECTIONS = [  # (file in founder/, heading, which skill writes it)
    ("summary.md", "Summary", "founder-plan"),
    ("rcf.md", "The outside view", "founder-rcf"),
    ("board.md", "What the board said", "founder-board"),
    ("competitors.md", "The competition", "founder-competitors"),
    ("panel/results.md", "The buyer panel", "founder-consumer"),
    ("pricing.md", "Pricing", "founder-pricing"),
    ("offer.md", "The offer", "founder-offer"),
    ("cfo.md", "The numbers", "founder-cfo"),
    ("marketing.md", "Marketing", "founder-marketing"),
    ("brand.md", "Brand", "founder-brand"),
    ("ops.md", "Operations", "founder-ops"),
    ("launch.md", "Launch plan", "founder-launch"),
]


class PlanError(Exception):
    pass


def _load(folder, name):
    path = os.path.join(HERE, "..", folder, name + ".py")
    spec = importlib.util.spec_from_file_location("founder_" + name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_unit_economics():
    return _load("founder-cfo", "unit_economics")


def _read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    except FileNotFoundError:
        return None
    except UnicodeDecodeError:
        raise PlanError("%s is not UTF-8 text" % path)


def _strip_h1(text):
    lines = text.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    # demote headings one level so they nest under the section heading
    return "\n".join(("#" + l) if l.startswith("#") else l for l in lines).strip()


def verdict(d, min_buy_rate=0.25):
    """Return (verdict, checks, numbers, panel). checks = [(ok, text)]."""
    checks = []
    numbers = panel = spec = None
    ue = _load_unit_economics()
    raw = _read(os.path.join(d, "numbers.json"))
    if raw:
        path = os.path.join(d, "numbers.json")
        try:
            spec = json.loads(raw)
        except ValueError as e:
            raise PlanError("%s is not valid JSON: %s" % (path, e))
        try:
            numbers = ue.analyse(spec)
        except ue.NumbersError as e:
            raise PlanError("%s: %s" % (path, e))
        except (AttributeError, TypeError, KeyError, ValueError, ZeroDivisionError, OverflowError) as e:
            raise PlanError("%s does not have the shape founder-cfo writes: %s" % (path, e))
        u = numbers["unit"]
        c = numbers["contribution"]
        cur = numbers["currency"]
        checks.append((c > 0, "Each %s earns %s before fixed costs (%.0f%% contribution)." % (u, ue.money(c, cur), numbers["contribution_pct"] * 100)
                       if c > 0 else "Each %s LOSES %s before fixed costs." % (u, ue.money(-c, cur))))
        y = numbers["year1_profit"]
        checks.append((y > 0, "Year 1 operating profit: %s." % ue.money(y, cur, whole=True) if y > 0
                       else "Year 1 operating LOSS: %s." % ue.money(-y, cur, whole=True)))
        be, cap = numbers["breakeven_per_day"], numbers["capacity_per_day"]
        if cap is not None:
            fits = not math.isinf(be) and be <= float(cap)
            checks.append((fits, "Break-even is %s %ss a day against a capacity of %s." % (
                "never reached" if math.isinf(be) else "{:,.0f}".format(math.ceil(be)), u, cap)))
    raw = _read(os.path.join(d, "panel", "results.json"))
    if raw:
        panel = json.loads(raw)
        r = panel["buy_rate"]
        checks.append((r >= min_buy_rate, "%d of %d simulated buyers buy (%.0f%%, the bar is %.0f%%)." % (
            panel["buys"], panel["answered"], r * 100, min_buy_rate * 100)))
    else:
        checks.append((False, "No buyer panel yet: run /founder-consumer"))
    checks += _outside_view(d, spec, numbers, panel)
    if numbers is None:
        v = "Incomplete"
    elif all(ok for ok, _ in checks):
        v = "Profitable"
    else:
        v = "Not yet"
    return v, checks, numbers, panel


def _outside_view(d, spec, numbers, panel):
    """Checks 6 and 7: founder/rcf.json passes rcf.py check, and the plan is not above it without evidence."""
    path = os.path.join(d, "rcf.json")
    if not os.path.exists(path):
        return [(False, "No outside view yet: run /founder-rcf")]
    rcf = _load("founder-rcf", "rcf")
    try:
        data = rcf.load(path)
    except rcf.RCFError as e:
        return [(False, "The outside view cannot be read: %s" % e)]
    problems, warnings = rcf.check(data)
    if data.get("example") is True:
        # example numbers are illustrative; a plan must not pass on them
        problems = ["it is example data, not real statistics: run /founder-rcf for this business"] + problems
    if problems:
        return [(False, "The outside view fails its check (%d problem%s, first: %s). Run rcf.py check." % (
            len(problems), "" if len(problems) == 1 else "s", problems[0]))]
    out = [(True, "The outside view has a source for each of its %d numbers%s." % (
        len(data["metrics"]), (" (%s)" % "; ".join(warnings)) if warnings else ""))]
    if numbers is None:
        return out
    rows = rcf.compare(data, spec, numbers, panel)
    fails = rcf.failures(rows)
    for r in fails:
        out.append((False, "%s in the plan is %s, above the reference class high of %s, with no evidence." % (
            r["label"], rcf._fmt(r["plan"], r["unit"]), rcf._fmt(r["high"], r["unit"]))))
    if not fails:
        warned = sum(1 for r in rows if r["status"] == "warn")
        out.append((True, "No plan number is above its reference class high without evidence (%d compared%s)." % (
            sum(1 for r in rows if r["status"] in ("ok", "warn", "justified")),
            (", %d above the median" % warned) if warned else "")))
    return out


def compile_plan(d, min_buy_rate=0.25):
    idea = _read(os.path.join(d, "idea.md"))
    name = None
    if idea:
        first = idea.splitlines()[0]
        name = first[2:].strip() if first.startswith("# ") else None
    v, checks, numbers, panel = verdict(d, min_buy_rate)
    _ue = _load_unit_economics()
    title = name or (numbers["business"] if numbers and numbers.get("business") else "Your business")
    L = ["# %s · Business plan" % title, ""]
    L.append("**Verdict: %s**" % v)
    L.append("")
    for ok, text in checks:
        L.append("- %s %s" % ("✓" if ok else "✗", text))
    if v == "Incomplete":
        L.append("- No numbers yet. Run /founder-cfo, then compile again.")
    L.append("")
    if numbers:
        be = numbers["breakeven_per_day"]
        m = lambda v, whole=False: _ue.money(v, numbers["currency"], whole)
        price = "| Price | %s a %s |" % (m(numbers["price"]), numbers["unit"])
        if numbers["price_includes_vat"]:
            price = "| Price (incl. VAT) | %s a %s (%s before VAT) |" % (m(numbers["price"]), numbers["unit"], m(numbers["net_price"]))
        L += ["| key number | |", "| --- | ---: |",
              price,
              "| Profit margin at plan | %.0f%% per %s |" % (numbers["margin_at_plan"] * 100, numbers["unit"]),
              "| Break-even | %s %ss a day |" % ("never" if math.isinf(be) else "{:,.0f}".format(math.ceil(be)), numbers["unit"]),
              "| Year 1 operating profit | %s |" % m(numbers["year1_profit"], True),
              "| Startup spend | %s |" % m(numbers["startup"], True),
              "| Cash needed before it pays for itself | %s |" % m(numbers["cash_needed"], True),
              "| Startup money earned back | %s |" % ("month %d" % numbers["payback_month"] if numbers["payback_month"] else "not in year 1")]
        if panel:
            L.append("| Buyer panel | %d buy · %d pass |" % (panel["buys"], panel["passes"]))
        L.append("")
    if idea:
        L += ["## The idea", "", _strip_h1(idea), ""]
    missing = []
    for fname, heading, skill in SECTIONS:
        text = _read(os.path.join(d, fname))
        if text:
            L += ["## %s" % heading, "", _strip_h1(text), ""]
        else:
            missing.append((heading, skill))
    if missing:
        L += ["## Not done yet", ""]
        for heading, skill in missing:
            L.append("- %s: run /%s" % (heading, skill))
        L.append("")
    L.append("_The panel is simulated buyers and the numbers are projections from your inputs. Confirm demand with real"
             " customers and costs with real quotes before you spend. Not financial, legal or tax advice._")
    return v, "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", default="founder")
    ap.add_argument("--min-buy-rate", type=float, default=0.25)
    ap.add_argument("--check", action="store_true", help="print the verdict only; exit 0 if Profitable")
    ap.add_argument("--out", help="default: <dir>/business-plan.md")
    a = ap.parse_args(argv)
    if not os.path.isdir(a.dir):
        print("error: no %s/ folder here. Run the other founder skills first." % a.dir, file=sys.stderr)
        return 2
    try:
        v, text = compile_plan(a.dir, a.min_buy_rate)
        if a.check:
            _, checks, _, _ = verdict(a.dir, a.min_buy_rate)
    except PlanError as e:
        print("error: %s" % e, file=sys.stderr)
        return 2
    if a.check:
        print("Verdict: %s" % v)
        for ok, t in checks:
            print("  %s %s" % ("✓" if ok else "✗", t))
        return 0 if v == "Profitable" else 1
    out = a.out or os.path.join(a.dir, "business-plan.md")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(text)
    print("Verdict: %s. Wrote %s" % (v, out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
