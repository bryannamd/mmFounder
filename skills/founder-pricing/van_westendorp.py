#!/usr/bin/env python3
"""Price sensitivity (Van Westendorp) for founder-pricing. Standard library only.

Every buyer on the panel answers four questions: at what price would it be too
cheap to trust, a bargain, getting expensive, and too expensive to buy. Plotted
together, those four answers give you an acceptable price range and the price
that leaves the fewest people unhappy.

    python3 van_westendorp.py founder/panel/answers
    python3 van_westendorp.py prices.csv --out founder/pricing-curve.md
    python3 van_westendorp.py founder/panel/answers --json
    python3 van_westendorp.py founder/panel/answers --currency KRW
    python3 van_westendorp.py founder/panel/answers --market Korea

Input is either the panel's answers folder (one JSON per buyer, written by
founder-consumer) or a CSV with the columns too_cheap, cheap, expensive,
too_expensive (one row per respondent; extra columns are ignored). A respondent
missing any of the four numbers, or giving them out of order (too cheap must be
the lowest, too expensive the highest), is dropped and counted.

The four points it reports:

    PMC  point of marginal cheapness   below this, too many think it's too cheap
    PME  point of marginal expensiveness above this, too many think it's too expensive
    OPP  optimal price point            as many say "too cheap" as "too expensive"
    IPP  indifference price point       as many say "a bargain" as "expensive"

--currency sets how prices are shown (default: the panel's currency, else USD;
KRW prices are read on a grid that steps in 10 won). If the panel next to the
answers folder (../personas.json) deals buyers in more than one currency, --market NAME is required and only that
market's buyers are counted: prices in different currencies cannot share a curve.

PMC to PME is the acceptable range. These are answers from simulated buyers:
use the range to choose what to TEST, then test it with real ones.
"""

import argparse
import csv
import glob
import json
import os
import importlib.util
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
KEYS = ("too_cheap", "cheap", "expensive", "too_expensive")


class PricingError(Exception):
    pass


def _load_unit_economics():
    path = os.path.join(HERE, "..", "founder-cfo", "unit_economics.py")
    spec = importlib.util.spec_from_file_location("founder_unit_economics", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


money = _load_unit_economics().money


def _f(v):
    try:
        x = float(str(v).replace("$", "").replace("₩", "").replace("원", "").replace(",", "").replace(" ", "").strip())
    except (TypeError, ValueError):
        return None
    return x if x > 0 else None


def _panel_currency(path):
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(path)), "panel.json"), encoding="utf-8") as fh:
            return json.load(fh)["customer"].get("currency")
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def _market_ids(path, market):
    """The buyer ids to count, or None for all. Reads the panel's personas.json next to the answers folder."""
    pp = os.path.join(os.path.dirname(os.path.abspath(path)), "personas.json")
    cards = []
    if os.path.exists(pp):
        try:
            with open(pp, encoding="utf-8") as fh:
                cards = json.load(fh)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise PricingError("%s is not valid JSON: %s" % (pp, e))
    currencies = sorted({c["currency"] for c in cards if c.get("currency")})
    if market is None:
        if len(currencies) > 1:
            markets = sorted({c["market"] for c in cards if c.get("market")})
            raise PricingError("this panel has buyers in %s: give --market (one of %s)" % (
                ", ".join(currencies), ", ".join(markets)))
        # one currency: the cards' own, else the customer's in panel.json
        return None, currencies[0] if currencies else _panel_currency(path)
    picked = [c for c in cards if c.get("market") == market]
    if not picked:
        raise PricingError("no buyers in market %r (looked in %s)" % (market, pp))
    return {c["id"] for c in picked}, picked[0].get("currency")


def read(path, market=None):
    """Return (rows, dropped) where rows are (too_cheap, cheap, expensive, too_expensive)."""
    if market is not None and not os.path.isdir(path):
        raise PricingError("--market works on a panel's answers folder, not a CSV")
    raw = []
    if os.path.isdir(path):
        ids, _ = _market_ids(path, market)
        for fp in sorted(glob.glob(os.path.join(path, "*.json"))):
            if ids is not None and os.path.splitext(os.path.basename(fp))[0] not in ids:
                continue
            try:
                with open(fp, encoding="utf-8") as fh:
                    a = json.load(fh)
            except (json.JSONDecodeError, UnicodeDecodeError):
                raw.append(None)
                continue
            raw.append(tuple(_f(a.get("price_" + k)) for k in KEYS))
    elif path.endswith(".csv"):
        with open(path, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                raw.append(tuple(_f(r.get(k)) for k in KEYS))
    else:
        raise PricingError("give the panel's answers folder or a .csv")
    rows, dropped = [], 0
    for r in raw:
        if r is None or any(v is None for v in r) or not (r[0] <= r[1] <= r[2] <= r[3]):
            dropped += 1
            continue
        rows.append(r)
    return rows, dropped


def curves(rows, grid):
    n = float(len(rows))
    tc = [sum(1 for r in rows if r[0] >= p) / n for p in grid]          # too cheap at p (falls)
    ch = [sum(1 for r in rows if r[1] >= p) / n for p in grid]          # a bargain at p (falls)
    ex = [sum(1 for r in rows if r[2] <= p) / n for p in grid]          # expensive at p (rises)
    te = [sum(1 for r in rows if r[3] <= p) / n for p in grid]          # too expensive at p (rises)
    return tc, ch, ex, te


def cross(grid, falling, rising):
    """First price where the rising curve meets the falling one (linear interpolation)."""
    for i in range(1, len(grid)):
        d0 = rising[i - 1] - falling[i - 1]
        d1 = rising[i] - falling[i]
        if d0 <= 0 <= d1 and d1 != d0:
            t = -d0 / (d1 - d0)
            return grid[i - 1] + t * (grid[i] - grid[i - 1])
        if d0 == 0:
            return grid[i - 1]
    return None


def analyse(rows, step=None, currency="USD"):
    if len(rows) < 5:
        raise PricingError("need at least 5 complete answers (got %d)" % len(rows))
    lo = min(r[0] for r in rows)
    hi = max(r[3] for r in rows)
    if (currency or "USD").upper() == "KRW":
        # nobody prices in fractions of a won: step in whole 10 won
        step = step or max(10, int(round((hi - lo) / 400, -1)))
    step = step or max(0.01, round((hi - lo) / 400, 2))
    grid, p = [], lo
    while p <= hi + 1e-9:
        grid.append(round(p, 4))
        p += step
    tc, ch, ex, te = curves(rows, grid)
    not_cheap = [1 - v for v in ch]
    not_exp = [1 - v for v in ex]
    pts = {
        "PMC": cross(grid, tc, not_cheap),
        "PME": cross(grid, not_exp, te),
        "OPP": cross(grid, tc, te),
        "IPP": cross(grid, ch, ex),
    }
    return {"n": len(rows), "points": pts, "range": [pts["PMC"], pts["PME"]],
            "median": {k: sorted(r[i] for r in rows)[len(rows) // 2] for i, k in enumerate(KEYS)}}


def report(res, dropped, price=None, currency="USD"):
    m = lambda v: "n/a" if v is None else money(v, currency)
    p = res["points"]
    L = ["# Price sensitivity", "",
         "%d complete answers%s. Simulated buyers: use this to pick what to test, not as the final word." % (
             res["n"], (", %d dropped (incomplete or out of order)" % dropped) if dropped else ""), "",
         "| point | price | what it means |", "| --- | ---: | --- |",
         "| PMC | %s | below this, too many think it is too cheap to be good |" % m(p["PMC"]),
         "| OPP | %s | as many say too cheap as too expensive: the least resistance |" % m(p["OPP"]),
         "| IPP | %s | as many call it a bargain as call it expensive |" % m(p["IPP"]),
         "| PME | %s | above this, too many say it is too expensive to buy |" % m(p["PME"]), "",
         "**Acceptable range: %s to %s.**" % (m(p["PMC"]), m(p["PME"])), ""]
    md = res["median"]
    L.append("Median answers: too cheap %s, a bargain %s, getting expensive %s, too expensive %s." % (
        m(md["too_cheap"]), m(md["cheap"]), m(md["expensive"]), m(md["too_expensive"])))
    if price is not None and p["PMC"] is not None and p["PME"] is not None:
        where = "inside" if p["PMC"] <= price <= p["PME"] else ("below" if price < p["PMC"] else "above")
        L += ["", "Your current price, %s, is **%s** the acceptable range." % (m(price), where)]
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("source", help="the panel's answers folder, or a CSV")
    ap.add_argument("--price", type=float, help="your current price, to place it on the range")
    ap.add_argument("--out", help="write the report here (markdown)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--currency", help="currency code for the report (default: the panel's currency, else USD)")
    ap.add_argument("--market", help="count only this market's buyers (needed when the panel mixes currencies)")
    a = ap.parse_args(argv)
    try:
        currency = a.currency
        if os.path.isdir(a.source):
            _, market_currency = _market_ids(a.source, a.market)
            currency = currency or market_currency
        currency = (currency or "USD").upper()
        rows, dropped = read(a.source, a.market)
        res = analyse(rows, currency=currency)
    except (PricingError, FileNotFoundError) as e:
        print("error: %s" % e, file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(dict(res, dropped=dropped), indent=1))
        return 0
    text = report(res, dropped, a.price, currency)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print("wrote %s" % a.out)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
