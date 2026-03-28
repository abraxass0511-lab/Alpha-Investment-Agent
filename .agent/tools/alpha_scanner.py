"""
Alpha Scanner V5 — Finnhub Only Engine (FMP 완전 제거)

파이프라인:
  Wikipedia → S&P 500 목록
  [1+2단계] Finnhub /metric     → 시총 $10B+ & ROE 15%+  (1콜로 동시 처리)
  [3+6단계] Finnhub /candle     → 50MA 필터 + 12-1 모멘텀 사전 계산 (1콜로 동시 처리)
  [4단계]   Finnhub /earnings   → Surprise ≥10% OR EPS Growth ≥20%
  [5단계]   별도 alpha_sentiment.py (Finnhub News + VADER + Gemini)
  [6단계]   3단계에서 이미 계산한 12-1 모멘텀으로 Top 5 소팅 (추가 콜 0)

Finnhub: 분당 60콜, 일일 제한 없음 — 쿼터 걱정 완전 제거!
"""

import os
import sys
import json
import time
import requests
import pandas as pd
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# ============================================================
# Config
# ============================================================
SCAN_TIMEOUT = 35 * 60  # 35분
SCAN_START = time.time()

load_dotenv()
FINNHUB_KEY = os.getenv("FINNHUB_API_KEY")

# 콜 추적
finnhub_call_count = 0


def check_timeout():
    elapsed = time.time() - SCAN_START
    if elapsed > SCAN_TIMEOUT:
        print(f"\n🚨 스캔 타임아웃! ({int(elapsed//60)}분 경과)")
        return True
    return False


# ============================================================
# Finnhub API 호출 (분당 60콜 준수: 1.1초 간격)
# ============================================================
def finnhub_request(endpoint, params=None, timeout=10):
    """Finnhub API 호출 — 5회 재시도 + 점진적 대기로 데이터 100% 수집 목표"""
    global finnhub_call_count

    if check_timeout():
        return None
    if not FINNHUB_KEY:
        print("    ❌ FINNHUB_API_KEY 미설정")
        return None

    url = f"https://finnhub.io/api/v1{endpoint}"
    if params is None:
        params = {}
    params["token"] = FINNHUB_KEY

    for attempt in range(5):  # 5회 재시도
        try:
            finnhub_call_count += 1
            r = requests.get(url, params=params, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                wait = 10 * (attempt + 1)  # 10, 20, 30, 40, 50초
                print(f"    ⏳ Finnhub 429 (시도 {attempt+1}/5) → {wait}초 대기...")
                time.sleep(wait)
                continue
            print(f"    ⚠️ Finnhub HTTP {r.status_code} (시도 {attempt+1}/5)")
            time.sleep(5)
        except Exception as e:
            print(f"    ⚠️ Finnhub 에러: {e} (시도 {attempt+1}/5)")
            time.sleep(5)
    return None


# ============================================================
# S&P 500 목록 — Wikipedia (무료, API 콜 0)
# ============================================================
def get_sp500_tickers():
    url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
    try:
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30)
        soup = BeautifulSoup(r.text, 'html.parser')
        table = soup.find('table', {'id': 'constituents'})
        result = []
        if table:
            for row in table.find_all('tr')[1:]:
                cols = row.find_all('td')
                if len(cols) >= 2:
                    ticker = cols[0].text.strip().replace('.', '-')
                    name = cols[1].text.strip()
                    result.append({"symbol": ticker, "name": name})
        return result
    except Exception as e:
        print(f"❌ S&P 500 목록 수집 실패: {e}")
        return []


# ============================================================
# Yahoo Finance 최후 백업 (Finnhub 10회 시도 후에도 실패한 경우만 사용)
# ============================================================
def yahoo_backup_metric(symbol):
    """Yahoo Finance에서 시총+ROE 백업 — 최후 수단"""
    try:
        import yfinance as yf
        t = yf.Ticker(symbol)
        info = t.info
        mcap = info.get("marketCap", 0)  # Yahoo는 달러 단위
        roe = info.get("returnOnEquity", 0)  # Yahoo는 소수점 (0.25 = 25%)
        if mcap and roe is not None:
            return {
                "mcap_m": mcap / 1_000_000,  # 백만 달러로 변환
                "roe": roe * 100 if roe < 1 else roe,  # % 변환
            }
    except Exception as e:
        print(f"    ⚠️ Yahoo 백업 실패({symbol}): {e}")
    return None


def yahoo_backup_candle(symbol):
    """Yahoo Finance에서 1년 종가 백업 — 최후 수단"""
    try:
        import yfinance as yf
        t = yf.Ticker(symbol)
        hist = t.history(period="1y")
        if len(hist) >= 50:
            closes = hist["Close"].tolist()
            return closes
    except Exception as e:
        print(f"    ⚠️ Yahoo 백업 실패({symbol}): {e}")
    return None


def yahoo_backup_earnings(symbol):
    """Yahoo Finance에서 어닝 데이터 백업 — 최후 수단"""
    try:
        import yfinance as yf
        t = yf.Ticker(symbol)
        earnings = t.earnings_history
        if earnings is not None and len(earnings) > 0:
            latest = earnings.iloc[0]
            surprise_pct = latest.get("surprisePercent", 0) or 0
            return {"surprisePercent": surprise_pct * 100 if abs(surprise_pct) < 1 else surprise_pct}
    except Exception as e:
        print(f"    ⚠️ Yahoo 백업 실패({symbol}): {e}")
    return None


# ============================================================
# [1+2단계] Finnhub /metric → 시총 + ROE 동시 필터
# ============================================================
def stage12_finnhub_metric(tickers, name_map):
    """
    Finnhub /stock/metric 으로 시총 & ROE 동시 검사
    503종목 × 1.1초 = ~9.2분
    Finnhub 무응답 시 재시도 → 데이터 100% 수집 목표
    """
    passed = []
    null_count = 0
    yahoo_backup_count = 0

    for i, sym in enumerate(tickers):
        if check_timeout():
            break

        data = finnhub_request("/stock/metric", {"symbol": sym, "metric": "all"})

        # 첫 시도 실패 시 3초 후 재시도
        if data is None:
            time.sleep(3)
            data = finnhub_request("/stock/metric", {"symbol": sym, "metric": "all"})

        mcap = None
        roe = None

        if data:
            metric = data.get("metric", {})
            mcap = metric.get("marketCapitalization")
            roe = metric.get("roeTTM")

        # Finnhub 데이터 없으면 → Yahoo 최후 백업
        if mcap is None or roe is None:
            ydata = yahoo_backup_metric(sym)
            if ydata:
                mcap = mcap or ydata["mcap_m"]
                roe = roe or ydata["roe"]
                yahoo_backup_count += 1
                print(f"    🔄 {sym} Yahoo 백업 사용 (mcap={round(mcap)}, roe={round(roe,1)})")

        # 그래도 없으면 탈락
        if mcap is None or roe is None:
            null_count += 1
            continue

        if mcap < 10000:
            continue

        if roe < 15:
            continue

        passed.append({
            "Symbol": sym,
            "Name": name_map.get(sym, sym),
            "MarketCap_M": round(mcap),
            "ROE(%)": round(roe, 2),
        })

        if (i + 1) % 50 == 0 or i == len(tickers) - 1:
            elapsed = round((time.time() - SCAN_START) / 60, 1)
            print(f"   📡 {i+1}/{len(tickers)} 처리 | 통과: {len(passed)} | ⏱️ {elapsed}분")

        time.sleep(1.1)

    if null_count > 0:
        print(f"   ⚠️ 최종 데이터 없음: {null_count}종목 (Finnhub+Yahoo 모두 실패)")
    if yahoo_backup_count > 0:
        print(f"   🔄 Yahoo 백업 사용: {yahoo_backup_count}종목")

    return passed


# ============================================================
# [3+6단계] Finnhub /candle → 50MA 필터 + 12-1 모멘텀 사전 계산
# ============================================================
def stage3_finnhub_candle(candidates):
    """
    Finnhub /stock/candle 로 252일(1년) 캔들 데이터 수집
    → 50MA 필터 (3단계) + 12-1 모멘텀 사전 계산 (6단계용)
    Finnhub 실패 시 Yahoo 백업으로 100% 데이터 보장
    """
    now = int(time.time())
    one_year_ago = now - (365 * 24 * 60 * 60)

    passed = []
    yahoo_count = 0

    for i, item in enumerate(candidates):
        if check_timeout():
            break

        sym = item["Symbol"]
        closes = None

        # 1차: Finnhub
        data = finnhub_request("/stock/candle", {
            "symbol": sym,
            "resolution": "D",
            "from": one_year_ago,
            "to": now,
        })

        if data and data.get("s") == "ok":
            closes = data.get("c", [])

        # 2차: Yahoo 백업
        if closes is None or len(closes) < 50:
            yc = yahoo_backup_candle(sym)
            if yc and len(yc) >= 50:
                closes = yc
                yahoo_count += 1
                print(f"    🔄 {sym} Yahoo 캔들 백업 사용")

        if closes and len(closes) >= 50:
            current_price = closes[-1]
            ma50 = sum(closes[-50:]) / 50

            if current_price > ma50:
                ma_momentum = round(((current_price - ma50) / ma50) * 100, 2)
                item["Price"] = round(current_price, 2)
                item["MA50"] = round(ma50, 2)
                item["MA_Momentum(%)"] = ma_momentum

                if len(closes) > 21:
                    price_t1 = closes[-22]
                    price_t12 = closes[0]
                    if price_t12 > 0:
                        mom_12_1 = round((price_t1 / price_t12) - 1, 4)
                    else:
                        mom_12_1 = 0
                else:
                    mom_12_1 = 0

                item["Momentum_12_1"] = mom_12_1
                passed.append(item)

        if (i + 1) % 30 == 0 or i == len(candidates) - 1:
            print(f"   📡 {i+1}/{len(candidates)} 처리 | 통과: {len(passed)}")

        time.sleep(1.1)

    if yahoo_count > 0:
        print(f"   🔄 Yahoo 캔들 백업: {yahoo_count}종목")

    return passed


# ============================================================
# [4단계] Finnhub /earnings → 어닝 서프라이즈 + EPS Growth
# ============================================================
def stage4_finnhub_earnings(candidates):
    """
    Finnhub /stock/earnings 로 어닝 서프라이즈 + YoY EPS 성장률 검증
    Finnhub 실패 시 Yahoo 백업으로 100% 데이터 보장
    """
    passed = []
    yahoo_count = 0

    for i, item in enumerate(candidates):
        if check_timeout():
            break

        sym = item["Symbol"]
        surprise_pct = None
        eps_growth = 0

        # 1차: Finnhub
        data = finnhub_request("/stock/earnings", {"symbol": sym, "limit": 8})

        if data and isinstance(data, list) and len(data) > 0:
            surprise_pct = data[0].get("surprisePercent", 0) or 0

            if len(data) >= 5:
                current_actual = data[0].get("actual", 0) or 0
                yoy_actual = data[4].get("actual", 0) or 0
                if yoy_actual != 0 and current_actual != 0:
                    eps_growth = round((current_actual - yoy_actual) / abs(yoy_actual), 4)

        # 2차: Yahoo 백업 (Finnhub 데이터 없을 때)
        if surprise_pct is None:
            ydata = yahoo_backup_earnings(sym)
            if ydata:
                surprise_pct = ydata.get("surprisePercent", 0)
                yahoo_count += 1
                print(f"    🔄 {sym} Yahoo 어닝 백업 사용")
            else:
                surprise_pct = 0
                print(f"    ⚠️ {sym} → 어닝 데이터 없음 (Finnhub+Yahoo)")

        # 통과 기준: Surprise ≥ 10% OR EPS Growth ≥ 20%
        if surprise_pct >= 10 or eps_growth >= 0.20:
            reason = f"Surprise: {round(surprise_pct, 1)}%, Growth: {round(eps_growth * 100, 1)}%"
            item["GrowthReason"] = reason
            item["Surprise(%)"] = round(surprise_pct, 1)
            item["EPS_Growth(%)"] = round(eps_growth * 100, 1)
            passed.append(item)
            print(f"    ✅ {sym} → {reason}")
        else:
            print(f"    ❌ {sym} → Surprise: {round(surprise_pct, 1)}%, Growth: {round(eps_growth * 100, 1)}%")

        if (i + 1) % 20 == 0 or i == len(candidates) - 1:
            elapsed = round((time.time() - SCAN_START) / 60, 1)
            print(f"   📡 {i+1}/{len(candidates)} | 통과: {len(passed)} | ⏱️ {elapsed}분")

        time.sleep(1.1)

    if yahoo_count > 0:
        print(f"   🔄 Yahoo 어닝 백업: {yahoo_count}종목")

    return passed


# ============================================================
# 메인 파이프라인
# ============================================================
def run_scan():
    global finnhub_call_count
    finnhub_call_count = 0

    # S&P 500 목록
    sp500 = get_sp500_tickers()
    if not sp500:
        print("❌ S&P 500 목록 수집 실패")
        return

    total = len(sp500)
    name_map = {item["symbol"]: item["name"] for item in sp500}
    tickers = [item["symbol"] for item in sp500]

    print(f"🚀 [Alpha Scanner V5] Finnhub Only Engine 가동")
    print(f"   대상: {total}종목 | 쿼터: 무제한")

    # ========================================
    # [1+2단계] 체급 + 내실 — Finnhub /metric
    # ========================================
    print(f"\n{'='*55}")
    print(f"📊 [1+2단계] 체급($10B+) + 내실(ROE 15%+) — Finnhub /metric")
    print(f"{'='*55}")

    stage12 = stage12_finnhub_metric(tickers, name_map)
    c12 = len(stage12)
    print(f"\n✅ [1+2단계] {c12}건 통과 | Finnhub {finnhub_call_count}콜")

    # ========================================
    # [3+6단계] 에너지 + 모멘텀 사전계산 — Finnhub /candle
    # ========================================
    print(f"\n{'='*55}")
    print(f"📊 [3+6단계] 에너지(50MA) + 12-1 모멘텀 사전계산 — Finnhub /candle")
    print(f"{'='*55}")

    stage3 = stage3_finnhub_candle(stage12)
    c3 = len(stage3)
    print(f"\n✅ [3단계] {c3}건 통과 | Finnhub 총 {finnhub_call_count}콜")

    # ========================================
    # [4단계] 성장 — Finnhub /earnings
    # ========================================
    print(f"\n{'='*55}")
    print(f"📊 [4단계] 성장(Surprise/EPS Growth) — Finnhub /earnings")
    print(f"{'='*55}")

    stage4 = stage4_finnhub_earnings(stage3)
    c4 = len(stage4)
    print(f"\n✅ [4단계] {c4}건 통과 | Finnhub 총 {finnhub_call_count}콜")

    # ========================================
    # 결과 저장
    # ========================================
    if not os.path.exists('output_reports'):
        os.makedirs('output_reports')

    pd.DataFrame(stage4).to_csv("output_reports/daily_scan_latest.csv", index=False)

    elapsed_min = round((time.time() - SCAN_START) / 60, 1)

    with open("output_reports/metadata.json", "w") as f:
        json.dump({
            "total": total,
            "success_all": True,
            "step12": c12, "step3": c3, "step4": c4,
            "timestamp": datetime.now().isoformat(),
            "finnhub_calls": finnhub_call_count,
            "elapsed_min": elapsed_min,
            "engine": "Finnhub Only V5",
        }, f)

    print(f"\n{'='*55}")
    print(f"✅ [Alpha Scanner V5] 최종 결과")
    print(f"   Total: {total}종목")
    print(f"   1+2단계(체급+내실): {c12} → 3단계(에너지): {c3} → 4단계(성장): {c4}")
    print(f"   📡 Finnhub 총 {finnhub_call_count}콜 (쿼터: 무제한)")
    print(f"   ⏱️ 소요시간: {elapsed_min}분")
    print(f"{'='*55}")


# ============================================================
# 장 상태 판단 & 데이터 재사용 로직
# ============================================================
def is_us_market_open():
    """미국 장 개장 여부 (UTC 기준 13:30~21:00, 월~금)"""
    from datetime import timezone
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5:
        return False
    hour_min = now.hour * 60 + now.minute
    return 810 <= hour_min <= 1260  # 13:30~21:00 UTC

def get_last_trading_date():
    """마지막 거래일 (UTC 기준) — 주말 + 미국 공휴일 모두 인식"""
    from datetime import timezone
    try:
        from us_market_calendar import is_trading_day
    except ImportError:
        is_trading_day = None

    now = datetime.now(timezone.utc)
    market_close_today = now.replace(hour=21, minute=0, second=0, microsecond=0)

    if now >= market_close_today:
        target = now.date()
    else:
        target = (now - timedelta(days=1)).date()

    # 주말 + 공휴일을 건너뛰어 마지막 실제 거래일을 찾음
    for _ in range(10):  # 최대 10일 거슬러감 (연휴 대비)
        if target.weekday() >= 5:  # 토/일
            target -= timedelta(days=1)
            continue
        if is_trading_day and not is_trading_day(target):  # 공휴일
            target -= timedelta(days=1)
            continue
        break  # 거래일 발견!

    return target.strftime("%Y-%m-%d")


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(__file__))

    last_trading = get_last_trading_date()
    market_open = is_us_market_open()
    metadata_path = "output_reports/metadata.json"

    print(f"📊 마지막 거래일: {last_trading} | 장 상태: {'개장 중' if market_open else '마감'}")

    # 장이 열려있으면 → 항상 새 스캔
    if market_open:
        print("🔴 미국 장 개장 중 → 실시간 스캔 실행")
        run_scan()
        if os.path.exists(metadata_path):
            meta = json.load(open(metadata_path))
            meta["trading_date"] = last_trading
            meta["market_status"] = "live"
            json.dump(meta, open(metadata_path, "w"))
        sys.exit(0)

    # 장이 닫혀있으면 → 기존 데이터 확인
    if os.path.exists(metadata_path):
        try:
            meta = json.load(open(metadata_path))
            if meta.get("success_all") and meta.get("trading_date") == last_trading:
                print(f"✅ {last_trading} 데이터 이미 존재. 재스캔 불필요.")
                print(f"   기존 결과를 그대로 사용합니다.")
                sys.exit(0)
        except Exception:
            pass

    # 기존 데이터 없으면 새 스캔
    print(f"📡 {last_trading} 데이터 없음 → 새 스캔 실행")
    run_scan()

    if os.path.exists(metadata_path):
        meta = json.load(open(metadata_path))
        meta["trading_date"] = last_trading
        meta["market_status"] = "closed"
        json.dump(meta, open(metadata_path, "w"))
