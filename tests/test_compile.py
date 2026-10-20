import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from _load import load, example

plan = load("founder-plan", "compile")


class Compile(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        with open(os.path.join(self.d, "idea.md"), "w") as fh:
            fh.write("# Moss Matcha Bar\n\nA walk-in matcha cafe on King St W.\n")

    def tearDown(self):
        shutil.rmtree(self.d)

    def numbers(self, **change):
        with open(example("founder-cfo", "example.json")) as fh:
            s = json.load(fh)
        s.update(change)
        with open(os.path.join(self.d, "numbers.json"), "w") as fh:
            json.dump(s, fh)

    def panel(self, buys, n=100):
        os.makedirs(os.path.join(self.d, "panel"), exist_ok=True)
        with open(os.path.join(self.d, "panel", "results.json"), "w") as fh:
            json.dump({"buys": buys, "passes": n - buys, "answered": n, "buy_rate": buys / float(n)}, fh)

    def rcf(self, metrics=None, adjustments=(), **change):
        r = {"business": "Moss Matcha Bar", "reference_classes": [{"level": 1, "name": "cafes", "why": "same"}],
             "metrics": metrics if metrics is not None else [
                 {"key": "survival_1y", "label": "1-year survival", "class_level": 1, "value": 0.6, "unit": "ratio",
                  "source": "https://example.org/report", "source_date": "2024"}],
             "adjustments": list(adjustments)}
        r.update(change)
        with open(os.path.join(self.d, "rcf.json"), "w") as fh:
            json.dump(r, fh)

    def per_day(self, key, high):
        return {"key": key, "label": key, "class_level": 1, "value": high / 2.0, "high": high, "unit": "cups_per_day",
                "source": "https://example.org/report", "source_date": "2024-01"}

    def test_no_numbers_is_incomplete(self):
        v, text = plan.compile_plan(self.d)
        self.assertEqual(v, "Incomplete")
        self.assertIn("run /founder-cfo", text)

    def test_good_numbers_and_panel_is_profitable(self):
        self.numbers()
        self.panel(40)
        self.rcf()
        v, text = plan.compile_plan(self.d)
        self.assertEqual(v, "Profitable")
        self.assertTrue(text.startswith("# Moss Matcha Bar · Business plan"))
        self.assertIn("| Profit margin at plan | 38% per cup |", text)
        self.assertIn("40 buy · 60 pass", text)
        self.assertIn("- The buyer panel: run /founder-consumer", text.replace("## Not done yet", ""))

    def test_a_weak_panel_means_not_yet(self):
        self.numbers()
        self.panel(12)
        v, text = plan.compile_plan(self.d)
        self.assertEqual(v, "Not yet")
        self.assertIn("✗ 12 of 100 simulated buyers buy", text)

    def test_losing_money_means_not_yet(self):
        self.numbers(price=3.00)
        v, _ = plan.compile_plan(self.d)
        self.assertEqual(v, "Not yet")


    def test_no_panel_fails(self):
        self.numbers()
        self.rcf()
        v, text = plan.compile_plan(self.d)
        self.assertEqual(v, "Not yet")
        self.assertIn("✗ No buyer panel yet: run /founder-consumer", text)

    def test_no_outside_view_fails(self):
        self.numbers()
        self.panel(40)
        v, text = plan.compile_plan(self.d)
        self.assertEqual(v, "Not yet")
        self.assertIn("✗ No outside view yet: run /founder-rcf", text)
        self.assertIn("- The outside view: run /founder-rcf", text)

    def test_an_outside_view_without_sources_fails(self):
        self.numbers()
        self.panel(40)
        self.rcf(metrics=[{"key": "survival_1y", "class_level": 1, "value": 0.6, "unit": "ratio"}])
        v, text = plan.compile_plan(self.d)
        self.assertEqual(v, "Not yet")
        self.assertIn("✗ The outside view fails its check", text)

    def test_optimism_above_the_reference_class_fails_unless_evidenced(self):
        self.numbers()
        self.panel(40)
        self.rcf(metrics=[self.per_day("ramp_month1_per_day", 100)])
        v, text = plan.compile_plan(self.d)
        self.assertEqual(v, "Not yet")
        self.assertIn("✗ ramp_month1_per_day in the plan is 140, above the reference class high of 100", text)
        self.rcf(metrics=[self.per_day("ramp_month1_per_day", 100)],
                 adjustments=[{"metric": "ramp_month1_per_day", "direction": "better", "evidence": "pre-sold 2,000 cups"}])
        v, text = plan.compile_plan(self.d)
        self.assertEqual(v, "Profitable")
        self.assertIn("✓ No plan number is above its reference class high without evidence (1 compared)", text)

    def test_an_example_outside_view_cannot_make_it_profitable(self):
        self.numbers()
        self.panel(40)
        self.rcf(example=True)
        v, text = plan.compile_plan(self.d)
        self.assertEqual(v, "Not yet")
        self.assertIn("example data, not real statistics", text)

    def test_outside_view_section_comes_before_the_board(self):
        self.numbers()
        self.panel(40)
        self.rcf()
        for name, body in (("rcf.md", "# Outside view\n\nBase rates."), ("board.md", "# Board\n\nVotes.")):
            with open(os.path.join(self.d, name), "w") as fh:
                fh.write(body)
        _, text = plan.compile_plan(self.d)
        self.assertLess(text.index("## The outside view"), text.index("## What the board said"))

    def test_amounts_use_the_numbers_currency(self):
        with open(example("founder-cfo", "example.kr.json"), encoding="utf-8") as fh:
            s = json.load(fh)
        with open(os.path.join(self.d, "numbers.json"), "w", encoding="utf-8") as fh:
            json.dump(s, fh, ensure_ascii=False)
        self.panel(40)
        self.rcf()
        v, text = plan.compile_plan(self.d)
        self.assertIn("Each cup earns 4,089원 before fixed costs", text)
        self.assertIn("| Price (incl. VAT) | 6,500원 a cup (5,909원 before VAT) |", text)
        self.assertIn("| Startup spend | 103,000,000원 |", text)
        self.assertNotIn("$", text.split("## The idea")[0])

    def test_bad_numbers_is_one_error_line_and_exit_2(self):
        for body in ("{not json", '{"price": 6.5}', '{"price": 6.5, "plan_per_day": "lots"}', "[]",
                     '{"price": 5, "plan_per_day": 5, "days_per_month": 0}', '{"price": 1e400, "plan_per_day": 5}',
                     '{"price": NaN, "plan_per_day": 5}', b'{"business": "\xff", "price": 5}'):
            with open(os.path.join(self.d, "numbers.json"), "wb") as fh:
                fh.write(body if isinstance(body, bytes) else body.encode())
            for argv in (["--dir", self.d], ["--dir", self.d, "--check"]):
                err, out = io.StringIO(), io.StringIO()
                with redirect_stderr(err), redirect_stdout(out):
                    code = plan.main(argv)
                self.assertEqual(code, 2, body)
                lines = err.getvalue().splitlines()
                self.assertEqual(len(lines), 1, err.getvalue())
                self.assertTrue(lines[0].startswith("error: "), lines[0])
                self.assertNotIn("Traceback", err.getvalue())

    def test_check_exit_codes(self):
        self.numbers()
        self.panel(40)
        self.rcf()
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(plan.main(["--dir", self.d, "--check"]), 0)
        self.assertIn("Verdict: Profitable", out.getvalue())
        os.remove(os.path.join(self.d, "rcf.json"))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(plan.main(["--dir", self.d, "--check"]), 1)


if __name__ == "__main__":
    unittest.main()
