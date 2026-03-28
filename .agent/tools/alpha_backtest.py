"""
Alpha Backtest — 7년 Quality Momentum 전략 검증

전략:
  1+2) 시총 $10B+ & ROE 15%+
  3)   주가 > 50MA
  6)   12-1 모멘텀 Top 5 매수
  매도: 트레일링 스탑 -10% OR 50MA 이탈

기간: 2019.01 ~ 2026.03 (7년, 코로나+금리폭락 포함)
매도: 매일 체크 (가디언 동일)
매수: 월 1회 스캔일 (빈 슬롯 = 현금 보유)
벤치마크: S&P 500 (SPY)
"""

import os
import json
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

# ============================================================
# Config
# ============================================================
BACKTEST_START = "2019-01-01"
BACKTEST_END = "2026-03-28"
TOP_N = 5  # 매월 Top N 종목 매수
TRAILING_STOP = -0.10  # -10%
INITIAL_CAPITAL = 100_000  # $100K


# ============================================================
# S&P 500 목록
# ============================================================
def get_sp500_tickers():
    url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
    try:
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30)
        soup = BeautifulSoup(r.text, 'html.parser')
        table = soup.find('table', {'id': 'constituents'})
        tickers = []
        if table:
            for row in table.find_all('tr')[1:]:
                cols = row.find_all('td')
                if len(cols) >= 2:
                    ticker = cols[0].text.strip().replace('.', '-')
                    tickers.append(ticker)
        return tickers
    except Exception as e:
        print(f"S&P 500 목록 실패: {e}")
        return []


# ============================================================
# 데이터 다운로드 (Yahoo Finance 일괄)
# ============================================================
def download_price_data(tickers):
    """503종목 7년치 일봉 일괄 다운로드"""
    import yfinance as yf

    print(f"📥 {len(tickers)}종목 일괄 다운로드 시작...")
    print(f"   기간: {BACKTEST_START} ~ {BACKTEST_END}")

    data = yf.download(
        tickers,
        start=BACKTEST_START,
        end=BACKTEST_END,
        auto_adjust=True,
        threads=True,
    )

    if data.empty:
        print("❌ 데이터 다운로드 실패")
        return None

    if isinstance(data.columns, pd.MultiIndex):
        close_df = data["Close"]
    else:
        close_df = data[["Close"]]
        close_df.columns = tickers[:1]

    print(f"✅ 다운로드 완료: {close_df.shape[0]}일 x {close_df.shape[1]}종목")
    return close_df


# ============================================================
# 펀더멘털 필터 (현재 기준 — 생존자 편향 인정)
# ============================================================
def get_fundamentals(tickers):
    """현재 시총+ROE로 필터 (과거 데이터 제한으로 현재 기준 사용)"""
    import yfinance as yf

    print(f"📊 펀더멘털 수집 중 ({len(tickers)}종목)...")
    fundamentals = {}
    batch_size = 50

    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i+batch_size]
        for sym in batch:
            try:
                t = yf.Ticker(sym)
                info = t.info
                mcap = info.get("marketCap", 0)
                roe = info.get("returnOnEquity", 0)

                if mcap and roe:
                    mcap_m = mcap / 1_000_000
                    roe_pct = roe * 100 if roe < 1 else roe
                    if mcap_m >= 10000 and roe_pct >= 15:
                        fundamentals[sym] = {
                            "mcap_m": mcap_m,
                            "roe": roe_pct,
                        }
            except:
                pass

        pct = min((i + batch_size) / len(tickers) * 100, 100)
        print(f"   📡 {int(pct)}% 완료 | 통과: {len(fundamentals)}")
        time.sleep(0.5)

    print(f"✅ 펀더멘털 필터 통과: {len(fundamentals)}종목")
    return fundamentals


# ============================================================
# 백테스트 엔진 — 실제 운영과 동일한 로직
# ============================================================
def run_backtest(close_df, fundamentals):
    """
    ★ 실제 운영과 동일한 백테스트 ★
    
    매도 (매일 = 가디언):
      - 트레일링 스탑 -10% → 즉시 매도
      - 50MA 이탈 → 즉시 매도

    매수 (매일 1회 = 아침 스캔):
      - 6단계 기준 통과 종목만 매수
      - 스캔 통과 0건이면 빈 슬롯 = 현금 보유 (강제 채움 X)
      - 당일 매도 종목은 당일 재매수 금지
    """

    valid_symbols = [s for s in fundamentals.keys() if s in close_df.columns]
    close_filtered = close_df[valid_symbols].dropna(axis=1, how='all')

    print(f"\n🚀 백테스트 시작 (실제 운영 동일 로직)")
    print(f"   대상: {len(valid_symbols)}종목 | 기간: {BACKTEST_START}~{BACKTEST_END}")
    print(f"   전략: Top {TOP_N} Quality Momentum")
    print(f"   매도: 매일 트레일링 {int(TRAILING_STOP*100)}% + 50MA 이탈")
    print(f"   매수: 매일 1회 아침 스캔 (빈 슬롯 = 현금 보유)")

    import yfinance as yf
    spy_raw = yf.download("SPY", start=BACKTEST_START, end=BACKTEST_END, auto_adjust=True)
    if isinstance(spy_raw.columns, pd.MultiIndex):
        spy = spy_raw["Close"]["SPY"]
    else:
        spy = spy_raw["Close"]

    # 매일 스캔 (당일 매도 종목 재매수 금지용 세트)
    sold_today = set()

    capital = INITIAL_CAPITAL
    portfolio = {}
    history = []
    trade_log = []
    all_dates = close_filtered.index

    for day_idx, today in enumerate(all_dates):
        prices = close_filtered.loc[today].dropna()

        # ════════════════════════════════════════
        # 1) 매일: 트레일링 스탑 + 50MA (가디언)
        # ════════════════════════════════════════
        sell_list = []
        for sym, pos in list(portfolio.items()):
            if sym not in prices:
                continue
            current = float(prices[sym])

            # 고점 갱신
            if current > pos["peak_price"]:
                pos["peak_price"] = current

            # 트레일링 스탑 -10%
            drop = (current - pos["peak_price"]) / pos["peak_price"]
            if drop <= TRAILING_STOP:
                sell_list.append((sym, "trailing_stop", current))
                continue

            # 50MA 이탈
            hist = close_filtered.loc[:today, sym].dropna()
            if len(hist) >= 50:
                ma50 = float(hist.iloc[-50:].mean())
                if current < ma50:
                    sell_list.append((sym, "below_50ma", current))

        # 매도 실행
        for sym, reason, price in sell_list:
            pos = portfolio.pop(sym, None)
            if pos:
                pnl = (price - pos["buy_price"]) * pos["qty"]
                capital += price * pos["qty"]
                sold_today.add(sym)
                trade_log.append({
                    "date": today.strftime("%Y-%m-%d"),
                    "action": "SELL", "symbol": sym,
                    "price": round(price, 2), "reason": reason,
                    "pnl": round(pnl, 2),
                })

        # ════════════════════════════════════════
        # 2) 매일 아침 스캔: 매수 (빈 슬롯 강제 채움 X)
        #    당일 매도 종목은 재매수 금지
        # ════════════════════════════════════════
        open_slots = TOP_N - len(portfolio)

        if open_slots > 0:
            candidates = []
            for sym in prices.index:
                if sym not in valid_symbols or sym in portfolio or sym in sold_today:
                    continue
                hist = close_filtered.loc[:today, sym].dropna()
                if len(hist) < 252:
                    continue

                current = float(prices[sym])
                ma50 = float(hist.iloc[-50:].mean())

                # 50MA 위?
                if current <= ma50:
                    continue

                # 12-1 모멘텀 (최근 1개월 제외한 11개월 수익률)
                price_12m = float(hist.iloc[-252])
                price_1m = float(hist.iloc[-21])
                momentum = (price_1m / price_12m) - 1 if price_12m > 0 else 0

                # 양의 모멘텀만
                if momentum <= 0:
                    continue

                candidates.append({"symbol": sym, "price": current, "momentum": momentum})

            candidates.sort(key=lambda x: x["momentum"], reverse=True)
            buy_count = min(len(candidates), open_slots)

            for pick in candidates[:buy_count]:
                sym = pick["symbol"]
                price = pick["price"]
                alloc = capital / max(buy_count, 1) * 0.95
                qty = int(alloc / price) if price > 0 else 0
                if qty > 0:
                    capital -= qty * price
                    portfolio[sym] = {"qty": qty, "buy_price": price, "peak_price": price}
                    trade_log.append({
                        "date": today.strftime("%Y-%m-%d"),
                        "action": "BUY", "symbol": sym,
                        "price": round(price, 2),
                        "reason": f"momentum={round(pick['momentum']*100,1)}%",
                        "pnl": 0,
                    })

        # ════════════════════════════════════════
        # 3) 주간 기록 (매주 금요일)
        # ════════════════════════════════════════
        if today.weekday() == 4 or day_idx == len(all_dates) - 1:
            total_value = capital
            for sym, pos in portfolio.items():
                if sym in prices:
                    total_value += float(prices[sym]) * pos["qty"]
            spy_val = float(spy.loc[today]) if today in spy.index else 0.0
            history.append({
                "date": today.strftime("%Y-%m-%d"),
                "portfolio_value": round(total_value, 2),
                "capital_cash": round(capital, 2),
                "holdings": len(portfolio),
                "spy_price": round(spy_val, 2),
            })

        # 분기별 진행률
        if day_idx > 0 and day_idx % 63 == 0:
            total_value = capital
            for sym, pos in portfolio.items():
                if sym in prices:
                    total_value += float(prices[sym]) * pos["qty"]
            ret = (total_value / INITIAL_CAPITAL - 1) * 100
            print(f"   📊 {today.strftime('%Y-%m')} | ${total_value:,.0f} | {ret:+.1f}% | 보유: {len(portfolio)}")

        # 당일 매도 목록 초기화 (다음 날엔 재매수 가능)
        sold_today.clear()

    return history, trade_log


# ============================================================
# 성과 분석
# ============================================================
def analyze_results(history):
    """CAGR, MDD, Sharpe 계산"""
    df = pd.DataFrame(history)
    df["date"] = pd.to_datetime(df["date"])

    start_val = df["portfolio_value"].iloc[0]
    end_val = df["portfolio_value"].iloc[-1]
    years = (df["date"].iloc[-1] - df["date"].iloc[0]).days / 365.25

    total_return = (end_val / start_val - 1) * 100
    cagr = ((end_val / start_val) ** (1 / years) - 1) * 100 if years > 0 else 0

    # MDD
    peak = df["portfolio_value"].expanding().max()
    drawdown = (df["portfolio_value"] - peak) / peak
    mdd = drawdown.min() * 100

    # Sharpe (weekly returns)
    df["weekly_ret"] = df["portfolio_value"].pct_change()
    sharpe = (df["weekly_ret"].mean() / df["weekly_ret"].std()) * np.sqrt(52) if df["weekly_ret"].std() > 0 else 0

    # SPY 벤치마크
    spy_start = df["spy_price"].iloc[0]
    spy_end = df["spy_price"].iloc[-1]
    spy_return = (spy_end / spy_start - 1) * 100 if spy_start > 0 else 0
    spy_cagr = ((spy_end / spy_start) ** (1 / years) - 1) * 100 if years > 0 and spy_start > 0 else 0

    results = {
        "period": f"{df['date'].iloc[0].strftime('%Y.%m')} ~ {df['date'].iloc[-1].strftime('%Y.%m')}",
        "years": round(years, 1),
        "initial_capital": INITIAL_CAPITAL,
        "final_value": round(end_val, 2),
        "total_return_pct": round(total_return, 2),
        "cagr_pct": round(cagr, 2),
        "mdd_pct": round(mdd, 2),
        "sharpe_ratio": round(sharpe, 2),
        "spy_return_pct": round(spy_return, 2),
        "spy_cagr_pct": round(spy_cagr, 2),
        "alpha_vs_spy": round(cagr - spy_cagr, 2),
    }

    return results


# ============================================================
# 텔레그램 알림
# ============================================================
def send_backtest_result(results, trade_count):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return

    msg = (
        "📊 *알파 백테스트 결과*\n\n"
        f"📅 기간: {results['period']} ({results['years']}년)\n"
        f"💰 초기자본: ${results['initial_capital']:,}\n"
        f"💎 최종자산: ${results['final_value']:,.0f}\n\n"
        f"*수익률:*\n"
        f"  총 수익: {results['total_return_pct']:+.1f}%\n"
        f"  CAGR: {results['cagr_pct']:+.1f}%\n"
        f"  MDD: {results['mdd_pct']:.1f}%\n"
        f"  Sharpe: {results['sharpe_ratio']:.2f}\n\n"
        f"*벤치마크 (SPY):*\n"
        f"  SPY 수익: {results['spy_return_pct']:+.1f}%\n"
        f"  SPY CAGR: {results['spy_cagr_pct']:+.1f}%\n\n"
        f"*🏆 알파: {results['alpha_vs_spy']:+.1f}% (vs SPY)*\n\n"
        f"📈 총 거래: {trade_count}건\n"
        f"🔧 전략: Quality Momentum Top {TOP_N}\n"
        f"🛡️ 스탑: 트레일링 {int(TRAILING_STOP*100)}% + 50MA 이탈"
    )

    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"},
            timeout=30,
        )
        print("📱 백테스트 결과 텔레그램 전송 완료")
    except Exception as e:
        print(f"⚠️ 텔레그램 에러: {e}")


# ============================================================
# 메인
# ============================================================
def main():
    start_time = time.time()

    print(f"{'='*55}")
    print(f"🔬 Alpha Backtest — 7년 Quality Momentum 검증")
    print(f"{'='*55}")

    # 1. S&P 500 목록
    tickers = get_sp500_tickers()
    if not tickers:
        print("❌ S&P 500 목록 실패")
        return
    print(f"✅ S&P 500: {len(tickers)}종목")

    # 2. 가격 데이터 다운로드
    close_df = download_price_data(tickers)
    if close_df is None:
        return

    # 3. 펀더멘털 필터
    fundamentals = get_fundamentals(tickers)

    # 4. 백테스트 실행
    history, trade_log = run_backtest(close_df, fundamentals)

    # 5. 성과 분석
    results = analyze_results(history)

    elapsed = round((time.time() - start_time) / 60, 1)

    # 결과 출력
    print(f"\n{'='*55}")
    print(f"📊 백테스트 결과")
    print(f"{'='*55}")
    print(f"   기간: {results['period']} ({results['years']}년)")
    print(f"   초기자본: ${results['initial_capital']:,}")
    print(f"   최종자산: ${results['final_value']:,.0f}")
    print(f"   총 수익률: {results['total_return_pct']:+.1f}%")
    print(f"   CAGR: {results['cagr_pct']:+.1f}%")
    print(f"   MDD: {results['mdd_pct']:.1f}%")
    print(f"   Sharpe: {results['sharpe_ratio']:.2f}")
    print(f"   SPY CAGR: {results['spy_cagr_pct']:+.1f}%")
    print(f"   🏆 Alpha: {results['alpha_vs_spy']:+.1f}% (vs SPY)")
    print(f"   거래: {len(trade_log)}건")
    print(f"   ⏱️ 소요: {elapsed}분")
    print(f"{'='*55}")

    # 저장
    os.makedirs("output_reports", exist_ok=True)
    pd.DataFrame(history).to_csv("output_reports/backtest_history.csv", index=False)
    pd.DataFrame(trade_log).to_csv("output_reports/backtest_trades.csv", index=False)
    with open("output_reports/backtest_results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n💾 결과 저장 완료:")
    print(f"   - output_reports/backtest_history.csv")
    print(f"   - output_reports/backtest_trades.csv")
    print(f"   - output_reports/backtest_results.json")

    # 텔레그램 발송
    send_backtest_result(results, len(trade_log))


if __name__ == "__main__":
    main()
