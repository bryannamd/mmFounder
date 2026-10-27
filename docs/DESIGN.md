# mmFounder 설계 (1차 판)

원본: Jakeschincariol/founder-skill (MIT, upstream 커밋 fd9385b). 이 저장소는 원본 이력을 그대로 가진 포크다.

## 원칙

1. **덧붙이는 층.** 원본 파일은 연결에 필요한 만큼만 고친다. 한국 내용은 각 스킬 폴더의 `kr.md`에 모은다. 원본 갱신을 `git merge upstream/main`으로 계속 받기 위해서다.
2. **설정이 없으면 원본과 똑같이 동작한다.** `currency`·`markets`·`locale.json`이 없으면 출력·판정·카드 배분이 원본과 같아야 한다(아래 예외 3개 제외).
3. **숫자를 지어내지 않는다.** 원본 원칙을 RCF에도 그대로 적용한다. 출처 없는 기준값은 도구가 거부한다.
4. **표준 라이브러리만, 네트워크 없음.** 원본과 같다. Python 3.8+.
5. **em dash(U+2014) 금지.** `tests/test_repo.py`가 모든 텍스트 파일을 검사한다. 한국어 문서에서도 쓰지 않는다.
6. 코드 주석·스킬 본문 영어 문장은 원본 문체를 따른다. `kr.md`와 README는 한국어로 쓴다.

원본과 일부러 다르게 동작하는 곳(예외):
- `compile.py`: 패널 결과와 RCF 결과가 없으면 "Profitable"을 주지 않는다(각각 실패 검사로 표시).
- `compile.py`: 잘못된 `numbers.json`이면 Python 오류 전문 대신 `error: ...` 한 줄을 출력하고 종료 코드 2로 끝난다.
- `compile.py`: 핵심 숫자 표의 음수 금액은 원본의 `$-63,600` 대신 `-$63,600`으로 보인다(통화 함수 하나를 함께 쓰기 때문).
- 원칙 4의 예외(2026-10-27): `skills/founder-consumer/jev.py`의 `run` 명령만 네트워크를 쓴다(TypeSafe Jev API). 사용자가 키를 두고 직접 실행할 때만 동작한다. import나 다른 PANEL 명령에서는 네트워크가 일어나지 않는다. 다른 모든 파일은 네트워크 없음. 표준 라이브러리 원칙은 그대로다. 설계와 검토 기록: `docs/PLAN_2026-10-27_jev-panel.md`.

## 단계 순서

```
rcf -> board -> competitors -> consumer -> pricing -> offer -> cfo -> marketing -> brand -> ops -> launch -> plan
```

## 데이터 형식

### `founder/locale.json` (스킬이 읽는 설정, 선택)

```json
{"country": "KR", "language": "ko", "currency": "KRW", "price_includes_vat": true, "vat_rate": 0.10}
```

- 스킬은 이 파일을 보고 `kr.md`를 읽을지, 어떤 통화를 쓸지 정한다.
- 도구는 이 파일을 직접 읽지 않는다. 스킬이 값을 `numbers.json`·`customer.json`에 옮겨 쓰거나 CLI 인자로 넘긴다. 도구 입력이 파일 하나로 완결되게 하려는 것이다.
- 없으면 원본처럼 USD·영어로 본다.

### 통화 (`skills/founder-cfo/unit_economics.py`가 단일 원본)

| code | 표시 | 소수점 |
|---|---|---|
| USD, CAD | `$1,234.50` | 2 |
| EUR | `€1,234.50` | 2 |
| GBP | `£1,234.50` | 2 |
| JPY | `¥1,234` | 0 |
| KRW | `6,500원` | 0 |

- 금액은 K·M으로 줄이지 않는다. 항상 전체 금액에 천 단위 쉼표.
- 음수는 `-6,500원`, `-$4.76`.
- 모르는 code는 `CODE 1,234.50`(소수점 2).
- 다른 도구(`compile.py`, `van_westendorp.py`, `panel.py`)는 `unit_economics.py`를 `importlib`로 불러 같은 함수를 쓴다(`compile.py`가 이미 이렇게 한다).

### `numbers.json` 추가 필드

| field | 기본값 | 뜻 |
|---|---|---|
| `currency` | `"USD"` | 보고서 통화 |
| `price_includes_vat` | `false` | `price`가 부가세 포함 소비자가인지 |
| `vat_rate` | `0.10` (`price_includes_vat`가 true일 때만 사용) | 부가세율 |

- `price_includes_vat`가 true면 `net_price = price / (1 + vat_rate)`를 쓴다. 매출·공헌이익·마진·손익분기는 모두 `net_price` 기준이다.
- 보고서 "One unit" 표 첫 줄에 판매가(부가세 포함)와 부가세 제외가를 둘 다 보인다.
- `variable`·`fixed_monthly`·`startup` 비용은 부가세 제외 금액으로 넣는다고 문서에 적는다(일반과세자는 매입세액을 공제받는다). 간이과세자는 계산이 다르므로 세무사 확인 문구를 보고서에 넣는다.
- `--price` what-if도 같은 기준(부가세 포함 여부는 입력 파일 설정을 따른다).
- 예시: `skills/founder-cfo/example.kr.json` (KRW, 부가세 포함). 값은 예시임을 `business` 필드에 밝힌다.

### `customer.json` 추가 필드 (패널)

최상위:

| field | 기본값 | 뜻 |
|---|---|---|
| `language` | `"en"` | 브리프 언어 (`en`, `ko`) |
| `currency` | `"USD"` | 소득·가격 답 통화 |
| `markets` | 없음 | 국가별 구매자 비율 |

`markets`가 있으면 각 항목:

```json
{"name": "Korea", "country": "KR", "language": "ko", "currency": "KRW", "share": 0.3,
 "target": "...", "age": [24, 38], "segments": [...], "behaviours": [...], "objections": [...], "habits": [...],
 "pitch": "이 시장 구매자에게 보일 한국어 소개 문구 (선택, 없으면 --pitch 파일)"}
```

- 빠진 키는 최상위 값을 물려받는다.
- 배분: 먼저 `_quota`로 시장별 인원을 정하고, 시장마다 원본과 같은 방식으로 카드를 만든다. 카드에 `market`, `language`, `currency`를 추가한다.
- **`markets`가 없을 때는 RNG 호출 순서까지 원본과 같아야 한다.** 같은 seed면 원본 `panel.py`와 같은 카드가 나와야 한다(`git show fd9385b:skills/founder-consumer/panel.py`로 대조하는 테스트를 둔다. 원본 출력의 앞 3장 값을 테스트에 고정해도 된다).
- 이름: `language`별 이름 목록. `ko`는 한국 성+이름 120개 이상, 전체 패널에서 중복 없음.
- 브리프: `language`별 템플릿. `ko` 템플릿은 원본 BRIEF와 같은 내용·같은 JSON 키를 쓴다. 예의상 산다고 하지 말라는 지시, 사실을 지어내지 말라는 지시를 반드시 포함한다. `reason`·`objection`·`would_change_my_mind`는 구매자 말투의 한국어로, 가격 4개는 그 시장 통화의 숫자로 답하게 한다. `reason_code` 값은 영어 코드 그대로.
- 소득 표시: 통화 함수 사용. `ko`는 "연 소득은 약 45,000,000원".
- 집계: `markets`가 2개 이상이면 `by_market` 표를 추가한다. 소득 구간은 시장별로 따로 나누고 표 라벨에 시장 이름을 붙인다(통화가 다른 소득을 한 줄에 섞지 않는다).
- 예시: `skills/founder-consumer/customer.kr.example.json`, `pitch.kr.example.md` (한국 카페 예시, 값은 예시임을 밝힌다).

### `van_westendorp.py` 추가

- `₩`, `원`, 공백도 숫자에서 제거한다.
- `--currency CODE` (기본 USD): 보고서 표시 통화. KRW면 격자 간격을 10원 단위로 반올림한다.
- 패널 answers 폴더를 읽을 때 형제 파일 `../personas.json`이 있고 그 안에 통화가 2개 이상이면 `--market NAME`이 필수다. 없으면 오류. 있으면 그 시장 구매자 답만 쓴다.

### `jev.py` (founder-consumer, 선택. 2026-10-27)

- `jev.py run --dir D --price P --paid TEXT --unit TEXT [--customer C --pitch F --n N --seed S] [--model jev-1.14.0] [--ladder-max 5.0] [--budget-usd 1.0]`.
- 판정 밖 별도 층이다. 쓰는 곳: `D/jev-answers/Pxxx.json`(기존 답 키 + `jev` 블록: 모델, `p_buy`, 원본 확률, 지문, 플래그), `D/jev.json`(지문, 설정, 실행 이력, 전송 통계, `inflight`), `D/jev-results.md`·`.json`. 읽기만 하는 곳: `answers/`, `panel.json`, `personas.json`, `results.*`. `compile.py`는 Jev 산출물을 읽지 않는다.
- 요청 1건 = 카드 1장. 상태는 고객 언어 그대로, 질문은 영어 고정 틀(구매 noul 1, 고려 요인 choice 1, 가격 score 12). `reason`·`objection`·`would_change_my_mind`는 빈 문자열, `purchases_first_month`는 없음.
- 가격은 사다리(`--price` × 0.2~`--ladder-max`, 유효숫자 2자리)별 5단계 확률에서 누적 0.5 교차점을 보간한다. 사다리 밖은 경계값으로 저장하고 `flags.censored`로 표시한다. 순서 보정은 `flags.clamped`. `jev-results.md`의 가격 절은 `van_westendorp.py`의 `read → analyse → report`를 재사용하고 "탐색 추정"으로 표시한다.
- `panel.py` 변경은 `tally(d, answers="answers")` 인자 하나다. 기본값이면 원본과 같다.
- 지문이 다른 실행(카드 내용·피치·설정·모델·틀 버전이 하나라도 다름)은 거부한다. 자동 삭제는 없다. 카드 파일과 `jev.json`은 임시 파일 뒤 `os.replace`.
- 리다이렉트를 따르지 않는다(`urllib`은 다른 호스트로의 리다이렉트에도 `Authorization`을 넘긴다). 429·529·502·503·504·연결 오류만 재시도(최대 5회, 백오프, `Retry-After`). 키는 출력·파일·예외 어디에도 쓰지 않는다.
- `markets`가 있는 고객은 요청 전에 거부한다(1차 미지원).

### `founder/rcf.json` (새 스킬 `founder-rcf`)

```json
{
  "business": "...",
  "example": false,
  "reference_classes": [
    {"level": 1, "name": "가장 좁은 집단", "why": "왜 비슷한가"},
    {"level": 2, "name": "...", "why": "..."},
    {"level": 3, "name": "가장 넓은 집단", "why": "..."}
  ],
  "metrics": [
    {"key": "survival_1y", "label": "1년 생존율", "class_level": 3,
     "value": 0.641, "low": null, "high": null, "unit": "ratio",
     "source": "https://...", "source_title": "...", "source_date": "2023-12-21", "note": ""}
  ],
  "failure_reasons": [{"reason": "...", "source": "https://..."}],
  "adjustments": [{"metric": "ramp_month1_per_day", "direction": "better", "evidence": "왜 이 계획이 기준 집단보다 나은지, 확인 가능한 근거"}],
  "kill_criteria": [{"metric": "units_per_day_month2", "below": 120, "action": "가격·오퍼 재검토"}]
}
```

검사 규칙 (`rcf.py check`):
- `metrics`마다 `key`, `value`(숫자), `unit`, `source`(http/https), `source_date`(YYYY-MM-DD 또는 YYYY-MM 또는 YYYY), `class_level`(reference_classes에 있는 값)이 있어야 한다. 하나라도 없으면 실패.
- `low <= value <= high` (둘 다 있을 때).
- `example: true`면 경고 한 줄: 예시 데이터이며 실제 통계가 아니다.

비교 규칙 (`rcf.py compare`, `compile.py`가 같은 함수 사용):

| rcf key | 계획 쪽 값 | 비교 |
|---|---|---|
| `ramp_month1_per_day` | `ramp_per_day[0]` | 낙관 검사 |
| `ramp_month3_per_day` | `ramp_per_day[2]` | 낙관 검사 |
| `plan_per_day` | `plan_per_day` | 낙관 검사 |
| `contribution_pct` | `analyse()["contribution_pct"]` | 낙관 검사 |
| `margin_at_plan` | `analyse()["margin_at_plan"]` | 낙관 검사 |
| `buy_rate` 또는 `conversion_rate` | 패널 `buy_rate` | 정보만 (패널은 상한선이라 판정에 쓰지 않음) |
| `survival_*` 등 그 밖의 key | 없음 | 정보만 |

낙관 검사:
- `high`가 있고 계획 값 > `high`면 실패. 단 같은 `metric`의 `adjustments` 항목에 비어 있지 않은 `evidence`가 있으면 통과로 바꾸고 "근거 있는 낙관"으로 표시.
- `high`가 없고 계획 값 > `value`면 경고(판정에 영향 없음): 기준 집단 중앙값보다 높다.
- 계산에 필요한 계획 값이 없으면 건너뛰고 표시.

명령:
```bash
python3 skills/founder-rcf/rcf.py check founder/rcf.json
python3 skills/founder-rcf/rcf.py compare --rcf founder/rcf.json --numbers founder/numbers.json [--panel founder/panel/results.json] [--out founder/rcf-compare.md]
```
`check` 실패 시 종료 코드 1, 입력 오류 2. 예시: `skills/founder-rcf/rcf.example.json` (`example: true`).

### `compile.py` 판정

검사 순서: (원본 1~4) + 5. 패널 결과 있음 + 6. RCF 검사 통과(`rcf.py check`) + 7. RCF 낙관 검사 실패 없음.
- 숫자가 없으면 Incomplete (원본과 같음).
- 패널 결과가 없으면 실패 검사 "No buyer panel yet: run /founder-consumer".
- `rcf.json`이 없으면 실패 검사 "No outside view yet: run /founder-rcf".
- SECTIONS에 `("rcf.md", "The outside view", "founder-rcf")`를 board 앞에 추가.
- 금액은 `numbers.json`의 `currency`로 표시.

## 스킬 문서 연결 (원본 SKILL.md 수정 범위)

각 SKILL.md에 짧은 절 하나를 추가한다. 형식:

```markdown
## In Korea

If `founder/locale.json` says `"country": "KR"`, also read `kr.md` in this skill's folder (`${CLAUDE_SKILL_DIR}/kr.md`) and follow it: ...
```

| 스킬 | 추가 내용 |
|---|---|
| founder-rcf (새) | 전체 신규. 한국 자료원은 `sources-kr.md` |
| founder-board | Step 0에서 국가·통화를 확인해 `locale.json` 작성. `founder/rcf.md`가 있으면 4번째 위원 "Outside View lens" 추가(`lenses.md`에 렌즈 추가) |
| founder-competitors | 한국 지도·리뷰 출처(네이버 지도·카카오맵·플레이스 리뷰)는 `kr.md` |
| founder-consumer | `markets`·`language`·`currency` 사용법, 한국 브리프, 고정관념 경고는 `kr.md` |
| founder-pricing | `--currency`, `--market` |
| founder-offer | 한국 법규(청약철회 등)는 `kr.md` |
| founder-cfo | `currency`·`price_includes_vat`·`vat_rate`, 한국 수수료·세금 항목은 `kr.md`. RCF로 ramp 점검 |
| founder-marketing | 한국 채널·추천보증 심사지침은 `kr.md` |
| founder-brand | KIPRIS·KISA 도메인·국내 플랫폼 이름 확인은 `kr.md` |
| founder-ops | 한국 인허가·신고는 `kr.md` |
| founder-launch | 사전 예약 개인정보 동의 등은 `kr.md`. RCF `kill_criteria`를 30일 점검에 사용 |
| founder-plan | 새 검사 5~7 설명 |

`kr.md` 작성 규칙:
- 공식 기관 주소를 적고, 수수료·세율·기한처럼 바뀌는 값은 "공식 페이지에서 현재 값을 확인하라"로 쓴다. 확인하지 않은 숫자를 적지 않는다.
- 법률·세무 조언이 아니라는 문구를 원본처럼 한 번 넣는다.

## 패키징

- 플러그인 이름 `mmfounder`, 마켓플레이스 이름 `mmfounder`. 스킬 이름은 원본처럼 `founder-*` 유지.
- Claude Code: `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` (source `./`).
- Codex: 루트 `plugin.json`(mmCode 형식), `.agents/plugins/marketplace.json`, 스킬마다 `agents/openai.yaml`.
- `README.md`는 한국어. 원본 README는 `docs/UPSTREAM_README.md`로 옮기지 않고, 원본 출처·라이선스는 `THIRD_PARTY_NOTICES.md`에 적는다. 루트 `LICENSE`는 원본 그대로 두고 저작권 줄을 추가한다(`Copyright (c) 2026 bryannamd` 한 줄 추가).
- `tests/test_repo.py`는 새 이름·새 스킬 12개·새 README에 맞게 고친다.

## 아직 확인 안 됨

- Codex에서 패널·이사회 하위 에이전트 호출이 동작하는지.
- KIPRIS Plus Open API 상표 검색의 이용 조건. 1차 판은 검색 주소 안내만 한다.
