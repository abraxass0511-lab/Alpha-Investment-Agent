"""
★ Alpha Momentum Selector V4 — 12-1 모멘텀 기반 Elite 선별 ★

파이프라인:
  1+2단계 (체급+내실) → 3단계 (에너지/50MA) → 4단계 (성장/Surprise)
  → ★ 5단계 (12-1 모멘텀 Top5) ★

설계 원칙:
  - 4단계 통과 종목 전체에 대해 12-1 Month Momentum 계산
  - 양수 모멘텀만 통과, 상위 5개 선정 (음수 = 하락 추세 → 제외)
  - 빈 슬롯 = 현금 보유 (무리한 매수 방지)
  
데이터 무결성:
  - Symbol, Price, ROE 등 모든 숫자는 CSV 원본(row)에서만 추출
  - Finnhub/Yahoo는 모멘텀 계산용 가격 데이터만 제공
"""
import os
import json
import pandas as pd
import requests
from datetime import datetime
from dotenv import load_dotenv
import time

load_dotenv()
FINNHUB_KEY = os.getenv("FINNHUB_API_KEY")


# ═══════════════════════════════════════════════════════
# 5단계: 12-1 Month Momentum 계산
# ═══════════════════════════════════════════════════════
def calculate_12_1_momentum(symbol):
    """
    Step 5: 12-1 Month Momentum (Finnhub Primary → Yahoo Fallback)
    
    12개월 전 대비 1개월 전 가격 변동률.
    최근 1개월을 제외하여 단기 노이즈를 배제.
    
    ★ 각 소스별 최대 3회 재시도 + 지수 백오프
    Returns: float (성공 시) 또는 None (API 실패 시)
    """
    MAX_RETRIES = 3
    
    # ═══ 1차: Finnhub Candle API (Primary) ═══
    FKEY = os.getenv("FINNHUB_API_KEY")
    if FKEY:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                now = int(time.time())
                one_year_ago = now - (365 * 24 * 60 * 60)
                url = f"https://finnhub.io/api/v1/stock/candle?symbol={symbol}&resolution=D&from={one_year_ago}&to={now}&token={FKEY}"
                r = requests.get(url, timeout=15)
                
                if r.status_code == 429:
                    # Rate limit — 백오프 후 재시도
                    wait = 2 ** attempt
                    print(f"    ⏳ Finnhub {symbol} rate limit (시도 {attempt}/{MAX_RETRIES}) → {wait}초 대기")
                    time.sleep(wait)
                    continue
                
                if r.status_code != 200:
                    print(f"    ⚠️ Finnhub {symbol} HTTP {r.status_code} (시도 {attempt}/{MAX_RETRIES})")
                    time.sleep(1)
                    continue
                    
                data = r.json()
                if data.get("s") == "ok":
                    closes = data.get("c", [])
                    if len(closes) > 21:
                        price_t1 = closes[-22]
                        price_t12 = closes[0]
                        if price_t12 > 0:
                            return round((price_t1 / price_t12) - 1, 4)
                    else:
                        print(f"    ⚠️ Finnhub {symbol} 데이터 부족 ({len(closes)}일치, 22일 필요)")
                        break  # 데이터 자체가 부족하면 재시도 의미 없음 → Yahoo로
                else:
                    status = data.get("s", "unknown")
                    print(f"    ⚠️ Finnhub {symbol} 상태: {status} (시도 {attempt}/{MAX_RETRIES})")
                    if status == "no_data":
                        break  # 데이터 없으면 재시도 의미 없음 → Yahoo로
                    time.sleep(1)
                    continue
                    
            except requests.exceptions.Timeout:
                wait = 2 ** attempt
                print(f"    ⏳ Finnhub {symbol} 타임아웃 (시도 {attempt}/{MAX_RETRIES}) → {wait}초 대기")
                time.sleep(wait)
            except Exception as e:
                print(f"    ⚠️ Finnhub {symbol} 에러: {e} (시도 {attempt}/{MAX_RETRIES})")
                time.sleep(1)

    # ═══ 2차: Yahoo Finance (Fallback) — 3회 재시도 ═══
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            import yfinance as yf
            t = yf.Ticker(symbol)
            hist = t.history(period="1y")
            if len(hist) > 21:
                closes = hist["Close"].tolist()
                price_t1 = closes[-22]
                price_t12 = closes[0]
                if price_t12 > 0:
                    return round((price_t1 / price_t12) - 1, 4)
            else:
                print(f"    ⚠️ Yahoo {symbol} 데이터 부족 ({len(hist)}일)")
                break  # 데이터 부족은 재시도 의미 없음
        except Exception as e:
            wait = 2 ** attempt
            print(f"    ⚠️ Yahoo {symbol} 에러: {e} (시도 {attempt}/{MAX_RETRIES}) → {wait}초 대기")
            time.sleep(wait)

    # ★ Finnhub + Yahoo 둘 다 실패 → None 반환 (API 장애와 모멘텀 0 구분)
    print(f"    🚨 {symbol} 12-1 모멘텀 데이터 수집 실패 (Finnhub {MAX_RETRIES}회 + Yahoo {MAX_RETRIES}회 시도 후 포기)")
    return None


# ═══════════════════════════════════════════════════════
# 메인 실행
# ═══════════════════════════════════════════════════════
def run_momentum_selector():
    """★ 5단계: 4단계 통과 종목 → 12-1 모멘텀 Top5 선별 ★"""
    scan_file = "output_reports/daily_scan_latest.csv"
    if not os.path.exists(scan_file):
        print("❌ daily_scan_latest.csv 없음 — 스캐너가 실행되지 않았습니다.")
        return

    df = pd.read_csv(scan_file)

    # metadata 로드
    try:
        with open("output_reports/metadata.json", "r") as f:
            meta = json.load(f)
    except:
        meta = {"total": 503, "step12": 0, "step3": 0, "step4": 0}

    if df.empty:
        print("⚠️ 4단계 통과 종목 0건 — 빈 결과 처리")
        meta["step5"] = 0
        meta["step5_api_fail"] = 0
        with open("output_reports/metadata.json", "w") as f:
            json.dump(meta, f)
        pd.DataFrame().to_csv("output_reports/final_picks_latest.csv", index=False)
        return

    print(f"🚀 [Alpha Momentum Selector V4] 12-1 모멘텀 선별 가동...")
    print(f"   📋 대상: {len(df)}종목 (4단계 통과)")
    print(f"   🎯 양수 모멘텀 상위 5개 선정")

    # ── 전체 종목에 대해 12-1 모멘텀 계산 ──
    step5_api_fail = 0
    results = []

    for idx, row in df.iterrows():
        symbol = row.get("Symbol", "?")
        name = row.get("Name", symbol)
        
        mom = calculate_12_1_momentum(symbol)
        
        if mom is None:
            step5_api_fail += 1
            mom = 0.0
            reason = f"⚠️ 12-1 모멘텀: API 실패"
            print(f"    ⚠️ {symbol} 모멘텀 API 실패 → 0 처리")
        else:
            mom_pct = round(mom * 100, 2)
            reason = f"12-1 모멘텀: {mom_pct}%"
            if mom > 0:
                print(f"    ✅ {symbol} 모멘텀 {mom_pct}% (양수)")
            else:
                print(f"    ❌ {symbol} 모멘텀 {mom_pct}% (음수/제로 → 탈락)")

        results.append({
            "Symbol": symbol,
            "Name": name,
            "Price": row.get("Price", 0),
            "Momentum(%)": row.get("MA_Momentum(%)", 0),
            "ROE(%)": row.get("ROE(%)", 0),
            "MarketCap_M": row.get("MarketCap_M", 0),
            "MA50": row.get("MA50", 0),
            "Surprise(%)": row.get("Surprise(%)", 0),
            "EPS_Growth(%)": row.get("EPS_Growth(%)", 0),
            "Momentum_12_1": mom,
            "Status": "PASS" if mom > 0 else "FAIL",
            "Reason": reason,
        })

        # Finnhub Rate Limit 방지: 종목간 0.3초 대기
        time.sleep(0.3)

    # ── 양수 모멘텀만 필터 → 상위 5개 ──
    positive = [r for r in results if r["Momentum_12_1"] > 0]
    negative = [r for r in results if r["Momentum_12_1"] <= 0]

    final_picks = sorted(positive, key=lambda x: x["Momentum_12_1"], reverse=True)[:5]

    # Status 업데이트: 최종 선정된 종목만 BUY
    selected_symbols = {p["Symbol"] for p in final_picks}
    for r in results:
        if r["Symbol"] in selected_symbols:
            r["Status"] = "BUY (매수 승인 대기)"
            r["Reason"] += f" | Top {len(final_picks)} 선정"

    # ── 전체 결과 저장 (리밸런서용) ──
    all_df = pd.DataFrame(results)
    all_df.to_csv("output_reports/sentiment_all_latest.csv", index=False)
    print(f"   💾 전체 모멘텀 결과 저장: {len(results)}종목")

    # ── metadata 업데이트 ──
    meta["step5"] = len(final_picks)
    meta["step5_api_fail"] = step5_api_fail

    with open("output_reports/metadata.json", "w") as f:
        json.dump(meta, f)

    # ── 최종 결과 저장 ──
    if final_picks:
        final_df = pd.DataFrame(final_picks)
        final_df.to_csv("output_reports/final_picks_latest.csv", index=False)
        print(f"✅ 모멘텀 선별 완료! (양수 {len(positive)}개 중 Top {len(final_picks)} 선정)")
        if len(final_picks) < 5:
            print(f"    ℹ️ 빈 슬롯 {5 - len(final_picks)}개 = 현금 보유")
    else:
        pd.DataFrame().to_csv("output_reports/final_picks_latest.csv", index=False)
        print(f"❌ 양수 모멘텀 종목 없음 → 전액 현금 보유 모드")
        if negative:
            print(f"    ℹ️ 음수/제로 모멘텀: {len(negative)}종목 (전부 제외)")

    print(f"\n📊 결과 요약:")
    print(f"   4단계 통과: {len(df)}종목")
    print(f"   양수 모멘텀: {len(positive)}종목")
    print(f"   음수/제로: {len(negative)}종목")
    print(f"   API 실패: {step5_api_fail}종목")
    print(f"   ★ 최종 선정: {len(final_picks)}종목")


if __name__ == "__main__":
    run_momentum_selector()
