# 목표 현금흐름 설계 (plan.py)

**목표 세후 월배당 ↔ 필요 원금을 비중안의 배당률로 계산하고, 종합과세·성장 전망·월별 공백을 판정한다.**

## 대상

- "월 300만원 배당 받으려면 얼마?", "3억으로 월 얼마?", 은퇴 현금흐름, 종합과세 회피 한도
- 입력 하나는 필수: 목표 세후 월배당(`--monthly-krw`) 또는 투자 원금(`--capital-krw`)
  - "세전"으로 말하면 ×0.85 해서 세후로 넣는다 (원천징수 15%)
- 다른 이자·배당 소득을 말하면 `--other-income-krw` (연간)

## 로직

- 스크립트: 트랙별 비중안(mix = 고배당·배당성장 반반, 캡 재적용) → 가중 배당률 → 원금/월배당 → 종합과세 판정 → 배당률 민감도 → 5·10년 전망(역사 CAGR / CPI 보수 시나리오) → 최근 12개월 배당락 기준 월별 세후 배당·공백월 보완 후보

## 경로

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe .claude/skills/dividend-consultant/scripts/plan.py (--monthly-krw 3000000 | --capital-krw 300000000) [--track high|growth|mix] [--n 10] [--other-income-krw 0] [--fx 1400]
```

| 인자 | 언제 |
|---|---|
| `--track high` | 지금 소득 필요·은퇴 |
| `--track growth` | 축적기·장기 |
| `--track mix` (기본) | 불명확, 둘 다 |

## 필드

| 리포트 항목 | JSON 경로 |
|---|---|
| 결론 | `result.capital_krw` (억 단위) 또는 `result.monthly_after_tax_krw`, `portfolio.gross_yield` |
| 종합과세 | `tax.comprehensive_taxation`, `financial_income_total_krw` vs `threshold_krw`, `max_monthly_after_tax_below_threshold_krw` |
| 비중안 표 | `portfolio.positions[]`: Symbol, Track, Weight, Amount_KRW, Shares, Div. Yield, Safety_Grade, Pay_Months |
| 민감도 | `sensitivity[]` — 배당률 3~7%별 필요 원금(또는 월배당) |
| 전망 | `projection_monthly_after_tax_krw`: historical / conservative_cpi × no_reinvest / reinvest × 5·10년, `growth_rates` |
| 월별 배당 | `calendar.monthly_after_tax_krw` 12칸, `empty_months`, `fillers[]` |

- 전망은 두 시나리오를 함께 보여주고 보수 시나리오를 기준으로 서술 (역사 CAGR은 최근 고성장 반영)
- 종합과세 true → "₩2,000만 이하로 맞추려면 세후 월 ≤ max_monthly…" + 연금저축·ISA 등 계좌 분산은 [정성] §10·§11

## 예외

- `calendar`가 비거나 `usdkrw` null → 월별 표 생략, 환율 실패 명시 (`--fx`로 재실행 가능)
- 월별 합계는 최근 12개월 실제 지급 기준이라 `result` 연간 금액과 다를 수 있음 → 1줄 명시
- 목표가 비현실적(원금 > 사용자가 말한 자산) → 숫자만 제시, 배당률을 높이는 쪽(고위험)으로 유도하지 않음
