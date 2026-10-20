import json
import os
import shutil
import tempfile
import unittest

from _load import load, example

panel = load("founder-consumer", "panel")


def customer():
    with open(example("founder-consumer", "customer.example.json"), encoding="utf-8") as fh:
        return json.load(fh)


class Deal(unittest.TestCase):
    def test_same_seed_same_cards(self):
        self.assertEqual(panel.deal(customer(), 100, 7), panel.deal(customer(), 100, 7))
        self.assertNotEqual(panel.deal(customer(), 100, 7), panel.deal(customer(), 100, 8))

    def test_quotas_are_exact_and_names_unique(self):
        cards = panel.deal(customer(), 100, 3)
        segs = {}
        for c in cards:
            segs[c["segment"]] = segs.get(c["segment"], 0) + 1
        self.assertEqual(segs, {"Early-career professional": 45, "Mid-career professional": 40, "High earner": 15})
        self.assertEqual(len({c["name"] for c in cards}), 100)
        self.assertEqual(cards[0]["id"], "P001")
        self.assertEqual(cards[-1]["id"], "P100")
        for c in cards:
            seg = next(s for s in customer()["segments"] if s["name"] == c["segment"])
            self.assertTrue(seg["income"][0] - 500 <= c["income"] <= seg["income"][1] + 500)
            self.assertIn(c["objection"], customer()["objections"])

    def test_bad_profile_is_refused(self):
        c = customer()
        del c["objections"]
        with self.assertRaises(panel.PanelError):
            panel.deal(c)


class Flow(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        panel.init(self.d, example("founder-consumer", "customer.example.json"),
                   example("founder-consumer", "pitch.example.md"), n=20, seed=5)

    def tearDown(self):
        shutil.rmtree(self.d)

    def answer(self, pid, buys, code="price", **extra):
        a = {"id": pid, "buys": buys, "reason_code": code, "reason": "because %s" % pid,
             "purchases_first_month": 4 if buys else 0, "would_change_my_mind": "" if buys else "a lower price"}
        a.update(extra)
        with open(os.path.join(self.d, "answers", pid + ".json"), "w") as fh:
            json.dump(a, fh)

    def test_briefs_carry_the_card_and_the_pitch(self):
        waves = panel.write_briefs(self.d, wave=10)
        self.assertEqual([len(w) for w in waves], [10, 10])
        with open(waves[0][0][1], encoding="utf-8") as fh:
            brief = fh.read()
        self.assertIn("Moss Matcha Bar", brief)
        self.assertIn('"id": "P001"', brief)
        self.assertIn("Do not be agreeable", brief)

    def test_answered_buyers_get_no_new_brief(self):
        self.answer("P001", True, "quality")
        ids = [j[0] for w in panel.write_briefs(self.d) for j in w]
        self.assertNotIn("P001", ids)
        self.assertEqual(len(ids), 19)

    def test_check_and_tally(self):
        for i in range(1, 21):
            pid = "P%03d" % i
            self.answer(pid, i <= 8, "quality" if i <= 8 else ("price" if i <= 15 else "habit"))
        # one broken answer: wrong reason code
        self.answer("P020", False, "vibes")
        probs = dict(panel.check(self.d))
        self.assertEqual(list(probs), ["P020"])
        res = panel.tally(self.d)
        self.assertEqual((res["buys"], res["passes"], res["answered"]), (8, 11, 19))
        self.assertEqual(res["why_not"][0][0], "price")
        self.assertEqual(res["why_not"][0][1], 7)
        self.assertEqual(res["skipped"][0][0], "P020")
        text = panel.results_md(res)
        self.assertIn("**8 buy · 11 pass**", text)
        self.assertIn("not customers", text)

    def test_save_files_a_printed_answer_and_refuses_junk(self):
        reply = 'Here is my answer:\n```json\n{"id": "P002", "buys": false, "reason_code": "price", "reason": "too much"}\n```'
        panel.save(self.d, "P002", reply)
        self.assertNotIn("P002", dict(panel.check(self.d)))
        with self.assertRaises(panel.PanelError):
            panel.save(self.d, "P003", '{"id": "P003", "buys": "maybe", "reason_code": "price", "reason": "x"}')
        self.assertEqual(dict(panel.check(self.d))["P003"], "missing")
        with self.assertRaises(panel.PanelError):
            panel.save(self.d, "P999", '{"id": "P999"}')

    def test_tally_with_no_answers_refuses(self):
        with self.assertRaises(panel.PanelError):
            panel.tally(self.d)



# the first three cards the original panel.py (upstream fd9385b) deals for the example, n=100, seed 7
ORIGINAL_SEED7 = [
    {"id": "P001", "name": "Mason", "age": 34, "segment": "Early-career professional", "income": 82000,
     "behaviour": "Health-first", "behaviour_how": "Reads labels, swaps coffee for anything that feels cleaner.",
     "objection": "My coffee place is closer", "habit": "you work from home three days a week"},
    {"id": "P002", "name": "June", "age": 24, "segment": "Early-career professional", "income": 39000,
     "behaviour": "Daily regular", "behaviour_how": "Buys the same drink at the same place most mornings.",
     "objection": "I'd try it once, not daily", "habit": "you walk past King St W on the way to the office"},
    {"id": "P003", "name": "Chloe", "age": 32, "segment": "High earner", "income": 195000,
     "behaviour": "Trend chaser", "behaviour_how": "Tries whatever is new and posts about it.",
     "objection": "My coffee place is closer", "habit": "you go to a gym near Spadina before work"},
]
# sha256 of json.dumps(cards, sort_keys=True) from the original panel.py
ORIGINAL_HASH = {(100, 7): "4805ca5e99cadfcc163e22bf93d2035c40fc7e615d95ae9029b35bb6a9de6e3d",
                 (250, 11): "721c0f6c58ad2fb564af95063f2b71b2d3bf3b985fc08a2356d55dd5e2e68bca"}


def kr_customer():
    with open(example("founder-consumer", "customer.kr.example.json"), encoding="utf-8") as fh:
        return json.load(fh)


def two_markets(share_kr=0.3):
    c = customer()
    kr = kr_customer()
    c["markets"] = [
        {"name": "Canada", "country": "CA", "share": 1 - share_kr, "currency": "CAD"},
        {"name": "Korea", "country": "KR", "language": "ko", "currency": "KRW", "share": share_kr,
         "target": kr["target"], "age": kr["age"], "segments": kr["segments"], "behaviours": kr["behaviours"],
         "objections": kr["objections"], "habits": kr["habits"], "pitch": "성수역 근처 말차 카페, 한 잔 6,500원."},
    ]
    return c


class Original(unittest.TestCase):
    def test_no_markets_deals_the_original_cards(self):
        import hashlib
        cards = panel.deal(customer(), 100, 7)
        self.assertEqual(cards[:3], ORIGINAL_SEED7)
        self.assertEqual([list(c) for c in cards[:3]], [list(c) for c in ORIGINAL_SEED7])
        for (n, seed), h in ORIGINAL_HASH.items():
            got = hashlib.sha256(json.dumps(panel.deal(customer(), n, seed), sort_keys=True).encode()).hexdigest()
            self.assertEqual(got, h, (n, seed))

    def test_english_brief_keeps_the_original_wording(self):
        d = tempfile.mkdtemp()
        try:
            panel.init(d, example("founder-consumer", "customer.example.json"),
                       example("founder-consumer", "pitch.example.md"), n=100, seed=7)
            with open(panel.write_briefs(d)[0][0][1], encoding="utf-8") as fh:
                brief = fh.read()
        finally:
            shutil.rmtree(d)
        self.assertIn("Mason, 34. Early-career professional. You earn about $82,000 a year.", brief)
        self.assertIn('"price_too_expensive": the price at which you would not buy it at all (a number)\n}', brief)


class Markets(unittest.TestCase):
    def test_shares_are_exact(self):
        for n, want in ((100, {"Canada": 70, "Korea": 30}), (7, {"Canada": 5, "Korea": 2}), (1, {"Canada": 1})):
            got = {}
            for c in panel.deal(two_markets(), n, 4):
                got[c["market"]] = got.get(c["market"], 0) + 1
            self.assertEqual(got, want, n)

    def test_cards_carry_market_language_currency_and_unique_names(self):
        cards = panel.deal(two_markets(0.5), 200, 9)
        self.assertEqual([c["id"] for c in cards], ["P%03d" % i for i in range(1, 201)])
        self.assertEqual(len({c["name"] for c in cards}), 200)
        for c in cards:
            if c["market"] == "Korea":
                self.assertEqual((c["language"], c["currency"]), ("ko", "KRW"))
                self.assertIn(c["name"], panel.KO_NAMES)
                self.assertTrue(30000000 - 50000 <= c["income"] <= 130000000 + 50000)
                self.assertEqual(c["income"] % 100000, 0)
            else:
                self.assertEqual((c["language"], c["currency"]), ("en", "CAD"))
                self.assertIn(c["name"], panel.FIRST_NAMES)
        self.assertEqual(panel.deal(two_markets(0.5), 200, 9), cards)

    def test_lowercase_currency_is_read_as_upper(self):
        c = two_markets(0.5)
        c["markets"][1]["currency"] = "krw"
        kr = [x for x in panel.deal(c, 20, 3) if x["market"] == "Korea"]
        self.assertTrue(kr)
        for x in kr:
            self.assertEqual(x["currency"], "KRW")
            self.assertEqual(x["income"] % 100000, 0)

    def test_korean_names(self):
        self.assertGreaterEqual(len(panel.KO_NAMES), 120)
        self.assertEqual(len(set(panel.KO_NAMES)), len(panel.KO_NAMES))
        for name in panel.KO_NAMES:
            self.assertGreaterEqual(len(name), 2)
        cards = panel.deal(kr_customer(), 300, 2)
        self.assertEqual(len({c["name"] for c in cards}), 300)

    def test_bad_markets_are_refused(self):
        for markets in ([], [{"share": 1}], [{"name": "A"}, {"name": "A"}], [{"name": "A", "share": "lots"}],
                        [{"name": "A", "language": "fr"}], [{"name": "A", "share": 0}]):
            c = customer()
            c["markets"] = markets
            with self.assertRaises(panel.PanelError, msg=markets):
                panel.deal(c, 10)


class KoreanFlow(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d)

    def test_korean_brief(self):
        panel.init(self.d, example("founder-consumer", "customer.kr.example.json"),
                   example("founder-consumer", "pitch.kr.example.md"), n=5, seed=1)
        with open(panel.write_briefs(self.d)[0][0][1], encoding="utf-8") as fh:
            brief = fh.read()
        _, cards = panel.load_state(self.d)
        self.assertIn("%s, %d세." % (cards[0]["name"], cards[0]["age"]), brief)
        self.assertIn("연 소득은 약 %s입니다." % panel.money(cards[0]["income"], "KRW"), brief)
        self.assertRegex(brief, r"연 소득은 약 [0-9]{2,3},[0-9]{3},000원입니다")
        for needle in ("예의상 산다고 하지 마세요", "사실을 지어내지 마세요", "맞장구치지 마세요", "성수역",
                       "당신 말투", "reason_code 값은 영어 그대로", "KRW", '"id": "P001"',
                       " / ".join(panel.REASONS)):
            self.assertIn(needle, brief)
        for key in ("id", "buys", "purchases_first_month", "reason_code", "reason", "objection", "would_change_my_mind",
                    "price_too_cheap", "price_cheap", "price_expensive", "price_too_expensive"):
            self.assertIn('"%s":' % key, brief)

    def test_market_briefs_and_tally_by_market(self):
        path = os.path.join(self.d, "customer.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(two_markets(0.5), fh, ensure_ascii=False)
        cards = panel.init(self.d, path, example("founder-consumer", "pitch.example.md"), n=20, seed=3)
        briefs = {}
        for w in panel.write_briefs(self.d):
            for pid, bp in w:
                with open(bp, encoding="utf-8") as fh:
                    briefs[pid] = fh.read()
        for c in cards:
            b = briefs[c["id"]]
            if c["market"] == "Korea":
                self.assertIn("성수역 근처 말차 카페", b)
                self.assertIn("원입니다", b)
            else:
                self.assertIn("Moss Matcha Bar", b)
                self.assertIn("You earn about $", b)
                self.assertIn("(a number in CAD)", b)
        for i, c in enumerate(cards):
            with open(os.path.join(self.d, "answers", c["id"] + ".json"), "w") as fh:
                json.dump({"id": c["id"], "buys": c["market"] == "Korea" and i % 2 == 0, "reason_code": "price",
                           "reason": "x"}, fh)
        res = panel.tally(self.d)
        markets = {k: (n, r) for k, n, r in res["by_market"]}
        self.assertEqual(markets["Korea"][0], 10)
        self.assertEqual(markets["Canada"], (10, 0.0))
        bands = [k for k, _, _ in res["by_income"]]
        self.assertTrue(all(k.startswith(("Korea: ", "Canada: ")) for k in bands), bands)
        self.assertTrue(all("원" in k and "$" not in k for k in bands if k.startswith("Korea")), bands)
        self.assertTrue(all("$" in k and "원" not in k for k in bands if k.startswith("Canada")), bands)
        self.assertIn("## By market", panel.results_md(res))

    def test_one_currency_panel_has_no_market_table(self):
        panel.init(self.d, example("founder-consumer", "customer.example.json"),
                   example("founder-consumer", "pitch.example.md"), n=6, seed=3)
        for i in range(1, 7):
            with open(os.path.join(self.d, "answers", "P%03d.json" % i), "w") as fh:
                json.dump({"id": "P%03d" % i, "buys": i < 3, "reason_code": "price", "reason": "x"}, fh)
        res = panel.tally(self.d)
        self.assertNotIn("by_market", res)
        self.assertTrue(any(k.startswith("under $") for k, _, _ in res["by_income"]))


if __name__ == "__main__":
    unittest.main()
