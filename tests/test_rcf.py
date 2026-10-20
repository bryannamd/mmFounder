import copy
import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from _load import load, example

rcf = load("founder-rcf", "rcf")
ue = load("founder-cfo", "unit_economics")


def sample():
    with open(example("founder-rcf", "rcf.example.json"), encoding="utf-8") as fh:
        return json.load(fh)


def numbers():
    with open(example("founder-cfo", "example.kr.json"), encoding="utf-8") as fh:
        return json.load(fh)


def metric(key, value, high=None, low=None, unit="cups_per_day", **extra):
    m = {"key": key, "label": key, "class_level": 1, "value": value, "low": low, "high": high, "unit": unit,
         "source": "https://example.org/report", "source_date": "2024-05"}
    m.update(extra)
    return m


def one(metrics, adjustments=()):
    return {"business": "test", "reference_classes": [{"level": 1, "name": "cafes", "why": "same"}],
            "metrics": list(metrics), "adjustments": list(adjustments)}


def run(spec, r, panel=None):
    return {row["key"]: row for row in rcf.compare(r, spec, ue.analyse(spec), panel)}


class Check(unittest.TestCase):
    def test_the_example_passes_with_a_warning(self):
        problems, warnings = rcf.check(sample())
        self.assertEqual(problems, [])
        self.assertEqual(len(warnings), 1)
        self.assertIn("example data, not real statistics", warnings[0])
        for m in sample()["metrics"]:
            self.assertIn("illustrative", m["note"])

    def test_a_number_without_a_source_fails(self):
        for change in ({"source": ""}, {"source": "kosis"}, {"source": None}, {"source_date": "May 2024"},
                       {"source_date": "2024-5"}, {"source_date": "2024-13"}, {"value": "65%"}, {"value": True},
                       {"unit": ""}, {"class_level": 9}, {"key": ""}):
            r = sample()
            r["metrics"][0].update(change)
            problems, _ = rcf.check(r)
            self.assertEqual(len(problems), 1, (change, problems))
        r = sample()
        del r["metrics"][1]["source"]
        self.assertIn("needs a 'source'", rcf.check(r)[0][0])

    def test_dates_in_three_shapes_pass(self):
        for d in ("2023-12-21", "2023-12", "2023"):
            r = one([metric("survival_1y", 0.6, unit="ratio", source_date=d)])
            self.assertEqual(rcf.check(r)[0], [], d)

    def test_an_inverted_range_fails(self):
        for low, value, high in ((0.8, 0.6, 0.9), (0.1, 0.6, 0.5), (0.7, 0.6, 0.5)):
            r = one([metric("survival_1y", value, high=high, low=low, unit="ratio")])
            problems, _ = rcf.check(r)
            self.assertTrue(problems, (low, value, high))
        self.assertEqual(rcf.check(one([metric("survival_1y", 0.6, high=0.6, low=0.6, unit="ratio")]))[0], [])

    def test_no_metrics_or_classes_fails(self):
        self.assertTrue(rcf.check({"metrics": []})[0])
        self.assertTrue(rcf.check(one([]))[0])
        r = one([metric("plan_per_day", 100)])
        r["reference_classes"] = []
        self.assertTrue(rcf.check(r)[0])


class Compare(unittest.TestCase):
    def test_optimism_above_high_fails(self):
        rows = run(numbers(), one([metric("ramp_month1_per_day", 60, high=80)]))
        self.assertEqual(rows["ramp_month1_per_day"]["status"], "fail")
        self.assertEqual(rows["ramp_month1_per_day"]["plan"], 90)
        self.assertEqual(len(rcf.failures(list(rows.values()))), 1)

    def test_evidence_turns_a_fail_into_justified(self):
        adj = [{"metric": "ramp_month1_per_day", "direction": "better", "evidence": "300 pre-sold cups"}]
        rows = run(numbers(), one([metric("ramp_month1_per_day", 60, high=80)], adj))
        self.assertEqual(rows["ramp_month1_per_day"]["status"], "justified")
        self.assertIn("300 pre-sold cups", rows["ramp_month1_per_day"]["text"])
        empty = [{"metric": "ramp_month1_per_day", "direction": "better", "evidence": "  "}]
        rows = run(numbers(), one([metric("ramp_month1_per_day", 60, high=80)], empty))
        self.assertEqual(rows["ramp_month1_per_day"]["status"], "fail")

    def test_above_the_median_with_no_high_is_a_warning(self):
        rows = run(numbers(), one([metric("plan_per_day", 180), metric("ramp_month3_per_day", 150)]))
        self.assertEqual(rows["plan_per_day"]["status"], "warn")
        self.assertEqual(rows["ramp_month3_per_day"]["status"], "ok")
        self.assertEqual(rcf.failures(list(rows.values())), [])

    def test_ratios_and_inside_the_range(self):
        a = ue.analyse(numbers())
        rows = run(numbers(), one([metric("contribution_pct", 0.6, high=a["contribution_pct"], unit="ratio"),
                                   metric("margin_at_plan", 0.1, high=0.2, unit="ratio")]))
        self.assertEqual(rows["contribution_pct"]["status"], "ok")
        self.assertEqual(rows["margin_at_plan"]["status"], "fail")
        rows = run(numbers(), one([metric("margin_at_plan", 10, high=20, unit="percent")]))
        self.assertEqual(rows["margin_at_plan"]["status"], "skipped")

    def test_missing_plan_numbers_are_skipped(self):
        s = numbers()
        del s["ramp_per_day"]
        rows = run(s, one([metric("ramp_month1_per_day", 60, high=80)]))
        self.assertEqual(rows["ramp_month1_per_day"]["status"], "skipped")

    def test_panel_and_other_keys_are_shown_only(self):
        r = one([metric("buy_rate", 0.2, high=0.25, unit="ratio"), metric("survival_1y", 0.6, unit="ratio")])
        rows = run(numbers(), r, panel={"buy_rate": 0.9})
        self.assertEqual(rows["buy_rate"]["status"], "info")
        self.assertEqual(rows["buy_rate"]["plan"], 0.9)
        self.assertEqual(rows["survival_1y"]["status"], "info")

    def test_the_example_pair(self):
        rows = rcf.compare(sample(), numbers(), ue.analyse(numbers()))
        status = {r["key"]: r["status"] for r in rows}
        self.assertEqual(status, {"survival_1y": "info", "ramp_month1_per_day": "ok", "ramp_month3_per_day": "justified",
                                  "plan_per_day": "warn", "contribution_pct": "ok", "margin_at_plan": "ok",
                                  "buy_rate": "info"})
        text = rcf.report_md(sample(), rows, rcf.check(sample())[1])
        self.assertIn("example data, not real statistics", text)
        self.assertIn("## Kill criteria", text)


class Cli(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d)

    def write(self, name, obj):
        path = os.path.join(self.d, name)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False)
        return path

    def main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = rcf.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_exit_codes(self):
        good = example("founder-rcf", "rcf.example.json")
        self.assertEqual(self.main("check", good)[0], 0)
        bad = copy.deepcopy(sample())
        bad["metrics"][0]["source"] = ""
        code, out, _ = self.main("check", self.write("bad.json", bad))
        self.assertEqual(code, 1)
        self.assertIn("check failed: 1 problem", out)
        self.assertEqual(self.main("check", os.path.join(self.d, "none.json"))[0], 2)
        with open(os.path.join(self.d, "junk.json"), "w") as fh:
            fh.write("{not json")
        code, _, err = self.main("check", os.path.join(self.d, "junk.json"))
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("error: "))

    def test_compare_exits_1_on_unjustified_optimism(self):
        nums = example("founder-cfo", "example.kr.json")
        code, out, _ = self.main("compare", "--rcf", example("founder-rcf", "rcf.example.json"), "--numbers", nums)
        self.assertEqual(code, 0)
        self.assertIn("| 셋째 달 하루 판매량 | 1 | 130 | 100 | 120 | justified", out)
        r = self.write("r.json", one([metric("ramp_month1_per_day", 60, high=80)]))
        out_md = os.path.join(self.d, "rcf-compare.md")
        code, _, _ = self.main("compare", "--rcf", r, "--numbers", nums, "--out", out_md)
        self.assertEqual(code, 1)
        with open(out_md, encoding="utf-8") as fh:
            self.assertIn("more optimistic than its reference class", fh.read())


if __name__ == "__main__":
    unittest.main()
