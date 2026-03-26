import os
import json
import pandas as pd
import yfinance as yf
from datetime import datetime
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import random
from dotenv import load_dotenv

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
    """FMP API 통합 호출 함수 - 429 자동 재시도 + 호출 카운트"""
    global fmp_call_count
    max_retries = 5
    
    for attempt in range(max_retries):
        try:
            fmp_call_count += 1
            r = requests.get(url, timeout=timeout)
            
            if r.status_code == 200:
                return r
            
            if r.status_code == 429:
                wait_time = 60 * (attempt + 1)
                print(f"    ⏳ FMP 429 (시도 {attempt+1}/{max_retries}) → {wait_time}초 대기 후 재시도...")
                time.sleep(wait_time)
                continue
            
            # 기타 에러
            print(f"    ⚠️ FMP HTTP {r.status_code} → 30초 대기 후 재시도...")
            time.sleep(30)
            
        except Exception as e:
            print(f"    ⚠️ FMP 에러({e}) → 30초 대기 후 재시도...")
            time.sleep(30)
    
    return None

# ============================================================
# S&P 500 티커 수집
# ============================================================
def get_sp500_tickers():
    url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
    headers = {'User-Agent': random.choice(USER_AGENTS)}
    try:
        response = requests.get(url, headers=headers)
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
    """Yahoo Finance에서 기본 데이터 수집"""
    try:
        t = yf.Ticker(symbol)
        info = t.info
        if not info or 'marketCap' not in info: return None
        
        m_cap = info.get('marketCap', 0)
        
        hist = t.history(period="100d")
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
    except:
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
    
    attempt = 1
    while remaining_tickers:
        print(f"🔄 시도 {attempt}: 남은 종목 {len(remaining_tickers)}개 스캔 중...")
        
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_to_symbol = {executor.submit(process_item, s): s for s in remaining_tickers}
            for future in as_completed(future_to_symbol):
                symbol = future_to_symbol[future]
                res = future.result()
                if res:
                    results[symbol] = res
        
        remaining_tickers = [s for s in tickers if s not in results]
        
        if remaining_tickers:
            print(f"⚠️ {len(remaining_tickers)}개 누락. 짧은 대기 후 다시 시도합니다...")
            time.sleep(attempt * 2 + random.random() * 5)
            attempt += 1
            if attempt > 30:
                print("🚨 30회 시도 후 중단. (야후 차단 심각)")
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
    run_persistent_scan()
