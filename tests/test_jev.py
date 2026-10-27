import collections
import email.utils
import http.client
import io
import json
import math
import os
import shutil
import socket
import tempfile
import unittest
import urllib.error
import urllib.request
import urllib.response
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from _load import load, example

jev = load("founder-consumer", "jev")
panel = jev.panel
plan = load("founder-plan", "compile")

FAKE_KEY = "tsk-fake-0b7c1e9a4d2f6058"  # made up for these tests, never a real key
MODEL = "jev-1.14.0"
NOW = 1793000000.0
# five-level probabilities at the twelve ladder prices: Jev's real reply for exp2-v2 P001 (eleven prices), plus a twelfth
PRICE_ROWS = [
    [0.17, 0.72, 0.10, 0.01, 0.00], [0.15, 0.64, 0.19, 0.02, 0.00], [0.13, 0.63, 0.22, 0.02, 0.00],
    [0.08, 0.50, 0.39, 0.03, 0.00], [0.03, 0.25, 0.64, 0.07, 0.01], [0.01, 0.10, 0.72, 0.16, 0.01],
    [0.00, 0.07, 0.32, 0.59, 0.02], [0.01, 0.05, 0.18, 0.70, 0.06], [0.01, 0.04, 0.09, 0.68, 0.18],
    [0.01, 0.05, 0.05, 0.58, 0.31], [0.02, 0.04, 0.03, 0.55, 0.36], [0.01, 0.02, 0.02, 0.40, 0.55],
]
P001_REASONS = {"timing": 0.0, "quality": 0.07, "price": 0.01, "habit": 0.34, "trust": 0.55, "convenience": 0.01,
                "need": 0.01, "other": 0.0, "values": 0.01}
# the 6,500 won ladder, by hand: 1,300 1,950 2,925 3,900 5,200 8,125 10,400 13,000 16,250 21,450 32,500 to two figures,
# and 6,500 itself at the 1.0 step
LADDER_6500 = [1300.0, 2000.0, 2900.0, 3900.0, 5200.0, 6500.0, 8100.0, 10000.0, 13000.0, 16000.0, 21000.0, 33000.0]
COST = 2443 * 0.042 / 1000000  # one card of the example reply
Run = collections.namedtuple("Run", "code fake out err")
_env = {}


def setUpModule():
    # nothing in this file can reach a real key: HOME is an empty folder and TYPESAFE_API_KEY is unset
    _env.update(home=tempfile.mkdtemp(), saved=dict((k, os.environ.get(k)) for k in ("HOME", jev.KEY_ENV)))
    os.environ["HOME"] = _env["home"]
    os.environ.pop(jev.KEY_ENV, None)


def tearDownModule():
    for k, v in _env["saved"].items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    shutil.rmtree(_env["home"])


class Crash(BaseException):
    """The process stopping at that point. jev.py's last handler still runs; crash_on_replace makes its write fail too."""


def reply_for(body, p=0.38, reason="trust", model=MODEL, tokens=2443, rows=PRICE_ROWS):
    """A reply in the shape Jev returned for exp2-v2 P001, for the questions in this request."""
    answers, k = {}, 0
    for qid, q in body["questions"].items():
        if q["type"] == "noul":
            answers[qid] = {"type": "noul", "noul": p}
        elif q["type"] == "choice":
            probs = dict(P001_REASONS)
            probs[reason], probs["trust"] = probs["trust"], probs[reason]
            answers[qid] = {"type": "choice", "choice": reason, "confidence": 0.49,
                            "probabilities": dict((c, probs[c]) for c in q["criteria"])}
        else:
            row = rows[k]
            k += 1
            answers[qid] = {"type": "score", "score": round(sum(i * v for i, v in enumerate(row)), 2),
                            "confidence": 0.6, "legend": dict((str(i), t) for i, t in enumerate(q["criteria"])),
                            "probabilities": dict((str(i), v) for i, v in enumerate(row))}
    return {"model": model, "answers": answers, "usage": {"input_tokens": tokens, "output_tokens": 365}}


def respond(req, code, headers, text):
    msg = http.client.HTTPMessage()
    for k, v in headers.items():
        msg[k] = v
    r = urllib.response.addinfourl(io.BytesIO(text.encode("utf-8")), msg, req.full_url, code)
    r.msg = http.client.responses.get(code, "")
    return r


class FakeJev(urllib.request.HTTPSHandler):
    """Stands in for api.typesafe.ai at the opener's https boundary. It records every request and opens no socket.

    script: one action per request, then the default reply. An action is None (the default reply), an exception to
    raise, or (status, headers, body)."""

    def __init__(self, script=(), reply=reply_for):
        urllib.request.HTTPSHandler.__init__(self)
        self.script, self.reply, self.calls = list(script), reply, []

    def https_open(self, req):
        body = json.loads(req.data.decode("utf-8")) if req.data else None
        self.calls.append({"url": req.full_url, "headers": dict(req.header_items()), "body": body})
        act = self.script.pop(0) if self.script else None
        if isinstance(act, BaseException):
            raise act
        if act is None:
            return respond(req, 200, {}, json.dumps(self.reply(body)))
        return respond(req, *act)

    def names(self):
        return [c["body"]["state"]["who_decides"]["name"] for c in self.calls]


def rows(p0, c1, e, t):
    """Five-level rows whose curves are these: P(too cheap), P(too cheap or a bargain), P(expensive or worse), P(too expensive)."""
    return [[round(v, 10) for v in (a, b - a, 1 - b - c, c - d, d)] for a, b, c, d in zip(p0, c1, e, t)]


def files_under(d):
    for base, _, files in os.walk(d):
        for f in files:
            yield os.path.join(base, f)


def snapshot(d, names):
    out = {}
    for n in names:
        p = os.path.join(d, n)
        for f in ([os.path.join(p, x) for x in sorted(os.listdir(p))] if os.path.isdir(p) else [p]):
            with open(f, "rb") as fh:
                out[f] = fh.read()
    return out


class Base(unittest.TestCase):
    customer = "customer.kr.example.json"
    pitch = "pitch.kr.example.md"
    n = 10

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.d = os.path.join(self.root, "panel")
        panel.init(self.d, example("founder-consumer", self.customer), example("founder-consumer", self.pitch),
                   n=self.n, seed=7)
        self.cards = panel.load_state(self.d)[1]
        self.p = {}  # buy probability by card id; 0.38 when not set
        self.slept = []
        env = mock.patch.dict(os.environ, {jev.KEY_ENV: FAKE_KEY})
        env.start()
        self.addCleanup(env.stop)

    def tearDown(self):
        shutil.rmtree(self.root)

    def fake(self, *script, **kw):
        names = dict((c["name"], c["id"]) for c in self.cards)
        make = kw.get("reply") or (lambda body: reply_for(body, p=self.p.get(names.get(body["state"]["who_decides"]["name"]), 0.38)))
        return FakeJev(script, reply=make)

    def connector(self, fake, opener=None, sleep=None):
        def connect(key):
            return jev.Transport(key, opener=opener or jev.make_opener(urllib.request.ProxyHandler({}), fake),
                                 sleep=sleep or self.slept.append, now=lambda: NOW, jitter=lambda: 0.5)
        return connect

    def run_jev(self, *args, **kw):
        fake = kw.get("fake") or self.fake()
        argv = ["run", "--dir", kw.get("d", self.d), "--price", kw.get("price", "6500"), "--paid", "a matcha latte",
                "--unit", "per cup"] + list(args)
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = jev.main(argv, connect=self.connector(fake, kw.get("opener"), kw.get("sleep")))
        return Run(code, fake, out.getvalue(), err.getvalue())

    def record(self, d=None):
        with open(os.path.join(d or self.d, "jev.json"), encoding="utf-8") as fh:
            return json.load(fh)

    def answer(self, cid, d=None):
        with open(os.path.join(d or self.d, "jev-answers", cid + ".json"), encoding="utf-8") as fh:
            return json.load(fh)

    def agent(self, cid, buys, reason="x", d=None):
        with open(os.path.join(d or self.d, "answers", cid + ".json"), "w", encoding="utf-8") as fh:
            json.dump({"id": cid, "buys": buys, "reason_code": "price", "reason": reason}, fh)

    def no_tmp(self, d=None):
        self.assertEqual([f for f in files_under(d or self.d) if f.endswith(".tmp")], [])

    def ids(self, run):
        by_name = dict((c["name"], c["id"]) for c in self.cards)
        return [by_name[n] for n in run.fake.names()]


# ── 1. conversion and the price output ───────────────────────────────────────────
class Convert(unittest.TestCase):
    def test_interpolates_between_two_ladder_prices(self):
        x, side = jev.crossing([6900, 9900, 12900, 15900], [0.7, 0.6, 0.4, 0.2], True)
        self.assertAlmostEqual(x, 11400, places=6)  # 0.6 at 9,900 and 0.4 at 12,900: halfway
        self.assertIsNone(side)

    def test_exactly_half_counts_as_reached(self):
        self.assertEqual(jev.crossing([100, 200, 300], [0.7, 0.5, 0.3], True), (200, None))
        self.assertEqual(jev.crossing([100, 200, 300], [0.2, 0.5, 0.9], False), (200, None))
        # at the lowest price: a falling curve at 0.5 has not dropped below it yet, a rising one has reached it
        self.assertEqual(jev.crossing([100, 200], [0.5, 0.3], True), (100, None))
        self.assertEqual(jev.crossing([100, 200], [0.5, 0.7], False), (100, "low"))

    def test_censored_at_either_end(self):
        self.assertEqual(jev.crossing([100, 200], [0.4, 0.3], True), (100, "low"))
        self.assertEqual(jev.crossing([100, 200, 300], [0.9, 0.8, 0.6], True), (300, "high"))
        self.assertEqual(jev.crossing([100, 200], [0.6, 0.8], False), (100, "low"))
        self.assertEqual(jev.crossing([100, 200, 300], [0.1, 0.2, 0.3], False), (300, "high"))

    def test_two_crossings_take_the_first_and_are_flagged(self):
        r = rows([0.1] * 4, [0.8, 0.4, 0.7, 0.2], [0.1, 0.2, 0.25, 0.6], [0.0, 0.05, 0.1, 0.2])
        prices, flags = jev.price_points([100, 200, 300, 400], r)
        self.assertAlmostEqual(prices["cheap"], 175)  # 0.8 at 100, 0.4 at 200
        self.assertEqual(flags["multi_cross"], ["cheap"])

    def test_one_crossing_can_still_be_not_monotone(self):
        r = rows([0.1] * 4, [0.9, 0.7, 0.8, 0.4], [0.05, 0.1, 0.15, 0.5], [0.0, 0.05, 0.05, 0.1])
        prices, flags = jev.price_points([100, 200, 300, 400], r)
        self.assertAlmostEqual(prices["cheap"], 375)  # 0.8 at 300, 0.4 at 400
        self.assertEqual(flags["nonmonotone"], ["cheap"])
        self.assertEqual(flags["multi_cross"], [])
        self.assertEqual(flags["censored"], {"too_cheap": "low", "too_expensive": "high"})
        self.assertEqual((prices["too_cheap"], prices["expensive"], prices["too_expensive"]), (100, 400, 400))
        self.assertFalse(flags["clamped"])

    def test_a_flat_stretch(self):
        x, side = jev.crossing([100, 200, 300, 400], [0.8, 0.6, 0.6, 0.3], True)
        self.assertAlmostEqual(x, 300 + 100 / 3.0)  # 0.6 at 300, 0.3 at 400: a third of the way
        r = rows([0.1] * 4, [0.8, 0.6, 0.6, 0.3], [0.1, 0.2, 0.2, 0.6], [0.0, 0.0, 0.1, 0.1])
        _, flags = jev.price_points([100, 200, 300, 400], r)
        self.assertEqual((flags["nonmonotone"], flags["multi_cross"]), ([], []))

    def test_order_is_restored_and_flagged(self):
        # "a bargain" stays at exactly 0.5 until 300 while "expensive" reaches 0.5 at 200
        r = rows([0.1] * 4, [0.9, 0.5, 0.5, 0.2], [0.1, 0.5, 0.5, 0.8], [0.0, 0.1, 0.1, 0.3])
        prices, flags = jev.price_points([100, 200, 300, 400], r)
        self.assertEqual([prices[k] for k in jev.CURVES], [100, 300, 300, 400])
        self.assertTrue(flags["clamped"])
        self.assertEqual(flags["censored"], {"too_cheap": "low", "too_expensive": "high"})

    def test_two_crossings_are_flagged_and_one_is_not(self):
        ladder = [100, 200, 300]
        twice = rows([0.1] * 3, [0.8, 0.4, 0.7], [0.1, 0.2, 0.3], [0.0, 0.1, 0.1])  # below 0.5, then back above
        once = rows([0.1] * 3, [0.8, 0.4, 0.3], [0.1, 0.2, 0.3], [0.0, 0.1, 0.1])
        self.assertEqual(jev.price_points(ladder, twice)[1]["multi_cross"], ["cheap"])
        self.assertEqual(jev.price_points(ladder, once)[1]["multi_cross"], [])
        up_down = rows([0.0] * 3, [0.3, 0.2, 0.2], [0.2, 0.6, 0.4], [0.0, 0.1, 0.1])  # rising: up through 0.5, back down
        self.assertEqual(jev.price_points(ladder, up_down)[1]["multi_cross"], ["expensive"])

    def test_a_bargain_below_too_cheap_is_raised_to_it(self):
        # P(a bargain) is negative in this table. No checked reply looks like this: P(too cheap or a bargain) is never
        # below P(too cheap), so this guard can only change a value when price_points gets such a table directly
        r = rows([0.9, 0.8, 0.6, 0.2], [0.9, 0.4, 0.3, 0.2], [0.05, 0.1, 0.2, 0.6], [0.0, 0.0, 0.1, 0.55])
        prices, flags = jev.price_points([100, 200, 300, 400], r)
        self.assertAlmostEqual(prices["too_cheap"], 325)  # 0.6 at 300, 0.2 at 400: a quarter of the way
        self.assertAlmostEqual(prices["cheap"], 325)  # its own crossing: 0.9 at 100, 0.4 at 200, so 180
        self.assertAlmostEqual(prices["expensive"], 375)  # 0.2 at 300, 0.6 at 400
        self.assertAlmostEqual(prices["too_expensive"], 300 + 100 * 0.4 / 0.45)  # 0.1 at 300, 0.55 at 400
        self.assertEqual(flags, {"censored": {}, "multi_cross": [], "nonmonotone": [], "clamped": True})

    def test_probabilities_may_be_off_by_rounding_up_to_003(self):
        s = {"seed": 7, "currency": "KRW", "price": 6500.0, "paid": "x", "unit": "y", "ladder": LADDER_6500}
        qs = jev.questions({"id": "P001"}, s)
        # sums by hand: 1.03, 1.031, 1.04, 0.97, 0.969, 0.96
        for row, ok in (([0.17, 0.72, 0.10, 0.01, 0.03], True), ([0.17, 0.72, 0.10, 0.01, 0.031], False),
                        ([0.17, 0.72, 0.10, 0.01, 0.04], False), ([0.15, 0.70, 0.10, 0.01, 0.01], True),
                        ([0.15, 0.70, 0.10, 0.01, 0.009], False), ([0.14, 0.70, 0.10, 0.01, 0.01], False)):
            r = reply_for({"questions": qs})
            r["answers"]["price_01"]["probabilities"] = dict((str(i), v) for i, v in enumerate(row))
            self.assertEqual(jev.check_reply(r, MODEL, qs) is None, ok, row)

    def test_ladder_keeps_decimals(self):
        got = jev.ladder(6.5)
        self.assertEqual(got[0], 1.3)
        self.assertIsInstance(got[0], float)
        self.assertEqual(got, [1.3, 2.0, 2.9, 3.9, 5.2, 6.5, 8.1, 10.0, 13.0, 16.0, 21.0, 33.0])
        self.assertEqual(jev.ladder(6500), LADDER_6500)
        # by hand: 2,980 4,470 6,705 8,940 11,920 18,625 23,840 29,800 37,250 49,170 74,500 to two figures, half up,
        # and 14,900 itself at the 1.0 step (rounded it would be 15,000)
        self.assertEqual(jev.ladder(14900), [3000.0, 4500.0, 6700.0, 8900.0, 12000.0, 14900.0, 19000.0, 24000.0,
                                             30000.0, 37000.0, 49000.0, 75000.0])
        self.assertEqual(jev.ladder(6510)[5], 6510.0)

    def test_bad_ladder_inputs_are_refused(self):
        for top in (2.0, 3.0, 3.3, float("inf"), float("nan")):
            with self.assertRaises(jev.JevError, msg=top):
                jev.ladder(6500, top)
        for price in (0, -6500, float("nan"), float("inf")):
            with self.assertRaises(jev.JevError, msg=price):
                jev.ladder(price)
        with self.assertRaises(jev.JevError):
            jev.ladder(1, 3.31)  # 3.31 rounds to 3.3, the step below it: not strictly rising


class Replies(Base):
    def broken(self, change):
        def make(body):
            r = reply_for(body)
            change(r)
            return r
        return self.run_jev(fake=self.fake(reply=make))

    def test_broken_replies_are_refused_and_nothing_is_saved(self):
        cases = {
            "a missing question": lambda r: r["answers"].pop("price_05"),
            "a choice outside the options": lambda r: r["answers"]["reason_code"].update(choice="vibes"),
            "other options": lambda r: r["answers"]["reason_code"]["probabilities"].pop("need"),
            "probabilities adding up to 1.2": lambda r: r["answers"]["price_01"]["probabilities"].update({"0": 0.37}),
            "a negative probability": lambda r: r["answers"]["price_02"]["probabilities"].update({"0": -0.15, "1": 0.94}),
            "a probability above 1": lambda r: r["answers"]["buys"].update(noul=1.2),
            "NaN": lambda r: r["answers"]["buys"].update(noul=float("nan")),
            "another model": lambda r: r.update(model="jev-latest"),
            "an empty model": lambda r: r.update(model=""),
            "no usage": lambda r: r.pop("usage"),
            "negative usage": lambda r: r["usage"].update(input_tokens=-1),
            "fractional usage": lambda r: r["usage"].update(input_tokens=2443.5),
            "usage as text": lambda r: r["usage"].update(input_tokens="2443"),
        }
        for what, change in cases.items():
            with self.subTest(what):
                run = self.broken(change)
                self.assertEqual(run.code, 2, run.err)
                self.assertEqual(len(run.fake.calls), 1)
                self.assertIn("P001", run.err)
                self.assertFalse(os.path.exists(os.path.join(self.d, "jev-answers", "P001.json")))
                self.no_tmp()

    def test_an_answer_with_a_bad_price_is_not_saved(self):
        self.assertEqual(self.run_jev().code, 0)
        a = self.answer("P002")
        os.remove(os.path.join(self.d, "jev-answers", "P002.json"))
        for bad in (float("nan"), 0, -1300.0):
            a["price_cheap"] = bad
            with self.assertRaises(jev.JevError):
                jev._save_answer(os.path.join(self.d, "jev-answers", "P002.json"), "P002", a)
            self.assertFalse(os.path.exists(os.path.join(self.d, "jev-answers", "P002.json")))
            self.no_tmp()

    def test_a_real_shaped_reply_converts_by_hand(self):
        run = self.run_jev()
        self.assertEqual(run.code, 0, run.err)
        a = self.answer("P001")
        self.assertEqual((a["buys"], a["reason_code"], a["reason"], a["objection"]), (False, "trust", "", ""))
        self.assertNotIn("purchases_first_month", a)
        self.assertEqual(a["price_too_cheap"], 1300)  # below 0.5 already at the lowest price
        self.assertAlmostEqual(a["price_cheap"], 3900 + 1300 * 0.08 / 0.30, places=6)  # 0.58 at 3,900, 0.28 at 5,200
        self.assertAlmostEqual(a["price_expensive"], 7700, places=6)  # 0.17 at 6,500, 0.61 at 8,100
        self.assertAlmostEqual(a["price_too_expensive"], 21000 + 12000 * 0.14 / 0.19, places=6)  # 0.36, 0.55
        self.assertEqual(a["jev"]["flags"], {"censored": {"too_cheap": "low"}, "multi_cross": [], "nonmonotone": [],
                                             "clamped": False})
        self.assertEqual([e["price"] for e in a["jev"]["price_probabilities"]], LADDER_6500)
        self.assertEqual(a["jev"]["price_probabilities"][3]["probabilities"], PRICE_ROWS[3])
        self.assertEqual((a["jev"]["p_buy"], a["jev"]["input_tokens"], a["jev"]["model"]), (0.38, 2443, MODEL))
        self.assertIsNone(panel._answer_ok(os.path.join(self.d, "jev-answers", "P001.json"), "P001"))

    def test_the_price_section_goes_through_the_price_tool(self):
        self.assertEqual(self.run_jev().code, 0)
        with open(os.path.join(self.d, "jev-results.md"), encoding="utf-8") as fh:
            md = fh.read()
        res = self.record_results()
        self.assertEqual((res["price"]["complete"], res["price"]["dropped"]), (10, 0))
        self.assertIn("10 complete answers", md)
        self.assertIn("## Price: an exploratory estimate", md)
        self.assertIn("**Acceptable range: ", md)
        self.assertIn("원", md.split("## Price")[1])
        self.assertNotIn("# Price sensitivity", md)
        self.assertIn("| too cheap | 10 | 0 | 0 | 0 |", md)
        self.assertIn("| too expensive | 0 | 0 | 0 | 0 |", md)
        self.assertIn("0 cards had their four prices put back in order (clamped).", md)
        self.assertIn("Your current price, 6,500원, is **inside** the acceptable range.", md)
        self.assertEqual(res["price_flags"]["censored"]["too_cheap"], {"low": 10, "high": 0})

    def record_results(self):
        with open(os.path.join(self.d, "jev-results.json"), encoding="utf-8") as fh:
            return json.load(fh)


class LadderHint(Base):
    n = 8

    def run_with(self, high, d):
        """A run where the first `high` cards never reach 0.5 on "too expensive" inside the ladder."""
        names = set(c["name"] for c in self.cards[:high])
        flat_top = PRICE_ROWS[:11] + [PRICE_ROWS[10]]  # 0.36 at the top price as well
        reply = lambda body: reply_for(body, rows=flat_top if body["state"]["who_decides"]["name"] in names else PRICE_ROWS)
        run = self.run_jev(fake=self.fake(reply=reply), d=d)
        self.assertEqual(run.code, 0, run.err)
        with open(os.path.join(d, "jev-results.json"), encoding="utf-8") as fh:
            res = json.load(fh)
        with open(os.path.join(d, "jev-results.md"), encoding="utf-8") as fh:
            return run, res, fh.read()

    def test_more_than_a_quarter_censored_high_asks_for_a_higher_ladder_max(self):
        other = os.path.join(self.root, "same-cards")
        shutil.copytree(self.d, other)
        run, res, md = self.run_with(2, self.d)  # 2 of 8: a quarter exactly, not more
        self.assertEqual(res["price_flags"]["censored"]["too_expensive"], {"low": 0, "high": 2})
        self.assertEqual(res["raise_ladder_max"], [])
        self.assertNotIn("--ladder-max", run.out + md)
        run, res, md = self.run_with(3, other)  # 3 of 8
        self.assertEqual(res["price_flags"]["censored"]["too_expensive"], {"low": 0, "high": 3})
        self.assertEqual(res["raise_ladder_max"], ["too_expensive"])
        for text in (run.out, md):
            self.assertIn("More than a quarter of the cards are censored high on too expensive", text)
            self.assertIn("higher --ladder-max", text)


class TooFew(Base):
    n = 4

    def test_four_answers_skip_only_the_price_section(self):
        run = self.run_jev()
        self.assertEqual(run.code, 0, run.err)
        with open(os.path.join(self.d, "jev-results.md"), encoding="utf-8") as fh:
            md = fh.read()
        self.assertIn("Too few complete price answers for a curve: 4 cards", md)
        self.assertNotIn("Acceptable range", md)
        for heading in ("# Jev panel:", "## By segment", "## By buying behaviour", "## By income",
                        "## What weighs most", "## Highest buy probability", "## Price: an exploratory estimate"):
            self.assertIn(heading, md)
        self.assertEqual(len(os.listdir(os.path.join(self.d, "jev-answers"))), 4)


# The request for P001 of customer.kr.example.json dealt with seed 7, sent with --price 6500 --paid "a matcha latte"
# --unit "per cup". Written out in full here, not rebuilt from jev.py.
WANT_WHO = [("name", "안진우"), ("age", 25), ("group", "경력 직장인"), ("yearly_income", "51,200,000원"),
            ("buying_style", "매일 가는 단골"), ("how_they_buy", "거의 매일 아침 같은 곳에서 같은 음료를 산다."),
            ("everyday_context", "일주일에 사흘은 재택근무를 한다"),
            ("first_doubt_on_hearing_an_offer_like_this", "회사 앞 저가 커피가 더 가깝다"),
            ("one_of", "성수동 근처에서 일하며 일주일에 4번 이상 커피를 사 마시는 24~38세 직장인"),
            ("note", "Most people do not buy most things. Decide with this person's own money, habits and doubts in a"
                     " normal week.")]
WANT_PITCH = ("모스 말차 바, 서울 성수역 근처에 새로 여는 말차 카페입니다.\n최고급 말차와 귀리우유로 만든 아이스·따뜻한 말차 라테, 한 잔"
              " 6,500원.\n오전 7시부터 오후 6시까지. 바 좌석 6개, 대부분 테이크아웃. 오픈 첫 주에는 4,900원.")
WANT_BUYS = ("After seeing `offer_seen_for_the_first_time` once, would `who_decides` start paying for a matcha latte at"
             " 6,500원 per cup within the first month? Yes only if they would actually pay, not just use a free tier or a"
             " free trial.")
WANT_REASON = "When `who_decides` weighs whether to pay for a matcha latte, which of these matters most?"
WANT_PRICE = "If the price of a matcha latte were %s per cup, how would `who_decides` feel about that price?"
WANT_PRICES = ["1,300원", "2,000원", "2,900원", "3,900원", "5,200원", "6,500원", "8,100원", "10,000원", "13,000원",
               "16,000원", "21,000원", "33,000원"]
WANT_LEVELS = ["too cheap to be any good (quality doubt)", "a bargain", "about right, a fair price",
               "getting expensive, but might still buy", "too expensive, would not buy"]
# random.Random("7:P001") and random.Random("7:P002") shuffles of the reason codes: worked out once, now fixed
WANT_P001_OPTIONS = [("habit", "whether it fits their routine and they would keep using it"),
                     ("values", "whether it fits what they believe in"),
                     ("trust", "whether they trust the business, its claims or its reviews"), ("other", "something else"),
                     ("quality", "how good the product itself is"), ("convenience", "how easy it is to get, use or cancel"),
                     ("need", "whether they need this right now"), ("price", "the price"),
                     ("timing", "whether this is the right time (their schedule, money this month)")]
WANT_P002_ORDER = ["other", "price", "trust", "need", "timing", "values", "convenience", "quality", "habit"]


class Contract(Base):
    def test_the_request_for_one_card_is_exactly_this(self):
        run = self.run_jev()
        first = run.fake.calls[0]
        self.assertEqual(first["url"], "https://api.typesafe.ai/v1/systemone")
        self.assertEqual((first["headers"]["Authorization"], first["headers"]["Content-type"]),
                         ("Bearer " + FAKE_KEY, "application/json"))
        body = first["body"]
        self.assertEqual((sorted(body), body["model"]), (["model", "questions", "state"], "jev-1.14.0"))
        self.assertEqual(sorted(body["state"]), ["offer_seen_for_the_first_time", "who_decides"])
        self.assertEqual(list(body["state"]["who_decides"].items()), WANT_WHO)
        self.assertEqual(body["state"]["offer_seen_for_the_first_time"], WANT_PITCH)
        q = body["questions"]
        self.assertEqual(list(q), ["buys", "reason_code"] + ["price_%02d" % i for i in range(1, 13)])
        self.assertEqual(q["buys"], {"type": "noul", "instructions": WANT_BUYS})
        self.assertEqual((sorted(q["reason_code"]), q["reason_code"]["type"], q["reason_code"]["instructions"]),
                         (["criteria", "instructions", "type"], "choice", WANT_REASON))
        self.assertEqual(list(q["reason_code"]["criteria"].items()), WANT_P001_OPTIONS)
        for i, price in enumerate(WANT_PRICES):
            self.assertEqual(q["price_%02d" % (i + 1)],
                             {"type": "score", "instructions": WANT_PRICE % price, "criteria": WANT_LEVELS})
        self.assertEqual(list(run.fake.calls[1]["body"]["questions"]["reason_code"]["criteria"]), WANT_P002_ORDER)


# ── 2. fingerprint and folder state ──────────────────────────────────────────────
class State(Base):
    def setUp(self):
        Base.setUp(self)
        run = self.run_jev("--budget-usd", str(3.5 * COST))  # three cards, then the budget stops it
        self.assertEqual((run.code, len(run.fake.calls)), (1, 3), run.out + run.err)
        self.ans = os.path.join(self.d, "jev-answers")
        self.before = snapshot(self.d, ["jev-answers"])

    def refused(self, *args, **kw):
        run = self.run_jev(*args, **kw)
        self.assertEqual(run.code, 2, run.out + run.err)
        self.assertEqual(run.fake.calls, [])
        return run

    def edit(self, name, change):
        path = os.path.join(self.d, name)
        with open(path, encoding="utf-8") as fh:
            obj = json.load(fh)
        change(obj)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False)

    def test_untouched_it_sends_the_rest(self):
        run = self.run_jev()
        self.assertEqual((run.code, len(run.fake.calls)), (0, 7))

    def test_a_changed_card_is_refused_before_any_request(self):
        self.edit("personas.json", lambda cards: cards[2].update(income=cards[2]["income"] + 100000))
        self.assertIn("changed", self.refused().err)
        self.assertEqual(snapshot(self.d, ["jev-answers"]), self.before)

    def test_changed_settings_are_refused_before_any_request(self):
        self.edit("panel.json", lambda st: st.update(seed=8))
        self.assertIn("seed", self.refused().err)
        self.edit("panel.json", lambda st: st.update(seed=7))
        self.edit("panel.json", lambda st: st["customer"].update(currency="JPY"))
        self.assertIn("currency", self.refused().err)
        self.edit("panel.json", lambda st: st["customer"].update(currency="KRW"))
        with mock.patch.object(jev, "CONVERT", 2):
            self.assertIn("convert", self.refused().err)
        self.assertIn("price", self.refused(price="7000").err)
        self.assertEqual(snapshot(self.d, ["jev-answers"]), self.before)
        self.assertEqual(len(self.run_jev().fake.calls), 7)  # all put back: it carries on

    def test_a_small_price_change_is_refused(self):
        self.assertIn("ladder, price", self.refused(price="6510").err)

    def test_saved_probabilities_are_checked_again(self):
        cases = (
            ("P001", lambda a: a["jev"].update(p_buy=-0.38), "P001 (buys: the probability is not a number from 0 to 1)"),
            # P(about right) is in no curve: only the probability check can see this one
            ("P002", lambda a: a["jev"]["price_probabilities"][5]["probabilities"].__setitem__(2, 1.5),
             "P002 (price_06: a probability is not a number from 0 to 1)"),
            ("P003", lambda a: a["jev"].update(p_buy=0.6), "P003 (its answers do not follow from its probabilities)"),
        )
        for cid, change, why in cases:
            with self.subTest(cid):
                path = os.path.join(self.ans, cid + ".json")
                self.edit(os.path.join("jev-answers", cid + ".json"), change)
                with open(path, "rb") as fh:
                    edited = fh.read()
                self.assertIn(why, self.refused().err)
                with open(path, "rb") as fh:
                    self.assertEqual(fh.read(), edited)
                with open(path, "wb") as fh:
                    fh.write(self.before[path])

    def test_an_incomplete_folder_is_refused(self):
        os.remove(os.path.join(self.d, "panel.json"))
        self.assertIn("not a complete panel", self.refused().err)
        only_answers = os.path.join(self.root, "leftovers")
        os.makedirs(os.path.join(only_answers, "answers"))
        self.assertIn("not a complete panel", self.refused(d=only_answers).err)

    def test_answers_without_a_record_are_refused(self):
        os.remove(os.path.join(self.d, "jev.json"))
        self.assertIn("no jev.json", self.refused().err)

    def test_answers_for_other_cards_are_refused(self):
        shutil.copy(os.path.join(self.ans, "P001.json"), os.path.join(self.ans, "P999.json"))
        self.assertIn("P999.json", self.refused().err)

    def test_damaged_answers_are_refused_and_left_alone(self):
        with open(os.path.join(self.ans, "P002.json"), "w", encoding="utf-8") as fh:
            fh.write("{")
        self.assertIn("P002 (not valid JSON)", self.refused().err)
        with open(os.path.join(self.ans, "P002.json"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "{")
        with open(os.path.join(self.ans, "P002.json"), "wb") as fh:
            fh.write(self.before[os.path.join(self.ans, "P002.json")])
        self.edit(os.path.join("jev-answers", "P003.json"), lambda a: a.update(price_cheap=a["price_cheap"] + 1))
        self.assertIn("P003 (its answers do not follow from its probabilities)", self.refused().err)

    def test_dealing_into_an_existing_panel_is_refused(self):
        self.assertIn("already has a panel", self.refused("--n", "5").err)
        self.assertIn("--customer", self.refused("--customer", example("founder-consumer", self.customer)).err)


class Markets(Base):
    def test_markets_are_refused_before_any_request(self):
        with open(example("founder-consumer", "customer.example.json"), encoding="utf-8") as fh:
            c = json.load(fh)
        c["markets"] = [{"name": "Canada", "share": 1, "currency": "CAD"}]
        path = os.path.join(self.root, "markets.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(c, fh)
        new = os.path.join(self.root, "new")
        run = self.run_jev("--customer", path, "--pitch", example("founder-consumer", "pitch.example.md"), "--n", "5",
                           d=new)
        self.assertEqual((run.code, run.fake.calls), (2, []))
        self.assertIn("markets", run.err)
        self.assertFalse(os.path.exists(new))
        dealt = os.path.join(self.root, "dealt")
        panel.init(dealt, path, example("founder-consumer", "pitch.example.md"), n=5, seed=1)
        run = self.run_jev(d=dealt)
        self.assertEqual((run.code, run.fake.calls), (2, []))
        self.assertFalse(os.path.exists(os.path.join(dealt, "jev.json")))


class NewFolder(Base):
    def test_a_new_folder_is_dealt_then_sent(self):
        new = os.path.join(self.root, "panel-jev")
        run = self.run_jev("--customer", example("founder-consumer", self.customer),
                           "--pitch", example("founder-consumer", self.pitch), "--n", "12", "--seed", "3", d=new)
        self.assertEqual((run.code, len(run.fake.calls)), (0, 12), run.err)
        st, cards = panel.load_state(new)
        self.assertEqual((st["seed"], len(cards)), (3, 12))
        self.assertEqual(sorted(os.listdir(os.path.join(new, "jev-answers"))), ["P%03d.json" % i for i in range(1, 13)])
        self.assertEqual(os.listdir(os.path.join(new, "answers")), [])
        with open(os.path.join(new, "jev-results.json"), encoding="utf-8") as fh:
            self.assertIsNone(json.load(fh)["agreement"])

    def test_a_new_folder_needs_all_three(self):
        new = os.path.join(self.root, "panel-jev")
        run = self.run_jev("--customer", example("founder-consumer", self.customer), d=new)
        self.assertEqual((run.code, run.fake.calls), (2, []))
        self.assertIn("--customer, --pitch and --n", run.err)
        self.assertFalse(os.path.exists(new))


# ── 3. saving and resuming ───────────────────────────────────────────────────────
def crash_on_replace(name, after, then=None):
    """Crash just before or just after os.replace writes `name`. With then, the crash waits for the first write of
    `then` that comes after `name` was written. From the crash on no write lands, as when the process is killed."""
    real, seen = os.replace, {"name": False, "dead": False}

    def replace(src, dst):
        base = os.path.basename(dst)
        if seen["dead"]:
            raise Crash(dst)
        if then is None and base == name or then is not None and seen["name"] and base == then:
            if after:
                real(src, dst)
            seen["dead"] = True
            raise Crash(dst)
        if base == name:
            seen["name"] = True
        return real(src, dst)
    return mock.patch.object(jev.os, "replace", replace)


class Resume(Base):
    def test_a_run_writes_whole_files_and_a_second_run_sends_nothing(self):
        run = self.run_jev()
        self.assertEqual((run.code, len(run.fake.calls)), (0, 10), run.err)
        self.assertEqual(sorted(os.listdir(os.path.join(self.d, "jev-answers"))), ["P%03d.json" % i for i in range(1, 11)])
        self.no_tmp()
        rec = self.record()
        self.assertEqual((rec["derived"]["done"], rec["derived"]["input_tokens"], rec["inflight"]), (10, 24430, None))
        self.assertEqual([(r["attempts"], r["unknown"], r["stopped"]) for r in rec["runs"]], [(10, 0, None)])
        again = self.run_jev()
        self.assertEqual((again.code, again.fake.calls), (0, []))
        self.assertIn("nothing to send", again.out)
        self.assertEqual(len(self.record()["runs"]), 2)

    def crashed_then_resumed(self, patch, sent_again, unknown):
        with patch, self.assertRaises(Crash):
            self.run_jev()
        saved = sorted(os.listdir(os.path.join(self.d, "jev-answers")))
        saved = [f for f in saved if f.endswith(".json")]
        self.assertEqual(len(saved), 10 - sent_again)
        run = self.run_jev()
        self.assertEqual(run.code, 0, run.err)
        self.assertEqual(self.ids(run), ["P%03d" % i for i in range(11 - sent_again, 11)])
        self.no_tmp()
        rec = self.record()
        self.assertEqual(rec["runs"][0]["stopped"], "interrupted")
        self.assertEqual((rec["runs"][0]["unknown"], rec["runs"][1]["unknown"]), (unknown, 0))
        self.assertEqual((rec["runs"][1]["stopped"], rec["derived"]["done"], rec["inflight"]), (None, 10, None))
        self.assertEqual(len(os.listdir(os.path.join(self.d, "jev-answers"))), 10)

    def test_crash_before_the_answer_is_in_place(self):
        # the reply came back but P004 was not saved: one request of unknown outcome, sent again
        self.crashed_then_resumed(crash_on_replace("P004.json", after=False), sent_again=7, unknown=1)

    def test_crash_right_after_the_answer_is_in_place(self):
        self.crashed_then_resumed(crash_on_replace("P004.json", after=True), sent_again=6, unknown=0)

    def test_crash_before_the_record_is_updated(self):
        self.crashed_then_resumed(crash_on_replace("P004.json", after=False, then="jev.json"), sent_again=6, unknown=0)

    def test_crash_right_after_the_record_is_updated(self):
        self.crashed_then_resumed(crash_on_replace("P004.json", after=True, then="jev.json"), sent_again=6, unknown=0)

    def test_crash_while_waiting_for_a_reply(self):
        fake = self.fake(None, None, None, Crash("killed"))
        with self.assertRaises(Crash):
            self.run_jev(fake=fake)
        self.assertEqual(self.record()["inflight"], "P004")
        run = self.run_jev()
        self.assertIn("P004 was being sent when the last run stopped", run.out)
        self.assertEqual(len(run.fake.calls), 7)
        self.assertEqual(self.record()["runs"][0]["unknown"], 1)

    def test_option_order_is_per_card_whatever_was_skipped(self):
        other = os.path.join(self.root, "same-cards")
        shutil.copytree(self.d, other)
        full = self.run_jev()
        first = self.run_jev("--budget-usd", str(3.5 * COST), d=other)
        rest = self.run_jev(d=other)
        self.assertEqual((len(first.fake.calls), len(rest.fake.calls)), (3, 7))
        order = lambda calls: dict((c["body"]["state"]["who_decides"]["name"], list(c["body"]["questions"]["reason_code"]
                                                                                    ["criteria"])) for c in calls)
        self.assertEqual(order(first.fake.calls + rest.fake.calls), order(full.fake.calls))
        self.assertGreater(len(set(tuple(v) for v in order(full.fake.calls).values())), 1)
        for v in order(full.fake.calls).values():
            self.assertEqual(sorted(v), sorted(panel.REASONS))

    def test_the_agent_panel_files_are_not_touched(self):
        for i, c in enumerate(self.cards):
            self.agent(c["id"], i % 3 == 0, reason="" if i == 1 else "because")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(panel.main(["--dir", self.d, "tally"]), 0)
        names = ["answers", "panel.json", "personas.json", "results.md", "results.json"]
        before = snapshot(self.d, names)
        self.assertEqual(self.run_jev().code, 0)
        self.assertEqual(snapshot(self.d, names), before)


# ── 4. sending and cost ──────────────────────────────────────────────────────────
class Send(Base):
    n = 2

    def test_429_then_200_waits_as_told(self):
        for header, wait in (("3", 3.0), (email.utils.formatdate(NOW + 7, usegmt=True), 7.0), ("soon", 1.5),
                             ("600", 60)):
            with self.subTest(header):
                shutil.rmtree(os.path.join(self.d, "jev-answers"), ignore_errors=True)
                if os.path.exists(os.path.join(self.d, "jev.json")):
                    os.remove(os.path.join(self.d, "jev.json"))
                del self.slept[:]
                run = self.run_jev(fake=self.fake((429, {"Retry-After": header}, "slow down")))
                self.assertEqual((run.code, len(run.fake.calls)), (0, 3), run.err)
                self.assertEqual(self.slept, [wait])
                self.assertEqual(self.record()["runs"][-1]["retries"], 1)

    def test_529_is_retried(self):
        run = self.run_jev(fake=self.fake((529, {}, "overloaded")))
        self.assertEqual((run.code, len(run.fake.calls), self.slept), (0, 3, [1.5]))

    def test_retries_run_out(self):
        run = self.run_jev(fake=self.fake(*[(503, {}, "down")] * 6))
        self.assertEqual((run.code, len(run.fake.calls)), (2, 6))
        self.assertEqual(self.slept, [1.5, 2.5, 4.5, 8.5, 16.5])
        self.assertIn("gave up after 6 tries", run.err)
        rec = self.record()
        self.assertEqual((rec["runs"][0]["attempts"], rec["runs"][0]["retries"], rec["inflight"]), (6, 5, None))
        self.assertTrue(rec["runs"][0]["stopped"].startswith("P001: gave up"))

    def test_giving_up_after_timeouts_shows_the_unknown_outcomes(self):
        run = self.run_jev(fake=self.fake(*[socket.timeout("timed out")] * 6))
        self.assertEqual((run.code, len(run.fake.calls)), (2, 6))
        self.assertIn("6 requests had an unknown outcome", run.out)
        r = self.record()["runs"][0]
        self.assertEqual((r["timeouts"], r["unknown"], r["usd"]), (6, 6, 0.0))

    def test_a_reply_that_echoes_the_key_leaves_no_trace(self):
        run = self.run_jev(fake=self.fake(reply=lambda body: reply_for(body, model=FAKE_KEY)))
        self.assertEqual((run.code, len(run.fake.calls)), (2, 1))
        self.assertIn("P001: the Jev reply is not valid (the reply's model is not jev-1.14.0)", run.err)
        self.assertNotIn(FAKE_KEY, run.out + run.err)
        for path in files_under(self.root):
            with open(path, "rb") as fh:
                self.assertNotIn(FAKE_KEY.encode(), fh.read(), path)

    def test_a_quoted_key_is_taken_out_of_json_too(self):
        # a key with a quote in it passes _key_ok; an error body that quotes it as JSON escapes the quote
        quoted = 'tsk-fake-"quoted\\back-9f3e'
        body = json.dumps({"error": "bad key " + quoted})
        self.assertNotIn(quoted, body)  # JSON wrote it differently, which is the point
        self.assertNotIn("quoted", json.loads(jev._scrub(body, [quoted]))["error"])
        self.assertEqual(jev._scrub(body, [quoted]), json.dumps({"error": "bad key [key removed]"}))

    def test_the_history_and_stderr_take_the_key_out_the_same_way(self):
        # no problem string carries a reply's value now; this holds the boundary for one that might
        with mock.patch.object(jev, "check_reply", lambda reply, model, qs: "it echoed " + FAKE_KEY):
            run = self.run_jev()
        self.assertEqual(run.code, 2)
        self.assertIn("it echoed [key removed]", run.err)
        self.assertIn("it echoed [key removed]", self.record()["runs"][0]["stopped"])
        for path in files_under(self.root):
            with open(path, "rb") as fh:
                self.assertNotIn(FAKE_KEY.encode(), fh.read(), path)

    def test_a_saved_answer_holding_the_key_is_refused_without_printing_it(self):
        self.assertEqual(self.run_jev("--budget-usd", str(1.5 * COST)).code, 1)  # P001 saved, then the budget
        path = os.path.join(self.d, "jev-answers", "P001.json")
        with open(path, "rb") as fh:
            good = fh.read()
        cases = ((lambda a: a["jev"].update(model=FAKE_KEY), "P001 (the reply's model is not jev-1.14.0)"),
                 (lambda a: a.update(id=FAKE_KEY), "P001 (its id is not P001)"),
                 (lambda a: a.update(reason_code=FAKE_KEY), "P001 (its reason_code is not one of the panel's codes)"),
                 (lambda a: a["jev"].update(p_buy=FAKE_KEY), "P001 (buys: the probability is not a number from 0 to 1)"))
        for change, why in cases:
            with self.subTest(why):
                a = json.loads(good.decode("utf-8"))
                change(a)
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(a, fh)
                run = self.run_jev()
                self.assertEqual((run.code, run.fake.calls), (2, []))
                self.assertIn(why, run.err)
                self.assertNotIn(FAKE_KEY, run.out + run.err)
        with open(path, "wb") as fh:
            fh.write(good)
        self.assertEqual(self.run_jev().code, 0)

    def test_401_is_not_retried(self):
        run = self.run_jev(fake=self.fake((401, {}, '{"error": "bad key"}')))
        self.assertEqual((run.code, len(run.fake.calls), self.slept), (2, 1, []))
        self.assertIn("HTTP 401", run.err)

    def test_a_broken_200_is_not_retried(self):
        run = self.run_jev(fake=self.fake((200, {}, "<html>maintenance</html>")))
        self.assertEqual((run.code, len(run.fake.calls), self.slept), (2, 1, []))
        self.assertIn("not valid JSON", run.err)

    def test_a_redirect_is_not_followed(self):
        script = ((302, {"Location": "https://collector.example/steal"}, ""), (200, {}, "{}"))
        run = self.run_jev(fake=self.fake(*script))
        self.assertEqual((run.code, len(run.fake.calls)), (2, 1))
        self.assertEqual(run.fake.calls[0]["url"], jev.URL)
        self.assertIn("HTTP 302", run.err)
        self.assertIn("not followed", run.err)

    def test_timeouts_and_dropped_connections_are_retried_and_counted(self):
        cases = ((urllib.error.URLError(socket.timeout("timed out")), 1, 1), (socket.timeout("timed out"), 1, 1),
                 (http.client.RemoteDisconnected("closed"), 0, 1),
                 (urllib.error.URLError(ConnectionResetError(54, "Connection reset by peer")), 0, 1),
                 (urllib.error.URLError(BrokenPipeError(32, "Broken pipe")), 0, 1),
                 (urllib.error.URLError(ConnectionRefusedError(61, "Connection refused")), 0, 0),
                 (urllib.error.URLError(socket.gaierror(8, "nodename nor servname provided")), 0, 0))
        for exc, timeouts, unknown in cases:
            with self.subTest(exc):
                shutil.rmtree(os.path.join(self.d, "jev-answers"), ignore_errors=True)
                if os.path.exists(os.path.join(self.d, "jev.json")):
                    os.remove(os.path.join(self.d, "jev.json"))
                run = self.run_jev(fake=self.fake(exc))
                self.assertEqual((run.code, len(run.fake.calls)), (0, 3), run.err)
                r = self.record()["runs"][-1]
                self.assertEqual((r["retries"], r["timeouts"], r["unknown"]), (1, timeouts, unknown))
                if unknown:
                    self.assertIn("unknown outcome", run.out)

    def test_counts_survive_a_crash_between_retries(self):
        fake = self.fake(socket.timeout("timed out"), socket.timeout("timed out"), Crash("killed"))
        with self.assertRaises(Crash):
            self.run_jev(fake=fake)
        self.assertEqual(len(fake.calls), 3)
        r = self.record()["runs"][0]
        self.assertEqual((r["attempts"], r["retries"], r["timeouts"], r["unknown"]), (3, 2, 2, 2))
        self.assertEqual(self.run_jev().code, 0)
        r = self.record()["runs"][0]
        self.assertEqual((r["unknown"], r["stopped"]), (3, "interrupted"))  # the third try was cut off too

    def test_counts_survive_a_crash_while_waiting_to_retry(self):
        def die(seconds):
            raise Crash("killed while waiting")
        with self.assertRaises(Crash):
            self.run_jev(fake=self.fake(socket.timeout("timed out")), sleep=die)
        rec = self.record()
        r = rec["runs"][0]
        self.assertEqual((r["attempts"], r["timeouts"], r["unknown"], rec["inflight"]), (1, 1, 1, None))
        self.assertEqual(self.run_jev().code, 0)
        r = self.record()["runs"][0]
        self.assertEqual((r["unknown"], r["stopped"]), (1, "interrupted"))  # no request was out: nothing more to count

    def test_a_key_that_would_break_the_header_is_refused_before_sending(self):
        for bad in (FAKE_KEY + "\nsecond line", FAKE_KEY + " x", FAKE_KEY + "\x07", FAKE_KEY + "é"):
            with mock.patch.dict(os.environ, {jev.KEY_ENV: bad}):
                run = self.run_jev()
            self.assertEqual((run.code, run.fake.calls), (2, []), repr(bad))
            self.assertIn("the key in %s has whitespace, control or non-ASCII characters" % jev.KEY_ENV, run.err)
            self.assertNotIn(FAKE_KEY, run.out + run.err)

    def test_an_unforeseen_error_is_one_line_without_the_key(self):
        bad = FAKE_KEY + "\nsecond line"  # what a two-line key file gives, were it to get past api_key()

        def refuse(*a, **k):
            raise AssertionError("a socket was opened")

        def connect(key):  # the real https handler: http.client refuses the header before it opens a socket
            return jev.Transport(key, opener=jev.make_opener(urllib.request.ProxyHandler({})), sleep=self.slept.append)
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(jev, "api_key", lambda: bad), mock.patch.object(socket, "create_connection", refuse), \
                mock.patch.object(socket.socket, "connect", refuse), redirect_stdout(out), redirect_stderr(err):
            code = jev.main(["run", "--dir", self.d, "--price", "6500", "--paid", "a matcha latte", "--unit", "per cup"],
                            connect=connect)
        self.assertEqual(code, 2)
        self.assertTrue(err.getvalue().startswith("error: ValueError: Invalid header value"), err.getvalue())
        self.assertEqual(err.getvalue().count("\n"), 1)
        self.assertIn("[key removed]", err.getvalue())
        self.assertNotIn(FAKE_KEY, out.getvalue() + err.getvalue())
        rec = self.record()
        self.assertEqual((rec["inflight"], rec["runs"][0]["stopped"]), ("P001", "interrupted"))
        self.assertEqual(self.run_jev().code, 0)
        self.assertEqual(self.record()["runs"][0]["unknown"], 1)  # the next run cannot tell it never went out

    def test_ctrl_c_keeps_the_counts_and_the_card_that_was_out(self):
        with self.assertRaises(KeyboardInterrupt):
            self.run_jev(fake=self.fake(socket.timeout("timed out"), KeyboardInterrupt()))
        rec = self.record()
        r = rec["runs"][0]
        self.assertEqual((r["attempts"], r["retries"], r["timeouts"], r["unknown"]), (2, 1, 1, 1))
        self.assertEqual((r["stopped"], rec["inflight"]), ("interrupted", "P001"))
        self.assertIsNotNone(r["ended"])
        self.assertEqual(self.run_jev().code, 0)
        self.assertEqual(self.record()["runs"][0]["unknown"], 2)  # the cut-off second try is counted too

    def test_no_key_stops_before_anything(self):
        with mock.patch.dict(os.environ):
            os.environ.pop(jev.KEY_ENV)
            run = self.run_jev()
        self.assertEqual((run.code, run.fake.calls), (2, []))
        self.assertIn(jev.KEY_ENV, run.err)
        self.assertFalse(os.path.exists(os.path.join(self.d, "jev.json")))

    def test_the_key_file_must_be_private(self):
        folder = os.path.join(_env["home"], ".config", "typesafe")
        os.makedirs(folder)
        self.addCleanup(shutil.rmtree, os.path.join(_env["home"], ".config"))
        path = os.path.join(folder, "api_key")
        with open(path, "w") as fh:
            fh.write(FAKE_KEY + "-file\n")
        with mock.patch.dict(os.environ):
            os.environ.pop(jev.KEY_ENV)
            os.chmod(path, 0o644)
            run = self.run_jev()
            self.assertEqual((run.code, run.fake.calls), (2, []))
            self.assertIn("chmod 600", run.err)
            self.assertFalse(os.path.exists(os.path.join(self.d, "jev.json")))
            os.chmod(path, 0o600)
            run = self.run_jev()
        self.assertEqual(run.code, 0, run.err)
        self.assertEqual(run.fake.calls[0]["headers"]["Authorization"], "Bearer " + FAKE_KEY + "-file")
        self.assertNotIn(FAKE_KEY, run.out + run.err)

    def test_the_key_is_never_printed_or_written(self):
        echo = (401, {}, '{"error": "key %s is not valid"}' % FAKE_KEY)
        failed = self.run_jev(fake=self.fake(echo))
        self.assertEqual(failed.code, 2)
        self.assertIn("HTTP 401", failed.err)
        self.assertIn("[key removed]", failed.err)
        retried = self.run_jev(fake=self.fake((503, {}, FAKE_KEY), urllib.error.URLError("refused " + FAKE_KEY)))
        done = self.run_jev()
        self.assertEqual((retried.code, done.code), (0, 0), retried.err + done.err)
        self.assertEqual(done.fake.calls, [])
        self.assertEqual(retried.fake.calls[0]["headers"]["Authorization"], "Bearer " + FAKE_KEY)
        for run in (failed, retried, done):
            self.assertNotIn(FAKE_KEY, run.out + run.err)
        for path in files_under(self.root):
            with open(path, "rb") as fh:
                self.assertNotIn(FAKE_KEY.encode(), fh.read(), path)


class Budget(Base):
    def test_the_budget_counts_this_runs_cost_and_a_new_run_counts_afresh(self):
        run = self.run_jev("--budget-usd", str(3.5 * COST))
        # before card 4: 3 cards paid plus about one more is 4 cards, past 3.5 cards
        self.assertEqual((run.code, len(run.fake.calls)), (1, 3), run.err)
        self.assertIn("first card: 2443 input tokens", run.out)
        self.assertIn("stopped at the budget", run.out)
        rest = self.run_jev("--budget-usd", str(3.5 * COST))
        self.assertEqual((rest.code, len(rest.fake.calls)), (1, 3))
        last = self.run_jev()
        self.assertEqual((last.code, len(last.fake.calls)), (0, 4))
        runs = self.record()["runs"]
        self.assertEqual([r["attempts"] for r in runs], [3, 3, 4])
        self.assertEqual([r["input_tokens"] for r in runs], [3 * 2443, 3 * 2443, 4 * 2443])
        self.assertTrue(runs[0]["stopped"].startswith("budget"))
        self.assertIsNone(runs[2]["stopped"])
        self.assertAlmostEqual(runs[0]["usd"], 3 * COST)
        self.assertEqual(self.record()["derived"]["input_tokens"], 10 * 2443)

    def test_a_bad_budget_is_refused(self):
        for v in ("0", "-1", "nan"):
            run = self.run_jev("--budget-usd", v)
            self.assertEqual((run.code, run.fake.calls), (2, []), v)


# ── 5. the tables, and the verdict staying with the agent panel ──────────────────
# By hand, from the ten cards customer.kr.example.json deals with seed 7 and the buy probabilities in Results.p.
# Jev buyers: P001 P002 P003 P004 P008 P009. Incomes cut at the 4th and 7th lowest: 37,300,000 and 51,200,000.
BY_SEGMENT = [["사회초년생", 5, 0.8], ["경력 직장인", 4, 0.5], ["고소득 직장인", 1, 0.0]]
BY_BEHAVIOUR = [["매일 가는 단골", 2, 1.0], ["건강 우선", 2, 1.0], ["주말에만 사치", 1, 1.0], ["유행 따라가기", 2, 0.5],
                ["리뷰 먼저 보기", 1, 0.0], ["할인 찾기", 1, 0.0], ["단골 카페 고수", 1, 0.0]]
BY_INCOME = [["under 37,300,000원", 3, 1.0], ["51,200,000원 and up", 4, 0.5], ["37,300,000원 to 51,200,000원", 3, 1 / 3.0]]


class Results(Base):
    def setUp(self):
        Base.setUp(self)
        # 0.5 counts as a buyer, 0.49 does not
        self.p = {"P001": 0.7, "P002": 0.6, "P003": 0.5, "P004": 0.55, "P005": 0.3, "P006": 0.49, "P007": 0.2,
                  "P008": 0.8, "P009": 0.65, "P010": 0.1}

    def results(self):
        with open(os.path.join(self.d, "jev-results.json"), encoding="utf-8") as fh:
            res = json.load(fh)
        with open(os.path.join(self.d, "jev-results.md"), encoding="utf-8") as fh:
            return res, fh.read()

    def test_tally_reads_the_jev_answers(self):
        self.assertEqual(self.run_jev().code, 0)
        t = panel.tally(self.d, answers="jev-answers")
        self.assertEqual((t["buys"], t["passes"], t["answered"], t["skipped"]), (6, 4, 10, []))
        for key, want in (("by_segment", BY_SEGMENT), ("by_behaviour", BY_BEHAVIOUR), ("by_income", BY_INCOME)):
            self.assertEqual([list(r) for r in t[key]], want, key)
        self.assertIsNone(t["purchases_first_month_per_buyer"])
        self.assertEqual(t["price_answers"], 10)

    def test_the_report_has_every_section(self):
        for i, c in enumerate(self.cards):
            self.agent(c["id"], i < 7)  # agents: P001 to P007 buy
        run = self.run_jev()
        self.assertEqual(run.code, 0, run.err)
        self.assertIn("Wrote", run.out)
        res, md = self.results()
        for heading in ("# Jev panel:", "## By segment", "## By buying behaviour", "## By income", "## What weighs most",
                        "## Highest buy probability", "## Price: an exploratory estimate",
                        "## Agent panel and Jev, card by card"):
            self.assertIn(heading, md)
        for line in ("**6 buy · 4 pass** out of 10 cards", "not a share of buyers", "no quotes",
                     "judged separately from the buy question", "cross-table of independent predictions",
                     "not part of the verdict", "| 사회초년생 | 5 | 80%  (thin) |", "| 유행 따라가기 | 2 | 50%  (thin) |",
                     "| under 37,300,000원 | 3 | 100%  (thin) |", "| 37,300,000원 to 51,200,000원 | 3 | 33%  (thin) |"):
            self.assertIn(line, md)
        for key, want in (("by_segment", BY_SEGMENT), ("by_behaviour", BY_BEHAVIOUR), ("by_income", BY_INCOME)):
            self.assertEqual(res[key], want, key)
        # both buy P001-P004, the agent only P005-P007, Jev only P008 P009, neither P010
        self.assertEqual(res["agreement"], {"n": 10, "both": 4, "agent_only": 3, "jev_only": 2, "neither": 1})
        self.assertIn("| agent: buy | 4 | 3 |", md)
        self.assertIn("| agent: pass | 2 | 1 |", md)
        self.assertEqual(res["reasons"], [["trust", 10, 6, 4]])
        self.assertEqual([r["id"] for r in res["top"]],
                         ["P008", "P001", "P009", "P002", "P004", "P003", "P006", "P005", "P007", "P010"])
        self.assertEqual(res["top"][0], {"id": "P008", "p_buy": 0.8, "segment": "경력 직장인", "behaviour": "매일 가는 단골"})
        self.assertAlmostEqual(res["mean_p_buy"], 0.489)
        self.assertEqual((res["threshold"], res["model"], res["currency"], res["cards"]), (0.5, MODEL, "KRW", 10))

    def test_no_agent_answers_means_no_agreement(self):
        self.assertEqual(self.run_jev().code, 0)
        res, md = self.results()
        self.assertIsNone(res["agreement"])
        self.assertNotIn("card by card", md)


class Verdict(Base):
    customer = "customer.example.json"
    pitch = "pitch.example.md"
    n = 20

    def setUp(self):
        Base.setUp(self)
        self.founder = os.path.join(self.root, "founder")
        os.makedirs(self.founder)
        shutil.move(self.d, os.path.join(self.founder, "panel"))
        self.d = os.path.join(self.founder, "panel")
        shutil.copy(example("founder-cfo", "example.json"), os.path.join(self.founder, "numbers.json"))
        with open(os.path.join(self.founder, "rcf.json"), "w") as fh:
            json.dump({"business": "Moss Matcha Bar", "reference_classes": [{"level": 1, "name": "cafes", "why": "same"}],
                       "metrics": [{"key": "survival_1y", "label": "1-year survival", "class_level": 1, "value": 0.6,
                                    "unit": "ratio", "source": "https://example.org/report", "source_date": "2024"}],
                       "adjustments": []}, fh)
        self.p = dict((c["id"], 0.9) for c in self.cards)  # Jev says everyone buys

    def verdict_with_jev(self, agent_buys):
        for i, c in enumerate(self.cards):
            self.agent(c["id"], i < agent_buys)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(panel.main(["--dir", self.d, "tally"]), 0)
        before = plan.verdict(self.founder)
        run = self.run_jev(price="6.5")
        self.assertEqual(run.code, 0, run.err)
        self.assertTrue(os.path.exists(os.path.join(self.d, "jev-results.json")))
        after = plan.verdict(self.founder)
        self.assertEqual(after, before)
        return [ok for ok, text in after[1] if "simulated buyers buy" in text]

    def test_just_below_the_bar_stays_below(self):
        self.assertEqual(self.verdict_with_jev(4), [False])  # 4 of 20 is 20%

    def test_at_the_bar_stays_at_it(self):
        self.assertEqual(self.verdict_with_jev(5), [True])  # 5 of 20 is 25%


# ── 7. Jev's real answers, replayed ──────────────────────────────────────────────
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "jev")
LADDER_14900 = [3000.0, 4500.0, 6700.0, 8900.0, 12000.0, 14900.0, 19000.0, 24000.0, 30000.0, 37000.0, 49000.0, 75000.0]


class Replay(unittest.TestCase):
    """The answer files of a real run: HabitNav's 20 cards, jev-1.14.0, these questions, 2026-10-27. No key and no
    card text in them. The numbers below were written down from that run's output, not worked out by this code."""
    settings = {"model": MODEL, "seed": 7, "currency": "KRW", "price": 14900.0, "paid": "the monthly plan",
                "unit": "per month", "ladder": LADDER_14900}

    def answers(self):
        out = []
        for i in range(1, 21):
            with open(os.path.join(FIXTURES, "P%03d.json" % i), encoding="utf-8") as fh:
                out.append(json.load(fh))
        return out

    def test_each_file_follows_from_its_own_probabilities(self):
        for a in self.answers():
            with self.subTest(a["id"]):
                self.assertIsNone(panel._answer_ok(os.path.join(FIXTURES, a["id"] + ".json"), a["id"]))
                self.assertEqual([e["price"] for e in a["jev"]["price_probabilities"]], LADDER_14900)
                reply = jev.reply_from(a)
                self.assertIsNone(jev.check_reply(reply, MODEL, jev.questions({"id": a["id"]}, self.settings)))
                # the fingerprint needs the cards and the pitch, which are not kept: compare the conversion only
                self.assertEqual(jev.convert(a["id"], reply, self.settings, a["jev"]["fingerprint"]), a)

    def test_the_price_tool_reads_them(self):
        rows, dropped = jev.vw.read(FIXTURES)
        self.assertEqual((len(rows), dropped), (20, 0))
        res = jev.vw.analyse(rows, currency="KRW")
        self.assertEqual(res["n"], 20)
        self.assertEqual(dict((k, panel.money(v, "KRW")) for k, v in res["points"].items()),
                         {"PMC": "3,180원", "OPP": "3,180원", "IPP": "11,190원", "PME": "18,300원"})

    def test_the_counts_are_those_of_the_real_run(self):
        answers = self.answers()
        self.assertEqual([a["id"] for a in answers if a["buys"]], ["P015"])
        self.assertEqual(collections.Counter(a["reason_code"] for a in answers),
                         {"trust": 9, "habit": 5, "quality": 3, "price": 2, "timing": 1})
        f = jev.flag_counts(answers)
        self.assertEqual(f["censored"], {"too_cheap": {"low": 20, "high": 0}, "cheap": {"low": 0, "high": 0},
                                         "expensive": {"low": 0, "high": 0}, "too_expensive": {"low": 0, "high": 5}})
        self.assertEqual(f["nonmonotone"], {"too_cheap": 1, "cheap": 3, "expensive": 2, "too_expensive": 0})
        self.assertEqual(f["multi_cross"], {"too_cheap": 0, "cheap": 0, "expensive": 0, "too_expensive": 0})
        self.assertEqual(f["clamped"], 0)
        self.assertEqual(sum(a["jev"]["input_tokens"] for a in answers), 48418)
        # the mean the real run printed (0.3655 over 20 cards): a probability below 0.5 can move without changing buys
        self.assertEqual(round(sum(a["jev"]["p_buy"] for a in answers) / 20, 4), 0.3655)


# ── 6. the panel's own tally is unchanged ────────────────────────────────────────
class Regression(Base):
    def test_default_tally_reads_answers_and_keeps_empty_reasons(self):
        self.agent("P001", False, reason="")
        self.agent("P002", False, reason="too far")
        self.agent("P003", True, reason="")
        t = panel.tally(self.d)
        self.assertEqual(t, panel.tally(self.d, answers="answers"))
        self.assertEqual((t["buys"], t["passes"], t["answered"]), (1, 2, 3))
        self.assertEqual(t["why_not"], [("price", 2, ["", "too far"], ["P001", "P002"])])
        self.assertEqual(t["why_yes"], [("price", 1, [""], ["P003"])])
        self.assertEqual([s[0] for s in t["skipped"]], ["P%03d" % i for i in range(4, 11)])

    def test_import_and_help_open_no_socket(self):
        def refuse(*a, **k):
            raise AssertionError("a socket was opened")
        out = io.StringIO()
        with mock.patch.object(socket.socket, "connect", refuse), mock.patch.object(socket, "create_connection", refuse):
            mod = load("founder-consumer", "jev")
            with redirect_stdout(out), self.assertRaises(SystemExit) as cm:
                mod.main(["run", "--help"])
        self.assertEqual(cm.exception.code, 0)
        self.assertIn("--budget-usd", out.getvalue())

    def test_reason_texts_cover_the_panel_codes(self):
        self.assertEqual(sorted(jev.REASON_TEXT), sorted(panel.REASONS))
        self.assertTrue(all(math.isfinite(v) for v in jev.ladder(14900)))


if __name__ == "__main__":
    unittest.main()
