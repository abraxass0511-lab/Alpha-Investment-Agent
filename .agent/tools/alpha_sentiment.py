"""
★ Alpha Sentiment V3 — MarketAux ML 정량 심리 분석 엔진 ★

핵심 설계:
1. 데이터 필터링: MarketAux match_score ≥ 0.8 (주인공 뉴스만)
2. 비대칭 임계값: 신규 ≥ 0.7 (BUY) / 보유 ≥ 0.5 (Hold) / < 0.5 (Exit)
3. 변동성 제어: 심리 5일선(SMA₅) — 당일 0.7+ AND SMA₅ 0.6+ 이중 게이트
4. No News Rule: 뉴스 0건 = 중립(0.5) → 신규 BUY 차단, 보유 HOLD 유지

데이터 무결성 원칙:
- Symbol, Price, ROE 등 모든 숫자는 CSV 원본(row)에서만 추출
- MarketAux는 심리 점수만 제공 → 다른 데이터 생성/수정 불가
"""
import os
import json
import pandas as pd
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
import time

load_dotenv()
MARKETAUX_KEY = os.getenv("MARKETAUX_API_KEY")
FINNHUB_KEY = os.getenv("FINNHUB_API_KEY")  # 6단계 모멘텀 계산용 (유지)

# ★ 5단계 핵심 상수 ★
RELEVANCE_THRESHOLD = 0.8   # match_score 이 이상인 기사만 사용 (주인공 필터)
SENTIMENT_BUY_LINE = 0.7    # 신규 매수 통과 기준
SENTIMENT_HOLD_LINE = 0.5   # 보유 유지 기준
SMA_APPROVAL_LINE = 0.6     # SMA₅ 이중 게이트 기준
SMA_MIN_DAYS = 3            # 콜드 스타트: 최소 3일 데이터 필요
NEWS_LIMIT = 10             # 종목당 최대 기사 수

HISTORY_FILE = "output_reports/sentiment_history.json"


# ═══════════════════════════════════════════════════════
# 심리 히스토리 관리 (SMA₅ 용)
# ═══════════════════════════════════════════════════════
def load_sentiment_history():
    """날짜별 종목별 심리 점수 히스토리 로드"""
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except:
        pass
    return {}


def save_sentiment_history(history):
    """히스토리 저장 (최근 10일만 유지하여 파일 크기 관리)"""
    os.makedirs("output_reports", exist_ok=True)
    
    # 10일 이상 된 데이터 정리
    cutoff = (datetime.utcnow() - timedelta(days=10)).strftime("%Y-%m-%d")
    cleaned = {}
    for sym, dates in history.items():
        recent = {d: s for d, s in dates.items() if d >= cutoff}
        if recent:
            cleaned[sym] = recent
    
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(cleaned, f, indent=2)


def calculate_sma5(history, symbol):
    """
    심리 5일선(SMA₅) 계산
    
    - 5일 이상 히스토리 → 최근 5일 평균
    - 3~4일 히스토리 → 해당 일수 평균
    - 3일 미만 → None (콜드 스타트: SMA 게이트 비활성)
    """
    if symbol not in history:
        return None
    
    dates = sorted(history[symbol].keys(), reverse=True)
    if len(dates) < SMA_MIN_DAYS:
        return None  # 콜드 스타트: 데이터 부족
    
    recent = dates[:5]  # 최근 5일 (또는 있는 만큼)
    scores = [history[symbol][d] for d in recent]
    return round(sum(scores) / len(scores), 3)


def update_history(history, symbol, score, date_str):
    """오늘 점수를 히스토리에 추가"""
    if symbol not in history:
        history[symbol] = {}
    history[symbol][date_str] = score


# ═══════════════════════════════════════════════════════
# 텔레그램 알림
# ═══════════════════════════════════════════════════════
def _alert_sentiment_gap(symbol, reason=""):
    """5단계 뉴스 데이터 누락 시 텔레그램 알림"""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if token and chat_id:
        msg = (
            f"⚠️ *5단계 뉴스 데이터 누락*\n\n"
            f"종목: `{symbol}`\n"
            f"{reason}\n"
            f"_해당 종목은 5단계 스킵됩니다_"
        )
        try:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"},
                timeout=10,
            )
        except:
            pass
    print(f"    ⚠️ {symbol} {reason}")


# ═══════════════════════════════════════════════════════
# MarketAux API
# ═══════════════════════════════════════════════════════
def fetch_marketaux_sentiment(symbol):
    """
    ★ MarketAux API: 종목별 뉴스 + ML 심리점수 수집 ★
    필터: match_score ≥ 0.8 (주인공 뉴스만)
    
    Returns:
        dict: 정상 응답 ({"scores": [...], ...})
        "QUOTA_EXCEEDED": 쿼터 부족 (429/402)
        "API_ERROR": 기타 API 오류
        None: API 키 없음 등 설정 오류
    """
    if not MARKETAUX_KEY:
        print(f"    ❌ MARKETAUX_API_KEY 없음")
        return "API_ERROR"

    url = "https://api.marketaux.com/v1/news/all"
    params = {
        "symbols": symbol,
        "filter_entities": "true",
        "must_have_entities": "true",
        "language": "en",
        "limit": NEWS_LIMIT,
        "published_after": (datetime.utcnow() - timedelta(days=3)).strftime('%Y-%m-%dT%H:%M'),
        "api_token": MARKETAUX_KEY,
    }

    try:
        r = requests.get(url, params=params, timeout=15)

        if r.status_code == 429:
            print(f"    ⚠️ MarketAux 쿼터 초과 (429) — {symbol}")
            return "QUOTA_EXCEEDED"
        if r.status_code == 402:
            print(f"    ⚠️ MarketAux 플랜 제한 (402) — {symbol}")
            return "QUOTA_EXCEEDED"
        if r.status_code != 200:
            print(f"    ⚠️ MarketAux HTTP {r.status_code} — {symbol}")
            return "API_ERROR"

        data = r.json()
        articles = data.get("data", [])

        if not articles:
            return {"scores": [], "articles_total": 0, "articles_relevant": 0, "sources": []}

        scores = []
        sources = []

        for article in articles:
            entities = article.get("entities", [])
            source = article.get("source", "Unknown")

            for ent in entities:
                ent_symbol = ent.get("symbol", "")
                match_score = ent.get("match_score", 0) or 0
                sent_score = ent.get("sentiment_score")

                # ★ 핵심 필터: 심볼 일치 + 관련도 0.8 이상 + 점수 존재 ★
                if (ent_symbol == symbol
                        and match_score >= RELEVANCE_THRESHOLD
                        and sent_score is not None):
                    scores.append(float(sent_score))
                    sources.append(source)

        return {
            "scores": scores,
            "articles_total": len(articles),
            "articles_relevant": len(scores),
            "sources": list(set(sources)),
        }

    except Exception as e:
        print(f"    ⚠️ MarketAux 에러({e}) — {symbol}")
        return "API_ERROR"


# ═══════════════════════════════════════════════════════
# 5단계 핵심 분석 함수
# ═══════════════════════════════════════════════════════
def analyze_ticker_marketaux(row, history, today_str):
    """
    ★ 5단계 심리 분석 — 4대 규칙 적용 ★
    
    규칙1: 관련도 ≥ 0.8 필터 (주인공 뉴스만)
    규칙2: 신규 매수 ≥ 0.7 / 보유 ≥ 0.5
    규칙3: SMA₅ ≥ 0.6 이중 게이트
    규칙4: No News = 중립(0.5) → 신규 BUY 차단, 보유 HOLD 유지
    """
    symbol = row.get('Symbol')
    name = row.get('Name')
    price = row['Price']
    momentum = row['MA_Momentum(%)']
    roe = row['ROE(%)']

    # 1. MarketAux에서 ML 심리점수 수집
    result = fetch_marketaux_sentiment(symbol)

    if result == "QUOTA_EXCEEDED":
        print(f"    📭 {symbol} MarketAux 쿼터 부족 → 분석 불가")
        return "QUOTA_EXCEEDED"
    if result == "API_ERROR" or result is None:
        print(f"    📭 {symbol} MarketAux API 장애 → 분석 불가")
        return "API_ERROR"

    scores = result["scores"]
    total = result["articles_total"]
    relevant = result["articles_relevant"]
    sources = result["sources"]

    # ★ 규칙4: No News Rule (중립 간주) ★
    if not scores:
        # 관련도 0.8+ 뉴스 0건 → 중립(0.5) 간주
        # "뉴스 없음 = 악재도 없음" → 0.5 < 0.7이므로 신규 BUY 차단, 보유 HOLD 유지
        no_news_score = 0.50
        update_history(history, symbol, no_news_score, today_str)  # SMA₅ 축적용 기록
        sma5 = calculate_sma5(history, symbol)
        sma5_label = f"{sma5:.3f}" if sma5 is not None else "N/A (축적 중)"
        print(f"    📭 {symbol} 관련 뉴스 0건 (전체 {total}건) → 중립(0.5) 간주 [HOLD (관망)]")
        return {
            "Symbol": symbol,
            "Name": name,
            "Price": price,
            "Momentum(%)": momentum,
            "Sentiment": no_news_score,
            "SMA5": sma5,
            "ROE(%)": roe,
            "MarketCap_M": row.get('MarketCap_M', 0),
            "MA50": row.get('MA50', 0),
            "Surprise(%)": row.get('Surprise(%)', 0),
            "EPS_Growth(%)": row.get('EPS_Growth(%)', 0),
            "Status": "HOLD (관망/대기)",
            "Reason": f"📭 뉴스 0건 → 중립(0.5) 간주 (전체 {total}건, 관련도≥{RELEVANCE_THRESHOLD})",
        }

    # 2. ★ 정량 점수 계산: 관련도 0.8+ 기사들의 평균 sentiment ★
    avg_marketaux = sum(scores) / len(scores)  # -1 ~ +1
    today_score = round((avg_marketaux + 1) / 2, 3)  # 알파 스케일 (0~1)

    # 3. 히스토리에 오늘 점수 기록 (SMA₅ 계산용)
    update_history(history, symbol, today_score, today_str)

    # 4. ★ 규칙3: SMA₅ 이중 게이트 ★
    sma5 = calculate_sma5(history, symbol)
    sma5_pass = True
    sma5_label = "N/A (축적 중)"

    if sma5 is not None:
        sma5_label = f"{sma5:.3f}"
        if sma5 < SMA_APPROVAL_LINE:
            sma5_pass = False  # SMA₅ < 0.6 → 매수 차단

    # 5. ★ 규칙2: 매수 상태 판정 ★
    status = "REJECT"
    if today_score >= SENTIMENT_BUY_LINE and sma5_pass:
        status = "BUY (매수 승인 대기)"
    elif today_score >= SENTIMENT_BUY_LINE and not sma5_pass:
        status = "HOLD (SMA₅ 미달 — 추세 확인 중)"
    elif today_score >= SENTIMENT_HOLD_LINE:
        status = "HOLD (관망/대기)"

    if today_score < 0.3:
        print(f"    ❌ {symbol} 즉시 탈락 — 심리 {today_score:.3f} < 0.3")
        return None

    source_label = ", ".join(sources[:3]) if sources else "N/A"
    reason = (
        f"MarketAux ML 📊 "
        f"today={today_score:.3f} SMA₅={sma5_label} "
        f"({relevant}/{total}건, 관련도≥{RELEVANCE_THRESHOLD}, "
        f"출처: {source_label})"
    )

    print(f"    ✅ {symbol} today={today_score:.3f} SMA₅={sma5_label} [{status}]")

    return {
        "Symbol": symbol,
        "Name": name,
        "Price": price,
        "Momentum(%)": momentum,
        "Sentiment": today_score,
        "SMA5": sma5,
        "ROE(%)": roe,
        "MarketCap_M": row.get('MarketCap_M', 0),
        "MA50": row.get('MA50', 0),
        "Surprise(%)": row.get('Surprise(%)', 0),
        "EPS_Growth(%)": row.get('EPS_Growth(%)', 0),
        "Status": status,
        "Reason": reason,
    }


# ═══════════════════════════════════════════════════════
# 6단계: 12-1 모멘텀
# ═══════════════════════════════════════════════════════
def calculate_12_1_momentum(symbol):
    """
    Step 6: 12-1 Month Momentum (Finnhub Primary → Yahoo Fallback)
    Returns: float (성공 시) 또는 None (API 실패 시)
    """
    # 1차: Finnhub Candle API (Primary)
    FKEY = os.getenv("FINNHUB_API_KEY")
    if FKEY:
        try:
            now = int(time.time())
            one_year_ago = now - (365 * 24 * 60 * 60)
            url = f"https://finnhub.io/api/v1/stock/candle?symbol={symbol}&resolution=D&from={one_year_ago}&to={now}&token={FKEY}"
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                data = r.json()
                if data.get("s") == "ok":
                    closes = data.get("c", [])
                    if len(closes) > 21:
                        price_t1 = closes[-22]
                        price_t12 = closes[0]
                        if price_t12 > 0:
                            return round((price_t1 / price_t12) - 1, 4)
        except Exception as e:
            print(f"    ⚠️ Finnhub 6단계 에러({e}) ({symbol})")

    # 2차: Yahoo Finance (Fallback)
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
    except Exception as e:
        print(f"    ⚠️ Yahoo 6단계 폴백 에러({e}) ({symbol})")

    # ★ Finnhub + Yahoo 둘 다 실패 → None 반환 (API 장애와 모멘텀 0 구분)
    print(f"    🚨 {symbol} 12-1 모멘텀 데이터 수집 실패 (Finnhub+Yahoo)")
    return None


# ═══════════════════════════════════════════════════════
# 메인 실행
# ═══════════════════════════════════════════════════════
def run_sentiment_v3():
    """★ MarketAux 기반 5단계 + 6단계 실행 ★"""
    scan_file = "output_reports/daily_scan_latest.csv"
    if not os.path.exists(scan_file):
        print("❌ daily_scan_latest.csv 없음 — 스캐너가 실행되지 않았습니다.")
        return

    df = pd.read_csv(scan_file)
    if df.empty:
        print("⚠️ 4단계 통과 종목 0건 — 빈 결과 처리")
        try:
            with open("output_reports/metadata.json", "r") as f:
                meta = json.load(f)
        except:
            meta = {}
        meta["step5"] = 0
        meta["step6"] = 0
        with open("output_reports/metadata.json", "w") as f:
            json.dump(meta, f)
        pd.DataFrame().to_csv("output_reports/final_picks_latest.csv", index=False)
        return

    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    history = load_sentiment_history()

    print(f"🚀 [Alpha Sentiment V3] MarketAux ML 정량 분석 가동...")
    print(f"   📋 대상: {len(df)}종목 | 관련도 필터: ≥{RELEVANCE_THRESHOLD}")
    print(f"   🎯 BUY: ≥{SENTIMENT_BUY_LINE} & SMA₅≥{SMA_APPROVAL_LINE} | HOLD: ≥{SENTIMENT_HOLD_LINE}")
    print(f"   📅 날짜: {today_str} | 히스토리: {len(history)}종목")
    print(f"   🔑 API Key: {'있음' if MARKETAUX_KEY else '❌ 없음'}")

    sentiment_all = []
    quota_fail_count = 0    # ★ 쿼터 부족 카운터
    api_error_count = 0     # ★ API 오류 카운터
    analyzed_count = 0      # ★ 정상 분석 카운터

    # MarketAux Rate Limit: 무료 100콜/일 → 직렬 처리 (안전)
    for idx, row in df.iterrows():
        try:
            res = analyze_ticker_marketaux(row, history, today_str)
            if res == "QUOTA_EXCEEDED":
                quota_fail_count += 1
            elif res == "API_ERROR":
                api_error_count += 1
            elif res:
                sentiment_all.append(res)
                analyzed_count += 1
        except Exception as e:
            api_error_count += 1
            print(f"    ❌ {row.get('Symbol', '?')} 분석 에러: {e}")

        # MarketAux Rate Limit 방지: 종목간 0.5초 대기
        time.sleep(0.5)

    # ★ 쿼터 부족 요약 로그
    if quota_fail_count > 0:
        print(f"   🚨 MarketAux 쿼터 부족: {quota_fail_count}종목 분석 불가!")
    if api_error_count > 0:
        print(f"   ⚠️ MarketAux API 오류: {api_error_count}종목")

    # 히스토리 저장 (다음날 SMA₅ 계산용)
    save_sentiment_history(history)
    print(f"   💾 심리 히스토리 저장: {len(history)}종목")

    # 전체 센티먼트 결과 저장 (리밸런서용)
    if sentiment_all:
        all_sent_df = pd.DataFrame(sentiment_all)
        all_sent_df.to_csv("output_reports/sentiment_all_latest.csv", index=False)
        print(f"   💾 전체 센티먼트 결과 저장: {len(sentiment_all)}종목")

    # ★ BUY 후보: Sentiment ≥ 0.7 AND SMA₅ 게이트 통과 ★
    buy_candidates = [p for p in sentiment_all if "BUY" in p['Status']]
    buy_count = len(buy_candidates)

    try:
        with open("output_reports/metadata.json", "r") as f:
            meta = json.load(f)
    except:
        meta = {"total": 503, "step12": 0, "step3": 0, "step4": 0}

    meta["step5"] = buy_count

    # ★ 5단계 API 장애 정보를 metadata에 기록 ★
    meta["step5_quota_fail"] = quota_fail_count
    meta["step5_api_error"] = api_error_count
    meta["step5_analyzed"] = analyzed_count
    meta["step5_total_target"] = len(df)

    # [Step 6] 12-1 Momentum Sorting (Elite 5 Selection)
    final_picks = []
    step6_api_fail = 0  # ★ 6단계 API 실패 카운터

    if buy_count > 0:
        print(f"⚖️ [Step 6] 12-1 모멘텀 소팅 중... (대상: {buy_count}개 종목)")
        for item in buy_candidates:
            mom = calculate_12_1_momentum(item['Symbol'])
            if mom is None:
                step6_api_fail += 1
                mom = 0.0  # API 실패 시 0으로 처리 (탈락 대상이지만 원인은 기록)
                item['Reason'] += f" | ⚠️ 12-1 모멘텀: API 실패"
            else:
                item['Reason'] += f" | 12-1 모멘텀: {round(mom*100, 2)}%"
            item['Momentum_12_1'] = mom

        positive_mom = [x for x in buy_candidates if x['Momentum_12_1'] > 0]
        negative_mom = [x for x in buy_candidates if x['Momentum_12_1'] <= 0]

        if negative_mom:
            for item in negative_mom:
                sym = item['Symbol']
                mom_pct = round(item['Momentum_12_1'] * 100, 2)
                print(f"    ❌ {sym} 탈락 — 12-1 모멘텀 {mom_pct}% (음수)")

        final_picks = sorted(positive_mom, key=lambda x: x['Momentum_12_1'], reverse=True)[:5]
        meta["step6"] = len(final_picks)

        if len(final_picks) < 5:
            print(f"    ℹ️ 양수 모멘텀 {len(positive_mom)}개 → Top {len(final_picks)} 선정 (빈 슬롯 = 현금 보유)")
    else:
        meta["step6"] = 0

    # ★ 6단계 API 장애 정보를 metadata에 기록 ★
    meta["step6_api_fail"] = step6_api_fail

    with open("output_reports/metadata.json", "w") as f:
        json.dump(meta, f)

    if final_picks:
        final_df = pd.DataFrame(final_picks)
        final_df.to_csv("output_reports/final_picks_latest.csv", index=False)
        print(f"✅ MarketAux V3 완료. (Final Pick: {len(final_picks)}건 / Step 5 Pass: {buy_count}건)")
    else:
        pd.DataFrame().to_csv("output_reports/final_picks_latest.csv", index=False)
        print("❌ 최종 통과 종목 없음 (Step 5 기준 미달).")


if __name__ == "__main__":
    run_sentiment_v3()
