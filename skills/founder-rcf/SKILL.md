---
name: founder-rcf
description: >-
  The outside view. Before anyone falls in love with the plan, this skill asks
  what happened to businesses like it: it names three reference classes from
  narrow to wide, collects base rates for each (survival, how fast early sales
  grow, ticket and margin ranges, why they closed, and for online businesses the
  conversion rate and cost per customer), every number with a link and a date,
  and checks the plan's own numbers against them. Reference class forecasting, as
  in Daniel Kahneman's and Bent Flyvbjerg's work on the planning fallacy. Use when
  the user says "what are the odds", "how do businesses like this do", "base
  rate", "outside view", "is my forecast realistic", "reference class", or starts
  the founder pack on a new idea.
argument-hint: "<the business, or leave blank to use founder/idea.md>"
---

# founder-rcf

Every founder has an inside view: their own plan, their own reasons it will work.
The outside view asks a different question. Of the businesses that looked like
this one, how many survived, and how fast did the survivors grow? Start there,
and move away from it only as far as evidence allows.

What the user typed after `/founder-rcf`: `$ARGUMENTS`. If that is blank, take the
business from `founder/idea.md` (write it first if missing; see `/founder-board`
step 0).

Tool in this folder:

```bash
python3 "${CLAUDE_SKILL_DIR}/rcf.py" check founder/rcf.json
```

## The rules

- **No number without a source.** Every base rate has a link and a date, and a title
  when the source has one.
  If you cannot find a source, leave the metric out and say what is missing. Never
  fill a gap from memory or from a guess. `rcf.py check` rejects a metric with no
  source.
- **This skill needs the web.** Use a web search or fetch tool to find the sources.
  If you have none, say so and ask the user for the material: links, reports,
  PDFs, a trade association's figures, their own records from similar ventures.
  Work only from what they give you.
- **Read, do not scrape.** Read pages as a person would. Respect each site's terms.
- **Say what the number measures.** A survival rate for all new establishments is
  not a survival rate for specialty cafés. Put each metric in the class it
  describes, and note where the match is loose.

## Step 1: three reference classes

From `founder/idea.md`, name three groups of past businesses, from the narrowest
that is still big enough to have statistics to the widest:

| level | what it is | example for a matcha café |
| --- | --- | --- |
| 1 | closest match | specialty tea and matcha bars in a dense city |
| 2 | the same trade | independent cafés |
| 3 | the same kind of venture | new small food-service businesses |

For each, write why it is a fair comparison. A narrow class with no data is not
better than a wide one with data; keep all three so the numbers can be read
together.

## Step 2: collect the base rates

Search for each of these, per class where the data exists:

- **Survival**: the share still operating after 1, 3 and 5 years.
- **How early sales grow**: sales or customers per day in month 1 and month 3, or
  the typical ramp. This is the number the CFO's ramp is checked against.
- **Ticket and margin**: the range of price per sale and of gross or contribution
  margin.
- **Why they closed**: the reasons, ranked, from surveys or post-mortems.
- **Online businesses**: conversion rate and cost to win a customer, and for apps
  or subscriptions the first-year retention.

Public sources worth trying outside Korea: the US Bureau of Labor Statistics
Business Employment Dynamics (survival of new establishments by year started,
`https://www.bls.gov/bdm/`), TrustMRR (revenue of startups verified through their
payment account, `https://trustmrr.com`), and for subscription apps RevenueCat's
State of Subscription Apps report
(`https://www.revenuecat.com/state-of-subscription-apps`). Add the statistics
office or trade association of the user's own country. If
`founder/locale.json` says `"country": "KR"`, read `sources-kr.md` in this skill's
folder (`${CLAUDE_SKILL_DIR}/sources-kr.md`) for the Korean starting points.

Keep the raw findings in `founder/rcf-sources.md`: link, date read, what was taken.

## Step 3: write `founder/rcf.json`

Shape: `rcf.example.json` in this folder (an example with `"example": true`; real
files set it to `false`).

```json
{
  "business": "...",
  "example": false,
  "reference_classes": [
    {"level": 1, "name": "...", "why": "why it is a fair comparison"},
    {"level": 2, "name": "...", "why": "..."},
    {"level": 3, "name": "...", "why": "..."}
  ],
  "metrics": [
    {"key": "survival_1y", "label": "1-year survival", "class_level": 3,
     "value": 0.641, "low": null, "high": null, "unit": "ratio",
     "source": "https://...", "source_title": "...", "source_date": "2023-12-21", "note": ""}
  ],
  "failure_reasons": [{"reason": "...", "source": "https://..."}],
  "adjustments": [{"metric": "ramp_month1_per_day", "direction": "better", "evidence": "why this plan beats the class, in terms someone can check"}],
  "kill_criteria": [{"metric": "units_per_day_month2", "below": 120, "action": "revisit price and offer"}]
}
```

- `key` names the metric. The ones that `rcf.py compare` can set against the plan
  are `ramp_month1_per_day`, `ramp_month3_per_day`, `plan_per_day`,
  `contribution_pct` and `margin_at_plan` (shares as ratios, 0.38 for 38%). A
  `buy_rate` or `conversion_rate` is shown next to the panel's buy rate for
  information only. Any other key (`survival_5y`, `cac`) is carried into the
  report without a comparison.
- `value` is the middle of the class (median if the source gives one). `low` and
  `high` are the range the source reports, if it does. A plan above `high` is the
  warning sign.
- `adjustments` is where the founder argues the plan is better than the class.
  Each entry needs evidence a stranger could check (a signed lease in a street with
  more foot traffic, a waitlist of 300, a supplier price). "We will work harder" is
  not evidence.

## Step 4: check it

```bash
python3 "${CLAUDE_SKILL_DIR}/rcf.py" check founder/rcf.json
```

It fails (exit code 1) if a metric has no number, unit, link, date or a class that
exists, or if `low <= value <= high` does not hold. Fix the file, not the check.
An `"example": true` file prints a warning that it is example data, not real
statistics.

## Step 5: compare with the plan

Needs `founder/numbers.json` (run `/founder-cfo` first, or compare once the CFO's
inputs exist):

```bash
python3 "${CLAUDE_SKILL_DIR}/rcf.py" compare --rcf founder/rcf.json --numbers founder/numbers.json \
  --panel founder/panel/results.json --out founder/rcf-compare.md
```

`--panel` is optional. The table says for each metric whether the plan is inside
the class, above its `high` (fail, unless an `adjustments` entry gives evidence;
then it shows as an optimism with evidence), or above the median with no range
(warning). Read it from the outside in: start at the class value, then move toward
the plan only as far as the evidence in `adjustments` carries you.

## Step 6: the outside view

Write `founder/rcf.md`, plain words, one page:

1. **The reference classes** and why each is a fair comparison.
2. **The base rates** as a table: metric, class, value and range, source link, date.
3. **Where the plan is better and where it is worse** than the class, one line each,
   from `rcf-compare.md`. Say which differences have evidence and which are hope.
4. **The odds in one sentence**, e.g. "Of businesses like this, about two in three
   are still open after a year", with the source. Do not invent a probability that
   no source gives.
5. **Kill criteria**: the numbers that, if the real business falls below them, mean
   stop or change course, each with the action. `/founder-launch` reads these.

## Output

`founder/rcf.json`, `founder/rcf-sources.md`, `founder/rcf-compare.md`,
`founder/rcf.md`. Then say the odds in one line and name the biggest gap between
the plan and the class. Next: `/founder-board` (it adds an Outside View seat when
`founder/rcf.md` exists), or `/founder-cfo` to bring the ramp down to what the
evidence supports.

## Where the pack goes next

```
rcf -> board -> competitors -> consumer -> pricing -> offer -> cfo -> marketing -> brand -> ops -> launch -> plan
```

Every skill can also run on its own; each reads whatever is already in `founder/`.

## Honest limits, say them once

A base rate is a statement about the past of other businesses, not a forecast for
this one. Classes are never a perfect match, and the best sources are often
national or old. The outside view tells you where to start the argument; the
founder's evidence moves the number from there. Not financial, legal or tax advice.
