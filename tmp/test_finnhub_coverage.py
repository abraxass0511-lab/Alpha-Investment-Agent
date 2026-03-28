"""
Finnhub /metric 커버리지 테스트
S&P 500 중 30개 대표 종목의 marketCapitalization, roeTTM 반환 여부 확인
"""
import os, requests, time, json

FINNHUB_KEY = os.getenv("FINNHUB_API_KEY", "")

# S&P 500에서 다양한 섹터/규모의 30개 샘플
TEST_TICKERS = [
    # 메가캡
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK.B", "JPM", "V",
    # 대형주
    "UNH", "XOM", "LLY", "MA", "PG", "HD", "COST", "ABBV", "MRK", "CVX",
    # 중형주 (시총 $10B 근처)
    "APTV", "BWA", "CZR", "GNRC", "MTCH", "NCLH", "PAYC", "TECH", "POOL", "EPAM"
]

results = {"total": 0, "mcap_ok": 0, "roe_ok": 0, "both_ok": 0, "mcap_null": [], "roe_null": []}

for ticker in TEST_TICKERS:
    url = f"https://finnhub.io/api/v1/stock/metric?symbol={ticker}&metric=all&token={FINNHUB_KEY}"
    try:
        r = requests.get(url, timeout=10)
        data = r.json()
        metric = data.get("metric", {})
        
        mcap = metric.get("marketCapitalization")
        roe = metric.get("roeTTM")
        
        results["total"] += 1
        
        mcap_valid = mcap is not None and mcap > 0
        roe_valid = roe is not None
        
        if mcap_valid:
            results["mcap_ok"] += 1
        else:
            results["mcap_null"].append(ticker)
            
        if roe_valid:
            results["roe_ok"] += 1
        else:
            results["roe_null"].append(ticker)
            
        if mcap_valid and roe_valid:
            results["both_ok"] += 1
            
        print(f"  {ticker:6s} | mcap={str(mcap):>12s} | roe={str(roe):>8s} | {'✅' if mcap_valid and roe_valid else '⚠️ NULL'}")
        
    except Exception as e:
        print(f"  {ticker:6s} | ERROR: {e}")
        results["mcap_null"].append(ticker)
        results["roe_null"].append(ticker)
    
    time.sleep(1.1)

print("\n" + "="*50)
print(f"총 {results['total']}개 종목 테스트")
print(f"  시총 OK: {results['mcap_ok']}/{results['total']}")
print(f"  ROE OK:  {results['roe_ok']}/{results['total']}")
print(f"  둘 다 OK: {results['both_ok']}/{results['total']}")
print(f"  시총 NULL: {results['mcap_null']}")
print(f"  ROE NULL:  {results['roe_null']}")
print(f"\n커버리지: {results['both_ok']/results['total']*100:.1f}%")
