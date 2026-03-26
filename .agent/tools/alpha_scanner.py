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

def get_fmp_data(symbol):
    if not FMP_KEY: return None, None
    try:
        url = f"https://financialmodelingprep.com/stable/key-metrics-ttm?symbol={symbol}&apikey={FMP_KEY}"
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            data = r.json()
            if data: return data[0].get('returnOnEquityTTM'), data[0].get('marketCap')
    except: pass
    return None, None

def process_item(symbol):
    """Attempt to get ALL info for ONE ticker. Return Result if success, else None."""
    try:
        t = yf.Ticker(symbol)
        info = t.info
        if not info or 'marketCap' not in info: return None
        
        m_cap = info.get('marketCap', 0)
        roe_y = info.get('returnOnEquity', 0)
        
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
            'ROE_Yahoo': roe_y,
            'Momentum(%)': round(((close - ma50) / ma50) * 100, 2)
        }
    except:
        return None

def check_growth_step_3_5(symbol):
    """
    Phase 4: Growth Verification (FMP 전용 - Yahoo 백업 없음)
    FMP API만 사용. 429 에러 시 대기 후 재시도 (최대 5회).
    1. Earnings Surprise >= 10%
    2. EPS Growth (YoY) >= 20%
    OR 조건: 둘 중 하나만 만족하면 통과
    """
    if not FMP_KEY:
        print(f"    🚨 FMP API Key 없음! 4단계 검증 불가.")
        return False, "FMP API Key Missing"
    
    max_retries = 5
    
    for attempt in range(max_retries):
        try:
            # --- Call 1: Earnings Surprise ---
            url_surprise = f"https://financialmodelingprep.com/api/v3/earnings-surprises/{symbol}?apikey={FMP_KEY}"
            s_res = requests.get(url_surprise, timeout=15)
            
            if s_res.status_code == 429:
                wait_time = 60 * (attempt + 1)
                print(f"    ⏳ FMP 429 (시도 {attempt+1}/{max_retries}) → {wait_time}초 대기 후 재시도...")
                time.sleep(wait_time)
                continue
            
            # 두 API 호출 사이 13초 대기 (Rate Limit 준수)
            time.sleep(13)
            
            # --- Call 2: Financial Growth ---
            url_growth = f"https://financialmodelingprep.com/api/v3/financial-growth/{symbol}?period=quarter&limit=1&apikey={FMP_KEY}"
            g_res = requests.get(url_growth, timeout=15)
            
            if g_res.status_code == 429:
                wait_time = 60 * (attempt + 1)
                print(f"    ⏳ FMP 429 (시도 {attempt+1}/{max_retries}) → {wait_time}초 대기 후 재시도...")
                time.sleep(wait_time)
                continue
            
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
                
                # 데이터가 비어있는 경우
                return False, f"FMP No Data ({symbol})"
            
            # 기타 HTTP 에러 (5xx 등)
            print(f"    ⚠️ FMP HTTP {s_res.status_code}/{g_res.status_code} → 30초 대기 후 재시도...")
            time.sleep(30)
            
        except Exception as e:
            print(f"    ⚠️ FMP 에러({e}) → 30초 대기 후 재시도...")
            time.sleep(30)
    
    # 최대 재시도 초과
    print(f"    🚨 {symbol}: FMP {max_retries}회 재시도 실패. SKIP.")
    return False, f"FMP Failed after {max_retries} retries"

def run_persistent_scan():
    tickers = get_sp500_tickers()
    if not tickers: tickers = ['AAPL', 'MSFT', 'NVDA']
    
    total_count = len(tickers)
    print(f"🚀 [Alpha Persistent Scanner] 전수 조사 시작 (대상: {total_count} 종목)")
    
    results = {} # {symbol: data}
    remaining_tickers = list(tickers)
    
    attempt = 1
    while remaining_tickers:
        print(f"🔄 시도 {attempt}: 남은 종목 {len(remaining_tickers)}개 스캔 중...")
        
        # Yahoo 차단 방지를 위해 매우 보수적인 병렬 처리 (2명)
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_to_symbol = {executor.submit(process_item, s): s for s in remaining_tickers}
            for future in as_completed(future_to_symbol):
                symbol = future_to_symbol[future]
                res = future.result()
                if res:
                    results[symbol] = res
        
        # 남은 종목 갱신
        remaining_tickers = [s for s in tickers if s not in results]
        
        if remaining_tickers:
            print(f"⚠️ {len(remaining_tickers)}개 누락. 짧은 대기 후 다시 시도합니다...")
            time.sleep(attempt * 2 + random.random() * 5)
            attempt += 1
            if attempt > 30: # 무한 루프 방지용 (하지만 매우 높게 설정)
                print("🚨 30회 시도 후 중단. (야후 차단 심각)")
                break

    # 2. 비즈니스 로직 적용 (Size, ROE, Momentum, Growth)
    final_picks = []
    c1, c2, c3, c4 = 0, 0, 0, 0
    
    # Phase 1~3: Size, Quality(FMP ROE 기본 → Yahoo 백업), Momentum
    step3_passed = []
    for symbol, data in results.items():
        if data['MarketCap'] >= 10e9:
            c1 += 1
            # 2단계: FMP ROE 기본, Yahoo 백업
            roe_fmp, _ = get_fmp_data(symbol)
            if roe_fmp is not None:
                roe = roe_fmp
            else:
                roe = data['ROE_Yahoo']  # FMP 실패 시 Yahoo 백업
            if roe >= 0.15:
                c2 += 1
                if data['Price'] > data['MA50']:
                    c3 += 1
                    data['ROE(%)'] = round(roe * 100, 2)
                    step3_passed.append((symbol, data))
    
    print(f"📊 1~3단계 완료: {c1}/{c2}/{c3}")
    
    # Phase 4: Growth (FMP 전용 - Yahoo 백업 없음, 429 시 재시도)
    for idx, (symbol, data) in enumerate(step3_passed):
        print(f"🔍 [4단계] {symbol} 성장성 검증 중... ({idx+1}/{len(step3_passed)})")
        passed_4, reason_4 = check_growth_step_3_5(symbol)
        if passed_4:
            c4 += 1
            data['GrowthReason'] = reason_4
            final_picks.append(data)
        time.sleep(15)  # FMP 분당 5회 제한 준수 (2콜/종목 + 내부13초 + 외부15초)

    # 결과 저장
    if not os.path.exists('output_reports'): os.makedirs('output_reports')
    pd.DataFrame(final_picks).to_csv("output_reports/daily_scan_latest.csv", index=False)
    
    with open("output_reports/metadata.json", "w") as f:
        json.dump({
            "total": total_count,
            "success_all": (len(results) == total_count),
            "step1": c1, "step2": c2, "step3": c3, "step4": c4,
            "timestamp": datetime.now().isoformat()
        }, f)
        
    print(f"✅ 결과: Total {total_count} (Success: {len(results)}) -> {c1}/{c2}/{c3}/{c4}")


if __name__ == "__main__":
    run_persistent_scan()
