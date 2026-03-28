"""Finnhub S&P 500 구성종목 API 테스트"""
import os, requests

key = os.getenv("FINNHUB_API_KEY")
r = requests.get(f"https://finnhub.io/api/v1/index/constituents?symbol=^GSPC&token={key}")

print(f"Status: {r.status_code}")

if r.status_code == 200:
    data = r.json()
    constituents = data.get("constituents", [])
    print(f"✅ S&P 500 종목 수: {len(constituents)}")
    print(f"처음 10개: {constituents[:10]}")
    print(f"마지막 10개: {constituents[-10:]}")
elif r.status_code == 403:
    print("❌ 프리미엄 전용 API — 무료 티어에서 사용 불가")
    print(f"응답: {r.text[:200]}")
else:
    print(f"⚠️ 기타 에러: {r.text[:200]}")
