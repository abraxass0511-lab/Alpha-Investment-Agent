import os
import json
import pandas as pd
import requests
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
import time

load_dotenv()
FINNHUB_KEY = os.getenv("FINNHUB_API_KEY")
analyzer = SentimentIntensityAnalyzer()

# 고퀄리티 언론사 리스트
PREMIUM_SOURCES = ["Reuters", "Bloomberg", "CNBC", "MarketWatch", "Wall Street Journal", "WSJ", "Financial Times", "FT"]
# 결정적 키워드 리스트
BOOST_KEYWORDS = ["Surprise", "Upgrade", "Exclusive", "New Contract", "Beat", "Approval", "Soar", "Bullish", "Buy"]

def fetch_finnhub_news(symbol):
    if not FINNHUB_KEY: return []
    # 최근 2일 데이터 수집 (48시간)
    to_date = datetime.now().strftime('%Y-%m-%d')
    from_date = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d')
    url = f"https://finnhub.io/api/v1/company-news?symbol={symbol}&from={from_date}&to={to_date}&token={FINNHUB_KEY}"
    try:
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            return r.json()
    except:
        pass
    return []

def select_quality_news(news_list):
    """양보다 질: 정예 뉴스 5~10개 선정 로직"""
    if not news_list: return []
    
    scored_news = []
    now_ts = int(time.time())
    
    for item in news_list:
        score = 0
        title = item.get('headline', '')
        source = item.get('source', '')
        ts = item.get('datetime', 0)
        
        # 1. 출처의 신뢰도 (+5점)
        if any(ps in source for ps in PREMIUM_SOURCES): score += 5
        
        # 2. 키워드 가중치 (+3점)
        if any(kw.lower() in title.lower() for kw in BOOST_KEYWORDS): score += 3
        
        # 3. 시간의 신설도 (24시간 이내 +5점)
        if (now_ts - ts) < 86400: score += 5
        
        scored_news.append({'title': title, 'score': score, 'source': source})
        
    # 점수 높은 순으로 정렬 후 상위 10개 추출
    sorted_news = sorted(scored_news, key=lambda x: x['score'], reverse=True)
    return sorted_news[:10]

def analyze_ticker_finnhub(row):
    symbol = row.get('Symbol')
    name = row.get('Name')
    
    news = fetch_finnhub_news(symbol)
    quality_news = select_quality_news(news)
    
    if not quality_news: return None
    
    sentiment_scores = []
    premium_found = False
    for item in quality_news:
        title = item['title']
        v_score = analyzer.polarity_scores(title)['compound']
        
        # 만약 로이터/블룸버그급 뉴스라면 가중치 적용
        if item['score'] >= 10: 
            v_score *= 1.2
            premium_found = True
            
        sentiment_scores.append(v_score)
        
    avg_score = sum(sentiment_scores) / len(sentiment_scores) if sentiment_scores else 0
    final_score = round(avg_score, 3)
    
    # 대표님 매수 원칙: 0.7+ (BUY)
    status = "REJECT"
    if final_score >= 0.7: status = "BUY (매수 승인 대기)"
    elif final_score >= 0.4: status = "HOLD (관망/대기)"
    
    if final_score < 0.3: return None # 0.3 미만은 아예 제외
    
    # 핵심 근거 동적 생성
    source_label = "Premium 🏛️" if premium_found else "Stable 📡"
    reason = f"{name} ({symbol})은 최근 {source_label} 뉴스 소스를 통해 긍정적 흐름이 포착되었습니다. (심리 점수: {final_score})"
    
    return {
        "Symbol": symbol,
        "Name": name,
        "Price": row['Price'],
        "Momentum(%)": row['Momentum(%)'],
        "Sentiment": final_score,
        "ROE(%)": row['ROE(%)'],
        "Status": status,
        "Reason": reason
    }

import yfinance as yf

def calculate_12_1_momentum(symbol):
    """
    Step 6: Calculate 12-1 Month Momentum
    기본: FMP Historical Price / 백업: Yahoo Finance
    Formula: (Price_{t-1} / Price_{t-12}) - 1
    """
    FMP_KEY = os.getenv("FMP_API_KEY")
    
    # === 1차 시도: FMP API (기본) ===
    if FMP_KEY:
        try:
            url = f"https://financialmodelingprep.com/api/v3/historical-price-full/{symbol}?timeseries=252&apikey={FMP_KEY}"
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                data = r.json()
                prices = data.get('historical', [])
                if len(prices) > 21:
                    price_t_minus_1 = prices[21]['close']   # 약 1개월 전
                    price_t_minus_12 = prices[-1]['close']   # 약 12개월 전
                    momentum = (price_t_minus_1 / price_t_minus_12) - 1
                    return round(momentum, 4)
            print(f"    ⚠️ FMP 6단계 {r.status_code} → Yahoo 백업 전환 ({symbol})")
        except Exception as e:
            print(f"    ⚠️ FMP 6단계 에러({e}) → Yahoo 백업 전환 ({symbol})")
    
    # === 2차 시도: Yahoo Finance (백업) ===
    try:
        t = yf.Ticker(symbol)
        hist = t.history(period="1y")
        if len(hist) > 21:
            price_t_minus_1 = hist['Close'].iloc[-21]
            price_t_minus_12 = hist['Close'].iloc[0]
            momentum = (price_t_minus_1 / price_t_minus_12) - 1
            return round(momentum, 4)
    except:
        pass
    return 0.0

def run_sentiment_v2():
    scan_file = "output_reports/daily_scan_latest.csv"
    if not os.path.exists(scan_file): return
    
    df = pd.read_csv(scan_file)
    if df.empty: return
    
    print(f"🚀 [Alpha Sentiment V2] Finnhub 정예 분석 가동 (품질 필터링 적용)...")
    
    sentiment_passed = []
    # Finnhub API Rate Limit 방지를 위해 Worker 조절 (10명)
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(analyze_ticker_finnhub, row) for _, row in df.iterrows()]
        for future in as_completed(futures):
            res = future.result()
            if res: sentiment_passed.append(res)

    # 전체 센티먼트 결과 저장 (리밸런서가 보유종목 기준 0.4로 재검증할 때 사용)
    if sentiment_passed:
        all_sent_df = pd.DataFrame(sentiment_passed)
        all_sent_df.to_csv("output_reports/sentiment_all_latest.csv", index=False)
        print(f"   💾 전체 센티먼트 결과 저장: {len(sentiment_passed)}종목")
            
    # 정합성 카운트 (BUY 전용 - Sentiment >= 0.7)
    buy_candidates = [p for p in sentiment_passed if "BUY" in p['Status']]
    buy_count = len(buy_candidates)
    
    try:
        with open("output_reports/metadata.json", "r") as f:
            meta = json.load(f)
    except:
        meta = {"total": 503, "step1": 0, "step2": 0, "step3": 0, "step4": 0}
        
    meta["step5"] = buy_count
    
    # [Step 6] 12-1 Momentum Sorting (Elite 5 Selection)
    final_picks = []
    if buy_count > 0:
        print(f"⚖️ [Step 6] 12-1 모멘텀 소팅 중... (대상: {buy_count}개 종목)")
        for item in buy_candidates:
            mom = calculate_12_1_momentum(item['Symbol'])
            item['Momentum_12_1'] = mom
            item['Reason'] += f" | 12-1 모멘텀: {round(mom*100, 2)}%"
        
        # Sort by 12-1 Momentum and take top 5
        final_picks = sorted(buy_candidates, key=lambda x: x['Momentum_12_1'], reverse=True)[:5]
        meta["step6"] = len(final_picks)
    else:
        meta["step6"] = 0

    with open("output_reports/metadata.json", "w") as f:
        json.dump(meta, f)
        
    if final_picks:
        final_df = pd.DataFrame(final_picks)
        final_df.to_csv("output_reports/final_picks_latest.csv", index=False)
        print(f"✅ 분석 및 소팅 완료. (Final Pick: {len(final_picks)}건 / Step 5 Pass: {buy_count}건)")
    else:
        pd.DataFrame().to_csv("output_reports/final_picks_latest.csv", index=False)
        print("❌ 최종 통과 종목 없음 (Step 5 기준 미달).")

if __name__ == "__main__":
    run_sentiment_v2()
