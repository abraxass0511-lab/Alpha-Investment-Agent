"""
alpha_rebalancer.py — 에이전트 알파의 리밸런서

매일 아침 스캔 후 실행하여 보유 종목의 적격 여부를 재검증합니다.
1~6단계 중 하나라도 부합하지 않는 종목 → 매도 추천 (승인 대기)
신규 매수 추천 종목 → 매수 추천 (승인 대기)

매도 기준:
  ② 1~6단계 중 하나라도 탈락 → 다음날 리포트에서 승인 요청
  (①번 트레일링 스탑은 alpha_guardian.py에서 장중 자동 처리)

출력: output_reports/rebalance_recommendations.json
"""

import os
import sys
import json
import csv
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

FINNHUB_KEY = os.getenv("FINNHUB_API_KEY")


def diagnose_scan_failure(symbol):
    """
    보유 종목이 스캔에서 빠진 원인을 단계별로 진단합니다.
    Yahoo Finance + Finnhub를 직접 조회하여 정확한 탈락 사유를 파악합니다.
    """
    reasons = []
    diag = {}  # 진단 데이터 저장

    # === 1+2단계: 시총 & ROE ===
    try:
        import yfinance as yf
        tk = yf.Ticker(symbol)
        info = tk.info

        mcap = info.get("marketCap", 0) or 0
        mcap_b = mcap / 1e9
        diag["mcap_b"] = round(mcap_b, 1)

        roe_raw = info.get("returnOnEquity", 0)
        roe_pct = (roe_raw * 100) if roe_raw and abs(roe_raw) < 5 else (roe_raw or 0)
        diag["roe"] = round(roe_pct, 1)

        if mcap_b < 10:
            reasons.append(f"1단계(체급) 탈락: 시총 ${mcap_b:.1f}B < $10B")
        if roe_pct < 15:
            reasons.append(f"2단계(내실) 탈락: ROE {roe_pct:.1f}% < 15%")

        # === 3단계: Price > 50MA ===
        hist = tk.history(period="3mo")
        if len(hist) >= 50:
            current_price = float(hist["Close"].iloc[-1])
            ma50 = float(hist["Close"].tail(50).mean())
            diag["price"] = round(current_price, 2)
            diag["ma50"] = round(ma50, 2)

            if current_price <= ma50:
                reasons.append(
                    f"3단계(에너지) 탈락: 종가 ${current_price:.2f} < 50MA ${ma50:.2f}"
                )
        else:
            reasons.append("3단계 진단 불가: 캔들 데이터 부족")

    except Exception as e:
        reasons.append(f"Yahoo 진단 실패: {e}")

    # === 4단계: Surprise / Growth (Finnhub) ===
    if not reasons:  # 1~3단계 통과했는데 빠졌으면 4단계 체크
        try:
            if FINNHUB_KEY:
                url = f"https://finnhub.io/api/v1/stock/earnings"
                r = requests.get(url, params={"symbol": symbol, "limit": 8, "token": FINNHUB_KEY}, timeout=10)
                if r.status_code == 200:
                    data = r.json()
                    if data and isinstance(data, list) and len(data) > 0:
                        surprise = data[0].get("surprisePercent", 0) or 0
                        diag["surprise"] = round(surprise, 1)

                        eps_growth = 0
                        if len(data) >= 5:
                            cur = data[0].get("actual")
                            yoy = data[4].get("actual")
                            if cur is not None and yoy is not None and yoy != 0:
                                eps_growth = round(((cur - yoy) / abs(yoy)) * 100, 1)
                        diag["growth"] = eps_growth

                        if surprise < 10 and eps_growth < 20:
                            reasons.append(
                                f"4단계(성장) 탈락: Surprise {surprise:.1f}% < 10% & Growth {eps_growth:.1f}% < 20%"
                            )
                    else:
                        reasons.append("4단계(성장) 탈락: 어닝 데이터 조회 불가")
            else:
                reasons.append("4단계 진단 불가: FINNHUB_API_KEY 미설정")
        except Exception as e:
            reasons.append(f"4단계 Finnhub 진단 실패: {e}")

    if not reasons:
        reasons.append("탈락 원인 특정 불가 — API 데이터와 스캔 결과 불일치")

    return reasons, diag


def load_csv(filepath):
    """CSV 파일을 읽어 심볼 딕셔너리로 반환합니다."""
    data = {}
    if not os.path.exists(filepath):
        return data
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                sym = row.get("Symbol", "").strip()
                if sym:
                    data[sym] = row
    except:
        pass
    return data


def get_held_stocks():
    """KIS API로 현재 보유 종목을 조회합니다."""
    try:
        sys.path.insert(0, os.path.dirname(__file__))
        from alpha_trader import AlphaTrader

        trader = AlphaTrader()
        result = trader.get_balance()
        if not result:
            return []

        holdings, _ = result
        held = []
        for h in holdings:
            sym = h.get('ovrs_pdno', '').strip()
            qty = int(float(h.get('ovrs_cblc_qty', '0')))
            if sym and qty > 0:
                held.append({
                    "symbol": sym,
                    "qty": qty,
                    "buy_avg": float(h.get('pchs_avg_pric', '0')),
                    "current": float(h.get('now_pric2', '0')),
                    "pnl_rate": float(h.get('evlu_pfls_rt', '0')),
                    "pnl_amt": float(h.get('frcr_evlu_pfls_amt', '0')),
                })
        return held
    except Exception as e:
        print(f"🚨 보유 종목 조회 에러: {e}")
        return []


def check_held_against_scan(held_stocks, scan_data, picks_data):
    """
    보유 종목을 1~6단계 기준으로 재검증합니다.
    
    ★ 5단계(심리) 비대칭 임계값:
      - 신규 매수: Sentiment ≥ 0.7 (입구는 좁게)
      - 기존 보유: Sentiment ≥ 0.5 유지 (출구는 넓게)
      - 위기 감지: Sentiment < 0.5 → 매도 추천
    
    ★ No News Rule:
      - 보유 종목 뉴스 없음 → "무소식이 희소식" → 유지(Hold)
    
    - daily_scan_latest.csv에 있음 = 1~4단계 통과
    - sentiment_all_latest.csv에서 보유종목 센티먼트 확인 (≥ 0.5)
    """
    sell_recommendations = []

    # 센티먼트 전체 결과 로드 (보유종목 기준 0.5로 체크)
    sentiment_data = load_csv("output_reports/sentiment_all_latest.csv")

    for stock in held_stocks:
        sym = stock["symbol"]
        reasons = []

        if sym in scan_data:
            row = scan_data[sym]
            # 스캔에 있으면 1~4단계 통과, 세부 기준 재확인
            # V3: MarketCap_M (백만달러 단위)
            market_cap_m = 0
            try:
                market_cap_m = float(row.get("MarketCap_M", "0"))
            except (ValueError, TypeError):
                pass

            price = 0
            try:
                price = float(row.get("Price", "0"))
            except (ValueError, TypeError):
                pass

            ma50 = 0
            try:
                ma50 = float(row.get("MA50", "0"))
            except (ValueError, TypeError):
                pass

            # ROE는 "Screener ✅" 문자열일 수 있음
            roe = 0
            try:
                roe_val = row.get("ROE(%)", "0")
                if isinstance(roe_val, str) and "Screener" in roe_val:
                    roe = 99  # Screener 통과 = ROE 15%+ 확정
                else:
                    roe = float(roe_val)
            except (ValueError, TypeError):
                pass

            # Surprise / Growth 수치 추출
            surprise = 0
            try:
                surprise = float(row.get("Surprise(%)", "0") or "0")
            except (ValueError, TypeError):
                pass
            eps_growth = 0
            try:
                eps_growth = float(row.get("EPS_Growth(%)", "0") or "0")
            except (ValueError, TypeError):
                pass

            if market_cap_m < 10_000:  # $10B = 10,000M
                reasons.append("1단계(체급) 탈락: 시총 $10B 미만")
            if price < ma50 and ma50 > 0:
                reasons.append(f"2단계(에너지) 탈락: 종가 ${price:.2f} < 50MA ${ma50:.2f}")
            if roe < 15:
                reasons.append(f"3단계(내실) 탈락: ROE {roe:.1f}% < 15%")

            # ★ 1~4단계 통과 수치 요약 (5~6단계 탈락 시 맥락 제공용)
            stage14_summary = (
                f"[1~4단계 통과] 시총 ${market_cap_m/1000:.1f}B, "
                f"ROE {roe:.1f}%, "
                f"종가 ${price:.2f} > 50MA ${ma50:.2f}, "
                f"Surprise {surprise:.1f}% / Growth {eps_growth:.1f}%"
            )

            # ★ 5단계(심리) 보유종목 기준: ≥ 0.5 유지 (비대칭 임계값)
            if sym in sentiment_data:
                sent_row = sentiment_data[sym]
                sent_score = float(sent_row.get("Sentiment", "0"))
                sma5_raw = sent_row.get("SMA5", "")
                sma5_str = sma5_raw if sma5_raw else "축적 중"
                if sent_score < 0.5:
                    reasons.append(
                        f"5단계(심리) 탈락: 센티먼트 {sent_score:.3f} < 0.5 "
                        f"(SMA₅: {sma5_str}) — {stage14_summary}"
                    )
            else:
                # ★ No News Rule: 보유 종목 뉴스 없음 → "무소식이 희소식" → 유지(Hold)
                pass

        else:
            # 스캔에 없음 → 어느 단계에서 탈락했는지 진단
            print(f"   🔍 {sym} 스캔 미포함 → 탈락 원인 진단 중...")
            diag_reasons, diag_data = diagnose_scan_failure(sym)
            for dr in diag_reasons:
                reasons.append(dr)
            if diag_data:
                diag_summary = ", ".join(f"{k}={v}" for k, v in diag_data.items())
                print(f"   📊 {sym} 진단 데이터: {diag_summary}")

        if reasons:
            sell_recommendations.append({
                "symbol": sym,
                "qty": stock["qty"],
                "buy_avg": stock["buy_avg"],
                "current": stock["current"],
                "pnl_rate": stock["pnl_rate"],
                "pnl_amt": stock["pnl_amt"],
                "reasons": reasons,
                "action": "SELL",
            })

    return sell_recommendations


def get_buy_recommendations(held_symbols, picks_data):
    """
    보유하지 않은 신규 매수 추천 종목을 가져옵니다.
    final_picks에 있지만 아직 보유하지 않은 종목 → 매수 추천
    """
    buy_recommendations = []

    for sym, row in picks_data.items():
        if sym not in held_symbols:
            buy_recommendations.append({
                "symbol": sym,
                "name": row.get("Name", sym),
                "price": row.get("Price", "0"),
                "reason": row.get("Reason", row.get("GrowthReason", "기준 통과")),
                "action": "BUY",
            })

    return buy_recommendations


def run_rebalancer():
    """리밸런싱 분석을 실행합니다."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    print("=" * 55)
    print(f"⚖️ 알파 리밸런서 — 포트폴리오 적격 심사 ({now})")
    print("=" * 55)

    # 1. 보유 종목 조회
    print("\n📊 [1] 보유 종목 조회...")
    held_stocks = get_held_stocks()

    if not held_stocks:
        print("📭 보유 종목 없음 — 매도 검증 생략.")
    else:
        print(f"📋 보유 종목: {len(held_stocks)}개 — {', '.join(s['symbol'] for s in held_stocks)}")

    # 2. 오늘 스캔 결과 로드
    print("\n📋 [2] 스캔 결과 로드...")
    scan_data = load_csv("output_reports/daily_scan_latest.csv")
    picks_data = load_csv("output_reports/final_picks_latest.csv")
    print(f"   1~4단계 통과: {len(scan_data)}종목")
    print(f"   5~6단계 통과: {len(picks_data)}종목")

    # 3. 매도 추천 (보유 종목 중 탈락한 것)
    print("\n🔍 [3] 보유 종목 재검증...")
    sell_recs = []
    if held_stocks:
        sell_recs = check_held_against_scan(held_stocks, scan_data, picks_data)
        if sell_recs:
            print(f"🚨 매도 추천: {len(sell_recs)}종목")
            for s in sell_recs:
                print(f"   🔻 {s['symbol']}: {', '.join(s['reasons'])}")
        else:
            print("✅ 모든 보유 종목 적격 — 매도 추천 없음.")

    # 4. 매수 추천 (보유하지 않은 신규 선정 종목)
    print("\n🔍 [4] 신규 매수 종목 확인...")
    held_symbols = [s["symbol"] for s in held_stocks]
    buy_recs = get_buy_recommendations(held_symbols, picks_data)
    if buy_recs:
        print(f"📈 매수 추천: {len(buy_recs)}종목")
        for b in buy_recs:
            print(f"   🟢 {b['symbol']} ({b['name']}): {b['reason']}")
    else:
        print("📭 신규 매수 추천 없음.")

    # 5. 결과 저장
    recommendations = {
        "timestamp": now,
        "sell": sell_recs,
        "buy": buy_recs,
        "held_count": len(held_stocks),
        "scan_passed": len(scan_data),
        "picks_passed": len(picks_data),
    }

    output_path = "output_reports/rebalance_recommendations.json"
    os.makedirs("output_reports", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(recommendations, f, indent=2, ensure_ascii=False)

    print(f"\n💾 리밸런싱 분석 저장: {output_path}")
    print(f"   매도 추천: {len(sell_recs)}건 / 매수 추천: {len(buy_recs)}건")

    return recommendations


if __name__ == "__main__":
    run_rebalancer()
