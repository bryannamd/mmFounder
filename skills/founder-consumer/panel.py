#!/usr/bin/env python3
"""The buyer panel for founder-consumer. Standard library only, no network.

It does the bookkeeping for a swarm of simulated buyers: it deals one persona card
per buyer from your target-customer profile (income, age, behaviour, objection),
writes one brief per buyer for a sub-agent to answer, checks the answers, and
tallies who buys, who doesn't, and why.

    python3 panel.py init --customer founder/customer.json --pitch founder/pitch.md [--n 100] [--seed 7]
    python3 panel.py prompts [--wave 10]     # one brief per buyer still to run, listed in waves
    python3 panel.py check                   # which answers are missing or broken
    python3 panel.py save P003 < reply.txt   # file a buyer's own JSON that it printed instead of writing
    python3 panel.py tally [--out founder/panel/results.md]
    python3 panel.py status

State lives in founder/panel/ (--dir to change it): panel.json, personas.json,
briefs/<id>.md, answers/<id>.json, results.md, results.json.

customer.json may also set "language" ("en" or "ko", for the briefs and the
names), "currency" (for incomes and price answers) and "markets": a list of
countries, each with a "name" and a "share" of the buyers. A market can set its
own target, age, segments, behaviours, objections, habits, language, currency
and pitch; anything it leaves out comes from the top of customer.json. Without
"markets" the cards are dealt exactly as before.

The tool never answers for a buyer. Every number in results.md is counted from
the answer files the sub-agents wrote. Simulated buyers are a fast, cheap way to
find objections and weak spots. They are not customers: confirm what matters
with real ones (a pre-sale, a waitlist, a landing page with a price on it).
"""

import argparse
import importlib.util
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

FIRST_NAMES = [
    "Maya", "Jordan", "Priya", "Marcus", "Sofia", "Ethan", "Aisha", "Liam", "Chloe", "Daniel", "Nadia", "Owen",
    "Grace", "Ravi", "Emma", "Kenji", "Zoe", "Luca", "Hana", "Noah", "Fatima", "Caleb", "Isla", "Mateo", "Leah",
    "Omar", "Ava", "Theo", "Mei", "Jonah", "Sara", "Diego", "Ruby", "Kofi", "Nora", "Felix", "Amara", "Ben", "Lina",
    "Sam", "Aria", "Julian", "Keisha", "Marco", "Ines", "Tariq", "Elena", "Hugo", "Yara", "Callum", "Rosa", "Idris",
    "Freya", "Andre", "Leila", "Mason", "Talia", "Rohan", "Esme", "Victor", "Anya", "Kai", "Beatriz", "Declan",
    "Sana", "Jasper", "Min", "Gabriel", "Olivia", "Arjun", "Clara", "Malik", "Iris", "Wes", "Noor", "Rafael", "Ivy",
    "Dev", "Maeve", "Tomas", "Celine", "Adrian", "Lucia", "Hamza", "Poppy", "Ezra", "Sienna", "Darius", "Quinn",
    "Selin", "Rhys", "Nia", "Oscar", "Tess", "Bilal", "Jade", "Luis", "Harper", "Emil", "Kira", "Pablo", "Alma",
    "Seth", "Zara", "Nico", "Farah", "Levi", "June", "Eli", "Ana", "Yusuf", "Lena", "Cole", "Mira", "Raj", "Elle",
    "Finn", "Dana", "Sol", "Ada",
]
KO_NAMES = [  # family name + given name, all different
    "김민준", "이서연", "박도윤", "최서윤", "정하준", "강지우", "조시우", "윤하윤", "장지호", "임지민", "한준서", "오수아", "서예준",
    "신서현", "권건우", "황민서", "안현우", "송하은", "류우진", "홍지유", "김선우", "이윤서", "박연우", "최채원", "정유준", "강지아",
    "조정우", "윤다은", "장승우", "임은서", "한준우", "오예은", "서지환", "신수빈", "권승현", "황지원", "안시윤", "송소윤", "류준혁",
    "홍예린", "김도현", "이하린", "박민재", "최유나", "정현준", "강가은", "조은우", "윤서아", "장지훈", "임채은", "한태윤", "오지안",
    "서민성", "신다인", "권재윤", "황수민", "안한결", "송서영", "류성민", "홍예서", "김동현", "이나은", "박상우", "최지은", "정민혁",
    "강하영", "조재원", "윤유진", "장태민", "임소희", "한준영", "오혜원", "서성현", "신민지", "권영훈", "황수연", "안진우", "송미래",
    "류석진", "홍지수", "김형준", "이은지", "박경민", "최보람", "정재민", "강다현", "조승민", "윤세아", "장태현", "임나연", "한주원",
    "오슬기", "서동하", "신아린", "권준호", "황소은", "안정민", "송하늘", "류영민", "홍가영", "김우현", "이민아", "박기현", "최수진",
    "정용준", "강혜진", "조상현", "윤예진", "장재현", "임은비", "한주안", "오서진", "서시현", "신다솜", "권규민", "황채윤", "안진혁",
    "송윤아", "류성훈", "홍지현", "김하람", "이지율", "박로운", "최이안", "정도하", "강시아", "조은호", "윤유하", "장라온", "임서후",
]
NAMES = {"en": FIRST_NAMES, "ko": KO_NAMES}
REASONS = ["price", "habit", "need", "trust", "quality", "convenience", "timing", "values", "other"]
ANSWER_FIELDS = {"id", "buys", "reason_code", "reason"}
WAVE = 10
INCOME_ROUND = {"KRW": -5, "JPY": -4}  # round() digits per currency; default -3


class PanelError(Exception):
    pass


def _load_unit_economics():
    path = os.path.join(HERE, "..", "founder-cfo", "unit_economics.py")
    spec = importlib.util.spec_from_file_location("founder_unit_economics", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


money = _load_unit_economics().money


# ── dealing ─────────────────────────────────────────────────────────────────────
def _quota(items, n, key="share"):
    """Split n across items by their shares, exactly (largest remainder)."""
    total = sum(float(it.get(key, 1)) for it in items) or 1.0
    raw = [n * float(it.get(key, 1)) / total for it in items]
    counts = [int(r) for r in raw]
    order = sorted(range(len(items)), key=lambda i: raw[i] - counts[i], reverse=True)
    for i in order[: n - sum(counts)]:
        counts[i] += 1
    return counts


def _group(customer, market):
    """A market with the top of customer.json filled in for whatever it leaves out."""
    g = {k: v for k, v in customer.items() if k != "markets"}
    g.update(market)
    return g


def groups(customer):
    """The groups cards are dealt from: each market, or the whole customer.json."""
    if not customer.get("markets"):
        return [customer]
    return [_group(customer, m) for m in customer["markets"]]


def validate_customer(c):
    if "business" not in c or c["business"] in ("", [], None):
        raise PanelError("customer.json needs 'business'")
    markets = c.get("markets")
    if markets is not None:
        if not isinstance(markets, list) or not markets:
            raise PanelError("'markets' must be a list of markets, each with a name and a share")
        seen = set()
        for m in markets:
            if not isinstance(m, dict) or not m.get("name"):
                raise PanelError("every market needs a name")
            if m["name"] in seen:
                raise PanelError("two markets are called %r" % m["name"])
            seen.add(m["name"])
            try:
                share = float(m.get("share", 1))
            except (TypeError, ValueError):
                raise PanelError("market %s: 'share' is not a number" % m["name"])
            if share < 0:
                raise PanelError("market %s: 'share' cannot be below zero" % m["name"])
        if not sum(float(m.get("share", 1)) for m in markets):
            raise PanelError("the market shares add up to zero")
    for g in groups(c):
        _validate_group(g, (" (market %s)" % g["name"]) if markets else "")


def _validate_group(c, where):
    for k in ("target", "segments", "behaviours", "objections"):
        if k not in c or c[k] in ("", [], None):
            raise PanelError("customer.json needs '%s'%s" % (k, where))
    if c.get("language", "en") not in BRIEFS:
        raise PanelError("'language' must be one of %s%s" % (", ".join(sorted(BRIEFS)), where))
    if not isinstance(c.get("currency", "USD"), str):
        raise PanelError("'currency' must be a code such as \"USD\" or \"KRW\"%s" % where)
    for s in c["segments"]:
        if "name" not in s or "income" not in s or len(s["income"]) != 2:
            raise PanelError("every segment needs a name and an income [low, high]")
    for b in c["behaviours"]:
        if "name" not in b:
            raise PanelError("every behaviour needs a name")


def deal(customer, n=100, seed=7):
    """Deal n persona cards. Same customer + n + seed = the same cards, every time."""
    validate_customer(customer)
    if n < 1:
        raise PanelError("--n must be at least 1")
    rng = random.Random(seed)
    pools = {}
    if not customer.get("markets"):
        return _deal_group(customer, n, rng, pools, 0)
    cards = []
    for g, k in zip(groups(customer), _quota(customer["markets"], n)):
        for c in _deal_group(g, k, rng, pools, len(cards)):
            c.update(market=g["name"], language=g.get("language", "en"), currency=g.get("currency", "USD").upper())
            cards.append(c)
    return cards


def _names(rng, pools, language, k):
    """The next k names in this language. A language's list is shuffled once, so no name repeats on a panel."""
    base = NAMES[language]
    if language not in pools:
        names = base[:]
        rng.shuffle(names)
        pools[language] = {"names": names, "used": 0}
    pool = pools[language]
    names, start = pool["names"], pool["used"]
    while len(names) < start + k:
        names += ["%s %d" % (x, len(names) // len(base) + 1) for x in base]
    pool["used"] = start + k
    return names[start:start + k]


def _deal_group(customer, n, rng, pools, first):
    # the same draws in the same order as a panel with no markets, so old seeds give old cards
    age = customer.get("age", [25, 45])
    segs = []
    for s, k in zip(customer["segments"], _quota(customer["segments"], n)):
        segs += [s] * k
    behs = []
    for b, k in zip(customer["behaviours"], _quota(customer["behaviours"], n)):
        behs += [b] * k
    rng.shuffle(segs)
    rng.shuffle(behs)
    names = _names(rng, pools, customer.get("language", "en"), n)
    objections = customer["objections"]
    habits = customer.get("habits") or []
    # round incomes to a step people actually say: 1,000 dollars, 100,000 won
    digits = INCOME_ROUND.get(customer.get("currency", "USD").upper(), -3)
    cards = []
    for i in range(n):
        s, b = segs[i], behs[i]
        lo, hi = float(s["income"][0]), float(s["income"][1])
        cards.append({
            "id": "P%03d" % (first + i + 1),
            "name": names[i],
            "age": rng.randint(int(age[0]), int(age[1])),
            "segment": s["name"],
            "income": int(round(rng.uniform(lo, hi), digits)),
            "behaviour": b["name"],
            "behaviour_how": b.get("how", ""),
            "objection": objections[rng.randrange(len(objections))],
            "habit": habits[rng.randrange(len(habits))] if habits else "",
        })
    return cards


# ── state ───────────────────────────────────────────────────────────────────────
def _path(d, *p):
    return os.path.join(d, *p)


def _read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=1, ensure_ascii=False)
        fh.write("\n")


def init(d, customer_path, pitch_path, n=100, seed=None):
    try:
        customer = _read_json(customer_path)
    except FileNotFoundError:
        raise PanelError("no such file: %s" % customer_path)
    try:
        with open(pitch_path, encoding="utf-8") as fh:
            pitch = fh.read().strip()
    except FileNotFoundError:
        raise PanelError("no such file: %s (write the pitch first: what you sell, the price, where)" % pitch_path)
    if not pitch:
        raise PanelError("the pitch is empty")
    if seed is None:
        seed = random.SystemRandom().randrange(1, 10 ** 6)
    cards = deal(customer, n, seed)
    _write_json(_path(d, "panel.json"), {"n": n, "seed": seed, "customer": customer, "pitch": pitch})
    _write_json(_path(d, "personas.json"), cards)
    os.makedirs(_path(d, "briefs"), exist_ok=True)
    os.makedirs(_path(d, "answers"), exist_ok=True)
    return cards


def load_state(d):
    try:
        return _read_json(_path(d, "panel.json")), _read_json(_path(d, "personas.json"))
    except FileNotFoundError:
        raise PanelError("no panel in %s: run init first" % d)


BRIEF = """You are a simulated buyer on a consumer panel. A founder wants to know, before spending any money, whether real people like you would buy. Your answer is only useful if it is honest: most people do not buy most things, and a polite yes is worse than a clear no.

=== WHO YOU ARE ===
{name}, {age}. {segment}. You earn about {income_text} a year.
How you buy: {behaviour}. {behaviour_how}
{habit_line}The first thing that comes to mind when you hear an offer like this: "{objection}"
You are one of these people: {target}.
=== END ===

=== WHAT IS BEING OFFERED (you see it for the first time, the way a passer-by or a scroller would) ===
{pitch}
=== END ===

Decide as {name} would, with {name}'s money, habits and doubts, in a normal week. Do not be agreeable. Do not invent facts about the business beyond what is written above.

Create the file {out} with your file-writing tool (do not just print the answer in your reply) containing ONLY this JSON, no markdown fence, nothing else:
{{
  "id": "{id}",
  "buys": true or false,
  "purchases_first_month": how many times you would buy in the first month (0 if you would not buy),
  "reason_code": one of {reasons},
  "reason": "why, in one or two sentences, in your own voice",
  "objection": "the doubt that weighs most for you, in your own words",
  "would_change_my_mind": "the one thing that would flip your answer, or empty",
  "price_too_cheap": the price at which it would seem too cheap to be any good (a number{in_currency}),
  "price_cheap": the price at which it would feel like a bargain (a number{in_currency}),
  "price_expensive": the price at which it starts to feel expensive but you might still buy (a number{in_currency}),
  "price_too_expensive": the price at which you would not buy it at all (a number{in_currency})
}}
"""

BRIEF_KO = """당신은 소비자 패널의 가상 구매자입니다. 한 창업자가 돈을 쓰기 전에, 당신 같은 실제 사람들이 이것을 살지 알고 싶어 합니다. 정직하게 답해야만 쓸모가 있습니다. 대부분의 사람은 대부분의 물건을 사지 않습니다. 예의상 하는 "살게요"는 분명한 "안 살래요"보다 나쁩니다.

=== 당신은 누구인가 ===
{name}, {age}세. {segment}. 연 소득은 약 {income_text}입니다.
사는 방식: {behaviour}. {behaviour_how}
{habit_line}이런 제안을 들으면 가장 먼저 드는 생각: "{objection}"
당신은 이런 사람들 중 한 명입니다: {target}.
=== 끝 ===

=== 제안 내용 (지나가던 사람이나 화면을 넘기던 사람처럼 처음 봅니다) ===
{pitch}
=== 끝 ===

평범한 한 주에 {name}의 돈과 습관과 의심을 가지고 {name}처럼 결정하세요. 맞장구치지 마세요. 예의상 산다고 하지 마세요. 위에 적힌 것 말고 이 사업에 대한 사실을 지어내지 마세요.

파일 쓰기 도구로 {out} 파일을 만드세요(답을 응답에 출력만 하지 마세요). 파일에는 아래 JSON만 넣습니다. 마크다운 코드 블록도, 다른 글도 넣지 마세요. 키 이름과 reason_code 값은 영어 그대로 씁니다. reason, objection, would_change_my_mind는 당신 말투의 한국어로 씁니다. 가격 4개는 {currency} 금액을 기호와 쉼표 없이 숫자로만 씁니다.
{{
  "id": "{id}",
  "buys": true 또는 false,
  "purchases_first_month": 첫 달에 몇 번 살지 (안 사면 0),
  "reason_code": {reasons} 중 하나,
  "reason": "이유를 한두 문장으로, 당신 말투로",
  "objection": "당신에게 가장 크게 걸리는 의심을 당신 말로",
  "would_change_my_mind": "답을 뒤집을 한 가지, 없으면 빈 문자열",
  "price_too_cheap": 너무 싸서 품질이 의심되는 가격 (숫자, {currency}),
  "price_cheap": 싸다고 느끼는 가격 (숫자, {currency}),
  "price_expensive": 비싸게 느껴지기 시작하지만 그래도 살 수도 있는 가격 (숫자, {currency}),
  "price_too_expensive": 절대 사지 않을 가격 (숫자, {currency})
}}
"""
BRIEFS = {"en": BRIEF, "ko": BRIEF_KO}
HABIT_LINE = {"en": "Your day: %s.\n", "ko": "당신의 하루: %s.\n"}


def write_briefs(d, wave=WAVE):
    state, cards = load_state(d)
    by_market = {g.get("name"): g for g in groups(state["customer"])}
    todo = []
    for c in cards:
        out = _path(d, "answers", c["id"] + ".json")
        if _answer_ok(out, c["id"]) is None:
            continue
        g = by_market[c["market"]] if c.get("market") else state["customer"]
        lang = c.get("language", g.get("language", "en"))
        cur = c.get("currency", g.get("currency", "USD")).upper()
        pitch = g.get("pitch") if c.get("market") and g.get("pitch") else state["pitch"]
        kw = dict(c, pitch=pitch, target=g["target"], out=os.path.abspath(out),
                  habit_line=(HABIT_LINE[lang] % c["habit"]) if c.get("habit") else "",
                  reasons=" / ".join(REASONS), income_text=money(c["income"], cur, whole=True),
                  currency=cur, in_currency="" if cur == "USD" else " in %s" % cur)
        brief = BRIEFS[lang].format(**kw)
        bp = _path(d, "briefs", c["id"] + ".md")
        with open(bp, "w", encoding="utf-8") as fh:
            fh.write(brief)
        todo.append((c["id"], os.path.abspath(bp)))
    waves = [todo[i:i + wave] for i in range(0, len(todo), wave)]
    return waves


def _answer_ok(path, pid):
    """None if the answer file is good, else a short problem string."""
    if not os.path.exists(path):
        return "missing"
    try:
        a = _read_json(path)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return "not valid JSON"
    missing = ANSWER_FIELDS - set(a)
    if missing:
        return "missing " + ", ".join(sorted(missing))
    if a.get("id") != pid:
        return "id is %r, expected %s" % (a.get("id"), pid)
    if not isinstance(a.get("buys"), bool):
        return "'buys' must be true or false"
    if a.get("reason_code") not in REASONS:
        return "reason_code %r is not one of %s" % (a.get("reason_code"), ", ".join(REASONS))
    return None


def save(d, pid, text):
    """File a buyer's OWN answer that it printed instead of writing. Never used to answer for a buyer."""
    _, cards = load_state(d)
    if pid not in {c["id"] for c in cards}:
        raise PanelError("no buyer %s on this panel" % pid)
    start = text.find("{")
    if start < 0:
        raise PanelError("no JSON object in the reply")
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as e:
        raise PanelError("the reply's JSON does not parse: %s" % e)
    path = _path(d, "answers", pid + ".json")
    _write_json(path, obj)
    prob = _answer_ok(path, pid)
    if prob:
        os.remove(path)
        raise PanelError("%s's answer is not valid (%s); re-run its brief instead" % (pid, prob))
    return path


def check(d):
    _, cards = load_state(d)
    probs = []
    for c in cards:
        p = _answer_ok(_path(d, "answers", c["id"] + ".json"), c["id"])
        if p:
            probs.append((c["id"], p))
    return probs


# ── tally ───────────────────────────────────────────────────────────────────────
def _rate(rows):
    return (sum(1 for r in rows if r["buys"]) / len(rows)) if rows else 0.0


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def tally(d):
    state, cards = load_state(d)
    by_id = {c["id"]: c for c in cards}
    rows, skipped = [], []
    for c in cards:
        path = _path(d, "answers", c["id"] + ".json")
        p = _answer_ok(path, c["id"])
        if p:
            skipped.append((c["id"], p))
            continue
        a = _read_json(path)
        rows.append(dict(by_id[c["id"]], **{k: v for k, v in a.items() if k != "id"}, id=c["id"]))
    if not rows:
        raise PanelError("no valid answers yet: run the briefs first (panel.py prompts)")

    def group(key):
        out = {}
        for r in rows:
            out.setdefault(r[key], []).append(r)
        return sorted(((k, len(v), _rate(v)) for k, v in out.items()), key=lambda t: -t[2])

    # income in thirds of the dealt range, so the bands mean the same thing every run
    # each market gets its own bands: incomes in different currencies never share a row
    multi = len(state["customer"].get("markets") or []) >= 2
    order = []
    for r in rows:
        if r.get("market") not in order:
            order.append(r.get("market"))
    for mk in order:
        rs = [r for r in rows if r.get("market") == mk]
        cur = rs[0].get("currency", state["customer"].get("currency", "USD"))
        w = lambda v: money(v, cur, whole=True)
        label = ("%s: " % mk) if multi else ""
        incomes = sorted(r["income"] for r in rs)
        cut1, cut2 = incomes[len(incomes) // 3], incomes[2 * len(incomes) // 3]
        for r in rs:
            r["income_band"] = label + (("under %s" % w(cut1)) if r["income"] < cut1 else (
                ("%s and up" % w(cut2)) if r["income"] >= cut2 else "%s to %s" % (w(cut1), w(cut2))))

    no = [r for r in rows if not r["buys"]]
    yes = [r for r in rows if r["buys"]]

    def reasons(rs):
        out = {}
        for r in rs:
            out.setdefault(r["reason_code"], []).append(r)
        return sorted(((k, v) for k, v in out.items()), key=lambda kv: -len(kv[1]))

    def mean(vals):
        vals = [v for v in vals if v is not None]
        return sum(vals) / len(vals) if vals else None

    res = {
        "business": state["customer"]["business"], "seed": state["seed"], "dealt": len(cards),
        "answered": len(rows), "skipped": skipped, "buys": len(yes), "passes": len(no),
        "buy_rate": len(yes) / len(rows),
        "by_segment": group("segment"), "by_behaviour": group("behaviour"), "by_income": group("income_band"),
        "why_not": [(k, len(v), [r["reason"] for r in v[:2]], [r["id"] for r in v[:2]]) for k, v in reasons(no)],
        "why_yes": [(k, len(v), [r["reason"] for r in v[:2]], [r["id"] for r in v[:2]]) for k, v in reasons(yes)],
        "flip": [r["would_change_my_mind"] for r in no if (r.get("would_change_my_mind") or "").strip()],
        "purchases_first_month_per_buyer": mean([_num(r.get("purchases_first_month")) for r in yes]),
        "price_answers": sum(1 for r in rows if all(_num(r.get(k)) is not None for k in
                                                     ("price_too_cheap", "price_cheap", "price_expensive", "price_too_expensive"))),
    }
    if multi:
        res["by_market"] = group("market")
    return res


def results_md(res):
    pct = lambda v: "%.0f%%" % (v * 100)
    L = ["# Buyer panel: %s" % res["business"], ""]
    L.append("**%d buy · %d pass** (%s buy) out of %d simulated buyers. Seed %s, so the same cards can be dealt again."
             % (res["buys"], res["passes"], pct(res["buy_rate"]), res["answered"], res["seed"]))
    if res["skipped"]:
        L.append("")
        L.append("%d of %d buyers have no valid answer and are left out: %s." % (
            len(res["skipped"]), res["dealt"], ", ".join("%s (%s)" % s for s in res["skipped"][:10])))
    L.append("")
    L.append("These are simulated buyers, not customers. Use this to find objections and weak spots, then confirm the"
             " big ones with real people before you spend.")
    tables = (("By segment", "by_segment"), ("By buying behaviour", "by_behaviour"), ("By income", "by_income"))
    if "by_market" in res:
        tables = (("By market", "by_market"),) + tables
    for title, key in tables:
        L += ["", "## %s" % title, "", "| group | buyers | buy rate |", "| --- | ---: | ---: |"]
        for k, n, r in res[key]:
            L.append("| %s | %d | %s%s |" % (k, n, pct(r), "  (thin)" if n < 8 else ""))
    L += ["", "## Why they pass", "", "| reason | buyers | in their words |", "| --- | ---: | --- |"]
    for k, n, quotes, ids in res["why_not"]:
        L.append("| %s | %d | %s |" % (k, n, " · ".join('"%s" (%s)' % (q.replace("|", "/"), i) for q, i in zip(quotes, ids))))
    L += ["", "## Why they buy", "", "| reason | buyers | in their words |", "| --- | ---: | --- |"]
    for k, n, quotes, ids in res["why_yes"]:
        L.append("| %s | %d | %s |" % (k, n, " · ".join('"%s" (%s)' % (q.replace("|", "/"), i) for q, i in zip(quotes, ids))))
    if res["flip"]:
        L += ["", "## What would flip a no", ""]
        for f in res["flip"][:12]:
            L.append("- %s" % f)
    if res["purchases_first_month_per_buyer"] is not None:
        L += ["", "Buyers say they would buy **%.1f times** in the first month on average." % res["purchases_first_month_per_buyer"]]
    if res["price_answers"]:
        L += ["", "%d buyers gave all four price answers. Run founder-pricing's van_westendorp.py on the answers folder." % res["price_answers"]]
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", default=os.path.join("founder", "panel"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init")
    i.add_argument("--customer", required=True)
    i.add_argument("--pitch", required=True)
    i.add_argument("--n", type=int, default=100)
    i.add_argument("--seed", type=int)
    p = sub.add_parser("prompts")
    p.add_argument("--wave", type=int, default=WAVE)
    sub.add_parser("check")
    sv = sub.add_parser("save")
    sv.add_argument("id")
    t = sub.add_parser("tally")
    t.add_argument("--out")
    sub.add_parser("status")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "init":
            cards = init(a.dir, a.customer, a.pitch, a.n, a.seed)
            st, _ = load_state(a.dir)
            print("dealt %d buyers (seed %s) into %s. Next: panel.py prompts" % (len(cards), st["seed"], a.dir))
        elif a.cmd == "prompts":
            waves = write_briefs(a.dir, a.wave)
            n = sum(len(w) for w in waves)
            if not n:
                print("every buyer has a valid answer. Next: panel.py tally")
            else:
                print("%d briefs in %d waves of up to %d. Launch one wave at a time:" % (n, len(waves), a.wave))
                for k, w in enumerate(waves, 1):
                    print("wave %d: %s" % (k, " ".join("%s=%s" % job for job in w)))
        elif a.cmd == "check":
            probs = check(a.dir)
            if not probs:
                print("all answers present and valid")
            for pid, prob in probs:
                print("%s: %s" % (pid, prob))
            return 1 if probs else 0
        elif a.cmd == "save":
            print("saved %s" % save(a.dir, a.id, sys.stdin.read()))
        elif a.cmd == "tally":
            res = tally(a.dir)
            text = results_md(res)
            out = a.out or _path(a.dir, "results.md")
            with open(out, "w", encoding="utf-8") as fh:
                fh.write(text)
            _write_json(_path(a.dir, "results.json"), res)
            print("%d buy · %d pass (%.0f%%). Wrote %s" % (res["buys"], res["passes"], res["buy_rate"] * 100, out))
        elif a.cmd == "status":
            st, cards = load_state(a.dir)
            probs = check(a.dir)
            print("%d buyers dealt (seed %s), %d answered, %d to go" % (len(cards), st["seed"], len(cards) - len(probs), len(probs)))
    except PanelError as e:
        print("error: %s" % e, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
