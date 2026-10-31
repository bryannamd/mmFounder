"""Score the Kickstarter check against PREREG.md.

Usage: python3 -I analyze.py [folder] [--sure 0.8]. Reads pairs.jsonl and answers.jsonl in the folder (default: this
folder) and writes results.json there. --sure is criterion 2's probability (0.8 in the first check)."""
import collections
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EPS = 1e-9


def wilson(k, n, z=1.96):
    if not n:
        return (float("nan"), float("nan"))
    p = k / n
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (c - h, c + h)


def score(x):  # x > 0 right, x == 0 half, x < 0 wrong
    return 1.0 if x > EPS else 0.5 if abs(x) <= EPS else 0.0


def slot(a):  # the slot one answer picked: 1 or 2, 0 when it gave exactly 0.5
    return 0 if abs(a["p1"] - 0.5) <= EPS else 1 if a["p1"] > 0.5 else 2


def rate(rows, key):
    return sum(r[key] for r in rows) / len(rows)


def acc(rows, key):
    k, n = sum(r[key] for r in rows), len(rows)
    lo, hi = wilson(k, n)
    return {"n": n, "right": k, "acc": round(k / n, 4) if n else None, "ci95": [round(lo, 4), round(hi, 4)]}


def main(folder=HERE, sure_at=0.8):
    pairs = {d["pair"]: d for d in map(json.loads, open(os.path.join(folder, "pairs.jsonl"), encoding="utf-8"))}
    ans = collections.defaultdict(dict)
    for a in map(json.loads, open(os.path.join(folder, "answers.jsonl"), encoding="utf-8")):
        ans[a["pair"]][a["order"]] = a
    rows = []
    for i, d in sorted(pairs.items()):
        A = ans.get(i, {})
        if "SF" not in A or "FS" not in A:
            continue
        s, f = d["success"], d["failure"]
        p_sf, p_fs = A["SF"]["p1"], A["FS"]["p2"]  # the success's probability in each order
        p = (p_sf + p_fs) / 2
        rows.append({"pair": i, "p": p, "chosen": max(p, 1 - p), "jev": score(p - 0.5),
                     "sf": score(p_sf - 0.5), "fs": score(p_fs - 0.5),
                     "slots": (slot(A["SF"]), slot(A["FS"])),
                     "first": (A["SF"]["p1"] + A["FS"]["p1"]) / 2,
                     "goal": score(f["usd"] - s["usd"]), "blurb": score(len(s["blurb"]) - len(f["blurb"])),
                     "same_sub": s["sub"] == f["sub"],
                     "ascii": all(ord(ch) < 128 for ch in s["blurb"] + f["blurb"])})
    sure = [r for r in rows if r["chosen"] >= sure_at - EPS]
    out = {"pairs": len(pairs), "scored": len(rows),
           "jev": acc(rows, "jev"), "sure_%g" % sure_at: acc(sure, "jev"),
           "smaller_goal": acc(rows, "goal"), "longer_blurb": acc(rows, "blurb"),
           "order_success_first": acc(rows, "sf"), "order_success_second": acc(rows, "fs"),
           "mean_p_project_1": round(sum(r["first"] for r in rows) / len(rows), 4),
           "answers_picking_project_1": sum(slot(a) == 1 for v in ans.values() for a in v.values()),
           # the two orders picked different projects: the same slot twice. A pair with a 0.5 answer is not counted
           "pairs_with_a_0.5_answer": sum(0 in r["slots"] for r in rows),
           "flipped_pairs": sum(r["slots"] in ((1, 1), (2, 2)) for r in rows),
           "flipped_second_slot_twice": sum(r["slots"] == (2, 2) for r in rows),
           "mean_chosen": round(sum(r["chosen"] for r in rows) / len(rows), 4),
           "same_sub": acc([r for r in rows if r["same_sub"]], "jev"),
           "both_ascii": acc([r for r in rows if r["ascii"]], "jev"), "bins": []}
    for lo, hi in ((0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)):
        b = [r for r in rows if lo - EPS <= r["chosen"] < hi - EPS]
        if b:
            out["bins"].append({"range": [lo, min(hi, 1.0)], "mean_chosen": round(sum(r["chosen"] for r in b) / len(b), 4),
                                **acc(b, "jev")})
    # found after seeing the answers: never part of the verdict
    # whole words, plural included: "expedition" and "especially" do not count
    has = lambda r, w: re.search(r"\b%ss?\b" % w, (r["name"] + " " + r["blurb"]).lower()) is not None
    out["post_hoc_sure_0.6"] = acc([r for r in rows if r["chosen"] >= 0.6 - EPS], "jev")
    out["post_hoc_words_success_only_vs_failure_only"] = {
        w: [sum(has(d["success"], w) and not has(d["failure"], w) for d in pairs.values()),
            sum(has(d["failure"], w) and not has(d["success"], w) for d in pairs.values())]
        for w in ("edition", "special")}
    j = rate(rows, "jev")  # the criteria compare unrounded rates
    out["criteria"] = {
        "1_overall_at_least_0.60": j >= 0.60,
        "2_sure_at_least_0.70_with_30_pairs": len(sure) >= 30 and rate(sure, "jev") >= 0.70,
        "3_beats_smaller_goal": j > rate(rows, "goal"),
        "3_beats_longer_blurb": j > rate(rows, "blurb")}
    out["pass"] = all(out["criteria"].values())
    with open(os.path.join(folder, "results.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    a = sys.argv[1:]
    sure_at = float(a.pop(a.index("--sure") + 1)) if "--sure" in a else 0.8
    rest = [x for x in a if x != "--sure"]
    main(rest[0] if rest else HERE, sure_at)
