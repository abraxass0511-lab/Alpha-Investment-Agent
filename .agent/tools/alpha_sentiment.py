import os
import glob
import pandas as pd
import yfinance as yf
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from datetime import datetime

analyzer = SentimentIntensityAnalyzer()

def get_latest_scan_file():
    files = glob.glob("output_reports/daily_scan_*.csv")
    if not files:
        return None
    files.sort(key=os.path.getmtime, reverse=True)
    return files[0]

def analyze_candidates():
    scan_file = get_latest_scan_file()
    if not scan_file:
        print("❌ 스캔된 1차 후보군 파일이 없습니다. Mission 1을 먼저 실행하세요.")
        return pd.DataFrame()

    df = pd.read_csv(scan_file)
    print(f"🚀 [Alpha Execution] 1차 통과된 {len(df)}개 우량주 대상 3(모멘텀), 4(심리)단계 필터링 시작!\n")
    
    final_picks = []

    for index, row in df.iterrows():
        symbol = row['Symbol']
        name = row['Name']
        
        try:
            ticker = yf.Ticker(symbol)
            
            # --- 3단계: Momentum 필터 (주가 > 50일 이평선) ---
            hist = ticker.history(period="6mo")
            if len(hist) < 50:
                continue
            
            ma50 = hist['Close'].rolling(window=50).mean()
            last_close = hist['Close'].iloc[-1]
            last_ma50 = ma50.iloc[-1]
            
            # 50일선 아래에 있으면 하락추세이므로 즉시 컷
            if last_close <= last_ma50:
                # print(f"  ❌ [탈락] {symbol}: 주가({round(last_close,2)}) <= 50일선({round(last_ma50,2)})")
                continue
                
            # --- 4단계: Sentiment 필터 (뉴스 감성 점수 파악) ---
            news_list = ticker.news
            if not news_list:
                continue # 뉴스가 아예 없어도 패스
                
            sentiment_scores = []
            for item in news_list[:5]: # 최근 주요 뉴스 5개 제목 분석
                title = item.get('title', '')
                if title:
                    score = analyzer.polarity_scores(title)['compound']
                    sentiment_scores.append(score)
            
            # 평균 감성 점수 도출 (-1 ~ 1)
            avg_sentiment = sum(sentiment_scores) / len(sentiment_scores) if sentiment_scores else 0
            
            # SKILL.md 규칙: 센티먼트 양수(+) 이상
            # (자연어 처리기 Vader 기준 0.1 이상이면 나름의 호재성 뉴스)
            if avg_sentiment > 0.0:
                final_picks.append({
                    "Symbol": symbol,
                    "Name": name,
                    "Current Price": round(last_close, 2),
                    "Momentum (%)": round((last_close - last_ma50) / last_ma50 * 100, 2), # 50일선 대비 이격도
                    "Sentiment": round(avg_sentiment, 3)
                })
                print(f"  ✅ [PASS] {symbol} (모멘텀: +{round((last_close - last_ma50) / last_ma50 * 100, 2)}%, 감성점수: {round(avg_sentiment,3)})")
            
        except Exception as e:
            # print(f"  ⚠️ [ERROR] {symbol} 분석 중 오류: {e}")
            pass

    # -- 최종 집중 투자 대상 5개 선정 (Sentiment 최고점 기준) --
    final_df = pd.DataFrame(final_picks)
    if not final_df.empty:
        # 뉴스 호재 점수가 가장 높은 놈, 그 다음이 모멘텀이 강한 놈
        final_df = final_df.sort_values(by=["Sentiment", "Momentum (%)"], ascending=[False, False]).head(5)
    
    return final_df

if __name__ == "__main__":
    final_stocks = analyze_candidates()
    
    print("\n🏆 [MISSION 2 완료] 최종 매수 후보 TOP 5")
    print("="*80)
    if not final_stocks.empty:
        print(final_stocks.to_string(index=False))
        
        # 파일 저장
        os.makedirs("output_reports", exist_ok=True)
        filename = f"output_reports/final_picks_{datetime.now().strftime('%Y%m%d')}.csv"
        final_stocks.to_csv(filename, index=False)
        
        print("="*80)
        print(f"\n📂 (내일장 즉시 매수 지시서가 '{filename}'에 저장되었습니다.)")
    else:
        print("❌ 현재 3, 4단계를 통과한 상승 추세의 우량주가 없습니다.")
        print("💵 (결정사항) 전액 현금 보유로 최대 낙폭(MDD) 방어 모드 진입!")
        print("="*80)
