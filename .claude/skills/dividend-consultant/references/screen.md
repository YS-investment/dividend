# 종목 발굴 (screen.py)

**트랙 게이트 통과 종목을 점수순으로 보여주고, 매수 가능 라벨 종목으로 비중안을 만든다.**

## 대상

- 새 종목 추천, 트랙별 후보, 새 포트폴리오 구성 요청
- 트랙 선택 (§3 "어떤 트랙을 쓸까")
  - 지금 배당소득 필요·은퇴·원금 큼 → `high`
  - 적립기·장기·연금 계좌 → `growth`
  - 불명확 → 한 번 묻는다. 둘 다 원하면 두 번 실행

## 로직

- 스크립트: 유니버스 전체 백분위 → 트랙 게이트(`filter_stocks`, 화면 기본값과 동일) → 점수 → 액션 라벨 → 비중안
- 비중안: `분할매수`/`매수 검토` 종목만, 점수순, 섹터당 최대 floor(n×35%)개, 종목 소득비중 ≤ 20%·평가액 ≤ 2/n

## 경로

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe .claude/skills/dividend-consultant/scripts/screen.py --track high|growth [--top 15] [--n 10] [--large-cap] [--sector "Utilities"] [--exclude KO,PEP]
```

| 인자 | 언제 |
|---|---|
| `--large-cap` | growth 트랙에서 "대형주만", 변동성 회피 요청 ($200억 이상) |
| `--sector` | 섹터 지정 요청 (StockAnalysis Sector 이름, 반복 가능) |
| `--exclude` | 이미 보유했거나 제외 요청한 종목 |
| `--n` | 원하는 종목 수 (기본 10) |

## 필드

| 리포트 항목 | JSON 경로 |
|---|---|
| 결론: 통과 수 / 유니버스 | `counts.passed` / `counts.universe`, `counts.by_action` |
| 적용 기준 | `params` (min_yield, min_growth_5y 등 — %로 표기), `macro` |
| 후보 표 | `candidates[]`: Symbol, Company Name, Sector, Div. Yield, Div_CAGR_5Y_Adj, Div. Gr. Years, Safety_Grade, Valuation, Timing_Signal, Score, Action |
| 비중안 표 | `proposal.positions[]`: Symbol, Weight, Div. Yield, Safety_Grade, Action |
| 비중안 요약 | `proposal.expected_yield`, `expected_after_tax_yield`, `weighted_div_cagr_5y`, `sector_shares` |
| ₩1억당 세후 월배당 | `proposal.monthly_after_tax_krw_per_100m` (§10 어림 계산) |
| 주의사항 | 후보의 `Alert`(배당률 10% 초과), `Yield_Trap`, `EPS_Alert`, `Crisis_Passed` 빈 값, `proposal.small_caps` |

- 후보 표는 `Action` 순으로 묶지 않고 점수순 유지, 라벨은 열로 표시
- 정확한 목표 금액 계산 요청은 plan 모드로 연결

## 예외

- `proposal.filled_positions < requested_positions` → "매수 가능 라벨 종목이 N개뿐" 명시, 다른 트랙 병행 제안
- `counts.passed == 0` → 기준을 낮추지 않는다. "현재 기준 통과 종목 없음" + 관심 종목이 있으면 `stock.py`로 탈락 이유 확인 제안
- `proposal.small_caps` 비어 있지 않음 → 시총 $20억 미만 종목 유동성·변동성 주의 1줄
