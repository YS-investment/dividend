# 포트폴리오 진단·개선 (portfolio.py)

**보유 종목의 배당소득·집중도·취약 종목을 판정하고, 집중 해소 수량과 교체 후보를 제시한다.**

## 대상

- "내 포트폴리오 진단", "리밸런싱", "이 종목들 괜찮아?", 월별 배당 확인
- 입력 우선순위: 채팅에 붙인 종목·수량 → 없으면 레포 루트 `holdings.csv` (`symbol,shares`)
  - 둘 다 없으면 "KO 100, O 50" 형식으로 달라고 한 번 묻는다
  - 금액만 주면 수량으로 바꿔 달라고 요청 (스크립트는 수량 기준)

## 로직

- 스크립트: `diagnose_portfolio` (소득·월별·섹터·등급·플래그) → 종목별 액션(`Hold_Action`) → 집중 해소 목표(`rebalance`) → `교체 검토` 종목의 대체 후보(같은 Sector_Group 우선, 두 트랙 매수 가능 종목)

## 경로

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe .claude/skills/dividend-consultant/scripts/portfolio.py [--text "KO 100, O 300"] [--file holdings.csv] [--alternatives 3]
```

## 필드

| 리포트 항목 | JSON 경로 |
|---|---|
| 결론 | `summary.annual_income_usd`/`annual_income_krw`, `portfolio_yield`, `after_tax_income_krw`(÷12 = 세후 월), `by_action` |
| 경고 | `summary.flags[]` — 문구 그대로 목록 |
| 보유 표 | `holdings[]`: Symbol, Value_Share, Income_Share, Yield_On_Price, Safety_Grade, Valuation, Timing_Signal, Hold_Action |
| 월별 배당 | `monthly_income_usd[]` (Month, Income) — 12칸 표, 0인 달 강조 |
| 섹터·등급 | `sectors[]` Value_Share, `grades[]` Income_Share |
| 개선안 ① 집중 | `rebalance[]`: 종목 → shares_now → shares_target, 섹터 → reduce_value_usd 또는 or_add_other_sectors_usd |
| 개선안 ② 교체 | `alternatives[]`: replace + reasons → candidates(Symbol, Sector_Group, Div. Yield, Safety_Grade, Valuation, Track, Action) |
| 성장성 | `summary.weighted_div_growth_5y` |

- 개선안 순서: 교체 검토 → 집중 해소 → 지급월 공백(§9 1·4·7·10 / 2·5·8·11 / 3·6·9·12 조합 설명)
- 교체 후보를 더 알고 싶다면 → `stock.py <후보들>` 연결

## 예외

- `summary.outside_universe` 종목 → "유니버스 밖, 실시간 계산" 표시
- ETF(`Hold_Action == '보유 (ETF)'`) → 등급·교체 대상 아님, §11 ETF 체크
- `annual_income_krw`가 null(환율 실패) → 달러만 표기
- 종합과세 플래그 → §10 범위(경고만, 누진 계산 안 함) 명시, 세무 전문가 확인 권고
