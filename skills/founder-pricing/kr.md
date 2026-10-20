# 한국 가격 설정 (founder-pricing)

`founder/locale.json`의 `country`가 `KR`일 때 읽는다.

이 문서는 법률·세무 조언이 아니다. 세율과 수수료는 바뀐다. 현재 값은 공식 페이지에서 확인하라.

## 원화 가격

```bash
python3 "${CLAUDE_SKILL_DIR}/van_westendorp.py" founder/panel/answers --currency KRW --price 6500 --out founder/pricing-curve.md
```

- `--currency KRW`면 가격 격자를 10원 간격으로 만든다. 결과 가격은 10원 단위가 아닐 수 있다.
- `--currency`를 빼면 패널의 `customer.json` 통화를 쓴다.
- 입력 숫자의 `₩`, `원`, 공백은 지워진다.
- 패널이 여러 시장이면 `--market NAME`이 필요하다(예: `--market Korea`). 통화가 다른 답을 한 표에 섞지 않는다.

## 부가세 포함 가격

한국 소비자 가격은 부가세 포함 금액으로 표시하는 것이 일반적이다. `founder/numbers.json`에서 `price_includes_vat`를 `true`로, `vat_rate`를 `0.10`으로 둔다. 부가세율 10%는 부가가치세법에 정해져 있다(국가법령정보센터 https://www.law.go.kr 에서 "부가가치세법"). 마진 계산은 부가세 제외 금액 기준이다. 자세한 항목은 `/founder-cfo`의 `kr.md`를 읽는다.

## 경쟁자 가격 비교

- 네이버 지도·카카오맵의 메뉴 가격과 배달앱 가격을 구분해 기록한다. 배달앱 가격이 매장 가격과 다를 수 있다.
- 가격에 부가세가 포함되었는지 확인하고 같은 기준으로 비교한다.
- 없던 "정상가"를 만들어 할인율을 보이지 않는다. 표시·광고 규제는 `/founder-marketing`의 `kr.md`를 읽는다.
