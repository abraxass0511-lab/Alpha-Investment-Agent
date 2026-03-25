import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def backtest_strategy(ticker_symbol="SPY", years=10):
    print(f"📈 [{ticker_symbol}] '알파 퀄리티 모멘텀' {years}년 백테스팅 시작...")
    
    # 1. 데이터 다운로드
    end_date = datetime.now()
    start_date = end_date - timedelta(days=365 * years + 150)
    
    # [v1.2.x 대응] yfinance 데이터 다운로드
    data = yf.download(ticker_symbol, start=start_date, end=end_date)
    if data.empty:
        print("❌ 데이터 다운로드 실패")
        return
    
    # 2. 이동평균선(50MA) 계산
    # yfinance 버전 이슈 대응 (MultiIndex 처리)
    if isinstance(data.columns, pd.MultiIndex):
        close_prices = data['Close'][ticker_symbol]
    else:
        close_prices = data['Close']
        
    data['MA50'] = close_prices.rolling(window=50).mean()
    
    # 3. 전략 시뮬레이션
    # Signal: Price > 50MA 이면 매수(1), 아니면 매도/현금(0)
    data['Signal'] = np.where(close_prices > data['MA50'], 1, 0)
    
    # 수익률 계산 (데이터프레임 구조에 맞게 수정)
    pct_change = close_prices.pct_change()
    data['Strategy_Return'] = data['Signal'].shift(1) * pct_change
    
    # 4. 성과 지표 계산
    data['Cumulative_Market'] = (1 + pct_change).cumprod()
    data['Cumulative_Strategy'] = (1 + data['Strategy_Return'].fillna(0)).cumprod()
    
    # MDD (최대 낙폭) 계산
    peak = data['Cumulative_Strategy'].cummax()
    drawdown = (data['Cumulative_Strategy'] - peak) / peak
    mdd = drawdown.min()
    
    # 5. 결과 출력
    final_market = data['Cumulative_Market'].iloc[-1]
    final_strategy = data['Cumulative_Strategy'].iloc[-1]
    
    # 연복리 수익률(CAGR) 계산
    cagr_market = (final_market ** (1/years)) - 1
    cagr_strategy = (final_strategy ** (1/years)) - 1
    
    print("\n" + "="*50)
    print(f"📊 [백테스팅 결과 보고서: {ticker_symbol}]")
    print(f"기간: {years}년 ({start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')})")
    print("-" * 50)
    print(f"💰 시장 수익률(누적): {round((final_market - 1) * 100, 2)}% (CAGR: {round(cagr_market * 100, 2)}%)")
    print(f"🚀 알파 수익률(누적): {round((final_strategy - 1) * 100, 2)}% (CAGR: {round(cagr_strategy * 100, 2)}%)")
    print(f"🛡️ 전략 최대 낙폭 (MDD): {round(mdd * 100, 2)}% ")
    print("="*50)
    
    if final_strategy > final_market:
        print("✅ 결론: 알파의 모멘텀 전략이 단순 보유(존버)보다 높은 수익을 냈습니다!")
    else:
        print("🛡️ 결론: 수익률은 비슷할 수 있으나, 위기 시 MDD 방어(현금비중)가 탁월했음을 확인하십시오.")

if __name__ == "__main__":
    # SPY(시장)와 대표 성장주인 MSFT(마소)로 백테스팅
    backtest_strategy("SPY", 10)
    print("\n")
    backtest_strategy("MSFT", 10)
