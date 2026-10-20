# 한국 재무 입력 (founder-cfo)

`founder/locale.json`의 `country`가 `KR`일 때 읽는다.

이 문서는 법률·세무 조언이 아니다. 세율, 수수료, 신고 기한, 과세 기준은 바뀐다. 아래 공식 페이지에서 현재 값을 확인하라. 구조, 인건비, 세금은 세무사에게 확인하라.

## numbers.json 설정

```json
{"currency": "KRW", "price_includes_vat": true, "vat_rate": 0.10}
```

- `price`는 소비자가(부가세 포함)를 넣는다. 도구가 `net_price = price / (1 + vat_rate)`로 부가세 제외 가격을 구해 매출, 공헌이익, 마진, 손익분기에 쓴다. 보고서 "One unit" 표 첫 줄에 두 가격이 함께 나온다.
- 부가세율 10%는 부가가치세법에 정해져 있다(국가법령정보센터 https://www.law.go.kr 에서 "부가가치세법"의 세율 조문).
- `variable`, `fixed_monthly`, `startup`은 **부가세 제외 금액**으로 넣는다. 일반과세자는 매입세액을 공제받기 때문이다. 견적서와 세금계산서의 공급가액을 쓴다.
- 간이과세자는 계산이 다르다(업종별 부가가치율 적용, 매입세액 공제 방식 차이). 이 도구는 일반과세자 기준이다. 간이과세자라면 세무사 확인 문구를 보고서에 넣는다. 일반·간이 구분 기준은 국세청 https://www.nts.go.kr 과 홈택스 https://www.hometax.go.kr 에서 확인한다.
- 예시: `example.kr.json` (KRW, 부가세 포함. 값은 예시다. 실제 견적으로 바꾼다).

## 비용 항목

값은 적지 않는다. 항목마다 확인할 곳을 적는다.

| 항목 | 넣는 곳 | 현재 값 확인 |
|---|---|---|
| 카드 수수료 | `variable`(매출 대비 비율을 판매가에 곱해 한 건 비용으로) | 연매출 구간별 우대 수수료율이 있다. 여신금융협회 가맹점 매출거래정보 https://www.cardsales.or.kr 에서 적용 요율을 확인한다. |
| 배달앱 | 건당 수수료·배달비는 `variable`, 월 광고비·월정액은 `fixed_monthly` | 배달의민족 https://ceo.baemin.com , 쿠팡이츠 https://partner.coupangeats.com 의 요금 안내. 중개수수료, 배달비, 결제수수료, 광고비를 따로 적는다. |
| 오픈마켓 | `variable` | 네이버 스마트스토어센터 https://sell.smartstore.naver.com 의 수수료 안내. 판매수수료와 결제수수료가 따로 붙는다. 쿠팡 윙(https://wing.coupang.com )은 로그인이 필요하다. |
| 앱마켓 | `variable` | Apple https://developer.apple.com/app-store/small-business-program/ , Google Play https://support.google.com/googleplay/android-developer/answer/112622 의 수수료 안내. |
| 4대보험 사업주 부담분 | `fixed_monthly` 인건비에 포함 | 4대사회보험 정보연계센터 https://www.4insure.or.kr |
| 최저임금 | 인건비 가정 | 최저임금위원회 https://www.minimumwage.go.kr |
| 소득세·법인세 | 이 도구는 계산하지 않는다 | 홈택스, 세무사 |

수수료율은 연매출과 입점 조건에 따라 업체마다 다르다. 내 조건으로 적용되는 요율을 해당 사이트에서 확인해 `founder/cfo-sources.md`에 날짜와 함께 적는다.

## 기준 집단으로 ramp 점검

`ramp_per_day`는 계획이 거짓말하기 쉬운 곳이다. `founder/rcf.json`이 있으면 비교한다.

```bash
python3 "${CLAUDE_SKILL_DIR}/../founder-rcf/rcf.py" compare --rcf founder/rcf.json --numbers founder/numbers.json
```
