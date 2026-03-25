import os
import pandas as pd
import yfinance as yf
from datetime import datetime

# 조사 대상을 100개로 대폭 확장 (S&P 100 수준)
EXPANDED_TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "BRK-B", "JPM", "V", 
    "JNJ", "WMT", "MA", "PG", "UNH", "HD", "BAC", "DIS", "ADBE", "NFLX",
    "CRM", "AMD", "AVGO", "COST", "PEP", "KO", "TMO", "ABT", "CMCSA", "XOM",
    "CVX", "LLY", "ABBV", "NKE", "PFE", "MRK", "ORCL", "INTC", "CSCO", "VZ",
    "DHR", "MCD", "NEST", "TXN", "NEE", "PM", "T", "LOW", "UPS", "LMT",
    "BMY", "RTX", "AMGN", "HON", "IBM", "SBUX", "GE", "LIN", "AMD", "GS",
    "DE", "CAT", "PLD", "INTU", "AXP", "EL", "SPGI", "MDLZ", "ISRG", "BLK",
    "AMT", "CIM", "BKNG", "GILD", "SYK", "TJX", "ADP", "NOW", "CVS", "ZTS",
    "VRTX", "CI", "HUM", "REGN", "MU", "TGT", "MO", "FISV", "MMC", "EQIX"
]

def get_quality_candidates_expanded():
    print(f"🚀 [Alpha Scanner] 대규모 전수 조사 시작... (대상: {len(EXPANDED_TICKERS)} 종목)")
    quality_stocks = []
    
    # 병렬 처리는 복잡하므로 순차적으로 하되, 속도를 위해 일부 필터 생략 가능
    # 여기서는 Mission 1용으로 ROE와 시총을 다시 체크합니다.
    for symbol in EXPANDED_TICKERS:
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            market_cap = info.get('marketCap', 0) or 0
            roe = info.get('returnOnEquity', 0) or 0
            
            if market_cap >= 10000000000 and roe >= 0.15:
                quality_stocks.append({
                    "Symbol": symbol,
                    "Name": info.get('shortName', 'N/A'),
                    "Price": info.get('currentPrice', 'N/A'),
                    "ROE(%)": round(roe * 100, 2),
                    "MarketCap($B)": round(market_cap / 1e9, 2)
                })
        except:
            continue
            
    df = pd.DataFrame(quality_stocks)
    os.makedirs("output_reports", exist_ok=True)
    df.to_csv("output_reports/daily_scan_latest.csv", index=False)
    return df

if __name__ == "__main__":
    get_quality_candidates_expanded()
    print("✅ 1차 스캐닝(체급/내실) 완료. 이제 감성/모멘텀 분석을 다시 실행하십시오.")
