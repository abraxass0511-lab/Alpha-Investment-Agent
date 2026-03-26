import yfinance as yf
from datetime import datetime

def check_nvda_10y_ago():
    target_date = "2016-03-25"
    ticker = "NVDA"
    print(f"--- Checking {ticker} at {target_date} ---")
    
    t = yf.Ticker(ticker)
    hist = t.history(start="2015-01-01", end="2016-12-31")
    
    # 1. Market Cap estimation
    # We need shares outstanding at that time. yfinance doesn't easily give historical shares outstanding.
    # But we can check historical news or common knowledge.
    # In early 2016, NVDA market cap was ~ $16B.
    
    # 2. Performance & Momentum
    if target_date in hist.index.strftime('%Y-%m-%d'):
        price = hist.loc[target_date]['Close']
        ma50 = hist['Close'].rolling(window=50).mean().loc[target_date]
        print(f"Price: {price}, 50MA: {ma50}")
        if price > ma50:
            print("Step 3: PASS (Price > 50MA)")
        
        # 12-1 momentum
        price_t_minus_1 = hist['Close'].iloc[hist.index.get_indexer([datetime.strptime("2016-02-25", "%Y-%m-%d")], method='nearest')[0]]
        price_t_minus_12 = hist['Close'].iloc[hist.index.get_indexer([datetime.strptime("2015-03-25", "%Y-%m-%d")], method='nearest')[0]]
        mom = (price_t_minus_1 / price_t_minus_12) - 1
        print(f"12-1 Momentum: {round(mom*100, 2)}%")
    else:
        # Nearest date if 25th was a weekend
        idx = hist.index.get_indexer([datetime.strptime(target_date, "%Y-%m-%d")], method='nearest')[0]
        actual_date = hist.index[idx]
        price = hist['Close'].iloc[idx]
        ma50 = hist['Close'].rolling(window=50).mean().iloc[idx]
        print(f"Actual Date: {actual_date}, Price: {price}, 50MA: {ma50}")
        if price > ma50:
            print("Step 3: PASS")
            
        price_t_minus_1 = hist['Close'].iloc[idx - 21] if idx > 21 else hist['Close'].iloc[0]
        price_t_minus_12 = hist['Close'].iloc[idx - 252] if idx > 252 else hist['Close'].iloc[0]
        mom = (price_t_minus_1 / price_t_minus_12) - 1
        print(f"12-1 Momentum (approx): {round(mom*100, 2)}%")

if __name__ == "__main__":
    check_nvda_10y_ago()
