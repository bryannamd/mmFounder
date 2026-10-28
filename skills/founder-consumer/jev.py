#!/usr/bin/env python3
"""Jev breadth for founder-consumer: the panel's persona cards, answered by TypeSafe's Jev model.

A separate layer next to the agent panel. Jev reads one persona card and the
pitch and answers with probabilities, not text: whether this person would pay,
what weighs most for them, and how each price on a ladder feels. The answers go
to jev-answers/ and jev-results.md, never to answers/ or results.json, so the
verdict (founder-plan) still comes from the agent panel only.

    python3 jev.py run --dir founder/panel --price 14900 --paid "the monthly plan" --unit "per month"
    python3 jev.py run --dir founder/panel-jev --customer founder/customer.json --pitch founder/pitch.md \\
        --n 200 --seed 7 --price 14900 --paid "the monthly plan" --unit "per month"

The first form uses the cards of an existing panel. The second deals new cards
into a new folder (panel.py init) and sends those.

    python3 jev.py sweep --dir founder/panel --pitch-template founder/pitch-template.md \\
        --prices 9900,12900,14900 --paid "the monthly plan" --unit "per month" [--dry-run]
    python3 jev.py sweep --dir founder/panel --pitches founder/pitch-a.md,founder/pitch-b.md \\
        --price 14900 --paid "the monthly plan" --unit "per month"

"sweep" runs the same cards once per variant, one run after another: each price
of --prices put in place of {price} in the template, or each file of --pitches.
Every variant gets its own folder under jev-sweeps/ and the same price ladder
(the baseline's), and the baseline runs --repeat times (default 2) to show how
much Jev moves between two runs of the same requests. jev-sweep.md compares each
variant with the baseline card by card. --dry-run prints what would be sent and
stops: no key, no folders, no requests.

This is the one founder tool that uses the network, and only in "run" and
"sweep": each card is one request to api.typesafe.ai carrying that card and the
pitch. The key comes from TYPESAFE_API_KEY, else from ~/.config/typesafe/api_key
(readable by you only: chmod 600). --budget-usd (default 1.00) stops the run
before a request that would take this run's estimated cost past it. It is an
estimate from token counts, not a cap on the bill.

State lives in the --dir folder: jev.json (the settings, a fingerprint of the
cards and settings, the run history) and jev-answers/<id>.json (the answer keys
the panel uses, plus Jev's own probabilities). Run it again to resume: cards with
a saved answer are not sent again. If the cards or the settings changed, it stops
and asks for a new --dir instead of mixing answers.

Exit codes: 0 done, 1 stopped at the budget (run again to continue), 2 error. A
sweep: 0 when every run is done, 1 when the budget stopped or skipped one, 2 when
one failed or its folder does not match.

Jev's probabilities are not customers either. The prices are an exploratory
estimate: a curve that never crosses 0.5 inside the ladder takes its end price.
"""

import argparse
import datetime
import email.utils
import hashlib
import http.client
import importlib.util
import itertools
import json
import math
import os
import random
import socket
import sys
import time
import urllib.error
import urllib.request
from decimal import Decimal, ROUND_HALF_UP

HERE = os.path.dirname(os.path.abspath(__file__))
URL = "https://api.typesafe.ai/v1/systemone"
HOST = "api.typesafe.ai"
MODEL = "jev-1.14.0"  # pinned: the jev-latest alias can change its answers
TEMPLATE = "v1"  # the questions below; a run never changes them
CONVERT = 1  # how the answer keys are made from the probabilities
USD_PER_TOKEN = 0.042 / 1000000  # input tokens; output is free
THRESHOLD = 0.5
MULTIPLES = [0.2, 0.3, 0.45, 0.6, 0.8, 1.0, 1.25, 1.6, 2.0, 2.5, 3.3]  # times --price, then --ladder-max on top
CURVES = ("too_cheap", "cheap", "expensive", "too_expensive")
FALLING = ("too_cheap", "cheap")
WIGGLE = 0.05  # a step this much the wrong way marks a curve as not monotone
SUM_SLACK = 0.03  # two-decimal probabilities: five levels can be 5 x 0.005 = 0.025 off; 0.01 stopped real replies
TIMEOUT = 60
RETRY = (429, 502, 503, 504, 529)
RETRIES = 5
WAIT_CAP = 30
RETRY_AFTER_CAP = 60
EXCERPT = 300
KEY_ENV = "TYPESAFE_API_KEY"
KEY_FILE = "~/.config/typesafe/api_key"
NOTE = "Most people do not buy most things. Decide with this person's own money, habits and doubts in a normal week."
BUYS_Q = ("After seeing `offer_seen_for_the_first_time` once, would `who_decides` start paying for {paid} at {price}"
          " {unit} within the first month? Yes only if they would actually pay, not just use a free tier or a free trial.")
REASON_Q = "When `who_decides` weighs whether to pay for {paid}, which of these matters most?"
PRICE_Q = "If the price of {paid} were {price} {unit}, how would `who_decides` feel about that price?"
REASON_TEXT = {
    "price": "the price",
    "habit": "whether it fits their routine and they would keep using it",
    "need": "whether they need this right now",
    "trust": "whether they trust the business, its claims or its reviews",
    "quality": "how good the product itself is",
    "convenience": "how easy it is to get, use or cancel",
    "timing": "whether this is the right time (their schedule, money this month)",
    "values": "whether it fits what they believe in",
    "other": "something else",
}
LEVELS = ["too cheap to be any good (quality doubt)", "a bargain", "about right, a fair price",
          "getting expensive, but might still buy", "too expensive, would not buy"]
PRICE_IDS = ["price_%02d" % (i + 1) for i in range(len(MULTIPLES) + 1)]
RAISE = ("More than a quarter of the cards are censored high on %s: the curve does not cross 0.5 inside the ladder."
         " Run again in a new --dir with a higher --ladder-max.")
SWEEPS = "jev-sweeps"  # a sweep's variant folders, inside the panel's folder
LOCK = "jev-sweep.lock"
VARIANT = "%02d-%s"  # the number keeps two variants apart, even two pitch files with the same name
REPEAT = "%s-r%d"
LOCKED = ("%s is there: another sweep is running in this folder, or one stopped without tidying up. Check, then delete"
          " it yourself.")
READ_RULE = ("If a variant's change in mean is about the size of the baseline's shift in mean between its repeats, or"
             " smaller, or its flipped cards are about as many as flip between the repeats, Jev could not tell that"
             " difference apart. The more variants, the more likely one difference is large by chance (%d variants"
             " here). Confirm two or three candidates with the agent panel, and one with a real test.")


class JevError(Exception):
    pass


def _load(folder, name):
    path = os.path.join(HERE, "..", folder, name + ".py")
    spec = importlib.util.spec_from_file_location("founder_" + name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


panel = _load("founder-consumer", "panel")
vw = _load("founder-pricing", "van_westendorp")
money = panel.money


def _finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _usd(v):
    return "$%.4f" % v  # API costs are fractions of a cent: money() would print $0.00


# ── the request ─────────────────────────────────────────────────────────────────
def _two_figures(x):
    """x rounded half up to two significant figures, still a decimal: 6.5 x 0.2 is 1.3, not 1."""
    if not x:
        return x
    return x.quantize(Decimal(1).scaleb(x.adjusted() - 1), rounding=ROUND_HALF_UP)


def ladder(price, top=5.0):
    """The twelve prices Jev is asked about: --price times MULTIPLES and --ladder-max.

    Each is rounded to two significant figures, except the 1.0 step, which is --price itself."""
    if not _finite(price) or price <= 0:
        raise JevError("--price must be a positive number (got %r)" % price)
    if not _finite(top) or top <= MULTIPLES[-1]:
        raise JevError("--ladder-max must be a number above %s (got %r)" % (MULTIPLES[-1], top))
    p = Decimal(repr(float(price)))
    out = [float(price) if m == 1.0 else float(_two_figures(p * Decimal(repr(float(m))))) for m in MULTIPLES + [top]]
    if not all(_finite(x) and x > 0 for x in out) or any(b <= a for a, b in zip(out, out[1:])):
        raise JevError("the price ladder (%s) is not strictly rising: choose another --price or --ladder-max"
                       % ", ".join("%g" % x for x in out))
    return out


def _numbers(text, flag):
    """The numbers of a comma-separated flag: "9900,12900" is [9900.0, 12900.0]."""
    try:
        return [float(x) for x in text.split(",")]
    except ValueError:
        raise JevError("%s takes numbers separated by commas, such as 9900,12900" % flag)


def given_ladder(price, text):
    """--ladder in place of ladder(): --price checked the same way, and twelve prices, one per price question, each
    a positive number above the one before. A sweep gives every variant the baseline's ladder this way."""
    if not _finite(price) or price <= 0:
        raise JevError("--price must be a positive number (got %r)" % price)
    out = _numbers(text, "--ladder")
    if len(out) != len(PRICE_IDS) or not all(_finite(x) and x > 0 for x in out) or any(
            b <= a for a, b in zip(out, out[1:])):
        raise JevError("--ladder must be %d positive prices, each above the one before (got %s)"
                       % (len(PRICE_IDS), ", ".join("%g" % x for x in out)))
    return out


def state(card, target, pitch, currency):
    """What Jev reads about one buyer, in the customer's own language."""
    who = {"name": card["name"], "age": card["age"], "group": card["segment"],
           "yearly_income": money(card["income"], currency, whole=True), "buying_style": card["behaviour"]}
    if card.get("behaviour_how"):
        who["how_they_buy"] = card["behaviour_how"]
    if card.get("habit"):
        who["everyday_context"] = card["habit"]
    who["first_doubt_on_hearing_an_offer_like_this"] = card["objection"]
    who["one_of"] = target
    who["note"] = NOTE
    return {"who_decides": who, "offer_seen_for_the_first_time": pitch}


def questions(card, s):
    """The fixed questions for one card. The reason options are shuffled per card, the same in every run."""
    codes = list(panel.REASONS)
    random.Random("%d:%s" % (s["seed"], card["id"])).shuffle(codes)
    cur = s["currency"]
    q = {"buys": {"type": "noul",
                  "instructions": BUYS_Q.format(paid=s["paid"], price=money(s["price"], cur), unit=s["unit"])},
         "reason_code": {"type": "choice", "instructions": REASON_Q.format(paid=s["paid"]),
                         "criteria": dict((c, REASON_TEXT[c]) for c in codes)}}
    for qid, x in zip(PRICE_IDS, s["ladder"]):
        q[qid] = {"type": "score", "instructions": PRICE_Q.format(paid=s["paid"], price=money(x, cur), unit=s["unit"]),
                  "criteria": list(LEVELS)}
    return q


def _settings(a, st, steps):
    """A run's settings, as jev.json keeps them: what its requests and its fingerprint depend on, apart from the cards."""
    return {"model": a.model, "price": float(a.price), "paid": a.paid.strip(), "unit": a.unit.strip(), "ladder": steps,
            "ladder_max": a.ladder_max if a.ladder is None else None,  # a given ladder makes no use of it
            "currency": st["customer"].get("currency", "USD").upper(), "seed": st["seed"], "template": TEMPLATE,
            "convert": CONVERT}


def fingerprint(cards, st, s):
    """sha256 of everything the requests and the converted answers depend on. The key is never in it."""
    obj = {"cards": cards, "pitch": st["pitch"], "target": st["customer"]["target"], "currency": s["currency"],
           "seed": s["seed"], "model": s["model"], "template": TEMPLATE, "convert": CONVERT, "ladder": s["ladder"],
           "price": s["price"], "paid": s["paid"], "unit": s["unit"], "reasons": REASON_TEXT, "levels": LEVELS,
           "questions": [BUYS_Q, REASON_Q, PRICE_Q, NOTE]}
    text = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── the reply ───────────────────────────────────────────────────────────────────
def _prob(v):
    return _finite(v) and 0 <= v <= 1


def _tokens(reply):
    usage = reply.get("usage") if isinstance(reply, dict) else None
    v = usage.get("input_tokens") if isinstance(usage, dict) else None
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


def check_reply(reply, model, qs):
    """None if a Jev reply answers these questions in the shape this tool reads, else a short problem string.

    The problem names the field and the rule it breaks, never the reply's own value: a reply can echo anything."""
    if not isinstance(reply, dict):
        return "the reply is not a JSON object"
    if reply.get("model") != model:
        return "the reply's model is not %s" % model
    if _tokens(reply) is None:
        return "usage.input_tokens is not a whole number of tokens"
    answers = reply.get("answers")
    if not isinstance(answers, dict):
        return "the reply has no answers"
    for qid, q in qs.items():
        a = answers.get(qid)
        if not isinstance(a, dict) or a.get("type") != q["type"]:
            return "%s is missing or not a %s answer" % (qid, q["type"])
        if q["type"] == "noul":
            if not _prob(a.get("noul")):
                return "%s: the probability is not a number from 0 to 1" % qid
            continue
        keys = list(q["criteria"]) if q["type"] == "choice" else [str(k) for k in range(len(LEVELS))]
        probs = a.get("probabilities")
        if not isinstance(probs, dict) or set(probs) != set(keys):
            return "%s: the probabilities are not one per option" % qid
        if not all(_prob(probs[k]) for k in keys):
            return "%s: a probability is not a number from 0 to 1" % qid
        if abs(sum(probs[k] for k in keys) - 1) > SUM_SLACK + 1e-9:
            return "%s: the probabilities do not add up to 1 (give or take %s)" % (qid, SUM_SLACK)
        if q["type"] == "choice" and a.get("choice") not in keys:
            return "%s: the choice is not one of the options" % qid
    return None


def crossing(ladder, ys, falling):
    """(price, None) where the curve first crosses 0.5, or (the ladder's end, "low" or "high") if it never does inside.

    A falling curve crosses where it first drops below 0.5, a rising one where it first reaches 0.5: exactly 0.5
    counts as reached. Between two ladder prices the crossing is on the straight line through them."""
    for i, y in enumerate(ys):
        if (y < THRESHOLD) if falling else (y >= THRESHOLD):
            if i == 0:
                return ladder[0], "low"
            y0 = ys[i - 1]
            return ladder[i - 1] + (ladder[i] - ladder[i - 1]) * (y0 - THRESHOLD) / (y0 - y), None
    return ladder[-1], "high"


def price_points(ladder, rows):
    """The four price answers and their flags, from the five-level probabilities at each ladder price."""
    r9 = lambda v: round(v, 9)  # two-decimal probabilities: 0.15 + 0.35 must be 0.5, not 0.49999999999999994
    curves = {"too_cheap": [r9(p[0]) for p in rows], "cheap": [r9(p[0] + p[1]) for p in rows],
              "expensive": [r9(p[3] + p[4]) for p in rows], "too_expensive": [r9(p[4]) for p in rows]}
    out, flags = {}, {"censored": {}, "multi_cross": [], "nonmonotone": [], "clamped": False}
    for k in CURVES:
        ys, falling = curves[k], k in FALLING
        out[k], side = crossing(ladder, ys, falling)
        if side:
            flags["censored"][k] = side
        if sum(1 for a, b in zip(ys, ys[1:]) if (a >= THRESHOLD) != (b >= THRESHOLD)) >= 2:
            flags["multi_cross"].append(k)
        if any(r9((b - a) if falling else (a - b)) > WIGGLE for a, b in zip(ys, ys[1:])):
            flags["nonmonotone"].append(k)
    first = dict(out)
    out["cheap"] = max(out["cheap"], out["too_cheap"])
    out["expensive"] = max(out["expensive"], out["cheap"])
    out["too_expensive"] = max(out["too_expensive"], out["expensive"])
    flags["clamped"] = out != first
    return out, flags


def convert(cid, reply, s, fp):
    """The panel's answer keys made from a checked reply, with the probabilities kept so it can be converted again."""
    ans = reply["answers"]
    p = ans["buys"]["noul"]
    rows = [[ans[qid]["probabilities"][str(k)] for k in range(len(LEVELS))] for qid in PRICE_IDS]
    prices, flags = price_points(s["ladder"], rows)
    a = {"id": cid, "buys": p >= THRESHOLD, "reason_code": ans["reason_code"]["choice"],
         "reason": "", "objection": "", "would_change_my_mind": ""}
    for k in CURVES:
        a["price_" + k] = prices[k]
    a["jev"] = {"model": reply["model"], "p_buy": p, "reason_probabilities": ans["reason_code"]["probabilities"],
                "price_probabilities": [{"price": x, "probabilities": r} for x, r in zip(s["ladder"], rows)],
                "input_tokens": reply["usage"]["input_tokens"], "fingerprint": fp, "convert_version": CONVERT,
                "flags": flags}
    return a


def reply_from(a):
    """The Jev reply a saved answer was made from, rebuilt from the probabilities it keeps. KeyError or TypeError if
    the jev block is damaged."""
    j = a["jev"]
    reply = {"model": j["model"], "usage": {"input_tokens": j["input_tokens"]}, "answers": {
        "buys": {"type": "noul", "noul": j["p_buy"]},
        "reason_code": {"type": "choice", "choice": a["reason_code"], "probabilities": j["reason_probabilities"]}}}
    for qid, e in zip(PRICE_IDS, j["price_probabilities"]):
        reply["answers"][qid] = {"type": "score",
                                 "probabilities": dict((str(k), v) for k, v in enumerate(e["probabilities"]))}
    return reply


def check_saved(path, card, s, fp):
    """(None, answer) if a saved Jev answer belongs to this run and follows from its own probabilities, else (problem, None).

    This runs before the key is read, so no problem string may carry a value from the file."""
    cid = card["id"]
    try:
        a = panel._read_json(path)
    except (ValueError, UnicodeDecodeError):
        return "not valid JSON", None
    if not isinstance(a, dict):
        return "not a JSON object", None
    prob = panel._answer_ok(path, cid)
    if prob:
        # the panel's own message quotes the file's id or reason_code: name the field, not the value
        if prob.startswith("id "):
            prob = "its id is not %s" % cid
        elif prob.startswith("reason_code "):
            prob = "its reason_code is not one of the panel's codes"
        return prob, None
    j = a.get("jev")
    if not isinstance(j, dict):
        return "no jev block", None
    if j.get("fingerprint") != fp:
        return "made with other cards or settings", None
    if j.get("convert_version") != CONVERT:
        return "made by another convert version", None
    try:
        if [e["price"] for e in j["price_probabilities"]] != s["ladder"]:
            return "its price ladder is not this run's", None
        reply = reply_from(a)
    except (KeyError, TypeError):
        return "its jev block is damaged", None
    prob = check_reply(reply, s["model"], questions(card, s))
    if prob:
        return prob, None
    if convert(cid, reply, s, fp) != a:
        return "its answers do not follow from its probabilities", None
    return None, a


# ── sending ─────────────────────────────────────────────────────────────────────
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Every 3xx becomes an error: urllib would carry the Authorization header to whatever host it is sent to."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def make_opener(*handlers):
    """The opener every request goes through. Tests pass a stand-in https handler; the rest stays the same."""
    return urllib.request.build_opener(_NoRedirect, *handlers)


def retry_after(value, now):
    """Seconds to wait from a Retry-After header: a number of seconds or an HTTP date, at most 60. None if neither."""
    if not value:
        return None
    value = value.strip()
    try:
        secs = float(value)
    except ValueError:
        try:
            when = email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError, IndexError, OverflowError):
            return None
        if when is None:
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=datetime.timezone.utc)
        secs = max(0.0, when.timestamp() - now)
    if not math.isfinite(secs) or secs < 0:
        return None
    return min(secs, RETRY_AFTER_CAP)


class Transport(object):
    """Sends one request at a time, retries what can be retried, and counts every attempt for the run history."""

    def __init__(self, key, opener=None, sleep=time.sleep, now=time.time, jitter=random.random):
        self.key, self.opener = key, opener or make_opener()
        self.sleep, self.now, self.jitter = sleep, now, jitter
        self.stats = {"attempts": 0, "retries": 0, "timeouts": 0, "unknown": 0}
        # checkpoint(True) right before each attempt, checkpoint(False) after one that failed and may be retried:
        # the run puts the counts, and whether a request is out, on disk in case the process dies
        self.checkpoint = None

    def _clean(self, raw):
        """Text safe to print: the key taken out first, then cut to EXCERPT characters."""
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "replace")
        return " ".join(_scrub(raw, [self.key]).split())[:EXCERPT]

    def post(self, body):
        data = json.dumps(body).encode("utf-8")
        for k in range(RETRIES + 1):
            req = urllib.request.Request(URL, data=data, method="POST", headers={
                "Authorization": "Bearer " + self.key, "Content-Type": "application/json"})
            self.stats["attempts"] += 1
            if k:
                self.stats["retries"] += 1
            if self.checkpoint:
                self.checkpoint(True)
            wait = None
            try:
                with self.opener.open(req, timeout=TIMEOUT) as resp:
                    raw = resp.read()
            except urllib.error.HTTPError as e:
                headers = e.headers or {}
                if 300 <= e.code < 400:
                    raise JevError("HTTP %d, a redirect to %s: not followed, so the key goes to %s only" % (
                        e.code, self._clean(headers.get("Location") or "nowhere"), HOST))
                if e.code not in RETRY:
                    try:
                        text = self._clean(e.read())
                    except (OSError, http.client.HTTPException):
                        text = ""
                    raise JevError("HTTP %d: %s" % (e.code, text or "(no body)"))
                problem = "HTTP %d" % e.code
                wait = retry_after(headers.get("Retry-After"), self.now())
            except urllib.error.URLError as e:
                if isinstance(e.reason, (socket.timeout, TimeoutError)):
                    self.stats["timeouts"] += 1
                # refused and DNS fail before the request; a reset, a broken pipe or a timeout may come after it left
                if not isinstance(e.reason, (ConnectionRefusedError, socket.gaierror)):
                    self.stats["unknown"] += 1
                problem = "no connection (%s)" % self._clean(str(e.reason))
            except (socket.timeout, TimeoutError):
                self.stats["timeouts"] += 1
                self.stats["unknown"] += 1
                problem = "timed out waiting for the reply"
            except (OSError, http.client.HTTPException) as e:
                self.stats["unknown"] += 1
                problem = "the connection dropped (%s)" % e.__class__.__name__
            else:
                try:
                    return json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, ValueError):
                    raise JevError("HTTP 200 but the reply is not valid JSON: %s" % self._clean(raw))
            if self.checkpoint:
                self.checkpoint(False)
            if k == RETRIES:
                raise JevError("gave up after %d tries, the last: %s" % (k + 1, problem))
            self.sleep(wait if wait is not None else min(2 ** k, WAIT_CAP) + self.jitter())


def _key_ok(key, where):
    # printable ASCII only: http.client quotes a header value it refuses, key and all, in its ValueError
    if not all(0x21 <= ord(ch) <= 0x7E for ch in key):
        raise JevError("the key in %s has whitespace, control or non-ASCII characters in it" % where)
    return key


def _scrub(text, keys):
    """text with every key taken out, also as it looks inside a repr() of a str or of bytes, or inside JSON."""
    for k in keys:
        # a key with a quote or a backslash looks different once JSON escapes it: an error body may quote it that way
        for form in (k, repr(k)[1:-1], repr(k.encode("utf-8"))[2:-1], json.dumps(k)[1:-1]):
            text = text.replace(form, "[key removed]")
    return text


def api_key():
    """The key from TYPESAFE_API_KEY, else from ~/.config/typesafe/api_key if only its owner can read that file."""
    key = os.environ.get(KEY_ENV, "").strip()
    if key:
        return _key_ok(key, KEY_ENV)
    path = os.path.expanduser(KEY_FILE)
    if not os.path.isfile(path):
        raise JevError("no TypeSafe API key: set %s or put the key in %s (chmod 600)" % (KEY_ENV, KEY_FILE))
    mode = os.stat(path).st_mode
    if mode & 0o077:
        raise JevError("%s can be read by other users (mode %03o): run chmod 600 on it first" % (path, mode & 0o777))
    with open(path, encoding="utf-8") as fh:
        key = fh.read().strip()
    if not key:
        raise JevError("%s is empty" % path)
    return _key_ok(key, path)


# ── files ───────────────────────────────────────────────────────────────────────
def _write_text(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def _write_bytes(path, data):
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)


def _save(path, obj):
    _write_text(path, json.dumps(obj, indent=1, ensure_ascii=False) + "\n")


def _save_answer(path, cid, a):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(a, indent=1, ensure_ascii=False) + "\n")
    prob = panel._answer_ok(tmp, cid)
    if not prob and not all(_finite(a["price_" + k]) and a["price_" + k] > 0 for k in CURVES):
        prob = "a price is not a positive number"
    if prob:
        os.remove(tmp)
        raise JevError("%s: the converted answer is not valid (%s)" % (cid, prob))
    os.replace(tmp, path)


def _stamp():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def folder_state(d):
    """"new" for a missing or empty folder, "panel" when it has panel.json and personas.json. Anything else stops."""
    if not os.path.exists(d) or (os.path.isdir(d) and not os.listdir(d)):
        return "new"
    if os.path.isfile(panel._path(d, "panel.json")) and os.path.isfile(panel._path(d, "personas.json")):
        return "panel"
    raise JevError("%s is not a complete panel (it needs both panel.json and personas.json) and it is not empty:"
                   " clean it up yourself or use a new --dir" % d)


def _no_markets(customer):
    if customer.get("markets") is not None:
        raise JevError("this customer.json has 'markets': Jev does not run panels with markets yet")


def _load_record(path):
    if not os.path.exists(path):
        return None
    try:
        rec = panel._read_json(path)
    except (ValueError, UnicodeDecodeError) as e:
        raise JevError("%s is not valid JSON (%s): fix it or use a new --dir" % (path, e))
    if not isinstance(rec, dict) or not isinstance(rec.get("runs"), list):
        raise JevError("%s is not a Jev record: fix it or use a new --dir" % path)
    return rec


def flag_counts(saved):
    out = {"censored": dict((k, {"low": 0, "high": 0}) for k in CURVES), "clamped": 0,
           "multi_cross": dict((k, 0) for k in CURVES), "nonmonotone": dict((k, 0) for k in CURVES)}
    for a in saved:
        f = a["jev"]["flags"]
        for k, side in f["censored"].items():
            out["censored"][k][side] += 1
        out["clamped"] += 1 if f["clamped"] else 0
        for name in ("multi_cross", "nonmonotone"):
            for k in f[name]:
                out[name][k] += 1
    return out


def derived(saved, n):
    """The part of jev.json that the answer files can always rebuild."""
    tokens = sum(a["jev"]["input_tokens"] for a in saved)
    return dict(flag_counts(saved), cards=n, done=len(saved), input_tokens=tokens, usd=tokens * USD_PER_TOKEN)


def _recover(rec, saved, ids):
    """Close the history of a run that was cut off. A card sent but not saved is one request of unknown outcome."""
    last = rec["runs"][-1] if rec["runs"] else None
    cid, rec["inflight"] = rec.get("inflight"), None
    if last is not None and last.get("ended") is None:
        last["stopped"] = "interrupted"
    if cid and not (isinstance(cid, str) and cid in saved):
        if last is not None:
            last["unknown"] = last.get("unknown", 0) + 1
        print("%s was being sent when the last run stopped: its outcome is unknown (it may have been billed)."
              " Sending it again." % (cid if isinstance(cid, str) and cid in ids else "A card"))


# ── results ─────────────────────────────────────────────────────────────────────
def _agent_ok(path, cid):
    try:
        return panel._answer_ok(path, cid) is None
    except (TypeError, AttributeError, OSError):  # valid JSON that is not an object, or a file that cannot be read
        return False


def agreement(d, cards, saved):
    """2x2 counts over the cards that have a valid agent answer, or None when no card has one."""
    cells, n = {"both": 0, "agent_only": 0, "jev_only": 0, "neither": 0}, 0
    for c in cards:
        path = panel._path(d, "answers", c["id"] + ".json")
        if not _agent_ok(path, c["id"]):
            continue
        agent, jev = panel._read_json(path)["buys"], saved[c["id"]]["buys"]
        cells["both" if agent and jev else "agent_only" if agent else "jev_only" if jev else "neither"] += 1
        n += 1
    return dict(cells, n=n) if n else None


def results(d, st, cards, saved, settings):
    """jev-results.json and the text of jev-results.md. Every table counts the same files: the current cards' answers."""
    t = panel.tally(d, answers="jev-answers")
    rows = [saved[c["id"]] for c in cards]
    by_id = dict((c["id"], c) for c in cards)
    yes = dict((k, n) for k, n, _, _ in t["why_yes"])
    no = dict((k, n) for k, n, _, _ in t["why_not"])
    reasons = sorted(((k, yes.get(k, 0) + no.get(k, 0), yes.get(k, 0), no.get(k, 0))
                      for k in panel.REASONS if k in yes or k in no), key=lambda r: -r[1])
    top = sorted(rows, key=lambda a: (-a["jev"]["p_buy"], a["id"]))[:10]
    flags = flag_counts(rows)
    cur = settings["currency"]
    complete, dropped = vw.read(panel._path(d, "jev-answers"))
    pricing, report = {"complete": len(complete), "dropped": dropped}, None
    if len(complete) < 5:
        pricing["note"] = "Too few complete price answers for a curve: %d cards (the price tool needs 5)." % len(complete)
    else:
        try:
            pricing.update(vw.analyse(complete, currency=cur))
            report = vw.report(pricing, dropped, price=settings["price"], currency=cur)
        except vw.PricingError as e:
            pricing["note"] = "No price curve: %s." % e
    res = {
        "business": st["customer"]["business"], "model": settings["model"], "threshold": THRESHOLD,
        "cards": len(rows), "buys": t["buys"], "passes": t["passes"],
        "mean_p_buy": sum(a["jev"]["p_buy"] for a in rows) / len(rows),
        "by_segment": t["by_segment"], "by_behaviour": t["by_behaviour"], "by_income": t["by_income"],
        "reasons": reasons,
        "top": [{"id": a["id"], "p_buy": a["jev"]["p_buy"], "segment": by_id[a["id"]]["segment"],
                 "behaviour": by_id[a["id"]]["behaviour"]} for a in top],
        "currency": cur, "ladder": settings["ladder"], "price": pricing, "price_flags": flags,
        "raise_ladder_max": [k for k in CURVES if flags["censored"][k]["high"] > 0.25 * len(rows)],
        "agreement": agreement(d, cards, saved),
    }
    return res, results_md(res, report)


def _cell(v):
    return str(v).replace("|", "/")


def _demote(text):
    lines = text.rstrip("\n").splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    return "\n".join(("##" + l) if l.startswith("#") else l for l in lines).strip()


def results_md(res, report):
    pct = lambda v: "%.0f%%" % (v * 100)
    L = ["# Jev panel: %s" % res["business"], ""]
    L.append("**%d buy · %d pass** out of %d cards. Jev (%s) gives each card a buy probability; a card counts as a"
             " buyer at %s or more." % (res["buys"], res["passes"], res["cards"], res["model"], res["threshold"]))
    L += ["", "Mean buy probability: %.3f. That is an average of probabilities, not a share of buyers." % res["mean_p_buy"]]
    L += ["", "Jev answers with probabilities and writes no text, so there are no quotes, objections or \"what would"
          " change my mind\" answers here: read those in the agent panel's results.md. The reasons below are the factor"
          " Jev weighed most for each card, judged separately from the buy question: read them as considerations, not as"
          " the reason for a decision."]
    L += ["", "This layer is not part of the verdict: founder-plan reads only the agent panel's results.json."]
    for title, key in (("By segment", "by_segment"), ("By buying behaviour", "by_behaviour"), ("By income", "by_income")):
        L += ["", "## %s" % title, "", "| group | cards | buy rate |", "| --- | ---: | ---: |"]
        for k, n, r in res[key]:
            L.append("| %s | %d | %s%s |" % (_cell(k), n, pct(r), "  (thin)" if n < 8 else ""))
    L += ["", "## What weighs most (judged separately from buying)", "", "| reason | cards |", "| --- | ---: |"]
    for k, n, _, _ in res["reasons"]:
        L.append("| %s | %d |" % (k, n))
    L += ["", "The same reasons next to the buy answer. These are two separate predictions for each card, so this is a"
          " cross-table of independent predictions, not why a card buys or passes.", "",
          "| reason | buy | pass |", "| --- | ---: | ---: |"]
    for k, _, y, n in res["reasons"]:
        L.append("| %s | %d | %d |" % (k, y, n))
    L += ["", "## Highest buy probability", "", "| card | buy probability | segment | behaviour |",
          "| --- | ---: | --- | --- |"]
    for r in res["top"]:
        L.append("| %s | %.2f | %s | %s |" % (r["id"], r["p_buy"], _cell(r["segment"]), _cell(r["behaviour"])))
    L += ["", "## Price: an exploratory estimate (a curve that never crosses 0.5 takes the ladder's end price)", ""]
    L.append(_demote(report) if report else res["price"]["note"])
    f = res["price_flags"]
    L += ["", "Prices asked about: %s." % ", ".join(money(x, res["currency"]) for x in res["ladder"]), "",
          "Censored low: the curve was already past 0.5 at the lowest price. Censored high: it had not got there by the"
          " highest. Either way the answer is the ladder's end price, not a measured one.", "",
          "| curve | censored low | censored high | crosses 0.5 more than once | not monotone |",
          "| --- | ---: | ---: | ---: | ---: |"]
    for k in CURVES:
        L.append("| %s | %d | %d | %d | %d |" % (k.replace("_", " "), f["censored"][k]["low"], f["censored"][k]["high"],
                                                 f["multi_cross"][k], f["nonmonotone"][k]))
    L += ["", "%d cards had their four prices put back in order (clamped)." % f["clamped"]]
    for k in res["raise_ladder_max"]:
        L += ["", RAISE % k.replace("_", " ")]
    ag = res["agreement"]
    if ag:
        L += ["", "## Agent panel and Jev, card by card", "",
              "%d cards have both a valid agent answer and a Jev answer." % ag["n"], "",
              "| | Jev: buy | Jev: pass |", "| --- | ---: | ---: |",
              "| agent: buy | %d | %d |" % (ag["both"], ag["agent_only"]),
              "| agent: pass | %d | %d |" % (ag["jev_only"], ag["neither"])]
    return "\n".join(L) + "\n"


# ── run ─────────────────────────────────────────────────────────────────────────
def _tried(this, who="This run"):
    unknown = (" %d requests had an unknown outcome: they may have been billed and are not in the cost."
               % this["unknown"]) if this["unknown"] else ""
    return "%s: %d requests (%d retries, %d timeouts), confirmed cost about %s.%s" % (
        who, this["attempts"], this["retries"], this["timeouts"], _usd(this["usd"]), unknown)


def run(a, connect=None, keys=None):
    """The run command. keys collects the key once it is read, so main() can take it out of any error."""
    connect = connect or Transport
    keys = [] if keys is None else keys
    steps = ladder(a.price, a.ladder_max) if a.ladder is None else given_ladder(a.price, a.ladder)
    if not _finite(a.budget_usd) or a.budget_usd <= 0:
        raise JevError("--budget-usd must be a positive number of dollars")
    paid, unit = a.paid.strip(), a.unit.strip()
    if not paid or not unit:
        raise JevError('--paid and --unit need words, such as --paid "the monthly plan" --unit "per month"')
    d, key = a.dir, None
    dealing = [o for o, v in (("--customer", a.customer), ("--pitch", a.pitch), ("--n", a.n), ("--seed", a.seed))
               if v is not None]
    if folder_state(d) == "new":
        if a.customer is None or a.pitch is None or a.n is None:
            raise JevError("%s has no panel yet: give --customer, --pitch and --n to deal the cards" % d)
        try:
            customer = panel._read_json(a.customer)
        except FileNotFoundError:
            raise JevError("no such file: %s" % a.customer)
        except (ValueError, UnicodeDecodeError) as e:
            raise JevError("%s is not valid JSON: %s" % (a.customer, e))
        if not isinstance(customer, dict):
            raise JevError("%s is not a JSON object" % a.customer)
        _no_markets(customer)
        key = api_key()
        keys.append(key)
        panel.init(d, a.customer, a.pitch, a.n, a.seed)
    elif dealing:
        raise JevError("%s already has a panel: drop %s (its cards are dealt already)" % (d, ", ".join(dealing)))
    st, cards = panel.load_state(d)
    _no_markets(st["customer"])
    s = _settings(a, st, steps)
    fp = fingerprint(cards, st, s)
    jpath, ad = panel._path(d, "jev.json"), panel._path(d, "jev-answers")
    rec = _load_record(jpath)
    if rec is not None and rec.get("fingerprint") != fp:
        old = rec.get("settings") if isinstance(rec.get("settings"), dict) else {}
        diff = [k for k in sorted(s) if k != "ladder_max" and old.get(k) != s[k]]
        raise JevError("the cards or settings changed since the last Jev run in %s (%s): use a new --dir, or delete"
                       " jev-answers/ and jev.json yourself" % (d, ", ".join(diff) or "the cards, pitch or target"))
    ids = set(c["id"] for c in cards)
    if os.path.isdir(ad):
        if rec is None:
            raise JevError("%s has jev-answers/ but no jev.json, so they cannot be checked: delete jev-answers/"
                           " yourself or use a new --dir" % d)
        extra = sorted(f for f in os.listdir(ad) if f.endswith(".json") and f[:-len(".json")] not in ids)
        if extra:
            raise JevError("jev-answers/ has files for cards that are not on this panel (%s): move them out or use a"
                           " new --dir" % ", ".join(extra[:10]))
    saved, bad = {}, []
    for c in cards:
        path = os.path.join(ad, c["id"] + ".json")
        if os.path.exists(path):
            prob, ans = check_saved(path, c, s, fp)
            if prob:
                bad.append("%s (%s)" % (c["id"], prob))
            else:
                saved[c["id"]] = ans
    if bad:
        raise JevError("these Jev answers are damaged or do not match this run: %s. Nothing was sent or overwritten:"
                       " fix or delete them yourself" % "; ".join(bad[:10]))
    todo = [c for c in cards if c["id"] not in saved]
    if todo and key is None:
        key = api_key()
        keys.append(key)

    # checks done: from here on jev.json is written
    if rec is None:
        rec = {"fingerprint": fp, "settings": s, "derived": None, "runs": [], "inflight": None}
    _recover(rec, saved, ids)
    this = {"started": _stamp(), "ended": None, "attempts": 0, "retries": 0, "timeouts": 0, "unknown": 0,
            "input_tokens": 0, "usd": 0.0, "stopped": None}
    rec["runs"].append(this)
    rec["derived"] = derived(list(saved.values()), len(cards))
    _save(jpath, rec)
    os.makedirs(ad, exist_ok=True)
    if not todo:
        print("every card already has a Jev answer: nothing to send.")
    else:
        print("About to send %d requests to %s, one per card: each carries one persona card and the pitch. The cost"
              " estimate prints after the first card, and the run stops before a request that would take it past %s"
              " (--budget-usd)." % (len(todo), HOST, _usd(a.budget_usd)))
        if saved:
            print("%d of %d cards already have a Jev answer and are not sent again." % (len(saved), len(cards)))
    t = connect(key) if todo else None
    if t is not None:
        def checkpoint(out):
            rec["inflight"] = cid if out else None  # set only while a request is out, or answered but not saved
            this.update(t.stats)
            _save(jpath, rec)
        t.checkpoint = checkpoint
    target, pitch, cur = st["customer"]["target"], st["pitch"], s["currency"]
    last = 0
    for c in cards:
        if c["id"] in saved:
            last = saved[c["id"]]["jev"]["input_tokens"]
    stopped = None
    try:
        for i, c in enumerate(todo):
            cid = c["id"]
            nxt = this["usd"] + last * USD_PER_TOKEN
            if nxt > a.budget_usd:
                stopped = ("budget: this run has cost about %s and the next card would take it to about %s, past"
                           " --budget-usd %s" % (_usd(this["usd"]), _usd(nxt), _usd(a.budget_usd)))
                break
            qs = questions(c, s)
            body = {"model": s["model"], "state": state(c, target, pitch, cur), "questions": qs}
            try:
                reply = t.post(body)
            except JevError as e:
                raise JevError("%s: %s" % (cid, e))
            tok = _tokens(reply)
            if tok is not None:
                this["input_tokens"] += tok
                this["usd"] = this["input_tokens"] * USD_PER_TOKEN
            prob = check_reply(reply, s["model"], qs)
            if prob:
                raise JevError("%s: the Jev reply is not valid (%s). Nothing was saved for this card" % (cid, prob))
            ans = convert(cid, reply, s, fp)
            _save_answer(os.path.join(ad, cid + ".json"), cid, ans)
            saved[cid], last = ans, tok
            rec["inflight"] = None
            rec["derived"] = derived(list(saved.values()), len(cards))
            this.update(t.stats)
            _save(jpath, rec)
            if i == 0:
                print("first card: %d input tokens, about %s. The other %d cards: about %s more, judged from this one."
                      % (tok, _usd(tok * USD_PER_TOKEN), len(todo) - 1, _usd((len(todo) - 1) * tok * USD_PER_TOKEN)))
    except JevError as e:
        rec["inflight"] = None
        this.update(t.stats, ended=_stamp(), stopped=_scrub(str(e), keys))
        _save(jpath, rec)
        print(_tried(this))
        raise
    except BaseException:
        # cut off (Ctrl-C) or failed in a way not foreseen: keep the counts, and inflight, for the next run
        this.update(t.stats, ended=_stamp(), stopped="interrupted")
        try:
            _save(jpath, rec)
        except Exception:
            pass  # the error already on its way out says more than this record could
        raise
    this.update(t.stats if t else {}, ended=_stamp(), stopped=stopped)
    _save(jpath, rec)
    if stopped:
        print("stopped at the %s. %d of %d cards are saved: run again to continue (a new run counts a new budget)."
              % (stopped, len(saved), len(cards)))
        print(_tried(this))
        return 1
    res, text = results(d, st, cards, saved, rec["settings"])
    _write_text(panel._path(d, "jev-results.md"), text)
    _save(panel._path(d, "jev-results.json"), res)
    print("%d cards: %d with a buy probability of %s or more, mean %.3f (an average of probabilities, not a share of"
          " buyers)." % (res["cards"], res["buys"], THRESHOLD, res["mean_p_buy"]))
    print(_tried(this))
    for k in res["raise_ladder_max"]:
        print(RAISE % k.replace("_", " "))
    print("Wrote %s" % panel._path(d, "jev-results.md"))
    return 0


# ── sweep ───────────────────────────────────────────────────────────────────────
def _read_pitch(path):
    """A pitch file's text, stripped as panel.py init strips it. JevError if it is missing, unreadable or empty."""
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read().strip()
    except FileNotFoundError:
        raise JevError("no such file: %s" % path)
    except (OSError, ValueError) as e:
        raise JevError("cannot read %s as text (%s)" % (path, e.__class__.__name__))
    if not text:
        raise JevError("%s is empty: write the pitch first" % path)
    return text


def _plain(x):
    return "%d" % x if x == int(x) else repr(x)  # 9900 in a folder name, not 9900.0; 6.5 as it is


def variants(a, currency):
    """[(name, price, pitch)]: each price of --prices in place of {price} in --pitch-template, or each file of
    --pitches at --price. A name is the variant's number and its price or file name: 01-p9900, 02-pitch-b."""
    if (a.prices is None) == (a.pitches is None):
        raise JevError("give --prices (with --pitch-template) or --pitches (with --price): one of the two")
    if a.prices is not None:
        if a.pitch_template is None or a.price is not None:
            raise JevError("--prices goes with --pitch-template and without --price: each price in the list is a variant")
        prices = _numbers(a.prices, "--prices")
        if not all(_finite(x) and x > 0 for x in prices):
            raise JevError("--prices must all be positive numbers (got %s)" % a.prices)
        if len(set(prices)) < len(prices):
            raise JevError("--prices has the same price twice (%s)" % a.prices)
        template = _read_pitch(a.pitch_template)
        if "{price}" not in template:
            raise JevError("%s has no {price} in it: write {price} where the price goes, with nothing around it (it"
                           " becomes the whole amount, such as %s)" % (a.pitch_template, money(prices[0], currency)))
        out = [("p" + _plain(x), x, template.replace("{price}", money(x, currency))) for x in prices]
        if any(not p or "{price}" in p for _, _, p in out):
            raise JevError("%s still has {price} in it once the price is in" % a.pitch_template)
    else:
        if a.price is None or a.pitch_template is not None:
            raise JevError("--pitches goes with --price and without --pitch-template: each file is a variant at that price")
        out = [(os.path.splitext(os.path.basename(p))[0], a.price, _read_pitch(p))
               for p in (x.strip() for x in a.pitches.split(","))]
    return [(VARIANT % (i, label), x, p) for i, (label, x, p) in enumerate(out, 1)]


def _runs(a, st, cards, vs, base, steps):
    """Every run of the sweep in the order they go: the baseline, the other variants, then the baseline again.

    Each carries its folder, the panel.json that folder needs (the snapshot with its pitch), the arguments run() gets,
    and the settings and fingerprint its answers must have. A repeat asks exactly what the baseline asks, so it has
    the same ones."""
    ladder_text = ",".join(repr(x) for x in steps)  # repr() reads back as the same float
    first = [v for v in vs if v[0] == base][0]
    order = [(n, 1, x, p) for n, x, p in [first] + [v for v in vs if v[0] != base]]
    order += [(base, k, first[1], first[2]) for k in range(2, a.repeat + 1)]
    runs = []
    for variant, k, price, pitch in order:
        name = variant if k == 1 else REPEAT % (variant, k)
        want = dict(st, pitch=pitch)
        args = argparse.Namespace(dir=panel._path(a.dir, SWEEPS, name), price=price, paid=a.paid, unit=a.unit,
                                  customer=None, pitch=None, n=None, seed=None, model=a.model, ladder_max=a.ladder_max,
                                  ladder=ladder_text, budget_usd=None)
        s = _settings(args, want, steps)
        runs.append({"name": name, "variant": variant, "run": k, "price": price, "pitch": pitch, "folder": args.dir,
                     "want": want, "args": args, "settings": s, "fingerprint": fingerprint(cards, want, s),
                     "status": None, "message": None, "new": False, "saved": 0, "cost": _cost([])})
    return runs


def _look(runs, people, cards, keys):
    """Read every run's folder and write nothing: still to make, made from this snapshot before (its saved answers
    counted), or left alone with the status "mismatch", or "error" for a folder half made or that cannot be read."""
    for r in runs:
        vd = r["folder"]
        try:
            if folder_state(vd) == "new":
                r["new"] = True
                continue
            with open(panel._path(vd, "personas.json"), "rb") as fh:
                same = fh.read() == people
            try:
                same = same and panel._read_json(panel._path(vd, "panel.json")) == r["want"]
            except ValueError:
                same = False
            if not same:
                r["status"], r["message"] = "mismatch", ("%s holds other cards, another pitch or another panel.json"
                                                          " than this sweep's: it is left as it is. Move it away to run"
                                                          " this variant" % vd)
                continue
            ad = panel._path(vd, "jev-answers")
            r["saved"] = sum(1 for c in cards if os.path.isfile(os.path.join(ad, c["id"] + ".json")))
        except Exception as e:  # this folder's error alone: the other runs go on
            r["status"], r["message"] = "error", _why(e, keys)


def _notice(a, d, cards, runs, steps, cur, base, nv):
    """What the sweep is about to send, printed before it sends anything. Returns how many requests it plans."""
    going = [r for r in runs if r["status"] is None]
    saved, held = sum(r["saved"] for r in going), len(runs) - len(going)
    todo = len(cards) * len(going) - saved
    print("Sweep in %s: %d variants by %s, %d cards each. The baseline %s runs %d %s: %d runs in all." % (
        d, nv, "price" if a.prices is not None else "pitch", len(cards), base, a.repeat,
        "time" if a.repeat == 1 else "times", len(runs)))
    print("Requests to send: %d (%d cards x %d runs = %d, less %d answers already saved%s). Each one goes to %s with"
          " one persona card and its variant's pitch." % (
              todo, len(cards), len(runs), len(cards) * len(runs), saved,
              (", less %d for the runs that will not run" % (len(cards) * held)) if held else "", HOST))
    print('The same in every variant: paid "%s", unit "%s", currency %s, model %s, and this price ladder: %s.' % (
        a.paid.strip(), a.unit.strip(), cur, a.model, ", ".join(money(x, cur) for x in steps)))
    print("Budget for the whole sweep: %s (--budget-usd), an estimate from token counts, not a cap on the bill."
          % _usd(a.budget_usd))
    for r in runs:
        head = "  %s%s, %s" % (r["name"], " (baseline)" if r["name"] == base else "", money(r["price"], cur))
        if r["saved"]:
            head += " (%d of %d answers saved)" % (r["saved"], len(cards))
        if r["status"]:
            print("%s: will not run (%s): %s" % (head, r["status"], r["message"]))
        elif r["run"] > 1:
            print("%s: the baseline again, the same requests" % head)
        else:
            print("%s: %s" % (head, " ".join(r["pitch"][:200].split())))
    return todo


def _history(path):
    """The run history in a jev.json: [] when there is none, or none that can be read (run() says why)."""
    try:
        rec = _load_record(path)
    except JevError:
        return []
    return [h for h in rec["runs"] if isinstance(h, dict)] if rec else []


def _cost(history):
    """Requests, retries, timeouts, unknown outcomes, tokens and confirmed dollars over these run-history entries."""
    out = {"attempts": 0, "retries": 0, "timeouts": 0, "unknown": 0, "input_tokens": 0, "usd": 0.0}
    for h in history:
        for k in out:
            if _finite(h.get(k)):
                out[k] += h[k]
    return out


def _why(e, keys):
    """A run that failed, in one line with the key taken out, as main() would print it."""
    text = str(e) if isinstance(e, (JevError, panel.PanelError, vw.PricingError)) else "%s: %s" % (
        e.__class__.__name__, e)
    return " ".join(_scrub(text, keys).split())


def _finished(r, cards):
    """A finished run's answers by card id, read again and checked as a resumed run checks them: (answers, problems)."""
    got, bad = {}, []
    for c in cards:
        path = os.path.join(r["folder"], "jev-answers", c["id"] + ".json")
        try:
            prob, a = check_saved(path, c, r["settings"], r["fingerprint"]) if os.path.isfile(path) else ("missing",
                                                                                                           None)
        except OSError as e:
            prob, a = "cannot be read (%s)" % e.__class__.__name__, None
        if prob:
            bad.append("%s (%s)" % (c["id"], prob))
        else:
            got[c["id"]] = a
    return got, bad


def _mean_p(rows):
    return sum(x["jev"]["p_buy"] for x in rows) / len(rows)


def _summary(got, cards, cur):
    """A finished variant's numbers: buys, mean probability, the price points on the shared ladder, the price flags
    added up over the four curves (and kept curve by curve), and what weighs most. All of them from the checked
    answers: the folder is not read again, so a file put there after the run counts nowhere."""
    rows = [got[c["id"]] for c in cards]
    f = flag_counts(rows)
    n = dict((k, sum(1 for x in rows if x["reason_code"] == k)) for k in panel.REASONS)
    top = sorted((k for k in panel.REASONS if n[k]), key=lambda k: -n[k])[:2]
    out = {"cards": len(rows), "buys": sum(1 for x in rows if x["buys"]), "mean_p_buy": _mean_p(rows),
           "ipp": None, "pme": None, "price_note": None,
           "censored_low": sum(v["low"] for v in f["censored"].values()),
           "censored_high": sum(v["high"] for v in f["censored"].values()), "clamped": f["clamped"],
           "nonmonotone": sum(f["nonmonotone"].values()), "multi_cross": sum(f["multi_cross"].values()),
           "flags": f, "top_reasons": [[k, n[k]] for k in top]}
    # check_saved made all four from the ladder, in order: every checked answer is a complete price answer
    complete = [tuple(float(x["price_" + k]) for k in vw.KEYS) for x in rows]
    if len(complete) < 5:
        out["price_note"] = "few"
    else:
        try:
            points = vw.analyse(complete, currency=cur)["points"]
            out["ipp"], out["pme"] = points["IPP"], points["PME"]
        except vw.PricingError:
            out["price_note"] = "failed"
    return out


def _pair(cards, base, other):
    """Two runs on the same cards, card by card: dp is p(other) minus p(base) for each card id."""
    dp = [(c["id"], other[c["id"]]["jev"]["p_buy"] - base[c["id"]]["jev"]["p_buy"]) for c in cards]
    vals, half = sorted(v for _, v in dp), len(dp) // 2
    top = max(dp, key=lambda t: abs(t[1]))  # of two cards as far apart, the first
    return {"delta_mean": _mean_p([other[c["id"]] for c in cards]) - _mean_p([base[c["id"]] for c in cards]),
            "median_dp": vals[half] if len(vals) % 2 else (vals[half - 1] + vals[half]) / 2.0,
            "max_dp": top[1], "max_dp_card": top[0], "mean_abs_dp": sum(abs(v) for _, v in dp) / len(dp),
            "flipped_to_buy": sum(1 for c in cards if other[c["id"]]["buys"] and not base[c["id"]]["buys"]),
            "flipped_to_pass": sum(1 for c in cards if base[c["id"]]["buys"] and not other[c["id"]]["buys"])}


def compare(a, d, st, cards, vs, runs, base, steps, cur, keys):
    """jev-sweep.json: the settings, every run with its status and cost, and the comparison. Only the runs done in
    this sweep are compared, their answers read again."""
    done = {}
    for r in runs:
        if r["status"] == "done":
            got, bad = _finished(r, cards)
            if bad:
                r["status"], r["message"] = "error", ("its answers changed after the run and fail the check: %s. Fix or"
                                                       " delete them, then run the sweep again" % "; ".join(bad[:10]))
            else:
                done[r["name"]] = got
    first = dict((r["variant"], r) for r in runs if r["run"] == 1)
    rows = []
    for name, price, _ in vs:
        row = {"name": name, "price": price, "status": first[name]["status"], "baseline": name == base}
        if name in done:
            row.update(_summary(done[name], cards, cur))
            if name != base and base in done:
                row.update(_pair(cards, done[base], done[name]))
        rows.append(row)
    rep = {"runs": [], "pairs": [], "note": None}
    for r in runs:
        if r["variant"] == base:
            e = {"name": r["name"], "status": r["status"]}
            if r["name"] in done:
                got = [done[r["name"]][c["id"]] for c in cards]
                e.update(buys=sum(1 for x in got if x["buys"]), mean_p_buy=_mean_p(got))
            rep["runs"].append(e)
    fin = [e["name"] for e in rep["runs"] if e["name"] in done]
    if a.repeat < 2:
        rep["note"] = "No repeat data: the baseline ran once (--repeat 1)."
    elif len(fin) < 2:
        rep["note"] = "No repeat data: fewer than two runs of the baseline finished in this sweep."
    else:
        for x, y in itertools.combinations(fin, 2):
            p = _pair(cards, done[x], done[y])
            rep["pairs"].append({"runs": [x, y], "mean_abs_dp": p["mean_abs_dp"],
                                 "flipped": p["flipped_to_buy"] + p["flipped_to_pass"], "shift": abs(p["delta_mean"])})
        rep["n_pairs"] = len(rep["pairs"])
        for k in ("mean_abs_dp", "flipped", "shift"):
            rep[k] = sum(q[k] for q in rep["pairs"]) / float(rep["n_pairs"])
    agree = {}
    for name, _, pitch in vs:
        ag = agreement(d, cards, done[name]) if name in done and pitch == st["pitch"] else None
        if ag:
            agree[name] = ag
    return {
        "business": st["customer"]["business"], "model": a.model, "threshold": THRESHOLD, "cards": len(cards),
        "settings": {"axis": "prices" if a.prices is not None else "pitches",
                     "values": [x for _, x, _ in vs] if a.prices is not None else [
                         x.strip() for x in a.pitches.split(",")],
                     "pitch_template": a.pitch_template, "baseline": base, "repeat": a.repeat, "ladder": steps,
                     "ladder_max": a.ladder_max, "model": a.model, "paid": a.paid.strip(), "unit": a.unit.strip(),
                     "currency": cur, "budget_usd": a.budget_usd,
                     "pitch_sha256": dict((n, hashlib.sha256(p.encode("utf-8")).hexdigest()) for n, _, p in vs)},
        "runs": [dict(r["cost"], name=r["name"], variant=r["variant"], run=r["run"], folder=r["folder"],
                      price=r["price"], status=r["status"], message=_scrub(r["message"], keys) if r["message"] else None)
                 for r in runs],
        "totals": _cost([r["cost"] for r in runs]),
        "variants": rows, "repeats": rep, "agreement": agree,
    }


def _signed(v):
    return "%+.3f" % (round(v, 3) + 0.0)  # a change that rounds to nothing is +0.000, not -0.000


def sweep_md(res):
    s = res["settings"]
    cur, base = s["currency"], s["baseline"]
    m = lambda v: "n/a" if v is None else money(v, cur)
    L = ["# Jev sweep: %s" % res["business"], ""]
    L.append("%d variants by %s on the same %d cards, each compared card by card with the baseline, %s. The questions"
             " and the price ladder are the same in every variant: only the pitch changes, and in a price sweep the"
             " price in the buy question with it. Jev (%s) gives each card a buy probability; a card counts as a buyer"
             " at %s or more." % (len(res["variants"]), {"prices": "price", "pitches": "pitch"}[s["axis"]],
                                  res["cards"], base, res["model"], res["threshold"]))
    L += ["", READ_RULE % len(res["variants"])]
    L += ["", "## Variants", "",
          "| variant | price | status | buy | mean | change in mean | flipped to buy | flipped to pass | IPP | PME |"
          " censored low | censored high | clamped | not monotone | crosses 0.5 twice | weighs most |",
          "| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |"]
    for v in res["variants"]:
        cells = [_cell(v["name"] + (" (baseline)" if v["baseline"] else "")), m(v["price"]), v["status"]]
        if "buys" in v:
            change = ["", "", ""]
            if "delta_mean" in v:
                change = [_signed(v["delta_mean"]), str(v["flipped_to_buy"]), str(v["flipped_to_pass"])]
            cells += ["%d" % v["buys"], "%.3f" % v["mean_p_buy"]] + change
            cells += [m(v["ipp"]), m(v["pme"])] if v["price_note"] is None else [v["price_note"]] * 2
            cells += [str(v[k]) for k in ("censored_low", "censored_high", "clamped", "nonmonotone", "multi_cross")]
            cells.append(", ".join("%s %d" % (k, n) for k, n in v["top_reasons"]))
        else:
            cells += [""] * 13
        L.append("| %s |" % " | ".join(cells))
    L += ["", "Mean is the average buy probability over the cards, not a share of buyers. The change in mean and the"
          " flips are against the baseline: a flipped card is on the other side of 0.5. IPP and PME come from the"
          " variant's own price answers on the shared ladder, an exploratory estimate as in jev-results.md (\"few\":"
          " under 5 complete price answers; \"failed\": the price tool found no curve). The censoring, clamping and"
          " other flag counts add up the four price curves; jev-sweep.json has them curve by curve."]
    L += ["", "## Card by card against the baseline", ""]
    others = [v for v in res["variants"] if "delta_mean" in v]
    if others:
        L += ["dp is a card's buy probability in the variant minus the same card's in the baseline.", "",
              "| variant | median dp | largest dp | on card |", "| --- | ---: | ---: | --- |"]
        for v in others:
            L.append("| %s | %s | %s | %s |" % (_cell(v["name"]), _signed(v["median_dp"]), _signed(v["max_dp"]),
                                                v["max_dp_card"]))
    elif not any("buys" in v for v in res["variants"] if v["baseline"]):
        L.append("The baseline did not finish in this sweep, so there is nothing to compare with.")
    else:
        L.append("No other variant finished in this sweep.")
    rep = res["repeats"]
    L += ["", "## The baseline, run again", "",
          "The same requests sent again: how far these runs are apart is Jev's own run-to-run wobble, not the offer.",
          "", "| run | status | buy | mean |", "| --- | --- | ---: | ---: |"]
    for e in rep["runs"]:
        L.append("| %s | %s | %s | %s |" % (_cell(e["name"]), e["status"], e.get("buys", ""),
                                            ("%.3f" % e["mean_p_buy"]) if "mean_p_buy" in e else ""))
    L.append("")
    if rep["note"]:
        L.append(rep["note"])
    else:
        L.append("%s: mean absolute dp per card %.3f, cards flipped %.1f, shift in mean %.3f." % (
            "One pair of runs" if rep["n_pairs"] == 1 else "Averaged over %d pairs of runs" % rep["n_pairs"],
            rep["mean_abs_dp"], rep["flipped"], rep["shift"]))
        if rep["n_pairs"] > 1:
            L.append("")
            for q in rep["pairs"]:
                L.append("- %s and %s: mean absolute dp %.3f, %d flipped, shift %.3f" % (
                    q["runs"][0], q["runs"][1], q["mean_abs_dp"], q["flipped"], q["shift"]))
    if res["agreement"]:
        L += ["", "## Agent panel and Jev, card by card", "",
              "Only for a variant whose pitch is the panel's own, the same text as in panel.json. The agent answers carry"
              " no fingerprint, so \"the same pitch\" is a comparison of the text and nothing more."]
        for name, ag in sorted(res["agreement"].items()):
            L += ["", "### %s: %d cards have both answers" % (name, ag["n"]), "",
                  "| | Jev: buy | Jev: pass |", "| --- | ---: | ---: |",
                  "| agent: buy | %d | %d |" % (ag["both"], ag["agent_only"]),
                  "| agent: pass | %d | %d |" % (ag["jev_only"], ag["neither"])]
    L += ["", "## Runs", "",
          "| run | folder | status | requests | retries | timeouts | unknown outcome | confirmed cost |",
          "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |"]
    t = res["totals"]
    for r in res["runs"] + [dict(t, name="all", status="", folder=None)]:
        L.append("| %s | %s | %s | %d | %d | %d | %d | %s |" % (
            _cell(r["name"]), _cell(os.path.join(SWEEPS, r["name"])) if r["folder"] else "", r["status"],
            r["attempts"], r["retries"], r["timeouts"], r["unknown"], _usd(r["usd"])))
    notes = [r for r in res["runs"] if r["message"]]
    if notes:
        L += [""] + ["- %s (%s): %s" % (r["name"], r["status"], r["message"]) for r in notes]
    L += ["", "The cost is an estimate from the tokens Jev reported, not the bill. A request with an unknown outcome may"
          " have been billed and is not in it."]
    return "\n".join(L) + "\n"


def _sweep(a, d, st, people, cards, vs, runs, base, steps, cur, connect, keys):
    """The sweep from its notice on, inside the lock: make the folders, run each run in turn, compare, write."""
    _look(runs, people, cards, keys)
    planned = _notice(a, d, cards, runs, steps, cur, base, len(vs))
    for r in runs:
        if r["new"]:
            try:
                os.makedirs(r["folder"], exist_ok=True)
                _write_bytes(panel._path(r["folder"], "personas.json"), people)
                _save(panel._path(r["folder"], "panel.json"), r["want"])
            except Exception as e:  # this folder cannot be made: its error alone
                r["status"], r["message"] = "error", _why(e, keys)
    last, got = [], [0]  # the input tokens of the sweep's latest reply, and of all the replies of the run going now

    def connect_and_tell(key):
        t = (connect or Transport)(key)
        post = t.post

        def post_and_tell(body):
            reply = post(body)
            tok = _tokens(reply)
            if tok is not None:
                if not last:
                    left = max(planned - 1, 0)
                    print("first request of the sweep: %d input tokens. The other %d planned: about %s more, judged"
                          " from this one." % (tok, left, _usd(left * tok * USD_PER_TOKEN)))
                last[:] = [tok]
                got[0] += tok
            return reply
        t.post = post_and_tell  # the replies of every run: the first gives the estimate, the latest the next card's
        return t

    stop = False
    for k, r in enumerate(runs, 1):
        if r["status"]:
            continue
        left = a.budget_usd - sum(x["cost"]["usd"] for x in runs)
        # a run judges its first card from its own saved cards only: the sweep judges it from the latest reply
        nxt = last[0] * USD_PER_TOKEN if last and r["saved"] < len(cards) else 0.0
        if stop or left <= 0 or nxt > left:
            r["status"], stop = "skipped", True
            continue
        print("\n[%d/%d] %s, %s" % (k, len(runs), r["name"], money(r["price"], cur)))
        jpath = panel._path(r["folder"], "jev.json")
        got[0], before, after = 0, None, None
        r["args"].budget_usd = left
        try:  # one run failing, or its record, does not stop the others
            before = _cost(_history(jpath))
            code = run(r["args"], connect_and_tell, keys)
            r["status"] = "done" if code == 0 else "budget"
        except Exception as e:
            r["status"], r["message"] = "error", _why(e, keys)
        try:
            after = _cost(_history(jpath))
        except Exception as e:
            if r["status"] != "error":
                r["status"], r["message"] = "error", _why(e, keys)
        if r["status"] == "error":
            print("%s: error: %s" % (r["name"], r["message"]))
        # what the history gained, not only the new entry: a request cut off earlier is counted now, on the entry before
        cost = dict((f, after[f] - before[f]) for f in after) if before and after else _cost([])
        # and no less than this run's replies: a record that could not be saved keeps none of their cost
        cost["input_tokens"] = max(cost["input_tokens"], got[0])
        cost["usd"] = max(cost["usd"], got[0] * USD_PER_TOKEN)
        r["cost"] = cost
        if r["status"] == "budget":
            stop = True
    res = compare(a, d, st, cards, vs, runs, base, steps, cur, keys)
    _write_text(panel._path(d, "jev-sweep.md"), sweep_md(res))
    _save(panel._path(d, "jev-sweep.json"), res)
    print("")
    for r in res["runs"]:
        print("%s: %s%s" % (r["name"], r["status"], (": %s" % r["message"]) if r["message"] else ""))
    print(_tried(res["totals"], "This sweep, every run"))
    print("Wrote %s" % panel._path(d, "jev-sweep.md"))
    seen = set(r["status"] for r in runs)
    return 2 if seen & {"error", "mismatch"} else 1 if seen & {"budget", "skipped"} else 0


def sweep(a, connect=None, keys=None):
    """The sweep command: run() once per variant on the same cards, one after another, then the comparison.

    keys goes on to every run(), so a key one of them read is taken out of anything the sweep prints or writes."""
    keys = [] if keys is None else keys
    d = a.dir
    if a.repeat < 1:
        raise JevError("--repeat must be 1 or more: how many times the baseline runs")
    if not _finite(a.budget_usd) or a.budget_usd <= 0:
        raise JevError("--budget-usd must be a positive number of dollars")
    if not a.paid.strip() or not a.unit.strip():
        raise JevError('--paid and --unit need words, such as --paid "the monthly plan" --unit "per month"')
    if folder_state(d) == "new":
        raise JevError("%s has no panel: sweep sends cards that are dealt already (panel.py init, or jev.py run with"
                       " --customer, --pitch and --n)" % d)
    # the snapshot, read once: every variant folder is made from these
    with open(panel._path(d, "personas.json"), "rb") as fh:
        people = fh.read()
    try:
        st, cards = panel._read_json(panel._path(d, "panel.json")), json.loads(people.decode("utf-8"))
    except ValueError as e:
        raise JevError("the panel in %s is not valid JSON (%s)" % (d, e))
    _no_markets(st["customer"])
    cur = st["customer"].get("currency", "USD").upper()
    vs = variants(a, cur)
    names = [v[0] for v in vs]
    base = names[0] if a.baseline is None else a.baseline
    if base not in names:
        raise JevError("--baseline %s is not a variant of this sweep: give one of %s" % (base, ", ".join(names)))
    steps = ladder(vs[names.index(base)][1], a.ladder_max)
    out = [money(x, cur) for _, x, _ in vs if not steps[0] <= x <= steps[-1]]
    if out:
        raise JevError("every variant is asked about the baseline's price ladder, %s to %s, and %s is outside it: choose"
                       " another --baseline or --ladder-max" % (money(steps[0], cur), money(steps[-1], cur),
                                                               ", ".join(out)))
    runs = _runs(a, st, cards, vs, base, steps)
    folders = [r["folder"] for r in runs]
    twice = sorted(set(f for f in folders if folders.count(f) > 1))
    if twice:
        raise JevError("two runs of this sweep would share a folder (%s): rename a pitch file" % ", ".join(twice))
    lock = panel._path(d, LOCK)
    if a.dry_run:
        if os.path.exists(lock):
            raise JevError(LOCKED % lock)
        _look(runs, people, cards, keys)
        _notice(a, d, cards, runs, steps, cur, base, len(vs))
        print("Dry run: nothing was sent, and no folder or lock file was made. To send, run the same command without"
              " --dry-run.")
        return 0
    mine = "started %s by process %d\n" % (_stamp(), os.getpid())  # made first: nothing stands between lock and try
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        raise JevError(LOCKED % lock)
    try:
        try:
            fh = os.fdopen(fd, "w", encoding="utf-8")
        except BaseException:
            os.close(fd)  # no file object took it over
            raise
        with fh:
            fh.write(mine)
        return _sweep(a, d, st, people, cards, vs, runs, base, steps, cur, connect, keys)
    finally:
        try:
            with open(lock, encoding="utf-8") as fh:
                # all of ours, or the part written before a stop. Deleted by hand and taken by another sweep: not ours
                ours = mine.startswith(fh.read())
            if ours:
                os.remove(lock)
        except OSError:
            pass  # gone already: nothing to tidy


def main(argv=None, connect=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="send the panel's cards to Jev (network, costs money)")
    r.add_argument("--dir", required=True, help="the panel folder, or a new folder to deal cards into")
    r.add_argument("--price", type=float, required=True, help="the price in the pitch, in the panel's currency")
    r.add_argument("--paid", required=True, help='what they would pay for, in English: "the monthly plan"')
    r.add_argument("--unit", required=True, help='what the price is for, in English: "per month", "per cup"')
    r.add_argument("--customer", help="customer.json, to deal a new panel into --dir")
    r.add_argument("--pitch", help="pitch.md, to deal a new panel into --dir")
    r.add_argument("--n", type=int, help="how many cards to deal into a new --dir")
    r.add_argument("--seed", type=int, help="the seed for a new --dir (default: random, and recorded)")
    r.add_argument("--model", default=MODEL, help="a pinned Jev model (default %s)" % MODEL)
    r.add_argument("--ladder-max", type=float, default=5.0, help="the top of the price ladder, times --price (above 3.3)")
    r.add_argument("--ladder", help="the 12 ladder prices, comma-separated and rising, in place of --price times the"
                                    " steps (--ladder-max is not used then). Sweep gives every variant the baseline's"
                                    " ladder this way")
    r.add_argument("--budget-usd", type=float, default=1.0,
                   help="stop before a request that would take this run's estimated cost past it (not a cap on the bill)")
    w = sub.add_parser("sweep", help="the same cards under several prices or pitches, one run after another (network,"
                                     " costs money)")
    w.add_argument("--dir", required=True, help="the panel folder, its cards dealt already")
    w.add_argument("--prices", help="the prices to try, comma-separated: 9900,12900,14900 (with --pitch-template)")
    w.add_argument("--pitch-template", help="the pitch with {price} where the price goes: {price} becomes 9,900원 or $6.50")
    w.add_argument("--pitches", help="the pitch files to try, comma-separated (with --price)")
    w.add_argument("--price", type=float, help="the price in every file of --pitches, in the panel's currency")
    w.add_argument("--paid", required=True, help='what they would pay for, in English: "the monthly plan"')
    w.add_argument("--unit", required=True, help='what the price is for, in English: "per month", "per cup"')
    w.add_argument("--baseline", help="the variant the others are compared with, by its name such as 02-p12900"
                                      " (default: the first)")
    w.add_argument("--repeat", type=int, default=2, help="how many times the baseline runs, to show how far two runs of"
                                                         " the same requests are apart (default 2)")
    w.add_argument("--model", default=MODEL, help="a pinned Jev model (default %s)" % MODEL)
    w.add_argument("--ladder-max", type=float, default=5.0, help="the top of the price ladder, times the baseline's price"
                                                                 " (above 3.3)")
    w.add_argument("--budget-usd", type=float, default=1.0,
                   help="stop before a request that would take the whole sweep's estimated cost past it (not a cap on"
                        " the bill)")
    w.add_argument("--dry-run", action="store_true", help="print what would be sent and stop: no key, no folders, no"
                                                          " requests")
    a = ap.parse_args(argv)
    keys = []
    line = lambda text: " ".join(_scrub(text, keys).split())
    try:
        return (sweep if a.cmd == "sweep" else run)(a, connect, keys)
    except (JevError, panel.PanelError, vw.PricingError) as e:
        print("error: %s" % line(str(e)), file=sys.stderr)
        return 2
    except Exception as e:  # the last net: one line with the key taken out, never a traceback
        print("error: %s: %s" % (e.__class__.__name__, line(str(e))), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
