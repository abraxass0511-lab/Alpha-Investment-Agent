"""
Finnhub /metric 커버리지 테스트
S&P 500 중 30개 대표 종목의 marketCapitalization, roeTTM 반환 여부 확인
결과를 텔레그램으로 전송
"""
import os, requests, time, json

FINNHUB_KEY = os.getenv("FINNHUB_API_KEY", "")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

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
lines = []

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
            
        status = "✅" if mcap_valid and roe_valid else "⚠️"
        line = f"{status} {ticker}: mcap={mcap}, roe={roe}"
        print(line)
        lines.append(line)
        
    except Exception as e:
        line = f"❌ {ticker}: ERROR {e}"
        print(line)
        lines.append(line)
        results["mcap_null"].append(ticker)
        results["roe_null"].append(ticker)
    
    time.sleep(1.1)

# 결과 요약
total = results["total"]
summary = f"""📊 *Finnhub 커버리지 테스트 결과*

테스트: S&P 500 샘플 {total}개

✅ 시총 OK: {results['mcap_ok']}/{total}
✅ ROE OK: {results['roe_ok']}/{total}
✅ 둘 다 OK: {results['both_ok']}/{total}

📈 *커버리지: {results['both_ok']/total*100:.1f}%*

⚠️ 시총 NULL: {results['mcap_null'] if results['mcap_null'] else '없음'}
⚠️ ROE NULL: {results['roe_null'] if results['roe_null'] else '없음'}"""

print("\n" + summary)

# 텔레그램 전송
if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
    # 요약 전송
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": TELEGRAM_CHAT_ID, "text": summary, "parse_mode": "Markdown"}
    )
    # 상세 결과 전송
    detail = "\n".join(lines)
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": TELEGRAM_CHAT_ID, "text": f"📋 상세 결과:\n{detail}"}
    )
    print("✅ 텔레그램 전송 완료")
