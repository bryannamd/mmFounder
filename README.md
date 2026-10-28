# mmFounder

**사업을 열기 전에 시험하는 스킬 12개.** 창업을 준비하는 사람이 돈을 쓰기 전에 아이디어, 가격, 수익, 출시 계획을 점검하도록 돕는다. 한국어와 원화, 부가세, 한국 자료원을 지원한다. Claude Code와 Codex에서 같은 이름으로 쓴다. 무료이고, 가입도 API 키도 연결할 계정도 필요 없다.

`skills/founder-rcf` `skills/founder-board` `skills/founder-competitors`
`skills/founder-consumer` `skills/founder-pricing` `skills/founder-offer`
`skills/founder-cfo` `skills/founder-marketing` `skills/founder-brand`
`skills/founder-ops` `skills/founder-launch` `skills/founder-plan`

이사회는 Alex Hormozi, Peter Thiel, Steve Jobs가 정리한 틀을 하나씩 적용해 아이디어를 평가한다. 재무 담당은 진짜 이익률을 구한다. 소비자 패널은 목표 고객을 닮은 가상 구매자 100명을 만들어 100가지 구매 상황에 사업을 통과시킨다. 새로 넣은 바깥 관점(rcf)은 비슷한 사업이 실제로 어땠는지부터 본다.

큰돈을 쓰고 나서 알게 되기 전에, 어떻게 출시하고 알리고 돈을 벌지 먼저 확인한다.

## 원본과의 관계

[Jakeschincariol/founder-skill](https://github.com/Jakeschincariol/founder-skill)의 포크다. 원작자는 Jake Schincariol([opusjake.ai](https://opusjake.ai)), 라이선스는 MIT, 포크 기준 커밋은 `fd9385b`다. 원본 이력을 그대로 가지고 있어서 원본 갱신을 계속 받을 수 있다. 출처와 라이선스 전문은 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)에 있다.

원본 파일은 연결에 필요한 만큼만 고쳤다. 한국 대응은 각 스킬 폴더의 `kr.md`에 모았다. 설정이 없으면 원본과 똑같이 동작한다. 예외는 아래 "판정 강화"의 두 가지다.

## 바뀐 점

- **바깥 관점(RCF) 스킬 추가.** `/founder-rcf`가 비슷한 사업의 기준값(생존율, 초기 판매 증가 속도, 객단가·마진, 폐업 이유)을 출처 주소와 날짜가 붙은 숫자로만 모은다. 출처 없는 숫자는 도구가 거부한다. 계획 숫자가 기준 집단의 상한을 넘으면 근거를 요구한다.
- **한국 자료원.** KIPRIS 상표 검색, 니스 분류, `.kr`·`.co.kr` 도메인(KISA), 네이버·카카오 이름 확인, 사업자등록(홈택스), 통신판매업 신고, 음식점 영업신고·위생교육, 옥외광고물, 다중이용업소 보험, 전자상거래법 청약철회, 개인정보 수집 동의, 추천·보증 심사지침(광고 표시)을 `kr.md`에 정리했다. KOSIS 기업생멸행정통계, 공정위 가맹사업거래 정보공개서, 소상공인365는 `founder-rcf/sources-kr.md`에 있다.
- **원화.** `numbers.json`의 `currency`로 통화를 정한다. 원화는 `6,500원`처럼 소수점 없이 전체 금액으로 보인다. 가격 격자는 10원 간격이다(결과 가격은 10원 단위가 아닐 수 있다).
- **부가세.** `price_includes_vat`와 `vat_rate`를 받는다. 부가세 포함 소비자가에서 부가세 제외 가격을 구해 매출, 공헌이익, 마진, 손익분기를 계산한다.
- **패널 한국어.** `customer.json`의 `language: "ko"`로 구매자 브리프와 답변이 한국어가 된다. 한국 성+이름 120개 이상이 쓰인다.
- **국가 비율.** `markets`로 시장별 구매자 비율, 언어, 통화, 소개 문구를 나눈다. 결과에 시장별 표가 생긴다. 통화가 다른 소득을 한 줄에 섞지 않는다.
- **판정 강화.** `/founder-plan`의 판정에 검사 3개를 더했다. 패널 결과가 있는가, RCF 검사를 통과했는가, 낙관 검사에 실패가 없는가. 패널 결과나 RCF가 없으면 "Profitable"을 주지 않는다. 원본과 일부러 다르게 동작하는 첫 번째 곳이다. 두 번째는 잘못된 `numbers.json`이다. Python 오류 전문 대신 `error: ...` 한 줄을 보이고 종료 코드 2로 끝난다.
- **이사회 4번째 위원.** `founder/rcf.md`가 있으면 Outside View 렌즈 위원이 더해진다.
- **Jev 폭 확장(선택).** `skills/founder-consumer/jev.py run`이 TypeSafe Jev(결정 전용 모델)에 카드 전원의 구매 확률, 주요 고려 요인, 가격 12단계를 묻는다. 카드 1장에 약 0.3초다. 결과는 `jev-answers/`와 `jev-results.md`에 따로 쓰이고 판정은 에이전트 패널만 읽는다. 쓰임새는 폭이다. 판정과 인용문은 에이전트 20명으로, 구간별 구매율·가격 곡선은 Jev 200장으로 본다. API 키와 비용이 들고 카드·피치가 외부로 전송된다. 저장소에서 네트워크를 쓰는 유일한 명령이다.

## 설치

### Claude Code

```sh
claude plugin marketplace add bryannamd/mmFounder
claude plugin install mmfounder@mmfounder
```

### Codex

```sh
codex plugin marketplace add https://github.com/bryannamd/mmFounder
codex plugin add mmfounder@mmfounder
```

Codex는 설치할 때 플러그인을 `$CODEX_HOME/plugins/cache/` 아래에 복사한다. 갱신하려면 `codex plugin remove mmfounder@mmfounder` 뒤에 `codex plugin add mmfounder@mmfounder`를 다시 실행한다. GitHub 주소로 등록한 마켓이면 그 앞에 `codex plugin marketplace upgrade mmfounder`를 먼저 실행한다. Claude Code는 `claude plugin update mmfounder@mmfounder`로 갱신한다. 로컬 사본으로 쓰려면 저장소를 받은 뒤 위 명령의 주소 자리에 그 폴더 경로를 넣는다.

폴더만 복사해서 쓸 수도 있다. 플러그인 이름 없이 `/founder-board`처럼 부르려면 이렇게 한다.

```sh
git clone https://github.com/bryannamd/mmFounder.git
cp -r mmFounder/skills/founder-* ~/.claude/skills/
```

프로젝트 안에서만 쓰려면 같은 폴더를 저장소의 `.claude/skills/`에 복사한다. Claude Code 없이도 `SKILL.md` 하나를 대화 맨 앞에 붙여 넣으면 하나의 모드로 동작한다. 이때는 하위 에이전트와 Python 도구를 쓸 수 없지만 방법은 통한다.

도구는 Python 3.8 이상이 필요하다. 설치할 패키지는 없다. 도구는 네트워크를 쓰지 않는다. 웹 검색은 스킬이 에이전트의 검색 도구로 한다.

### 부르는 법

| | Claude Code | Codex |
|---|---|---|
| 플러그인으로 설치 | `/mmfounder:founder-board`, `/mmfounder:founder-rcf`, … | `$mmfounder:founder-board`, `$mmfounder:founder-rcf`, … |
| 폴더 복사로 설치 | `/founder-board`, `/founder-rcf`, … | 해당 없음 |

Claude Code는 플러그인 스킬 앞에 플러그인 이름을 붙인다. 아래 표는 짧은 이름으로 적는다.

## 12개 스킬

| 명령 | 역할 | 하는 일 |
|---|---|---|
| `/founder-rcf` | 바깥 관점 | 기준 집단 3단계를 정하고 출처가 붙은 기준값을 모아 계획 숫자와 비교한다. 기준 집단에 비해 계획이 유리한지 불리한지, 중단 기준(kill criteria)을 `founder/rcf.md`에 쓴다. |
| `/founder-board` | 이사회 | 위원 3명(RCF가 있으면 4명)이 각자 공개된 틀 하나로 아이디어를 점수 매기고, 사업을 죽일 위험을 꼽고, 표결한다. 처음 시작할 때 국가와 통화를 확인해 `founder/locale.json`을 만든다. |
| `/founder-competitors` | 경쟁자 정찰 | 직접·간접 경쟁자와 대체재를 공개 자료로 찾아 가격, 포지셔닝, 고객 불만을 링크와 함께 정리한다. |
| `/founder-consumer` | 소비자 패널 | 목표 고객에서 가상 구매자 에이전트(기본 100명)를 만들어 누가 사고 누가 안 사는지, 이유가 무엇인지 모은다. |
| `/founder-pricing` | 가격 전략가 | 패널의 가격 답을 받아들일 가격대로 바꾸고, 경쟁자와 마진에 맞춰 시험할 가격을 고른다. |
| `/founder-offer` | 오퍼 설계자 | 구매자의 반대 이유에 답하는 오퍼(보너스, 보증, 진짜 긴급성, 이름)를 짜고 패널로 다시 시험한다. |
| `/founder-cfo` | 재무 담당 | 한 건당 이익, 진짜 이익률, 하루 손익분기, 첫해 월별 손익, 필요한 현금, 회수 기간, 가정 변경 결과를 구한다. |
| `/founder-marketing` | 마케팅 책임자 | 포지셔닝, 구매자가 쓰는 채널, 날짜가 붙은 30일 출시 캠페인, 문구 10개, 고객 한 명에게 쓸 수 있는 최대 비용을 정한다. |
| `/founder-brand` | 브랜드 디자이너 | 이름 후보와 상표·도메인·계정 확인 목록, 말투, 약속, 디자인 브리프를 만든다. |
| `/founder-ops` | 운영 관리자 | 공급처, 인력, 첫날 루틴, 도구, 확인할 인허가, 위험 목록을 만들고 실제 비용을 재무 담당에게 돌려준다. |
| `/founder-launch` | 출시 책임자 | 값싼 실제 시험을 먼저 하고, 날짜별 준비 일정, 출시일 진행표, 첫 30일 점검을 만든다. RCF의 중단 기준을 점검에 쓴다. |
| `/founder-plan` | 사업 계획 담당 | 모든 결과를 사업계획서 하나로 모으고, 숫자로 계산한 판정(Profitable, Not yet, Incomplete)을 맨 위에 둔다. |

## 단계 순서

아래 순서로 실행한다. 각 스킬은 다른 스킬이 프로젝트의 `founder/` 폴더에 쓴 파일을 읽는다.

```
rcf -> board -> competitors -> consumer -> pricing -> offer -> cfo -> marketing -> brand -> ops -> launch -> plan
```

1. **`/founder-rcf`**: 비슷한 사업의 기준값을 모아 `founder/rcf.json`과 `founder/rcf.md`를 쓴다. 출처 없는 숫자는 쓰지 않는다. 웹 검색 도구가 없으면 자료를 달라고 요청한다.
2. **`/founder-board`**: 국가·통화를 확인해 `founder/locale.json`을, 아이디어를 `founder/idea.md`에 쓰고 위원들 앞에 올린다.
3. **`/founder-competitors`**: 경쟁자를 지도·리뷰·가격으로 정리한다. 한국은 네이버 지도·카카오맵을 본다.
4. **`/founder-consumer`**: 목표 고객을 정하고 가상 구매자 카드를 만들어 한 명당 하위 에이전트 하나씩 돌린다.
5. **`/founder-pricing`**: 가격 답으로 받아들일 가격대를 구하고 현재 가격과 비교한다.
6. **`/founder-offer`**: 상위 반대 이유에 답하는 오퍼를 짜고 간이 패널로 구매율이 움직이는지 본다.
7. **`/founder-cfo`**: 단위 경제를 계산한다. RCF가 있으면 판매 증가 속도(ramp)를 기준 집단과 비교한다.
8. **`/founder-marketing`**, **`/founder-brand`**, **`/founder-ops`**, **`/founder-launch`**: 30일 캠페인, 이름과 디자인, 공급처와 루틴, 날짜가 붙은 출시를 만든다. 출시는 실제 구매자로 시험하는 것부터 시작한다.
9. **`/founder-plan`**: `founder/business-plan.md`를 만든다. 판정은 쓴 것이 아니라 계산한 것이다. 모든 단위가 돈을 벌고, 첫해에 이익이 나고, 손익분기가 수용량 안이고, 패널이 충분히 사고, 패널 결과가 있고, RCF 검사를 통과하고, 낙관 검사에 실패가 없을 때만 Profitable이다.

어느 스킬이든 혼자 실행해도 된다. 아직 생각 중인 아이디어에는 `/founder-consumer --quick`으로 먼저 반응을 보는 것이 좋다.

### 설정 파일 `founder/locale.json`

스킬이 읽는 선택 설정이다. 없으면 원본처럼 USD와 영어로 본다. 도구는 이 파일을 직접 읽지 않는다. 스킬이 값을 `numbers.json`·`customer.json`에 옮기거나 명령 인자로 넘긴다.

```json
{"country": "KR", "language": "ko", "currency": "KRW", "price_includes_vat": true, "vat_rate": 0.10}
```

`country`가 `KR`이면 스킬이 각 폴더의 `kr.md`를 읽는다.

## 도구

모두 표준 라이브러리만 쓰는 Python이다. `jev.py run`만 네트워크에 접속하고(TypeSafe Jev API, 키 필요), 나머지는 접속하지 않는다.

```bash
python3 skills/founder-rcf/rcf.py check founder/rcf.json                                  # 기준값 검사
python3 skills/founder-rcf/rcf.py compare --rcf founder/rcf.json --numbers founder/numbers.json
python3 skills/founder-cfo/unit_economics.py founder/numbers.json --out founder/cfo.md    # 이익률, 손익분기, 첫해
python3 skills/founder-consumer/panel.py init --customer founder/customer.json --pitch founder/pitch.md
python3 skills/founder-consumer/jev.py run --dir founder/panel --price 6500 --paid "a matcha latte" --unit "per cup"
python3 skills/founder-pricing/van_westendorp.py founder/panel/answers --currency KRW --price 6500
python3 skills/founder-plan/compile.py --dir founder                                      # 사업계획서와 판정
```

**`rcf.py`**는 `founder/rcf.json`을 검사하고(숫자, 단위, 출처 주소, 날짜, 기준 집단이 모두 있어야 한다) 계획 숫자와 비교한다. 계획이 기준 집단의 상한을 넘으면 실패이고, 같은 지표에 확인할 수 있는 근거가 적혀 있으면 "근거 있는 낙관"으로 표시한다. 예시: `skills/founder-rcf/rcf.example.json`(실제 통계가 아닌 예시).

**`unit_economics.py`**는 JSON 하나(예시: `skills/founder-cfo/example.json`, 원화 예시 `example.kr.json`)를 읽어 공헌이익, 손익분기, 계획 판매량의 이익률, 첫해 월별 손익, 필요한 현금, 회수 기간, 가정 변경 3가지를 보고한다. 모든 숫자가 입력에서 나온다. 빠진 필드는 오류이고 추측이 아니다.

**`panel.py`**는 목표 고객에서 구매자 카드를 만들고(같은 seed면 같은 카드), 구매자마다 브리프를 쓰고, 답을 검사하고 집계한다. 구매자 대신 답하지 않는다. 예시: `customer.example.json`, 한국어 예시 `customer.kr.example.json`, `pitch.kr.example.md`.

**`van_westendorp.py`**는 구매자별 가격 답 4개(패널 또는 실제 설문 CSV)에서 너무 싼 가격, 비싸지는 가격, 최적 가격, 무차별 가격을 구한다.

**`jev.py`**는 패널 카드 전원을 TypeSafe Jev에 묻고(카드 1장 = 요청 1건) `jev-answers/`, `jev.json`, `jev-results.md`를 쓴다. 에이전트 답과 판정은 건드리지 않는다. 키는 `TYPESAFE_API_KEY` 또는 `~/.config/typesafe/api_key`(권한 600). 카드·피치가 외부로 전송되고 비용이 들므로 실행 전에 사용자 확인을 받는다. 확률은 구매율이 아니고, 인용문이 없고, 같은 상품의 작은 오퍼 차이는 못 가린다. 설계와 검토 기록: `docs/PLAN_2026-10-27_jev-panel.md`.

`jev.py sweep`은 같은 카드에 가격 목록(피치 틀의 `{price}` 치환)이나 피치 목록을 순차로 돌리고, 변형을 카드별로 짝지어 비교한 `jev-sweep.md`를 쓴다. 모든 변형이 같은 가격 사다리를 쓴다. 기준 변형을 2번 돌린 반복 차이를 같이 보여 주고 자동 판정은 하지 않는다. 2026-10-28 점검(HabitNav 20장, 9,900원~19,000원)에서 구매 확률은 가격에 반응하지 않았고 가격 답은 표시 가격을 따라갔다. sweep으로 가격을 고르지 않는다. 설계와 점검 기록: `docs/PLAN_2026-10-27_jev-sweep.md`.

**`compile.py`**는 사업계획서를 모으고 판정을 계산한다.

시험은 이렇게 돌린다.

```bash
python3 -m unittest discover -s tests -v
```

## 한계와 알아둘 점

**이사회는 공개된 틀을 적용한다. 그 사람들이 아니다.** 렌즈 3개는 Alex Hormozi의 *$100M Offers*, Peter Thiel과 Blake Masters의 *Zero to One*, Walter Isaacson의 스티브 잡스 평전에 나온 생각을 우리 말로 짧게 요약한 것이다. 4번째 렌즈는 Daniel Kahneman의 계획 오류(planning fallacy) 논의와 Bent Flyvbjerg의 준거집단 예측을 요약했다. 위원은 그 사람의 목소리로 말하지 않고, 그 사람의 말을 인용하지 않고, 그 사람이 무엇을 지지한다고 주장하지 않는다. 이 프로젝트는 어느 쪽과도 관련이 없다.

**소비자 패널은 고객이 아니라 가상 구매자다.** 돈을 쓰기 전에 반대 이유, 고객층, 문구를 빠르고 싸게 찾는 방법이다. 예측이 아니다. 언어 모델은 맞장구치는 경향이 있으므로 구매율은 상한선으로 읽는다. 큰 결정은 실제 사람으로 확인한다. `/founder-launch`가 바로 그 시험부터 시작한다. 패널 답을 후기나 증언으로 쓰지 않는다. 한국 구매자를 AI가 흉내 내면 고정관념에 기대기 쉽다. 실제 고객 자료가 있으면 그것이 먼저다.

**숫자는 입력만큼만 믿을 수 있다.** 재무 담당은 추정치를 추정이라고 표시하고 실제 견적을 요청한다. 비용은 공급처에 확인하고, 사업 구조·인건비·세금은 세무사에게 확인한다. 기준값(RCF)은 다른 사업의 과거를 말하는 것이지 이 사업의 예측이 아니다.

**조사는 링크가 붙은 공개 자료만 쓴다.** 지어낸 경쟁자, 가격, 후기, 인용은 없다. 사이트 약관을 어기는 수집도 하지 않는다.

**Codex에서 하위 에이전트(패널·이사회) 호출이 동작하는지는 아직 확인하지 않았다.** Claude Code에서는 원본과 같은 방식으로 동작하도록 만들어져 있다.

**금융·법률·세무 조언이 아니다.** 인허가, 상표, 광고 표시는 사는 곳에 따라 다르고 바뀐다. 스킬은 무엇을 어디서 확인할지 알려 줄 뿐이고, 확정은 전문가가 한다. 수수료, 세율, 기한 같은 값은 `kr.md`에 적지 않고 공식 페이지에서 현재 값을 확인하도록 안내한다.

KIPRIS Plus Open API는 인증키와 서비스별 활용신청이 필요하다. 이용 조건을 아직 확인하지 않아 1차 판은 검색 주소만 안내한다.

## 파일

```
skills/founder-rcf/          SKILL.md, sources-kr.md, rcf.py, rcf.example.json
skills/founder-board/        SKILL.md, lenses.md
skills/founder-competitors/  SKILL.md, kr.md
skills/founder-consumer/     SKILL.md, kr.md, panel.py, customer.example.json, customer.kr.example.json, pitch.example.md, pitch.kr.example.md
skills/founder-pricing/      SKILL.md, kr.md, van_westendorp.py
skills/founder-offer/        SKILL.md, kr.md
skills/founder-cfo/          SKILL.md, kr.md, unit_economics.py, example.json, example.kr.json
skills/founder-marketing/    SKILL.md, kr.md
skills/founder-brand/        SKILL.md, kr.md
skills/founder-ops/          SKILL.md, kr.md
skills/founder-launch/       SKILL.md, kr.md
skills/founder-plan/         SKILL.md, compile.py
skills/*/agents/openai.yaml  Codex 표시 정보
tests/                       모든 도구의 시험
docs/DESIGN.md               이 포크의 설계
```

내 파일은 프로젝트의 `founder/` 폴더에 쌓인다. 스킬은 서로의 파일을 읽는다.

## 크레딧과 라이선스

원본은 Jake Schincariol([opusjake.ai](https://opusjake.ai))이 만들었다. 원작자의 자매 프로젝트: [Arena](https://github.com/Jakeschincariol/arena-skill), [Replica](https://github.com/Jakeschincariol/replica-skill), [X](https://github.com/Jakeschincariol/x-agent-skill), [LinkedIn](https://github.com/Jakeschincariol/linkedin-agent-skill), [Instagram](https://github.com/Jakeschincariol/instagram-agent-skill).

MIT. 가져다 바꿔서 써도 된다. 원본 고지는 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)에 있다.
