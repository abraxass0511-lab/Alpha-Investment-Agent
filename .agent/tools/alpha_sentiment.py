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

def gemini_sentiment_score(headlines, symbol):
    """
    [Gemini Flash AI 센티먼트 분석]
    
    ★ 절대 원칙 ★
    - AI는 뉴스 헤드라인을 읽고 점수(0.0~1.0)와 한줄 사유 반환만 함
    - AI가 주가, 시총, ROE 등 숫자 데이터를 생성하거나 수정하는 것은 불가능
    - 실패 시 None을 반환하여 VADER 백업으로 전환
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or not headlines:
        return None

    headlines_text = "\n".join([f"- {h}" for h in headlines[:10]])

    prompt = f"""다음은 {symbol} 종목에 대한 최근 뉴스 헤드라인입니다:

{headlines_text}

이 뉴스들을 종합적으로 분석하여 투자 심리 점수를 매겨주세요.

규칙:
1. 점수는 0.0(매우 부정) ~ 1.0(매우 긍정) 사이의 소수점 2자리 숫자
2. 반드시 아래 JSON 형식으로만 답하세요. 다른 텍스트 금지.
3. reason은 한국어로 30자 이내

{{"score": 0.75, "reason": "실적 호조와 신규 계약 긍정적"}}"""

    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 100},
        }
        r = requests.post(url, json=payload, timeout=15)
        
        if r.status_code == 429:
            print(f"    ⚠️ Gemini 무료 초과 → VADER 백업 ({symbol})")
            return None
        if r.status_code != 200:
            return None

        text = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        
        # JSON 파싱 (엄격 검증)
        # ```json ... ``` 래핑 제거
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        
        result = json.loads(text)
        score = float(result.get("score", -1))
        reason = str(result.get("reason", ""))

        # ★ 엄격 검증: 0.0~1.0 범위 밖이면 거부
        if score < 0.0 or score > 1.0:
            print(f"    ❌ Gemini 비정상 점수({score}) → VADER 백업 ({symbol})")
            return None

        return {"score": round(score, 3), "reason": reason[:50]}

    except Exception as e:
        print(f"    ⚠️ Gemini 에러({e}) → VADER 백업 ({symbol})")
        return None


def analyze_ticker_finnhub(row):
    """
    ★ 5단계 심리 분석 (Gemini Flash + VADER 이중 검증) ★
    
    데이터 무결성 원칙:
    - Symbol, Name, Price, ROE, Momentum 등 모든 숫자는 row(CSV 원본)에서만 가져옴
    - AI는 뉴스 헤드라인 판독만 수행 → 점수(0~1)와 사유 반환
    - AI가 row의 어떤 값도 생성하거나 수정할 수 없음
    """
    # ★ 숫자 데이터는 반드시 CSV 원본(row)에서만 추출 ★
    symbol = row.get('Symbol')
    name = row.get('Name')
    price = row['Price']         # API 원본 그대로
    momentum = row['Momentum(%)']  # API 원본 그대로
    roe = row['ROE(%)']          # API 원본 그대로
    
    # 1. Finnhub에서 실제 뉴스 수집 (AI 아님)
    news = fetch_finnhub_news(symbol)
    quality_news = select_quality_news(news)
    
    if not quality_news: return None
    
    headlines = [item['title'] for item in quality_news]
    premium_found = any(item['score'] >= 10 for item in quality_news)
    
    # 2. Gemini Flash로 심리 분석 시도
    ai_result = gemini_sentiment_score(headlines, symbol)
    
    if ai_result:
        # ★ AI 성공: Gemini 점수 사용 ★
        final_score = ai_result["score"]
        ai_reason = ai_result["reason"]
        engine = "Gemini Flash 🧠"
    else:
        # ★ AI 실패: VADER 백업 (기존 로직 그대로) ★
        sentiment_scores = []
        for item in quality_news:
            title = item['title']
            v_score = analyzer.polarity_scores(title)['compound']
            if item['score'] >= 10:
                v_score *= 1.2
            sentiment_scores.append(v_score)
        final_score = round(
            sum(sentiment_scores) / len(sentiment_scores) if sentiment_scores else 0,
            3
        )
        ai_reason = "VADER 규칙 기반 분석"
        engine = "VADER 📡"
    
    # 3. 매수 상태 판정 (기준은 동일)
    status = "REJECT"
    if final_score >= 0.7: status = "BUY (매수 승인 대기)"
    elif final_score >= 0.4: status = "HOLD (관망/대기)"
    
    if final_score < 0.3: return None
    
    source_label = "Premium 🏛️" if premium_found else "Stable 📡"
    reason = f"{ai_reason} ({engine}, {source_label}, 점수: {final_score})"
    
    # ★ 반환값: 숫자는 100% row 원본, AI는 reason만 제공 ★
    return {
        "Symbol": symbol,
        "Name": name,
        "Price": price,           # API 원본
        "Momentum(%)": momentum,  # API 원본
        "Sentiment": final_score,
        "ROE(%)": roe,            # API 원본
        "Status": status,
        "Reason": reason
    }


def calculate_12_1_momentum(symbol):
    """
    Step 6: Calculate 12-1 Month Momentum
    FMP Historical Price 전용 (Yahoo 제거)
    Formula: (Price_{t-1} / Price_{t-12}) - 1
    """
    FMP_KEY = os.getenv("FMP_API_KEY")

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
            print(f"    ⚠️ FMP 6단계 {r.status_code} ({symbol})")
        except Exception as e:
            print(f"    ⚠️ FMP 6단계 에러({e}) ({symbol})")

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
        for future in as_completed(futures, timeout=600):  # 10min max
            try:
                res = future.result(timeout=60)
                if res: sentiment_passed.append(res)
            except Exception:
                pass

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
