import os
import json
import signal
import pandas as pd
import yfinance as yf
from datetime import datetime
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import random
from dotenv import load_dotenv

# ============================================================
# Global Timeout: 90 min max
# ============================================================
SCAN_TIMEOUT = 90 * 60  # 90 minutes
SCAN_START = time.time()

def check_timeout():
    elapsed = time.time() - SCAN_START
    if elapsed > SCAN_TIMEOUT:
        print(f"\n🚨 스캔 타임아웃! ({int(elapsed//60)}분 경과, 제한: {SCAN_TIMEOUT//60}분)")
        return True
    return False

load_dotenv()
FMP_KEY = os.getenv("FMP_API_KEY")

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36'
]

# ============================================================
# FMP API 호출 카운터 (일일 사용량 추적)
# ============================================================
fmp_call_count = 0

def fmp_request(url, timeout=15):
    """FMP API - 429 auto retry + call count (max 3 retries)"""
    global fmp_call_count
    max_retries = 3
    
    for attempt in range(max_retries):
        if check_timeout(): return None
        try:
            fmp_call_count += 1
            r = requests.get(url, timeout=timeout)
            
            if r.status_code == 200:
                return r
            
            if r.status_code == 429:
                wait_time = min(30 * (attempt + 1), 60)  # max 60s wait
                print(f"    ⏳ FMP 429 (시도 {attempt+1}/{max_retries}) → {wait_time}초 대기...")
                time.sleep(wait_time)
                continue
            
            print(f"    ⚠️ FMP HTTP {r.status_code} → 15초 대기...")
            time.sleep(15)
            
        except Exception as e:
            print(f"    ⚠️ FMP 에러({e}) → 10초 대기...")
            time.sleep(10)
    
    return None

# ============================================================
# S&P 500 티커 수집
# ============================================================
def get_sp500_tickers():
    url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
    headers = {'User-Agent': random.choice(USER_AGENTS)}
    try:
        response = requests.get(url, headers=headers, timeout=30)
        soup = BeautifulSoup(response.text, 'html.parser')
        table = soup.find('table', {'id': 'constituents'})
        tickers = []
        if table:
            for row in table.find_all('tr')[1:]:
                ticker = row.find_all('td')[0].text.strip()
                tickers.append(ticker.replace('.', '-'))
        return tickers
    except:
        return []

# ============================================================
# 1단계: Yahoo에서 기본 데이터 수집 (Size + Price + MA50)
# ============================================================
def process_item(symbol):
    """Yahoo Finance에서 기본 데이터 수집 (60초 타임아웃)"""
    try:
        t = yf.Ticker(symbol)
        info = t.info
        if not info or 'marketCap' not in info: return None
        
        m_cap = info.get('marketCap', 0)
        
        hist = t.history(period="100d", timeout=30)
        if len(hist) < 50: return None
        
        close = hist['Close'].iloc[-1]
        ma50 = hist['Close'].rolling(window=50).mean().iloc[-1]
        
        return {
            'Symbol': symbol,
            'Name': info.get('shortName', symbol),
            'MarketCap': m_cap,
            'Price': round(close, 2),
            'MA50': ma50,
            'Momentum(%)': round(((close - ma50) / ma50) * 100, 2)
        }
    except Exception:
        return None

# ============================================================
# 3단계: FMP 전용 ROE 검증 (429 자동 재시도, Yahoo 백업 없음)
# ============================================================
def check_roe_fmp(symbol):
    """FMP API에서 ROE 데이터 수집 (전용, 백업 없음)"""
    if not FMP_KEY:
        return None
    
    url = f"https://financialmodelingprep.com/stable/key-metrics-ttm?symbol={symbol}&apikey={FMP_KEY}"
    r = fmp_request(url, timeout=10)
    
    if r and r.status_code == 200:
        data = r.json()
        if data and isinstance(data, list) and len(data) > 0:
            roe = data[0].get('returnOnEquityTTM')
            return roe
    
    return None

# ============================================================
# 4단계: FMP 전용 성장성 검증 (429 자동 재시도, Yahoo 백업 없음)
# ============================================================
def check_growth_fmp(symbol):
    """
    Phase 4: Growth Verification (FMP 전용)
    1. Earnings Surprise >= 10%
    2. EPS Growth (YoY) >= 20%
    OR 조건: 둘 중 하나만 만족하면 통과
    """
    if not FMP_KEY:
        return False, "FMP API Key Missing"
    
    # --- Call 1: Earnings Surprise ---
    url_surprise = f"https://financialmodelingprep.com/api/v3/earnings-surprises/{symbol}?apikey={FMP_KEY}"
    s_res = fmp_request(url_surprise)
    
    if not s_res:
        return False, f"FMP Surprise Failed ({symbol})"
    
    # 두 API 호출 사이 13초 대기 (Rate Limit 준수)
    time.sleep(13)
    
    # --- Call 2: Financial Growth ---
    url_growth = f"https://financialmodelingprep.com/api/v3/financial-growth/{symbol}?period=quarter&limit=1&apikey={FMP_KEY}"
    g_res = fmp_request(url_growth)
    
    if not g_res:
        return False, f"FMP Growth Failed ({symbol})"
    
    # 두 응답 모두 200인 경우 판정
    if s_res.status_code == 200 and g_res.status_code == 200:
        s_data = s_res.json()
        g_data = g_res.json()
        
        if isinstance(s_data, list) and len(s_data) > 0 and isinstance(g_data, list) and len(g_data) > 0:
            last_surprise = s_data[0].get('percentageEarningsSurprise', 0) or 0
            last_eps_growth = g_data[0].get('epsgrowth', 0) or 0
            
            if last_surprise >= 10 or last_eps_growth >= 0.20:
                return True, f"FMP Pass (Surprise: {round(last_surprise,1)}%, Growth: {round(last_eps_growth*100,1)}%)"
            return False, f"FMP Fail (Surprise: {round(last_surprise,1)}%, Growth: {round(last_eps_growth*100,1)}%)"
        
        return False, f"FMP No Data ({symbol})"
    
    return False, f"FMP HTTP Error ({symbol})"

# ============================================================
# 메인 파이프라인
# ============================================================
def run_persistent_scan():
    global fmp_call_count
    fmp_call_count = 0
    
    tickers = get_sp500_tickers()
    if not tickers: tickers = ['AAPL', 'MSFT', 'NVDA']
    
    total_count = len(tickers)
    print(f"🚀 [Alpha Persistent Scanner] 전수 조사 시작 (대상: {total_count} 종목)")
    
    # ============================================================
    # Yahoo 전수 조사 (1~2단계용 데이터 수집)
    # ============================================================
    results = {}
    remaining_tickers = list(tickers)
    max_yahoo_retries = 5  # max 5 retries (was 30)
    
    attempt = 1
    while remaining_tickers:
        if check_timeout(): break
        print(f"🔄 시도 {attempt}: 남은 종목 {len(remaining_tickers)}개 스캔 중...")
        
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_to_symbol = {executor.submit(process_item, s): s for s in remaining_tickers}
            for future in as_completed(future_to_symbol, timeout=300):  # 5min timeout per batch
                symbol = future_to_symbol[future]
                try:
                    res = future.result(timeout=60)  # 1min per stock
                    if res:
                        results[symbol] = res
                except Exception:
                    pass
        
        remaining_tickers = [s for s in tickers if s not in results]
        
        if remaining_tickers:
            coverage = len(results) / total_count * 100
            print(f"⚠️ {len(remaining_tickers)}개 누락 (커버리지: {coverage:.0f}%). 대기 후 재시도...")
            time.sleep(min(attempt * 3, 15))
            attempt += 1
            if attempt > max_yahoo_retries:
                print(f"🚨 {max_yahoo_retries}회 시도 후 중단. (커버리지: {coverage:.0f}%)")
                break

    # ============================================================
    # [1단계] 체급 (Size) — Yahoo ✅
    # ============================================================
    c1, c2, c3, c4 = 0, 0, 0, 0
    step1_passed = []
    
    for symbol, data in results.items():
        if data['MarketCap'] >= 10e9:
            c1 += 1
            step1_passed.append((symbol, data))
    
    print(f"📊 [1단계] 체급 완료: {c1}건 통과 (시총 $10B+)")
    
    # ============================================================
    # [2단계] 에너지 (Momentum) — Yahoo ✅
    # ============================================================
    step2_passed = []
    
    for symbol, data in step1_passed:
        if data['Price'] > data['MA50']:
            c2 += 1
            step2_passed.append((symbol, data))
    
    print(f"📊 [2단계] 에너지 완료: {c2}건 통과 (가격 > 50MA)")
    print(f"💡 FMP 호출 대상: {c2}건 (기존 {c1}건에서 대폭 절감!)")
    
    # ============================================================
    # [3단계] 내실 (Quality/ROE) — FMP 전용 🔒
    # ============================================================
    step3_passed = []
    
    for idx, (symbol, data) in enumerate(step2_passed):
        print(f"🔍 [3단계] {symbol} ROE 검증 중... ({idx+1}/{len(step2_passed)})")
        
        roe = check_roe_fmp(symbol)
        
        if roe is not None and roe >= 0.15:
            c3 += 1
            data['ROE(%)'] = round(roe * 100, 2)
            step3_passed.append((symbol, data))
            print(f"    ✅ {symbol} ROE: {round(roe*100,1)}% → PASS")
        elif roe is not None:
            print(f"    ❌ {symbol} ROE: {round(roe*100,1)}% → FAIL")
        else:
            print(f"    🚨 {symbol} FMP 데이터 없음 → SKIP")
        
        time.sleep(13)  # FMP 분당 5회 제한 준수
    
    print(f"📊 [3단계] 내실 완료: {c3}건 통과 (ROE 15%+)")
    
    # ============================================================
    # [4단계] 성장 (Growth) — FMP 전용 🔒
    # ============================================================
    final_picks = []
    
    for idx, (symbol, data) in enumerate(step3_passed):
        print(f"🔍 [4단계] {symbol} 성장성 검증 중... ({idx+1}/{len(step3_passed)})")
        passed_4, reason_4 = check_growth_fmp(symbol)
        if passed_4:
            c4 += 1
            data['GrowthReason'] = reason_4
            final_picks.append(data)
            print(f"    ✅ {symbol} → {reason_4}")
        else:
            print(f"    ❌ {symbol} → {reason_4}")
        time.sleep(15)  # FMP 분당 5회 제한 준수 (2콜/종목)
    
    print(f"📊 [4단계] 성장 완료: {c4}건 통과")

    # ============================================================
    # 결과 저장
    # ============================================================
    if not os.path.exists('output_reports'): os.makedirs('output_reports')
    pd.DataFrame(final_picks).to_csv("output_reports/daily_scan_latest.csv", index=False)
    
    with open("output_reports/metadata.json", "w") as f:
        json.dump({
            "total": total_count,
            "success_all": (len(results) == total_count),
            "step1": c1, "step2": c2, "step3": c3, "step4": c4,
            "timestamp": datetime.now().isoformat(),
            "fmp_calls": fmp_call_count
        }, f)
        
    print(f"\n{'='*50}")
    print(f"✅ 최종 결과: Total {total_count} (Yahoo 수집: {len(results)})")
    print(f"   1단계(체급): {c1} → 2단계(에너지): {c2} → 3단계(내실): {c3} → 4단계(성장): {c4}")
    print(f"   📡 FMP API 총 호출: {fmp_call_count}콜")
    print(f"{'='*50}")


if __name__ == "__main__":
    # 미국 장 개장일 체크
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from us_market_calendar import is_trading_day

    if not is_trading_day():
        print("📅 오늘은 미국 시장 휴장일입니다. 스캔을 건너뜁니다.")
        sys.exit(0)

    run_persistent_scan()
