# 데이터 신뢰도 점검 결과 — 수정 명세

작성일 2026-08-02 · 대상 커밋 `75b311e` (`final_df2.csv` 기준일 2026-07-31)

---

## 이 문서를 읽는 방법

**여기 적힌 결론을 그대로 믿고 구현하지 마십시오.**

항목마다 `[재현]` 스크립트와 `[기대값]`을 붙여놨습니다. **먼저 돌려서 숫자가 재현되는지 확인한 뒤**
수정에 들어가십시오. 재현이 안 되면 이 문서가 틀린 것이고, 그 경우 이 문서를 버리는 것이 맞습니다.

작성자는 외부에서 산출물(`final_df2.csv`)을 소비하는 쪽에서 역추적했고,
**스크래핑 파이프라인을 실제로 실행해보지는 못했습니다.** `update_all_data(use_scraping=True)`가
필요한 검증은 전부 미확인 상태입니다.

이 문서의 재현 스크립트는 작성 시점에 전부 실행해 기대값이 나오는 것을 확인했습니다.
특히 문제 1의 `their_way()`는 **저장된 `final_df2.csv` 값과 소수점까지 일치**했습니다
(KO·XOM·MO·ABBV 4종목). 코드 이해가 맞다는 근거이므로, 이 검증이 깨지면 나머지도 의심하십시오.

### 시작 전 필수 — `git pull`

이 문서의 모든 수치는 **`75b311e` (데이터 기준일 2026-07-31)** 기준입니다.
작성 시점의 로컬 클론은 `3a137fa` (07-13)로 **3주 뒤처져 있었고, 수치가 크게 다릅니다.**

| 항목 | 로컬 `3a137fa` | 원격 `75b311e` |
|---|---:|---:|
| 행 수 | 199 | 204 |
| `FCF_Dividend_Ratio == 0` | **33 (17%)** | **95 (47%)** |
| 5Y 밴드 `== 0` | 9 | 10 |

```bash
git pull                     # 먼저
git log -1 --format=%h       # 75b311e 이상인지 확인
```

당기지 않고 재현하면 기대값이 안 맞고, 이 문서가 틀렸다고 오판하게 됩니다.

모든 재현 스크립트는 이 저장소 루트에서 실행하는 것을 전제로 합니다.

```python
import pandas as pd, yfinance as yf, warnings
warnings.filterwarnings('ignore')
u = pd.read_csv('data/final_df2.csv')
```

---

## ⚠️ 0순위 — 손대기 전에 반드시 읽을 것

### 결측 표현을 바꾸면 스크리너 순위가 통째로 바뀝니다

`data_collector.py:851-853`이 yfinance 보강 컬럼을 전부 `0.0`으로 초기화합니다.
조회에 실패하면 그대로 `0.0`이 남습니다. **즉 `0.0`은 "값이 0"이 아니라 "모름"입니다.**

아래 문제 대부분의 근원이 이것이라 `NaN`으로 바꾸고 싶어지지만, 그 전에:

- `data_processor.py:169-177`이 `FCF_Dividend_Ratio`와 `Debt_to_Equity`를 **정규화해서
  복합점수(`high_div_composite` / `dividend_growth_composite`)에 넣습니다.**
- `0.0`을 `NaN`으로 바꾸면 정규화 분포가 달라지고 → **전 종목 점수가 바뀌고**
  → **두 스크리너(`pages/1_`, `pages/2_`)의 순위가 전부 바뀝니다.**
- `data_collector.py:982`의 `.fillna(0)`, `991-992`의 `if ... > 0 else 0` 가드도
  같은 전제 위에 서 있습니다.

**작업 순서 권고**

1. 수정 전 `final_df2.csv`를 보관하고, 두 스크리너의 상위 30종목·점수를 기록해 둡니다.
2. 값을 채우는 수정(문제 1·2·4)을 **먼저** 합니다. 이건 결측을 줄이므로 순위가 개선되는 방향입니다.
3. 결측 표현 변경(문제 5)은 **마지막에 독립 커밋**으로 하고, 전후 순위표를 나란히 비교합니다.
4. 순위가 크게 흔들리면 그건 버그가 아니라 **원래 0.0이 점수를 왜곡하고 있었다는 증거**입니다.
   다만 그 사실을 확인하고 넘어가야 합니다.

---

## 문제 1 — 배당률 밴드가 최댓값을 과소평가한다

**위치** `modules/data_collector.py:913-951`

**무엇이 문제인가**

밴드를 이렇게 만듭니다.

```python
hist_df['Dividends'] = hist_df['Dividends'].replace(0, float('nan')).ffill()   # 919
hist_df['Annual_Dividends'] = hist_df['Dividends'] * annual_multiplier          # 933
```

**마지막 1회 지급액 × 연간 지급횟수**로 연배당을 추정합니다.
지급액이 회차마다 다르거나 지급 시점이 밀리면 실제 최근 1년 합계와 벌어집니다.

**증거** — 최근 1년 실지급 합계(TTM 롤링)와 비교한 5년 밴드

| 종목 | 현재 방식 max | TTM 합계 max | 차이 |
|---|---:|---:|---:|
| T | 16.37% | **20.47%** | −20% |
| KO | 3.81% | **4.68%** | −19% |
| MO | 12.45% | **14.45%** | −14% |
| ABBV | 5.87% | 6.03% | −3% |
| XOM | 7.81% | 7.81% | 일치 |

**왜 중요한가** — 밴드 상단은 "지금이 싼가"를 재는 기준선입니다.
상단이 낮게 잡히면 현재 배당률이 상단에 더 가까워 보여 **매수 신호가 과하게 뜹니다.**
`Five_y_DividendYield_diff` · `Ten_y_DividendYield_diff`도 같은 밴드에서 파생되므로 함께 흔들립니다.

**[재현]**

```python
def their_way(t, freq=4):
    h = yf.Ticker(t).history(period='11y')[['Dividends','Close']]
    h['Dividends'] = h['Dividends'].replace(0, float('nan')).ffill()
    y = (h['Dividends'] * freq) / h['Close']
    return y.rolling(1260).mean().iloc[-1], y.rolling(1260).min().iloc[-1], y.rolling(1260).max().iloc[-1]

def ttm_way(t):
    tk = yf.Ticker(t); h = tk.history(period='11y')[['Close']]; d = tk.dividends
    if d.index.tz is not None: d.index = d.index.tz_localize(None)
    if h.index.tz is not None: h.index = h.index.tz_localize(None)
    y = (d.rolling('365D').sum().reindex(h.index, method='ffill') / h['Close']).dropna().tail(1260)
    return y.mean(), y.min(), y.max()

for t in ('KO','XOM','MO','T','ABBV'):
    print(t, [round(x*100,2) for x in their_way(t)], [round(x*100,2) for x in ttm_way(t)])
```

**[기대값]**

- `their_way`가 `final_df2.csv`의 저장값과 **정확히 일치**해야 합니다.
  (KO `3.15 / 2.38 / 3.81`, XOM `4.03 / 2.42 / 7.81`, MO `9.44 / 5.66 / 12.45`, ABBV `4.03 / 2.63 / 5.87`)
  일치하지 않으면 이 문서의 코드 이해가 틀린 것이므로 **여기서 멈추고 재검토**하십시오.
- `ttm_way`의 max가 위 표대로 더 높게 나와야 합니다.

**수정 방향** — 연배당을 `dividends.rolling('365D').sum()`으로 바꿉니다.
`Payout Freq.` 기반 배수(`921-931`)가 통째로 불필요해집니다.
단, 스크래핑된 `Payout Freq.`가 틀린 종목에서도 견고해지는 부수 효과가 있습니다.

---

## 문제 2 — `ffill()`이 배당 중단을 감추고, `rolling(1260)`이 이력 부족을 0으로 만든다

**위치** `modules/data_collector.py:919, 937-942, 946-951`

### 2-1. `ffill()`

`.replace(0, nan).ffill()`은 **마지막 지급액을 무한히 이어붙입니다.**
배당을 중단한 종목도 배당률이 0으로 떨어지지 않고 마지막 값이 계속 유지됩니다.

⚠️ **현재 204종목 유니버스에서는 실제 사례를 찾지 못했습니다** (전부 배당 지속 종목이라 당연합니다).
논리상의 결함이며, 스크리닝 이전 단계인 5,609종목 원본(`dividend_from_stockanalysis.csv`)이나
향후 배당 삭감 종목에서 드러납니다. **우선순위는 낮게 두되 문제 1 수정 시 함께 사라집니다**
(TTM 롤링 합계는 지급이 끊기면 자연히 0으로 내려갑니다).

### 2-2. `rolling(1260)`은 거래일 행 수 기준

`period="11y"`를 받아 `rolling(window=1260)`을 겁니다. 1260은 **행 개수**이므로
상장 이력이 5년 미만이면 전 구간이 `NaN`이고, `946-951`이 이를 `0.0`으로 저장합니다.

**증거** — 5Y 밴드가 `0`인 종목 **10/204**, 10Y 밴드가 `0`인 종목 **13/204**

| 종목 | 11년 조회 행수 | 진단 |
|---|---:|---|
| KVUE | 813 | 이력 부족 (1260 미만) |
| FG | 924 | 이력 부족 |
| LANC | 1 | **일시적 조회 실패로 보임** (장기 상장주) |
| JHG | 3 | **일시적 조회 실패로 보임** |

**LANC·JHG는 이력 부족이 아닙니다.** 수십 년 상장된 종목인데 1~3행만 돌아왔습니다.
yfinance 일시 오류이고, `953-958`의 `except: pass`가 이를 삼켜 `0.0`이 남습니다.
**재시도나 실패 기록이 없어 다음 실행에서도 조용히 넘어갑니다.**

**[재현]**

```python
u = pd.read_csv('data/final_df2.csv')
zero = u[u['Trainling_5Y_avg_dividend_yield'] == 0]['Symbol'].tolist()
print(len(zero), zero)
for s in zero:
    try: n = len(yf.Ticker(s).history(period='11y'))
    except Exception: n = -1
    print(f"{s:8} {n:>6}행  {'이력부족' if 0 < n < 1260 else ('조회실패' if n <= 0 else '충분')}")
```

**[기대값]** 10개 종목. KVUE 813행 · FG 924행 · LANC 1행 · JHG 3행.
행수가 다르게 나오면 조회 시점 문제이므로 **여러 번 돌려 재현성을 먼저 확인**하십시오.

**수정 방향**

- `rolling(window=1260)` → `rolling('1825D')` 등 **기간 기준**으로 바꾸고 `min_periods`를 명시합니다.
- 이력이 부족하면 `0.0`이 아니라 **결측으로 남기고**, 몇 년치로 계산했는지 별도 컬럼에 기록합니다.
- 조회 행수가 비정상(예: 100행 미만)이면 **재시도**하고, 그래도 실패하면 실패 목록에 기록합니다.

---

## 문제 3 — 점(`.`) 들어간 티커는 yfinance 보강이 통째로 실패한다

**위치** `modules/data_collector.py:856-962` (티커를 그대로 `yf.Ticker()`에 넘기는 전 구간)

**무엇이 문제인가**

yfinance는 클래스주 구분자로 **하이픈**을 씁니다. 스크래핑 원본은 **점**을 씁니다.
변환 없이 넘기므로 조회가 실패하고, 그 종목의 **yfinance 보강 컬럼이 전부 `0.0`**이 됩니다.

**증거** — 유니버스의 점 포함 티커 3개 전부, 모든 yfinance 컬럼이 `0.0`

| 티커 | ROE | Debt_to_Equity | FCF_Dividend_Ratio | 5Y avg | `-` 변환 시 조회 행수 |
|---|---:|---:|---:|---:|---:|
| BF.B | 0.0 | 0.0 | 0.0 | 0.0 | **2765** |
| MKC.V | 0.0 | 0.0 | 0.0 | 0.0 | **2765** |
| AGM.A | 0.0 | 0.0 | 0.0 | 0.0 | **2765** |

전부 정상 조회되는 종목입니다. **표기 변환만 하면 즉시 해결됩니다.**

**[재현]**

```python
for s in ('BF.B','MKC.V','AGM.A'):
    a = len(yf.Ticker(s).history(period='11y'))
    b = len(yf.Ticker(s.replace('.','-')).history(period='11y'))
    print(f"{s:8} 원본 {a:>5}행 → 하이픈 변환 {b:>5}행")
    print("   저장값:", u[u['Symbol']==s][['ROE','Debt_to_Equity','FCF_Dividend_Ratio']].to_dict('records'))
```

**[기대값]** 원본 0행 → 변환 후 2765행. 저장값은 전부 `0.0`.

**수정 방향** — yfinance 호출 직전에만 `symbol.replace('.', '-')`를 적용합니다.
**`Symbol` 컬럼 자체는 바꾸지 마십시오** — 스크래핑 원본·프리미엄 명단(`dividend_aristocrats.csv` 등)과
조인 키가 어긋납니다. 조회용 별칭으로만 씁니다.

`MKC`와 `MKC.V`가 동시에 유니버스에 있어 **같은 회사가 두 줄**로 잡힙니다.
클래스주를 유니버스에 남길지는 별도 판단이 필요합니다.

---

## 문제 4 — `FCF_Dividend_Ratio`가 204종목 중 95개(47%) 결측이다

**위치** `modules/data_collector.py:877-891`

**무엇이 문제인가**

```python
fcf = ticker_obj.info.get('freeCashflow', 0)
shares = ticker_obj.info.get('sharesOutstanding', 0)
div_rate = ticker_obj.info.get('dividendRate', 0)
if fcf != 0 and shares > 0 and div_rate > 0:
    ...
```

`info['freeCashflow']`가 비는 종목이 많고, 셋 중 하나만 없어도 통째로 건너뜁니다.
**결과적으로 절반 가까이가 `0.0`으로 남고, 이 값이 복합점수 정규화에 들어갑니다.**

**증거 ① — 결측률이 실행마다 크게 흔들린다 (이게 핵심입니다)**

| 커밋 | 데이터 기준일 | `FCF == 0` | 비율 |
|---|---|---:|---:|
| `3a137fa` | 2026-07-13 | 33 / 199 | **17%** |
| `75b311e` | 2026-07-31 | 95 / 204 | **47%** |

**3주 만에 결측이 3배로 뛰었습니다.** 종목 구성은 거의 그대로입니다.
개별 종목도 오갑니다 — XOM은 07-13에 `0.68`이었다가 07-31에 `0.0`이 됐습니다.

즉 **특정 종목이 FCF를 안 주는 게 아니라, `info['freeCashflow']` 호출이 그날그날 실패**합니다.
어떤 날 산출된 `final_df2.csv`인지에 따라 복합점수와 스크리너 순위가 달라진다는 뜻입니다.
문제 6(예외 삼킴)과 겹쳐서, **이 변동이 아무 로그에도 남지 않습니다.**

**증거 ② — 현금흐름표 기반은 커버리지가 높다**

외부에서 상위 20종목에 적용한 결과 **18/20 확보** (`info` 방식은 12/20)

**대체 산출** — `ticker.cashflow`의 `Free Cash Flow` ÷ `Cash Dividends Paid`

| 종목 | 현재 저장값 | 현금흐름표 기반 |
|---|---:|---:|
| KO | 0.57 | 0.60 |
| ADP | 1.97 | 1.83 |
| MO | 1.28 | 1.30 |
| KMB | 0.62 | 0.99 |

값이 서로 근접하므로 **정의가 바뀌는 것이 아니라 결측만 메우는 변경**입니다.

**[재현]**

```python
def fcf_from_stmt(t):
    cf = yf.Ticker(t).cashflow
    if cf is None or cf.empty: return None
    fcf = cf.loc['Free Cash Flow'].dropna().iloc[0] if 'Free Cash Flow' in cf.index else None
    paid = None
    for k in ('Cash Dividends Paid','Common Stock Dividend Paid','Dividends Paid'):
        if k in cf.index:
            v = cf.loc[k].dropna()
            if len(v): paid = abs(float(v.iloc[0])); break
    return round(fcf/paid, 2) if (fcf is not None and paid) else None

print("결측:", int((u['FCF_Dividend_Ratio']==0).sum()), "/", len(u))
for t in ('KO','ADP','MO','KMB'):
    print(t, u[u['Symbol']==t]['FCF_Dividend_Ratio'].iloc[0], '→', fcf_from_stmt(t))

# 결측률이 실행마다 흔들리는지 — 과거 커밋과 비교
import subprocess, io as _io
old = pd.read_csv(_io.BytesIO(subprocess.run(
    ['git','show','3a137fa:data/final_df2.csv'], capture_output=True).stdout))
print(f"3a137fa: {int((old['FCF_Dividend_Ratio']==0).sum())}/{len(old)}")
print("XOM:", old[old['Symbol']=='XOM']['FCF_Dividend_Ratio'].iloc[0],
      "→", u[u['Symbol']=='XOM']['FCF_Dividend_Ratio'].iloc[0])
```

**[기대값]** 결측 95/204 (`3a137fa`에서는 33/199). XOM `0.68` → `0.0`. 대체값은 위 표대로.

**수정 방향** — 현금흐름표를 1순위, `info['freeCashflow']`를 폴백으로 씁니다.
둘 다 실패하면 `0.0`이 아니라 **결측으로 남깁니다** (0순위 경고 참조).

⚠️ **부호에 주의하십시오.** 이 비율은 **높을수록 안전**합니다 (FCF가 배당을 몇 배 덮는가).
`1.0` 미만은 배당을 잉여현금흐름으로 못 덮는다는 뜻입니다.
현재 저장값 중 음수가 17개 있는데, 이는 FCF 적자로 실제 위험 신호입니다.
`0.0`(결측)과 음수(적자)를 같은 것으로 취급하면 안 됩니다.

---

## 문제 5 — `0.0`을 결측 표시로 쓰는 구조

**위치** `modules/data_collector.py:851-853`, `982`, `991-992`

```python
for col in yf_columns:
    if 'dividend' in col.lower() or col in ['FCF_Dividend_Ratio','Debt_to_Equity','ROE','EPS_Growth']:
        result[col] = 0.0        # ← 여기
```

**영향받는 컬럼** — `FCF_Dividend_Ratio` · `Debt_to_Equity` · `ROE` · `EPS_Growth` ·
`fiveYearAvgDivdendYield` · `Trainling_{5Y,10Y}_{avg,min,max}_dividend_yield` (10개)

문제 1~4가 만드는 결측이 전부 여기로 흘러들어 **"조회 실패"와 "실제로 0"이 구분되지 않습니다.**
`ROE = 0.0`인 종목이 적자 기업인지 조회 실패인지 데이터만 봐서는 알 수 없습니다.

**[재현]**

```python
cols = ['FCF_Dividend_Ratio','Debt_to_Equity','ROE','EPS_Growth',
        'Trainling_5Y_avg_dividend_yield','Trainling_10Y_avg_dividend_yield']
for c in cols:
    print(f"{c:38} 0값 {int((u[c]==0).sum()):>4}/{len(u)}")
```

**[기대값]** `75b311e` 기준

| 컬럼 | `0` 개수 |
|---|---:|
| `FCF_Dividend_Ratio` | 95 / 204 |
| `Debt_to_Equity` | 40 / 204 |
| `ROE` | 23 / 204 |
| `EPS_Growth` | 22 / 204 |
| `Trainling_5Y_avg_dividend_yield` | 10 / 204 |
| `Trainling_10Y_avg_dividend_yield` | 13 / 204 |

`ROE = 0`인 23종목 중 실제 적자 기업이 몇인지는 확인하지 않았습니다.
**결측과 실제 0이 섞여 있으므로 이 숫자를 "적자 기업 수"로 읽으면 안 됩니다.**

**수정 방향**

- 초기값을 `pd.NA`(또는 `np.nan`)로 바꿉니다.
- **0순위 경고대로 마지막에, 독립 커밋으로, 순위 전후 비교와 함께** 진행합니다.
- `data_processor.py`의 정규화가 결측을 어떻게 다룰지 먼저 정합니다
  (중앙값 대체 / 해당 지표 가중치 제외 / 종목 제외 — 어느 쪽이든 명시적으로).
- 결측 사유를 별도 컬럼(`_enrich_failed` 등)에 남기면 다음 점검이 쉬워집니다.

---

## 문제 6 — 예외를 전부 삼켜 실패가 보이지 않는다

**위치** `modules/data_collector.py:867, 910, 953-958, 960-962`

```python
except Exception as e:
    if "404" in str(e) or "delisted" in str(e).lower():
        pass          # 953-958
    else:
        pass
...
except Exception as e:
    continue          # 960-962
```

어떤 종목이 왜 실패했는지 **아무 기록도 남지 않습니다.**
문제 3(티커 표기)이 오래 발견되지 않은 것도, 문제 2-2의 LANC·JHG가 조용히 `0.0`이 된 것도
이 구조 때문입니다. GitHub Actions 로그에도 남지 않으므로 매일 돌아도 알 수 없습니다.

**수정 방향** — 실패를 세어서 요약을 출력하고, 실패 목록을 파일로 남깁니다.

```python
# 예시
failures = []   # (symbol, stage, reason)
...
except Exception as e:
    failures.append((ticker_symbol, 'rolling_metrics', str(e)[:120]))
    continue
...
# STAGE 3 종료 시
print(f"보강 실패 {len(failures)}종목")
if failures:
    pd.DataFrame(failures, columns=['Symbol','stage','reason']).to_csv(
        'data/enrichment_failures.csv', index=False)
```

**실패율이 일정 비율(예: 10%)을 넘으면 `update_all_data`가 중단**하도록 하는 것도 검토할 만합니다.
`validate_scraped_data`가 스크래핑 단계에는 있지만 **보강 단계에는 대응하는 검증이 없습니다.**

---

## 우선순위 요약

| # | 문제 | 영향 | 난이도 | 순서 |
|:-:|---|---|---|:-:|
| 3 | 점 티커 조회 실패 | 3종목 전 컬럼 결측 | 매우 낮음 (한 줄) | **1** |
| 6 | 예외 삼킴 | 모든 문제를 은폐 | 낮음 | **2** |
| 4 | FCF 결측률 17~47% 변동 | **실행일마다 순위가 달라짐** | 중간 | **3** |
| 1 | 밴드 max 과소 | 매수 신호 과다 | 중간 | **4** |
| 2 | ffill · rolling 결측 | 밴드 13종목 결측 | 중간 | **5** |
| 5 | `0.0` = 결측 | 순위 전면 변동 | 높음 (하류 영향) | **6** |

3·6번을 먼저 하면 나머지 문제의 실제 규모가 로그에 드러납니다.
5번은 반드시 마지막에, 순위 전후 비교와 함께 하십시오.

**가장 시급한 것은 4번입니다.** 다른 문제들은 값이 일관되게 틀리지만,
4번은 **같은 코드가 같은 종목에 대해 날마다 다른 결과**를 냅니다.
매일 도는 Actions가 그날 운에 따라 다른 순위를 내보내고 있고, 그 사실이 드러나지 않습니다.

---

## 확인하지 못한 것

작성자가 스크래핑 파이프라인을 실행할 수 없어 **미확인으로 남은 항목**입니다.
아래는 문제로 단정하지 않았으며, 점검 대상으로만 제시합니다.

- `collect_stockanalysis_data()`의 Selenium 스크래핑 정확도 — 원본 수치의 신뢰도 자체를 확인 못 함
- `Div. Gr. Years` · `Div. Growth 5Y` 등 **스크래핑으로 받는 컬럼**의 정합성
  (외부 검증에서 `Div. Gr. Years`는 yfinance로 재현이 불가능했습니다.
  yfinance 배당 시계열로 연속 증가 연수를 세면 PH 70→9년, KO 64→23년으로 크게 과소 집계됩니다.
  **스크래핑 값을 쓰는 현재 방식이 타당하다는 뜻이며, yfinance로 대체하려 하지 마십시오.**)
- `apply_dividend_criteria_filters` · `apply_initial_filters`의 임계값 타당성
- `add_missing_premium_stocks`가 프리미엄 종목을 되살릴 때 yfinance 보강이 함께 붙는지
- `validate_scraped_data`의 검증 항목이 충분한지
