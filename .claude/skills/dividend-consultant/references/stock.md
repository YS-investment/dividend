# 개별 종목 분석 (stock.py)

**한 종목의 배당 지속성·가격 매력을 등급·라벨로 판정하고, 트랙별 탈락 이유를 보여준다.**

## 대상

- "KO 어때", "O 배당 안전해?", "MO vs PM", 발굴·진단 결과의 후속 질문
- 티커 여러 개는 한 번에 실행 (비교 표)
- 유니버스 밖 종목·ETF도 가능 (실시간 계산)

## 로직

- 스크립트: 유니버스 행(없으면 yfinance 실시간) → 안전성 등급 세부 → 삭감·위기 → 밸류·타이밍 → 트랙별 게이트(`failed_gates`) → 액션 라벨 → 정성 체크리스트 키
- `failed_gates`는 게이트를 하나씩 단독 검사한 결과 (여러 개면 모두 걸린 것)

## 경로

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe .claude/skills/dividend-consultant/scripts/stock.py KO [O PEP ...]
```

- 한국 종목·잘못된 티커 → `error` 반환. 미국 티커(점 포함 `BF.B` 그대로)로 다시 받는다

## 필드

| 리포트 항목 | JSON 경로 (`stocks[i]`) |
|---|---|
| 결론 | `action.label` + `action.reasons`, `safety.Safety_Grade`, `valuation.Valuation` |
| 배당 | `dividend`: Div. Yield, Div_CAGR_5Y_Adj, Div. Gr. Years, Payout Ratio, chowder_number |
| 안전성 (§7) | `safety.Safety_Detail` (요소별 0–2점) → 요소별 표, Div_Coverage+Coverage_Basis, Net_Debt_EBITDA, Interest_Coverage |
| 실적 (§4-3) | `fundamentals`: Revenue_CAGR_3Y, EPS_CAGR_3Y, Growth_Badge, EPS_Alert |
| 삭감·위기 (§5) | `cut_crisis`: Cut_Flag, Div_Last_Cut_Year, Crisis_Passed |
| 밸류 (§8) | `valuation`: Yield_Pctl_5Y, Yield_TTM vs 5Y 평균/최저/최고, Yield_Trap |
| 타이밍 (§8) | `timing`: Timing_Signal, Price_vs_MA20, RSI_14, MFI_14, Timing_As_Of |
| 트랙 적합성 | `tracks.high/growth`: passed, failed_gates, rank/of, score |
| 정성 점검 (§11) | `checklist[]`: key + why → 기준서 §11 해당 항목 설명 |

- `Safety_Detail` 요소명 → 한국어: coverage 커버리지 · leverage 부채 · interest 이자보상 · cut_history 삭감 이력 · stability 이익 안정성 · crisis 위기 가점
- 여러 종목이면 종목별 섹션 대신 한 비교 표 + 종목별 결론 1줄

## 예외

- `in_universe == false` → "유니버스 밖 — 순위·점수 없음" 표시, `(데이터 없음)` 게이트는 데이터 부족으로 설명
- `Safety_Grade == 'ETF'` → 트랙·등급 생략, 배당률·5Y 성장·밸류와 ETF 체크리스트만
- `Safety_Grade == 'N/A'` → 데이터 부족(요소 3개 미만), 등급 대신 확인 가능한 지표만
