import io
import json
import math
import unittest
from contextlib import redirect_stdout

from _load import load, example

ue = load("founder-cfo", "unit_economics")


def spec():
    with open(example("founder-cfo", "example.json"), encoding="utf-8") as fh:
        return json.load(fh)


class UnitEconomics(unittest.TestCase):
    def test_example_reproduces_the_plan(self):
        a = ue.analyse(spec())
        self.assertAlmostEqual(a["contribution"], 4.76, places=2)
        self.assertEqual(round(a["margin_at_plan"] * 100), 38)
        self.assertEqual(math.ceil(a["breakeven_per_day"]), 186)
        self.assertEqual(round(a["year1_profit"]), 93926)
        self.assertEqual(a["startup"], 25280)
        self.assertEqual(a["payback_month"], 8)
        self.assertEqual(round(a["cash_needed"]), 34092)
        self.assertEqual(a["flags"], [])

    def test_price_below_variable_cost_is_flagged(self):
        s = spec()
        s["price"] = 1.50
        a = ue.analyse(s)
        self.assertTrue(math.isinf(a["breakeven_per_day"]))
        self.assertTrue(any("loses money" in f for f in a["flags"]))

    def test_breakeven_above_capacity_is_flagged(self):
        s = spec()
        s["capacity_per_day"] = 150
        a = ue.analyse(s)
        self.assertTrue(any("capacity is 150" in f for f in a["flags"]))

    def test_what_ifs_move_the_right_way(self):
        base = ue.analyse(spec())
        cheaper = ue.analyse(spec(), price=base["price"] * 0.9)
        fewer = ue.analyse(spec(), volume=0.8)
        self.assertLess(cheaper["year1_profit"], base["year1_profit"])
        self.assertGreater(cheaper["breakeven_per_day"], base["breakeven_per_day"])
        self.assertLess(fewer["year1_profit"], base["year1_profit"])
        self.assertEqual(len(ue.sensitivity(spec())), 4)

    def test_bad_input_is_refused_not_guessed(self):
        s = spec()
        s["ramp_per_day"] = [100] * 11
        with self.assertRaises(ue.NumbersError):
            ue.analyse(s)
        s = spec()
        del s["price"]
        with self.assertRaises(ue.NumbersError):
            ue.analyse(s)
        s = spec()
        s["variable"][0]["cost"] = "lots"
        with self.assertRaises(ue.NumbersError):
            ue.analyse(s)

    def test_report_mentions_the_key_numbers(self):
        s = spec()
        text = ue.report(s, ue.analyse(s))
        for needle in ("$4.76", "186 cups a day", "**38%**", "$93,926", "month 8"):
            self.assertIn(needle, text)



def kr_spec():
    with open(example("founder-cfo", "example.kr.json"), encoding="utf-8") as fh:
        return json.load(fh)


class Currency(unittest.TestCase):
    def test_full_amounts_with_separators(self):
        self.assertEqual(ue.money(1234.5), "$1,234.50")
        self.assertEqual(ue.money(-4.76), "-$4.76")
        self.assertEqual(ue.money(1234.5, "CAD"), "$1,234.50")
        self.assertEqual(ue.money(1234.5, "EUR"), "€1,234.50")
        self.assertEqual(ue.money(1234.5, "GBP"), "£1,234.50")
        self.assertEqual(ue.money(1234.6, "JPY"), "¥1,235")
        self.assertEqual(ue.money(6500, "KRW"), "6,500원")
        self.assertEqual(ue.money(-6500, "krw"), "-6,500원")
        self.assertEqual(ue.money(45000000, "KRW"), "45,000,000원")
        self.assertEqual(ue.money(2580000.4, "USD", whole=True), "$2,580,000")
        self.assertEqual(ue.money(1234.5, "CHF"), "CHF 1,234.50")

    def test_no_currency_means_the_original_report(self):
        s = spec()
        a = ue.analyse(s)
        self.assertEqual(a["currency"], "USD")
        self.assertEqual(a["price"], a["net_price"])
        text = ue.report(s, a)
        self.assertIn("| Price | $6.50 |", text)
        self.assertNotIn("VAT", text)

    def test_krw_report_shows_won_in_full(self):
        s = kr_spec()
        text = ue.report(s, ue.analyse(s))
        self.assertIn("16,000,000원 a month", text)
        self.assertIn("**4,089원** (69%)", text)
        self.assertNotIn("$", text)
        self.assertNotRegex(text, r"\d[KM]\b")

    def test_bad_currency_or_vat_is_refused(self):
        for change in ({"currency": 7}, {"price_includes_vat": "yes"}, {"price_includes_vat": True, "vat_rate": 10},
                       {"price_includes_vat": True, "vat_rate": "ten"}):
            s = kr_spec()
            s.update(change)
            with self.assertRaises(ue.NumbersError, msg=change):
                ue.analyse(s)


class Vat(unittest.TestCase):
    def test_sums_use_the_price_before_vat(self):
        a = ue.analyse(kr_spec())
        net = 6500 / 1.1
        self.assertEqual(a["price"], 6500)
        self.assertAlmostEqual(a["net_price"], net, places=6)
        self.assertAlmostEqual(a["contribution"], net - 1820, places=6)
        self.assertAlmostEqual(a["contribution_pct"], (net - 1820) / net, places=9)
        self.assertAlmostEqual(a["breakeven_per_day"], 16000000 / ((net - 1820) * 30), places=6)
        self.assertEqual(math.ceil(a["breakeven_per_day"]), 131)
        self.assertAlmostEqual(a["months"][0]["revenue"], 90 * 30 * net, places=4)
        self.assertAlmostEqual(a["margin_at_plan"], ((net - 1820) - 16000000 / (220 * 30.0)) / net, places=9)

    def test_vat_off_uses_the_price_as_given(self):
        s = kr_spec()
        s["price_includes_vat"] = False
        a = ue.analyse(s)
        self.assertEqual(a["net_price"], 6500)
        self.assertAlmostEqual(a["contribution"], 6500 - 1820)

    def test_what_ifs_take_vat_off_once(self):
        rows = dict(ue.sensitivity(kr_spec()))
        self.assertAlmostEqual(rows["Price -10%"]["net_price"], 6500 * 0.9 / 1.1, places=6)
        self.assertAlmostEqual(rows["Volume -20%"]["net_price"], 6500 / 1.1, places=6)
        path = example("founder-cfo", "example.kr.json")
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(ue.main([path, "--json", "--price", "7700", "--volume", "0.8"]), 0)
        a = json.loads(out.getvalue())
        self.assertAlmostEqual(a["net_price"], 7000, places=6)
        self.assertAlmostEqual(a["months"][0]["revenue"], 90 * 0.8 * 30 * 7000, places=4)

    def test_default_rate_is_ten_percent(self):
        s = kr_spec()
        del s["vat_rate"]
        self.assertAlmostEqual(ue.analyse(s)["net_price"], 6500 / 1.1)

    def test_what_if_price_follows_the_vat_setting(self):
        a = ue.analyse(kr_spec(), price=7700)
        self.assertAlmostEqual(a["net_price"], 7000)

    def test_report_shows_both_prices_and_the_tax_note(self):
        s = kr_spec()
        text = ue.report(s, ue.analyse(s))
        self.assertIn("| Price (incl. 10% VAT) | 6,500원 |", text)
        self.assertIn("| Price before VAT (what the business keeps) | 5,909원 |", text)
        self.assertIn("간이과세자", text)
        self.assertIn("세무사", text)


if __name__ == "__main__":
    unittest.main()
