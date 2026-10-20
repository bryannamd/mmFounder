#!/usr/bin/env python3
"""The outside view for founder-rcf. Standard library only, no network.

Reference class forecasting: before you trust your own plan, look at how
businesses like yours actually did. founder/rcf.json holds those base rates, each
with its source. This tool checks that every number has a source, then holds the
plan in founder/numbers.json up against them.

    python3 rcf.py check founder/rcf.json
    python3 rcf.py compare --rcf founder/rcf.json --numbers founder/numbers.json
    python3 rcf.py compare --rcf founder/rcf.json --numbers founder/numbers.json \\
        --panel founder/panel/results.json --out founder/rcf-compare.md

check fails (exit 1) if any metric is missing its key, a numeric value, a unit,
an http(s) source, a source_date (YYYY-MM-DD, YYYY-MM or YYYY) or a class_level
that is one of the reference_classes, or if low > value or value > high. A file
marked "example": true passes with a warning: it is not real data.

compare reads these keys against the plan:

    ramp_month1_per_day   ramp_per_day[0]                 optimism check
    ramp_month3_per_day   ramp_per_day[2]                 optimism check
    plan_per_day          plan_per_day                    optimism check
    contribution_pct      contribution / price (a ratio)  optimism check
    margin_at_plan        margin at plan (a ratio)        optimism check
    buy_rate, conversion_rate   the panel's buy rate      shown only
    anything else         nothing                         shown only

Optimism check: a plan number above the metric's "high" fails, unless an
"adjustments" entry for that metric gives evidence (then it passes, marked as
justified optimism). With no "high", a plan number above the "value" is a
warning only. A plan number that is not in numbers.json is skipped and shown.
The panel's buy rate is never judged: simulated buyers are a ceiling, not a rate.

The tool never fills in a base rate. Every number in the report comes from the
two files.
"""

import argparse
import datetime
import importlib.util
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OPTIMISM = {  # rcf key: what the plan number is
    "ramp_month1_per_day": "units a day in month 1",
    "ramp_month3_per_day": "units a day in month 3",
    "plan_per_day": "units a day at plan",
    "contribution_pct": "contribution as a share of price",
    "margin_at_plan": "profit margin at plan",
}
RATIOS = ("contribution_pct", "margin_at_plan")
PANEL_KEYS = ("buy_rate", "conversion_rate")
DATE_FORMATS = ("%Y-%m-%d", "%Y-%m", "%Y")


class RCFError(Exception):
    pass


def _load_unit_economics():
    path = os.path.join(HERE, "..", "founder-cfo", "unit_economics.py")
    spec = importlib.util.spec_from_file_location("founder_unit_economics", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            obj = json.load(fh)
    except FileNotFoundError:
        raise RCFError("no such file: %s" % path)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise RCFError("%s is not valid JSON: %s" % (path, e))
    if not isinstance(obj, dict):
        raise RCFError("%s must hold one JSON object" % path)
    return obj


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and not math.isinf(v) and not math.isnan(v)


def _is_date(v):
    if not isinstance(v, str):
        return False
    for f in DATE_FORMATS:
        try:
            d = datetime.datetime.strptime(v, f)
        except ValueError:
            continue
        # strptime takes "2023-1"; only the zero-padded form counts
        return d.strftime(f) == v
    return False


# ── check ───────────────────────────────────────────────────────────────────────
def check(rcf):
    """Return (problems, warnings). No problems means the file passes."""
    problems, warnings = [], []
    if rcf.get("example") is True:
        warnings.append("this is example data, not real statistics: replace every metric before you rely on it")
    classes = rcf.get("reference_classes")
    levels = set()
    if not isinstance(classes, list) or not classes:
        problems.append("'reference_classes' needs at least one class")
    else:
        for i, c in enumerate(classes):
            if not isinstance(c, dict) or isinstance(c.get("level"), (list, dict)) or c.get("level") is None \
                    or not c.get("name"):
                problems.append("reference_classes[%d] needs a level and a name" % i)
            else:
                levels.add(c["level"])
    metrics = rcf.get("metrics")
    if not isinstance(metrics, list) or not metrics:
        problems.append("'metrics' needs at least one metric")
        return problems, warnings
    for i, m in enumerate(metrics):
        if not isinstance(m, dict):
            problems.append("metrics[%d] is not an object" % i)
            continue
        where = "metrics[%d]%s" % (i, (" (%s)" % m["key"]) if isinstance(m.get("key"), str) and m["key"] else "")
        if not isinstance(m.get("key"), str) or not m["key"].strip():
            problems.append("%s needs a 'key'" % where)
        if not _is_num(m.get("value")):
            problems.append("%s needs a numeric 'value'" % where)
        if not isinstance(m.get("unit"), str) or not m["unit"].strip():
            problems.append("%s needs a 'unit'" % where)
        src = m.get("source")
        if not isinstance(src, str) or not src.strip().lower().startswith(("http://", "https://")):
            problems.append("%s needs a 'source' that is an http(s) address" % where)
        if not _is_date(m.get("source_date")):
            problems.append("%s needs a 'source_date' as YYYY-MM-DD, YYYY-MM or YYYY" % where)
        if isinstance(m.get("class_level"), (list, dict)) or m.get("class_level") not in levels:
            problems.append("%s: class_level %r is not one of the reference_classes" % (where, m.get("class_level")))
        for b in ("low", "high"):
            if m.get(b) is not None and not _is_num(m[b]):
                problems.append("%s: '%s' must be a number or null" % (where, b))
        lo, hi, v = m.get("low"), m.get("high"), m.get("value")
        if _is_num(v):
            if _is_num(lo) and lo > v:
                problems.append("%s: low (%s) is above value (%s)" % (where, lo, v))
            if _is_num(hi) and v > hi:
                problems.append("%s: value (%s) is above high (%s)" % (where, v, hi))
        if _is_num(lo) and _is_num(hi) and lo > hi:
            problems.append("%s: low (%s) is above high (%s)" % (where, lo, hi))
    return problems, warnings


# ── compare ─────────────────────────────────────────────────────────────────────
def plan_values(spec, a):
    """The plan's side of each optimism check, from numbers.json and unit_economics.analyse()."""
    out = {}
    ramp = spec.get("ramp_per_day")
    if isinstance(ramp, list) and len(ramp) >= 1:
        out["ramp_month1_per_day"] = float(ramp[0])
    if isinstance(ramp, list) and len(ramp) >= 3:
        out["ramp_month3_per_day"] = float(ramp[2])
    if spec.get("plan_per_day") is not None:
        out["plan_per_day"] = float(spec["plan_per_day"])
    if a:
        out["contribution_pct"] = a["contribution_pct"]
        out["margin_at_plan"] = a["margin_at_plan"]
    return out


def _evidence(rcf, key):
    for adj in rcf.get("adjustments") or []:
        if isinstance(adj, dict) and adj.get("metric") == key and str(adj.get("evidence") or "").strip():
            return adj["evidence"].strip()
    return None


def compare(rcf, spec, a, panel=None):
    """One row per metric: dict(key, label, class_level, unit, plan, value, high, status, text).

    status is fail, justified, warn, ok, skipped or info. Only fail counts against the plan.
    """
    plan = plan_values(spec, a)
    rows = []
    for m in rcf.get("metrics") or []:
        key = m.get("key")
        row = {"key": key, "label": m.get("label") or key, "class_level": m.get("class_level"),
               "unit": m.get("unit"), "plan": None, "value": m.get("value"), "high": m.get("high")}
        if key in OPTIMISM:
            if key not in plan:
                row.update(status="skipped", text="no plan number to compare (%s is not in numbers.json)" % OPTIMISM[key])
            elif key in RATIOS and m.get("unit") != "ratio":
                row.update(status="skipped", text="unit must be \"ratio\" (0.40 for 40%%) to compare with the plan, not %r"
                           % m.get("unit"))
            else:
                p = row["plan"] = plan[key]
                hi = m.get("high")
                if hi is not None and p > hi:
                    ev = _evidence(rcf, key)
                    if ev:
                        row.update(status="justified", text="above the reference class high, with evidence: %s" % ev)
                    else:
                        row.update(status="fail", text="above the reference class high and no evidence in 'adjustments'")
                elif hi is None and p > m.get("value"):
                    row.update(status="warn", text="above the reference class median (no high given)")
                else:
                    row.update(status="ok", text="inside the reference class")
        elif key in PANEL_KEYS:
            if panel and panel.get("buy_rate") is not None:
                row.update(plan=panel["buy_rate"], status="info",
                           text="shown only: simulated buyers are a ceiling, not a conversion rate")
            else:
                row.update(status="info", text="shown only (no panel results given)")
        else:
            row.update(status="info", text="shown only")
        rows.append(row)
    return rows


def failures(rows):
    return [r for r in rows if r["status"] == "fail"]


def _fmt(v, unit):
    if v is None:
        return "n/a"
    if unit == "ratio":
        return "%.1f%%" % (v * 100)
    return "{:,.0f}".format(v) if float(v) == int(v) else "{:,.2f}".format(v)


def report_md(rcf, rows, warnings=()):
    L = ["# Outside view: %s" % (rcf.get("business") or "your business"), ""]
    for w in warnings:
        L += ["**Warning: %s.**" % w, ""]
    fails = failures(rows)
    L.append("**%s.** %d metrics, %d compared with the plan, %d above their reference class with no evidence." % (
        "The plan is more optimistic than its reference class" if fails else "No plan number is above its reference class high",
        len(rows), sum(1 for r in rows if r["status"] in ("fail", "justified", "warn", "ok")), len(fails)))
    L += ["", "| metric | class | plan | reference | high | result |", "| --- | ---: | ---: | ---: | ---: | --- |"]
    for r in rows:
        L.append("| %s | %s | %s | %s | %s | %s: %s |" % (
            r["label"], r["class_level"], _fmt(r["plan"], r["unit"] if r["key"] not in PANEL_KEYS else "ratio"),
            _fmt(r["value"], r["unit"]), _fmt(r["high"], r["unit"]), r["status"], r["text"].replace("|", "/")))
    kills = rcf.get("kill_criteria") or []
    if kills:
        L += ["", "## Kill criteria", ""]
        for k in kills:
            L.append("- If %s is below %s: %s" % (k.get("metric"), k.get("below"), k.get("action")))
    L += ["", "Base rates describe businesses like yours, not yours. A plan above them needs a reason you can check."]
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("rcf", help="founder/rcf.json")
    cp = sub.add_parser("compare")
    cp.add_argument("--rcf", required=True)
    cp.add_argument("--numbers", required=True)
    cp.add_argument("--panel", help="founder/panel/results.json")
    cp.add_argument("--out", help="write the report here (markdown)")
    a = ap.parse_args(argv)
    try:
        rcf = load(a.rcf)
    except RCFError as e:
        print("error: %s" % e, file=sys.stderr)
        return 2
    problems, warnings = check(rcf)
    for w in warnings:
        print("warning: %s" % w)
    if problems:
        for p in problems:
            print("- %s" % p)
        print("check failed: %d problem%s in %s" % (len(problems), "" if len(problems) == 1 else "s", a.rcf))
        return 1
    if a.cmd == "check":
        print("ok: %d metrics, each with a source" % len(rcf["metrics"]))
        return 0
    ue = _load_unit_economics()
    try:
        spec = ue.load(a.numbers)
        analysis = ue.analyse(spec)
        panel = None
        if a.panel:
            panel = load(a.panel)
    except (ue.NumbersError, RCFError) as e:
        print("error: %s" % e, file=sys.stderr)
        return 2
    rows = compare(rcf, spec, analysis, panel)
    text = report_md(rcf, rows, warnings)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print("wrote %s" % a.out)
    else:
        sys.stdout.write(text)
    return 1 if failures(rows) else 0


if __name__ == "__main__":
    sys.exit(main())
