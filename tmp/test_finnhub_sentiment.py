"""
Finnhub News Sentiment API 테스트
- /news-sentiment 엔드포인트 응답 구조 확인
- 무료 플랜 지원 여부 확인
"""
import os, requests, json
from dotenv import load_dotenv

load_dotenv()
FINNHUB_KEY = os.getenv("FINNHUB_API_KEY")

test_symbols = ["AAPL", "MSFT", "NVDA", "META", "AMZN"]

print(f"🔑 API Key: {'있음' if FINNHUB_KEY else '❌ 없음'}")
print(f"{'='*60}")

for sym in test_symbols:
    url = f"https://finnhub.io/api/v1/news-sentiment?symbol={sym}&token={FINNHUB_KEY}"
    try:
        r = requests.get(url, timeout=10)
        print(f"\n📊 {sym} — HTTP {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            print(json.dumps(data, indent=2))
        elif r.status_code == 403:
            print("   ❌ 403 Forbidden — 무료 플랜 미지원 가능성")
        elif r.status_code == 429:
            print("   ⚠️ 429 Rate Limited")
        else:
            print(f"   ⚠️ 응답: {r.text[:200]}")
    except Exception as e:
        print(f"   ❌ 에러: {e}")
