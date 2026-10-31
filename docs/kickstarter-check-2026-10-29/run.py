"""Ask Jev about the Kickstarter pairs (PREREG.md). Dry run by default; --send calls the API. Run again to resume.

Usage: python3 -I run.py [folder] [--send]. The folder holds pairs.jsonl and gets the answers (default: this folder)."""
import importlib.util
import json
import os
import sys
import time

sys.dont_write_bytecode = True  # importing jev.py must not leave __pycache__ in the repository
JEV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "skills", "founder-consumer", "jev.py")
spec = importlib.util.spec_from_file_location("jev", JEV)
jev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jev)

HERE = os.path.dirname(os.path.abspath(__file__))
PAIRS, ANSWERS, LOG = (os.path.join(HERE, n) for n in ("pairs.jsonl", "answers.jsonl", "run-log.json"))
BUDGET = 0.05
BUCKETS = [(1000, "under $1,000"), (5000, "$1,000 to $5,000"), (10000, "$5,000 to $10,000"),
           (25000, "$10,000 to $25,000"), (50000, "$25,000 to $50,000"), (100000, "$50,000 to $100,000")]
INSTRUCTIONS = ("Exactly one of these two Kickstarter projects reached its funding goal by its deadline."
                " Which one reached its goal?")
QS = {"funded": {"type": "choice", "instructions": INSTRUCTIONS, "criteria": {
    "project_1": "The project in `project_1` reached its funding goal",
    "project_2": "The project in `project_2` reached its funding goal"}}}


def bucket(usd):
    return next((name for top, name in BUCKETS if usd < top), "$100,000 or more")


def view(r):
    cat = r["parent"] if r["sub"] in (None, r["parent"]) else "%s > %s" % (r["parent"], r["sub"])
    return {"name": r["name"], "blurb": r["blurb"], "category": cat, "funding_goal": bucket(r["usd"])}


def body(pair, order):
    a, b = (pair["success"], pair["failure"]) if order == "SF" else (pair["failure"], pair["success"])
    return {"model": jev.MODEL, "state": {"project_1": view(a), "project_2": view(b)}, "questions": QS}


def todo():
    pairs = [json.loads(line) for line in open(PAIRS, encoding="utf-8")]
    done = set()
    if os.path.exists(ANSWERS):
        done = {(a["pair"], a["order"]) for a in map(json.loads, open(ANSWERS, encoding="utf-8"))}
    jobs = []
    for p in pairs:
        for order in (("SF", "FS") if p["pair"] % 2 == 0 else ("FS", "SF")):
            if (p["pair"], order) not in done:
                jobs.append((p, order))
    return pairs, done, jobs


def main(send):
    pairs, done, jobs = todo()
    chars = sum(len(json.dumps(body(p, o), ensure_ascii=False)) for p, o in jobs)
    print("pairs %d, answers on disk %d, requests to send %d, about %d characters (about $%.4f at 4 characters a token)"
          % (len(pairs), len(done), len(jobs), chars, chars / 4 * jev.USD_PER_TOKEN))
    if not send:
        print(json.dumps(body(pairs[0], "SF"), ensure_ascii=False, indent=1))
        return 0
    t = jev.Transport(jev.api_key())
    cost, tokens, start = 0.0, 0, time.time()
    with open(ANSWERS, "a", encoding="utf-8") as out:
        for i, (p, order) in enumerate(jobs, 1):
            try:
                reply = t.post(body(p, order))
            except jev.JevError as e:
                print("stopped at request %d: %s" % (i, e))
                break
            problem = jev.check_reply(reply, jev.MODEL, QS)
            if problem:
                print("stopped at request %d: %s" % (i, problem))
                break
            a, n = reply["answers"]["funded"], jev._tokens(reply)
            out.write(json.dumps({"pair": p["pair"], "order": order, "p1": a["probabilities"]["project_1"],
                                  "p2": a["probabilities"]["project_2"], "choice": a["choice"],
                                  "confidence": a.get("confidence"), "tokens": n}) + "\n")
            out.flush()
            tokens += n
            cost = tokens * jev.USD_PER_TOKEN
            if i % 100 == 0:
                print("%d/%d sent, $%.4f, %.0f s" % (i, len(jobs), cost, time.time() - start))
            if cost > BUDGET:
                print("stopped: this run's cost $%.4f is over the $%.2f budget" % (cost, BUDGET))
                break
    log = {"sent": t.stats, "input_tokens": tokens, "usd": round(cost, 6), "seconds": round(time.time() - start, 1),
           "model": jev.MODEL, "finished": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(log) + "\n")
    print(json.dumps(log))
    return 0


if __name__ == "__main__":
    rest = [a for a in sys.argv[1:] if a != "--send"]
    if rest:  # another check's folder, such as a second deadline window
        PAIRS, ANSWERS, LOG = (os.path.join(rest[0], n) for n in ("pairs.jsonl", "answers.jsonl", "run-log.json"))
    sys.exit(main("--send" in sys.argv[1:]))
