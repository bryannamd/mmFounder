import csv
import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from _load import load

vw = load("founder-pricing", "van_westendorp")


def rows(n=40):
    out = []
    for i in range(n):
        k = i / float(n - 1)
        out.append((2.5 + k, 4.0 + k, 6.0 + 1.5 * k, 7.5 + 2 * k))
    return out


class Pricing(unittest.TestCase):
    def test_points_are_ordered_and_inside_the_answers(self):
        res = vw.analyse(rows())
        p = res["points"]
        for k in ("PMC", "PME", "OPP", "IPP"):
            self.assertIsNotNone(p[k], k)
            self.assertTrue(2.5 <= p[k] <= 9.5, (k, p[k]))
        self.assertLess(p["PMC"], p["PME"])
        self.assertLessEqual(p["PMC"], p["OPP"])
        self.assertLessEqual(p["OPP"], p["PME"])

    def test_out_of_order_and_incomplete_rows_are_dropped(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "p.csv")
        with open(path, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(vw.KEYS)
            for r in rows(10):
                w.writerow(r)
            w.writerow((9, 4, 6, 8))       # too cheap above a bargain: out of order
            w.writerow((3, "", 6, 8))      # incomplete
        got, dropped = vw.read(path)
        self.assertEqual((len(got), dropped), (10, 2))

    def test_too_few_answers_is_refused(self):
        with self.assertRaises(vw.PricingError):
            vw.analyse(rows(4))

    def test_report_places_the_price(self):
        res = vw.analyse(rows())
        self.assertIn("**inside** the acceptable range", vw.report(res, 0, price=6.5))
        self.assertIn("**above** the acceptable range", vw.report(res, 0, price=40))


    def test_won_signs_and_spaces_are_stripped(self):
        for v in ("₩6,500", "6,500원", "6 500", " 6500 원 "):
            self.assertEqual(vw._f(v), 6500.0, v)
        self.assertEqual(vw._f("$6.50"), 6.5)

    def test_krw_grid_steps_in_10_won(self):
        grids = []
        real = vw.curves
        vw.curves = lambda r, g: (grids.append(g), real(r, g))[1]
        try:
            res = vw.analyse([tuple(v * 1000 for v in r) for r in rows()], currency="KRW")
        finally:
            vw.curves = real
        steps = {round(b - a, 6) for a, b in zip(grids[0], grids[0][1:])}
        self.assertEqual(steps, {20.0})
        text = vw.report(res, 0, price=6500, currency="KRW")
        self.assertIn("6,500원", text)
        self.assertNotIn("$", text)

    def test_krw_grid_never_below_10_won(self):
        grids = []
        real = vw.curves
        vw.curves = lambda r, g: (grids.append(g), real(r, g))[1]
        try:
            vw.analyse([(3000 + i, 4000 + i, 5000 + i, 5500 + i) for i in range(10)], currency="KRW")
        finally:
            vw.curves = real
        self.assertEqual({round(b - a, 6) for a, b in zip(grids[0], grids[0][1:])}, {10.0})


class Markets(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.d, "answers"))
        cards = []
        for i, (r, mk, cur) in enumerate([(r, "Canada", "CAD") for r in rows(8)] +
                                         [(tuple(v * 1000 for v in r), "Korea", "KRW") for r in rows(6)], 1):
            pid = "P%03d" % i
            cards.append({"id": pid, "market": mk, "currency": cur})
            with open(os.path.join(self.d, "answers", pid + ".json"), "w") as fh:
                json.dump(dict(id=pid, **{"price_" + k: v for k, v in zip(vw.KEYS, r)}), fh)
        with open(os.path.join(self.d, "personas.json"), "w") as fh:
            json.dump(cards, fh)
        self.answers = os.path.join(self.d, "answers")

    def tearDown(self):
        shutil.rmtree(self.d)

    def test_mixed_currencies_need_a_market(self):
        with self.assertRaises(vw.PricingError) as e:
            vw.read(self.answers)
        self.assertIn("--market", str(e.exception))
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(vw.main([self.answers]), 2)
        self.assertIn("give --market", err.getvalue())

    def test_a_market_counts_only_its_buyers(self):
        self.assertEqual(len(vw.read(self.answers, "Canada")[0]), 8)
        got, _ = vw.read(self.answers, "Korea")
        self.assertEqual(len(got), 6)
        self.assertTrue(all(r[0] >= 2500 for r in got))
        with self.assertRaises(vw.PricingError):
            vw.read(self.answers, "Japan")

    def test_market_sets_the_currency(self):
        out = os.path.join(self.d, "curve.md")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(vw.main([self.answers, "--market", "Korea", "--out", out]), 0)
        with open(out, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("원", text)
        self.assertNotIn("$", text)

    def test_currency_defaults_to_the_panels(self):
        with open(os.path.join(self.d, "personas.json"), "w") as fh:
            json.dump([{"id": "P%03d" % i} for i in range(1, 15)], fh)
        with open(os.path.join(self.d, "panel.json"), "w") as fh:
            json.dump({"customer": {"currency": "KRW"}}, fh)
        out = os.path.join(self.d, "curve.md")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(vw.main([self.answers, "--out", out]), 0)
        with open(out, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("원", text)
        self.assertNotIn("$", text)

    def test_one_currency_panel_needs_no_market(self):
        with open(os.path.join(self.d, "personas.json"), "w") as fh:
            json.dump([{"id": "P%03d" % i} for i in range(1, 15)], fh)
        self.assertEqual(len(vw.read(self.answers)[0]), 14)


if __name__ == "__main__":
    unittest.main()
