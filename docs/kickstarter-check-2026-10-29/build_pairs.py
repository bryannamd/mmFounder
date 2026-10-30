"""Kickstarter success/failure pairs for the Jev check (PREREG.md). Usage: python3 -I build_pairs.py <ks.json.gz> <out.jsonl>"""
import collections
import datetime
import gzip
import heapq
import json
import math
import re
import sys

CUT = int(datetime.datetime(2026, 7, 1, tzinfo=datetime.timezone.utc).timestamp())
LOW, HIGH = 0.8, 1.2  # failure goal within [0.8 s, 1.2 s] of the success goal s, the rule behind the doc's count
LEAK = re.compile(r"\bfunded\b|stretch goal|\bunlocked\b", re.I)  # words written after a campaign succeeded


def load(path):
    seen, dups, leaks = {}, 0, collections.Counter()
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                d = json.loads(line)["data"]
            except (ValueError, KeyError, TypeError):
                continue
            st, dl = d.get("state"), d.get("deadline")
            if st not in ("successful", "failed") or not isinstance(dl, (int, float)) or dl < CUT:
                continue
            name, blurb = d.get("name"), d.get("blurb")
            if not (isinstance(name, str) and name.strip() and isinstance(blurb, str) and blurb.strip()):
                continue
            try:
                usd = float(d["goal"]) * float(d["static_usd_rate"])
            except (KeyError, TypeError, ValueError):
                continue
            c = d.get("category") or {}
            sub = c.get("name")
            parent = c.get("parent_name") or sub  # a top-level category has no parent: it is its own group
            if not (math.isfinite(usd) and usd > 0 and parent):
                continue
            if d["id"] in seen:  # one project can sit in several crawl files; their states never disagree here
                dups += 1
                continue
            if LEAK.search(name) or LEAK.search(blurb):
                leaks[st] += 1
                seen[d["id"]] = None
                continue
            seen[d["id"]] = {"id": d["id"], "state": st, "name": " ".join(name.split()),
                             "blurb": " ".join(blurb.split()), "parent": parent, "sub": sub, "usd": usd,
                             "country": d.get("country"), "deadline": int(dl)}
    return [r for r in seen.values() if r], dups, leaks


def fits(f, s):
    return LOW * s <= f <= HIGH * s


def nearest(groups):
    """Most constrained failure first, each to an unused success: same subcategory first, then the closest goal, then id."""
    pairs = []
    for g in sorted(groups):
        S, F = groups[g]
        cands = {f["id"]: [s for s in S if fits(f["usd"], s["usd"])] for f in F}
        used = set()
        for f in sorted(F, key=lambda f: (len(cands[f["id"]]), f["id"])):
            free = [s for s in cands[f["id"]] if s["id"] not in used]
            if free:
                s = min(free, key=lambda s: (s["sub"] != f["sub"], abs(math.log(s["usd"] / f["usd"])), s["id"]))
                used.add(s["id"])
                pairs.append((s, f))
    return pairs


def most(groups):
    """The largest number of pairs any matching can reach (points in intervals, smallest end first)."""
    total = 0
    for S, F in groups.values():
        ivs = sorted((LOW * s["usd"], HIGH * s["usd"]) for s in S)
        h, i = [], 0
        for p in sorted(f["usd"] for f in F):
            while i < len(ivs) and ivs[i][0] <= p:
                heapq.heappush(h, ivs[i][1])
                i += 1
            while h and h[0] < p:
                heapq.heappop(h)
            if h:
                heapq.heappop(h)
                total += 1
    return total


def main(src, out):
    recs, dups, leaks = load(src)
    by = collections.Counter(r["state"] for r in recs)
    print("unique projects", dict(by), "duplicate records skipped", dups, "leak words removed", dict(leaks))
    month = collections.defaultdict(collections.Counter)
    for r in recs:
        month[datetime.datetime.fromtimestamp(r["deadline"], datetime.timezone.utc).strftime("%Y-%m")][r["state"]] += 1
    for m in sorted(month):
        c = month[m]
        print(" ", m, dict(c), "success per failure %.1f" % (c["successful"] / max(c["failed"], 1)))
    for key in ("parent", "sub"):
        groups = collections.defaultdict(lambda: ([], []))
        for r in recs:
            # a subcategory name can sit under two parents (Comedy, Spaces): group by both
            groups[r["parent"] if key == "parent" else (r["parent"], r["sub"])][0 if r["state"] == "successful" else 1].append(r)
        print("max pairs, same %s:" % key, most(groups))
        if key == "parent":
            pairs = nearest(groups)
    lower = sum(1 for s, f in pairs if s["usd"] < f["usd"])
    higher = sum(1 for s, f in pairs if s["usd"] > f["usd"])
    same_sub = sum(1 for s, f in pairs if s["sub"] == f["sub"])
    gap = sorted(abs(math.log(s["usd"] / f["usd"])) for s, f in pairs)
    print("pairs used", len(pairs), "success goal lower", lower, "higher", higher, "same subcategory", same_sub,
          "median goal gap %.1f%%" % (100 * (math.exp(gap[len(gap) // 2]) - 1)))
    with open(out, "w", encoding="utf-8") as fh:
        for i, (s, f) in enumerate(sorted(pairs, key=lambda p: p[1]["id"])):
            fh.write(json.dumps({"pair": i, "success": s, "failure": f}, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main(*sys.argv[1:3])
