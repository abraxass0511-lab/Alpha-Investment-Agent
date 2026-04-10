"""
Alpha Strategy Backtest
=======================
알파 퀀트 전략의 과거 5년 성과를 시뮬레이션합니다.

전략 핵심:
- S&P500 대형주 (시총 $10B+)
- Price > 50MA (에너지 필터)
- 12-1 모멘텀 Top 5 선택
- 매월 리밸런싱, 동일 비중 (각 20%)
- 벤치마크: SPY (S&P500 ETF)

※ ROE/Surprise는 과거 시점별 재현이 어려워 핵심 팩터(모멘텀+MA)로 테스트
※ 생존 편향: 현재 S&P500 구성종목 사용 (과거 퇴출 종목 미포함)
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings
import os
warnings.filterwarnings('ignore')

# ── 설정 ──
START_DATE = "2021-04-01"
END_DATE = "2026-04-01"  
TOP_N = 5                # Top 5 모멘텀
MIN_MCAP_B = 10          # 시총 $10B+
REBAL_FREQ = "MS"        # 월초 리밸런싱
INITIAL_CAPITAL = 100000  # $100,000

print("=" * 60)
print("🔬 알파 전략 백테스트 시작")
print(f"   기간: {START_DATE} ~ {END_DATE} (5년)")
print(f"   전략: 시총${MIN_MCAP_B}B+ & Price>50MA & 12-1모멘텀 Top{TOP_N}")
print(f"   리밸런싱: 매월 초 / 동일비중 {100//TOP_N}%씩")
print(f"   초기자본: ${INITIAL_CAPITAL:,}")
print("=" * 60)

# ── S&P500 종목 가져오기 ──
print("\n📥 [1/4] S&P500 종목 리스트 다운로드...")
try:
    sp500_table = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")[0]
    tickers = sp500_table['Symbol'].str.replace('.', '-', regex=False).tolist()
    print(f"   ✅ {len(tickers)}개 종목 확인")
except Exception as e:
    print(f"   ⚠️ Wikipedia 실패, 기본 리스트 사용: {e}")
    # 대형주 위주 기본 리스트
    tickers = ['AAPL','MSFT','GOOGL','AMZN','NVDA','META','TSLA','BRK-B','JPM','V',
               'JNJ','WMT','PG','MA','UNH','HD','DIS','BAC','ADBE','CRM',
               'NFLX','CSCO','PFE','TMO','COST','ABT','AVGO','ACN','MRK','NKE',
               'LLY','ORCL','AMD','QCOM','TXN','INTC','AMAT','MU','LRCX','ADI',
               'NOW','ISRG','REGN','GILD','AMGN','MDLZ','SYK','ZTS','BDX','CI',
               'MMC','CME','ICE','AON','SHW','ECL','SNPS','CDNS','KLAC','MCHP',
               'ON','SWKS','MPWR','TER','FTNT','PANW','CRWD','ZS','DDOG','NET',
               'WDC','STX','LITE','KEYS','ANSS','CAT','DE','GE','HON','RTX',
               'LMT','NOC','GD','BA','MMM','EMR','ETN','ITW','PH','ROK',
               'XOM','CVX','COP','SLB','EOG','MPC','VLO','PSX','OXY','HAL']

# ── 가격 데이터 다운로드 ──
print(f"\n📥 [2/4] 가격 데이터 다운로드 ({len(tickers)}종목, ~5분 소요)...")
# 배치로 다운로드 (속도 최적화)
all_data = {}
batch_size = 50
failed = []

for i in range(0, len(tickers), batch_size):
    batch = tickers[i:i+batch_size]
    batch_str = " ".join(batch)
    try:
        data = yf.download(batch_str, start=START_DATE, end=END_DATE, 
                          auto_adjust=True, progress=False, threads=True)
        if 'Close' in data.columns.get_level_values(0) if isinstance(data.columns, pd.MultiIndex) else True:
            for sym in batch:
                try:
                    if isinstance(data.columns, pd.MultiIndex):
                        close = data['Close'][sym].dropna()
                    else:
                        close = data['Close'].dropna()
                    if len(close) > 252:  # 최소 1년 데이터
                        all_data[sym] = close
                except:
                    failed.append(sym)
    except Exception as e:
        failed.extend(batch)
    
    pct = min(100, (i + batch_size) / len(tickers) * 100)
    print(f"   진행: {pct:.0f}% ({len(all_data)}종목 성공)")

print(f"   ✅ {len(all_data)}종목 데이터 확보 (실패: {len(failed)})")

# SPY 벤치마크
print("\n📥 SPY (벤치마크) 다운로드...")
spy_data = yf.download("SPY", start=START_DATE, end=END_DATE, auto_adjust=True, progress=False)
spy_close = spy_data['Close'].squeeze()
print(f"   ✅ SPY {len(spy_close)} 거래일")

# ── 시가총액 필터용 현재 데이터 (근사치) ──
print("\n📥 [3/4] 시가총액 데이터 수집...")
mcap_data = {}
mcap_batch = list(all_data.keys())
for i in range(0, len(mcap_batch), 50):
    batch = mcap_batch[i:i+50]
    for sym in batch:
        try:
            tk = yf.Ticker(sym)
            info = tk.fast_info
            mcap = getattr(info, 'market_cap', 0) or 0
            if mcap > 0:
                mcap_data[sym] = mcap / 1e9  # in billions
        except:
            pass
    pct = min(100, (i + 50) / len(mcap_batch) * 100)
    print(f"   진행: {pct:.0f}% ({len(mcap_data)}종목)")

# 시총 $10B+ 필터
large_caps = [s for s, m in mcap_data.items() if m >= MIN_MCAP_B]
print(f"   ✅ 시총 ${MIN_MCAP_B}B+ 필터: {len(large_caps)}종목")

# ── 백테스트 실행 ──
print(f"\n🔬 [4/4] 백테스트 실행 중...")

# 월별 리밸런싱 날짜 생성
close_df = pd.DataFrame(all_data)
close_df = close_df.dropna(how='all')

# 월초 거래일
monthly_dates = close_df.resample(REBAL_FREQ).first().index
# 실제 거래일로 매핑
rebal_dates = []
for d in monthly_dates:
    valid = close_df.index[close_df.index >= d]
    if len(valid) > 0:
        rebal_dates.append(valid[0])
rebal_dates = sorted(set(rebal_dates))

# 최소 252 거래일(12개월) 이후부터 시작 (모멘텀 계산용)
start_idx = 0
for i, d in enumerate(rebal_dates):
    trading_days_before = len(close_df.index[close_df.index < d])
    if trading_days_before >= 252:
        start_idx = i
        break

rebal_dates = rebal_dates[start_idx:]
print(f"   리밸런싱 {len(rebal_dates)}회 (첫 리밸런싱: {rebal_dates[0].strftime('%Y-%m-%d')})")

# 포트폴리오 시뮬레이션
portfolio_value = [INITIAL_CAPITAL]
portfolio_dates = [rebal_dates[0]]
holdings_history = []
monthly_returns_alpha = []
monthly_returns_spy = []

current_holdings = {}  # {symbol: {'shares': n, 'price': p}}
cash = INITIAL_CAPITAL

for ri in range(len(rebal_dates) - 1):
    rebal_date = rebal_dates[ri]
    next_rebal = rebal_dates[ri + 1]
    
    # ── 종목 선택 (알파 전략) ──
    candidates = []
    
    for sym in large_caps:
        if sym not in all_data:
            continue
        
        series = close_df[sym]
        
        # 리밸런싱 날짜 기준 데이터
        hist = series[series.index <= rebal_date].dropna()
        if len(hist) < 252:
            continue
        
        current_price = hist.iloc[-1]
        
        # 3단계: Price > 50MA
        ma50 = hist.iloc[-50:].mean()
        if current_price <= ma50:
            continue
        
        # 5단계: 12-1 모멘텀 (12개월 전 대비, 최근 1개월 제외)
        price_12m_ago = hist.iloc[-252]   # 약 12개월 전
        price_1m_ago = hist.iloc[-21]     # 약 1개월 전
        
        if price_12m_ago <= 0:
            continue
        
        momentum_12_1 = (price_1m_ago / price_12m_ago) - 1
        
        candidates.append({
            'symbol': sym,
            'momentum': momentum_12_1,
            'price': current_price,
        })
    
    # 모멘텀 상위 TOP_N 선택
    candidates.sort(key=lambda x: x['momentum'], reverse=True)
    selected = candidates[:TOP_N]
    
    if not selected:
        continue
    
    # ── 포트폴리오 가치 계산 (이전 기간) ──
    if current_holdings:
        # 현재 보유 종목의 현재 가치
        total_val = cash
        for sym, info in current_holdings.items():
            if sym in close_df.columns:
                price_now = close_df[sym].loc[:rebal_date].dropna()
                if len(price_now) > 0:
                    total_val += info['shares'] * price_now.iloc[-1]
        cash = total_val
    
    # ── 리밸런싱 ──
    per_stock = cash / len(selected)
    current_holdings = {}
    
    selected_syms = []
    for s in selected:
        shares = per_stock / s['price']
        current_holdings[s['symbol']] = {
            'shares': shares,
            'price': s['price']
        }
        selected_syms.append(f"{s['symbol']}({s['momentum']*100:.0f}%)")
    
    cash = 0  # 전액 투자
    
    # ── 다음 리밸런싱까지의 수익 추적 ──
    # 일별 포트폴리오 가치
    period_dates = close_df.index[(close_df.index >= rebal_date) & (close_df.index < next_rebal)]
    
    for d in period_dates:
        day_val = 0
        for sym, info in current_holdings.items():
            if sym in close_df.columns:
                p = close_df[sym].loc[:d].dropna()
                if len(p) > 0:
                    day_val += info['shares'] * p.iloc[-1]
        if day_val > 0:
            portfolio_value.append(day_val)
            portfolio_dates.append(d)
    
    # 월간 수익률
    if len(portfolio_value) >= 2:
        month_ret = (portfolio_value[-1] / portfolio_value[-len(period_dates)-1]) - 1 if len(period_dates) > 0 else 0
        monthly_returns_alpha.append(month_ret)
        
        # SPY 월간 수익률
        spy_start = spy_close.loc[:rebal_date].dropna()
        spy_end = spy_close.loc[:next_rebal].dropna()
        if len(spy_start) > 0 and len(spy_end) > 0:
            spy_ret = (spy_end.iloc[-1] / spy_start.iloc[-1]) - 1
            monthly_returns_spy.append(spy_ret)
    
    if ri % 6 == 0:
        val = portfolio_value[-1] if portfolio_value else INITIAL_CAPITAL
        print(f"   {rebal_date.strftime('%Y-%m')} | 포트폴리오: ${val:,.0f} | 종목: {', '.join(selected_syms[:3])}...")

    holdings_history.append({
        'date': rebal_date,
        'symbols': [s['symbol'] for s in selected],
        'momentums': [s['momentum'] for s in selected],
    })

# 마지막 기간 가치 계산
if current_holdings:
    final_val = 0
    last_date = close_df.index[-1]
    for sym, info in current_holdings.items():
        if sym in close_df.columns:
            p = close_df[sym].dropna()
            if len(p) > 0:
                final_val += info['shares'] * p.iloc[-1]
    if final_val > 0:
        portfolio_value.append(final_val)
        portfolio_dates.append(last_date)

# ── 결과 분석 ──
print("\n" + "=" * 60)
print("📊 백테스트 결과")
print("=" * 60)

# 알파 전략 성과
total_return_alpha = (portfolio_value[-1] / INITIAL_CAPITAL - 1) * 100
years = (portfolio_dates[-1] - portfolio_dates[0]).days / 365.25
cagr_alpha = ((portfolio_value[-1] / INITIAL_CAPITAL) ** (1/years) - 1) * 100 if years > 0 else 0

# SPY 성과
spy_start_price = spy_close.loc[spy_close.index >= portfolio_dates[0]].iloc[0]
spy_end_price = spy_close.loc[spy_close.index <= portfolio_dates[-1]].iloc[-1]
total_return_spy = (spy_end_price / spy_start_price - 1) * 100
cagr_spy = ((spy_end_price / spy_start_price) ** (1/years) - 1) * 100 if years > 0 else 0

# 변동성 & 샤프
pv_series = pd.Series(portfolio_value, index=portfolio_dates[:len(portfolio_value)])
daily_returns = pv_series.pct_change().dropna()
volatility = daily_returns.std() * np.sqrt(252) * 100
sharpe = (cagr_alpha - 4.5) / (volatility) if volatility > 0 else 0  # RF=4.5%

# SPY 변동성
spy_aligned = spy_close.loc[(spy_close.index >= portfolio_dates[0]) & (spy_close.index <= portfolio_dates[-1])]
spy_daily_ret = spy_aligned.pct_change().dropna()
spy_vol = spy_daily_ret.std() * np.sqrt(252) * 100
spy_sharpe = (cagr_spy - 4.5) / spy_vol if spy_vol > 0 else 0

# 최대 낙폭 (MDD)
peak = pv_series.expanding().max()
drawdown = (pv_series - peak) / peak
mdd_alpha = drawdown.min() * 100

spy_peak = spy_aligned.expanding().max()
spy_dd = (spy_aligned - spy_peak) / spy_peak
mdd_spy = spy_dd.min() * 100

# 월간 승률
if monthly_returns_alpha:
    win_rate = sum(1 for r in monthly_returns_alpha if r > 0) / len(monthly_returns_alpha) * 100
else:
    win_rate = 0

print(f"\n{'지표':<20} {'알파 전략':>15} {'SPY (벤치마크)':>15}")
print("-" * 52)
print(f"{'총 수익률':<20} {total_return_alpha:>14.1f}% {total_return_spy:>14.1f}%")
print(f"{'연평균 수익률(CAGR)':<20} {cagr_alpha:>14.1f}% {cagr_spy:>14.1f}%")
print(f"{'연간 변동성':<20} {volatility:>14.1f}% {spy_vol:>14.1f}%")
print(f"{'샤프 비율':<20} {sharpe:>14.2f} {spy_sharpe:>14.2f}")
print(f"{'최대 낙폭(MDD)':<20} {mdd_alpha:>14.1f}% {mdd_spy:>14.1f}%")
print(f"{'월간 승률':<20} {win_rate:>14.1f}%")
print(f"{'최종 자산':<20} ${portfolio_value[-1]:>13,.0f} ${INITIAL_CAPITAL*(1+total_return_spy/100):>13,.0f}")

# 연도별 수익률
print(f"\n📅 연도별 수익률")
print("-" * 52)

pv_df = pd.DataFrame({'value': portfolio_value}, index=portfolio_dates[:len(portfolio_value)])
yearly = pv_df.resample('YE').last()
yearly_start = pv_df.resample('YE').first()

for i in range(len(yearly)):
    year = yearly.index[i].year
    yr_ret = (yearly.iloc[i]['value'] / yearly_start.iloc[i]['value'] - 1) * 100
    
    # SPY 연도별
    spy_yr = spy_close[spy_close.index.year == year]
    if len(spy_yr) > 1:
        spy_yr_ret = (spy_yr.iloc[-1] / spy_yr.iloc[0] - 1) * 100
    else:
        spy_yr_ret = 0
    
    alpha = yr_ret - spy_yr_ret
    emoji = "🟢" if alpha > 0 else "🔴"
    print(f"  {year}  |  알파: {yr_ret:>7.1f}%  |  SPY: {spy_yr_ret:>7.1f}%  |  {emoji} 초과: {alpha:>+7.1f}%")

# 최다 선정 종목
print(f"\n🏆 최다 선정 종목 (Top 10)")
print("-" * 40)
from collections import Counter
all_picks = []
for h in holdings_history:
    all_picks.extend(h['symbols'])
top_picks = Counter(all_picks).most_common(10)
for sym, count in top_picks:
    print(f"  {sym:<8} | {count}회 선정 ({count/len(holdings_history)*100:.0f}%)")

# 결과 저장
print(f"\n💾 결과 저장 중...")
result_path = "output_reports/backtest_result.csv"
os.makedirs("output_reports", exist_ok=True)
result_df = pd.DataFrame({
    'date': portfolio_dates[:len(portfolio_value)],
    'portfolio_value': portfolio_value
})
result_df.to_csv(result_path, index=False)

# 최종 판정
print("\n" + "=" * 60)
print("🧠 전략 판정")
print("=" * 60)

if cagr_alpha > cagr_spy and mdd_alpha > mdd_spy * 1.5:
    print("⚠️ 수익률은 높지만 변동성/MDD가 과도합니다.")
    print("   → 리스크 대비 수익이 SPY와 비슷하거나 낮을 수 있습니다.")
elif cagr_alpha > cagr_spy and sharpe > spy_sharpe:
    print("✅ 전략이 SPY를 초과 수익 + 리스크 조정 기준으로 아웃퍼폼합니다.")
    print("   → 단, 5종목 집중 리스크와 섹터 쏠림에 유의하세요.")
elif cagr_alpha < cagr_spy:
    print("🔴 전략이 SPY를 언더퍼폼합니다.")
    print("   → SPY ETF를 사는 것이 더 나을 수 있습니다.")
else:
    print("🟡 SPY와 비슷한 성과입니다. 추가 리스크 대비 초과수익이 부족합니다.")

print(f"\n⚠️ 주의사항:")
print(f"   - 생존 편향: 현재 S&P500 종목만 사용 (과거 퇴출 종목 미포함)")
print(f"   - ROE/Surprise 필터 미적용 (가격 기반 팩터만 테스트)")
print(f"   - 거래비용/세금 미반영")
print(f"   - 과거 성과는 미래를 보장하지 않음")
