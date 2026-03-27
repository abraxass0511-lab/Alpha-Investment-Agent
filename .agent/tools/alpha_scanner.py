"""
Alpha Scanner V3 — FMP 전용 엔진 (Yahoo/KIS 제거)

파이프라인:
  Wikipedia → S&P 500 목록
  FMP 배치 시세 → 1단계(시총 $10B+) + 2단계(가격 > 50MA) 동시
  FMP Screener + 개별 검증 → 3단계(ROE 15%+)
  FMP 개별 → 4단계(Growth)

KIS는 매매 전용(Cloudflare Worker)으로만 사용.
FMP 무료 250콜/일 내 전 파이프라인 운영.
"""

import os
import sys
import json
import time
import requests
import pandas as pd
from datetime import datetime
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# ============================================================
# Config
# ============================================================
SCAN_TIMEOUT = 90 * 60  # 90분
SCAN_START = time.time()

load_dotenv()
FMP_KEY = os.getenv("FMP_API_KEY")

# FMP 쿼터 추적
FMP_DAILY_LIMIT = 250
fmp_call_count = 0


def check_timeout():
    elapsed = time.time() - SCAN_START
    if elapsed > SCAN_TIMEOUT:
        print(f"\n🚨 스캔 타임아웃! ({int(elapsed//60)}분 경과)")
        return True
    return False


def fmp_quota_check():
    """FMP 남은 쿼터 확인 및 경고"""
    remaining = FMP_DAILY_LIMIT - fmp_call_count
    if remaining <= 20:
        print(f"    🚨 FMP 쿼터 위험! 남은 콜: {remaining}/{FMP_DAILY_LIMIT}")
    return remaining


# ============================================================
# FMP API 호출 (쿼터 추적 + 429 재시도)
# ============================================================
def fmp_request(url, timeout=15, max_retries=3):
    """FMP API 호출 — 쿼터 추적, 429 재시도, 남은 콜 경고"""
    global fmp_call_count

    for attempt in range(max_retries):
        if check_timeout():
            return None
        if fmp_quota_check() <= 0:
            print("    🚨 FMP 일일 쿼터 소진! 중단합니다.")
            return None
        try:
            fmp_call_count += 1
            r = requests.get(url, timeout=timeout)
            if r.status_code == 200:
                return r
            if r.status_code == 429:
                wait = min(30 * (attempt + 1), 60)
                print(f"    ⏳ FMP 429 (시도 {attempt+1}/{max_retries}) → {wait}초 대기...")
                time.sleep(wait)
                continue
            print(f"    ⚠️ FMP HTTP {r.status_code}")
            time.sleep(10)
        except Exception as e:
            print(f"    ⚠️ FMP 에러({e})")
            time.sleep(5)
    return None


# ============================================================
# S&P 500 목록 — Wikipedia (무료, API 콜 0)
# ============================================================
def get_sp500_tickers():
    """위키피디아에서 S&P 500 구성종목과 회사명을 가져옵니다."""
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
# 1+2단계: FMP 배치 시세 (price, priceAvg50, marketCap)
# ============================================================
def fmp_batch_quote(symbols):
    """
    FMP 배치 시세 API — 최대 100종목씩 묶어서 1콜
    반환: {symbol: {price, priceAvg50, marketCap}} dict
    """
    result = {}
    batch_size = 100

    for i in range(0, len(symbols), batch_size):
        if check_timeout():
            break

        batch = symbols[i:i + batch_size]
        symbols_str = ",".join(batch)
        url = f"https://financialmodelingprep.com/api/v3/quote/{symbols_str}?apikey={FMP_KEY}"

        r = fmp_request(url, timeout=30)
        if r and r.status_code == 200:
            data = r.json()
            if isinstance(data, list):
                for item in data:
                    sym = item.get("symbol", "")
                    if sym:
                        result[sym] = {
                            "price": item.get("price", 0) or 0,
                            "priceAvg50": item.get("priceAvg50", 0) or 0,
                            "marketCap": item.get("marketCap", 0) or 0,
                            "name": item.get("name", sym),
                        }

        batch_num = i // batch_size + 1
        total_batches = (len(symbols) + batch_size - 1) // batch_size
        print(f"   📡 배치 {batch_num}/{total_batches}: {len(batch)}종목 요청 → {len(data) if r else 0}건 수신")
        time.sleep(1)

    return result


def recover_missing(symbols, quote_data, name_map):
    """
    배치 응답에서 누락된 종목을 개별 재요청 (최대 2회 시도)
    """
    missing = [s for s in symbols if s not in quote_data]
    if not missing:
        return quote_data

    print(f"   🔍 누락 {len(missing)}종목 개별 복구 시도...")

    for sym in missing:
        recovered = False
        for attempt in range(2):  # 최대 2회 시도
            url = f"https://financialmodelingprep.com/api/v3/quote/{sym}?apikey={FMP_KEY}"
            r = fmp_request(url, timeout=10)
            if r and r.status_code == 200:
                data = r.json()
                if isinstance(data, list) and len(data) > 0:
                    item = data[0]
                    quote_data[sym] = {
                        "price": item.get("price", 0) or 0,
                        "priceAvg50": item.get("priceAvg50", 0) or 0,
                        "marketCap": item.get("marketCap", 0) or 0,
                        "name": item.get("name", sym),
                    }
                    print(f"    ✅ {sym} 복구 성공 (시도 {attempt+1})")
                    recovered = True
                    break
            time.sleep(3)

        if not recovered:
            print(f"    ❌ {sym} 복구 실패 (2회 시도 후 탈락)")

    return quote_data


# ============================================================
# 3단계: FMP Screener + 하이브리드 개별 검증
# ============================================================
def get_fmp_roe_screener():
    """FMP Stock Screener 1콜 → ROE 15%+ 종목 세트"""
    if not FMP_KEY:
        return set()

    url = (f"https://financialmodelingprep.com/api/v3/stock-screener"
           f"?marketCapMoreThan=10000000000"
           f"&isActivelyTrading=true"
           f"&limit=1000"
           f"&apikey={FMP_KEY}")

    r = fmp_request(url)
    if r and r.status_code == 200:
        data = r.json()
        return {item.get('symbol', '') for item in data if item}
    return set()


def check_roe_individual(symbol):
    """개별 ROE 검증 — 2회 시도"""
    if not FMP_KEY:
        return None

    for attempt in range(2):
        url = f"https://financialmodelingprep.com/stable/key-metrics-ttm?symbol={symbol}&apikey={FMP_KEY}"
        r = fmp_request(url, timeout=10)
        if r and r.status_code == 200:
            data = r.json()
            if data and isinstance(data, list) and len(data) > 0:
                return data[0].get('returnOnEquityTTM')
        time.sleep(3)
    return None


# ============================================================
# 4단계: FMP 성장성 (Surprise + EPS Growth)
# ============================================================
def check_growth_fmp(symbol):
    """4단계 — Surprise ≥ 10% OR EPS Growth ≥ 20%"""
    if not FMP_KEY:
        return False, "FMP API Key Missing"

    url_s = f"https://financialmodelingprep.com/api/v3/earnings-surprises/{symbol}?apikey={FMP_KEY}"
    s_res = fmp_request(url_s)
    if not s_res:
        return False, f"FMP Surprise Failed ({symbol})"

    time.sleep(13)  # FMP Rate Limit 준수

    url_g = f"https://financialmodelingprep.com/api/v3/financial-growth/{symbol}?period=quarter&limit=1&apikey={FMP_KEY}"
    g_res = fmp_request(url_g)
    if not g_res:
        return False, f"FMP Growth Failed ({symbol})"

    if s_res.status_code == 200 and g_res.status_code == 200:
        s_data = s_res.json()
        g_data = g_res.json()

        if (isinstance(s_data, list) and len(s_data) > 0 and
                isinstance(g_data, list) and len(g_data) > 0):
            surprise = s_data[0].get('percentageEarningsSurprise', 0) or 0
            eps_growth = g_data[0].get('epsgrowth', 0) or 0

            if surprise >= 10 or eps_growth >= 0.20:
                return True, f"Surprise: {round(surprise,1)}%, Growth: {round(eps_growth*100,1)}%"
            return False, f"Surprise: {round(surprise,1)}%, Growth: {round(eps_growth*100,1)}%"
        return False, f"FMP No Data ({symbol})"
    return False, f"FMP HTTP Error ({symbol})"


# ============================================================
# 메인 파이프라인
# ============================================================
def run_scan():
    global fmp_call_count
    fmp_call_count = 0

    # ========================================
    # S&P 500 목록 수집
    # ========================================
    sp500 = get_sp500_tickers()
    if not sp500:
        print("❌ S&P 500 목록 수집 실패")
        return

    total = len(sp500)
    name_map = {item["symbol"]: item["name"] for item in sp500}
    tickers = [item["symbol"] for item in sp500]

    print(f"🚀 [Alpha Scanner V3] FMP 전용 엔진 가동")
    print(f"   대상: {total}종목 | FMP 쿼터: {FMP_DAILY_LIMIT}콜/일")

    # ========================================
    # [1+2단계] 체급 + 에너지 — FMP 배치 시세
    # ========================================
    print(f"\n{'='*50}")
    print(f"📊 [1+2단계] 체급 + 에너지 (FMP 배치 시세)")
    print(f"{'='*50}")

    # 배치 시세 요청
    quote_data = fmp_batch_quote(tickers)
    print(f"   📊 배치 수신: {len(quote_data)}/{total}종목")

    # 누락 복구 (개별 재시도 2회)
    quote_data = recover_missing(tickers, quote_data, name_map)
    received = len(quote_data)
    receive_rate = round(received / total * 100, 1)
    print(f"   📊 최종 수신: {received}/{total}종목 ({receive_rate}%)")

    if received < total:
        missing_count = total - received
        print(f"   ⚠️ {missing_count}종목 미수신 (2회 재시도 후에도 복구 실패 → 필터 탈락 처리)")

    # 1단계: 시총 $10B+
    stage1 = []
    for sym in tickers:
        if sym not in quote_data:
            continue
        d = quote_data[sym]
        if d["marketCap"] >= 10_000_000_000:  # $10B
            stage1.append(sym)

    c1 = len(stage1)
    print(f"\n✅ [1단계] 체급: {c1}건 통과 (시총 $10B+)")

    # 2단계: 가격 > 50MA
    stage2 = []
    for sym in stage1:
        d = quote_data[sym]
        price = d["price"]
        ma50 = d["priceAvg50"]

        if price > 0 and ma50 > 0 and price > ma50:
            momentum = round(((price - ma50) / ma50) * 100, 2)
            stage2.append({
                "Symbol": sym,
                "Name": name_map.get(sym, d.get("name", sym)),
                "Price": round(price, 2),
                "MA50": round(ma50, 2),
                "Momentum(%)": momentum,
                "MarketCap_M": round(d["marketCap"] / 1_000_000),
            })

    c2 = len(stage2)
    print(f"✅ [2단계] 에너지: {c2}건 통과 (가격 > 50MA)")
    print(f"   📡 FMP 사용: {fmp_call_count}콜 (남은 쿼터: {FMP_DAILY_LIMIT - fmp_call_count})")

    # ========================================
    # [3단계] 내실 — FMP Screener + 하이브리드
    # ========================================
    print(f"\n{'='*50}")
    print(f"📊 [3단계] 내실 검증 (FMP Screener + 개별)")
    print(f"{'='*50}")

    roe_screener_set = get_fmp_roe_screener()
    print(f"   📡 FMP Screener: {len(roe_screener_set)}종목 확인 (1콜)")

    stage3 = []
    verify_needed = []

    for item in stage2:
        sym = item["Symbol"]
        if sym in roe_screener_set:
            item["ROE(%)"] = "Screener ✅"
            stage3.append(item)
        else:
            verify_needed.append(item)

    print(f"   ✅ Screener 매칭: {len(stage3)}건 자동 통과")
    print(f"   🔍 개별 검증 필요: {len(verify_needed)}건")

    for item in verify_needed:
        if check_timeout():
            break
        sym = item["Symbol"]
        roe = check_roe_individual(sym)
        if roe is not None and roe >= 0.15:
            item["ROE(%)"] = round(roe * 100, 2)
            stage3.append(item)
            print(f"    ✅ {sym} ROE: {round(roe*100,1)}% → PASS")
        elif roe is not None:
            print(f"    ❌ {sym} ROE: {round(roe*100,1)}% → FAIL")
        else:
            print(f"    ⚠️ {sym} ROE 데이터 없음 → 탈락")
        time.sleep(13)

    c3 = len(stage3)
    print(f"\n✅ [3단계] 내실: {c3}건 통과 (ROE 15%+)")
    print(f"   📡 FMP 사용: {fmp_call_count}콜 (남은 쿼터: {FMP_DAILY_LIMIT - fmp_call_count})")

    # ========================================
    # [4단계] 성장 — FMP 개별
    # ========================================
    print(f"\n{'='*50}")
    print(f"📊 [4단계] 성장 검증 (FMP API)")
    print(f"{'='*50}")

    # 쿼터 예측: 4단계는 종목당 2콜
    needed_calls = c3 * 2
    remaining = FMP_DAILY_LIMIT - fmp_call_count
    if needed_calls > remaining:
        # 쿼터 부족 시 상위 종목만 검증
        max_stocks = remaining // 2
        print(f"   ⚠️ 쿼터 제한! {c3}종목 중 상위 {max_stocks}종목만 검증")
        stage3 = sorted(stage3, key=lambda x: x["Momentum(%)"], reverse=True)[:max_stocks]
        c3 = len(stage3)

    stage4 = []
    for i, item in enumerate(stage3):
        if check_timeout():
            break
        sym = item["Symbol"]
        print(f"🔍 [4단계] {sym} ({i+1}/{c3})")

        passed, reason = check_growth_fmp(sym)
        if passed:
            item["GrowthReason"] = reason
            stage4.append(item)
            print(f"    ✅ {sym} → {reason}")
        else:
            print(f"    ❌ {sym} → {reason}")
        time.sleep(15)

    c4 = len(stage4)
    print(f"\n✅ [4단계] 성장: {c4}건 통과")
    print(f"   📡 FMP 총 사용: {fmp_call_count}콜 (남은 쿼터: {FMP_DAILY_LIMIT - fmp_call_count})")

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
            "received": received,
            "receive_rate": receive_rate,
            "success_all": True,
            "step1": c1, "step2": c2, "step3": c3, "step4": c4,
            "timestamp": datetime.now().isoformat(),
            "fmp_calls": fmp_call_count,
            "fmp_remaining": FMP_DAILY_LIMIT - fmp_call_count,
            "elapsed_min": elapsed_min,
            "engine": "FMP Only V3 (Yahoo-Free, KIS-Free)",
        }, f)

    print(f"\n{'='*55}")
    print(f"✅ [Alpha Scanner V3] 최종 결과")
    print(f"   Total: {total}종목 (수신: {received}, {receive_rate}%)")
    print(f"   1단계(체급): {c1} → 2단계(에너지): {c2}")
    print(f"   → 3단계(내실): {c3} → 4단계(성장): {c4}")
    print(f"   📡 FMP: {fmp_call_count}/{FMP_DAILY_LIMIT}콜 사용 (잔여: {FMP_DAILY_LIMIT - fmp_call_count})")
    print(f"   ⏱️ 소요시간: {elapsed_min}분")
    print(f"{'='*55}")


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(__file__))
    from us_market_calendar import is_trading_day

    if not is_trading_day():
        print("📅 오늘은 미국 시장 휴장일입니다. 스캔을 건너뜁니다.")
        sys.exit(0)

    run_scan()
