"""
MarketAux API 테스트
- 무료 플랜 (100콜/일)
- 뉴스별 entity-level sentiment_score (-1 ~ +1) 제공
- 가입: https://www.marketaux.com/
"""
import requests, json

# 무료 API 키 발급 테스트용 (실제 키 필요)
# https://www.marketaux.com/account/dashboard 에서 발급
API_TOKEN = "DEMO"  # 대표님이 발급받으신 키로 교체

test_symbols = ["AAPL", "NVDA", "MSFT"]

print("=" * 60)
print("📊 MarketAux News Sentiment API 테스트")
print("=" * 60)

for sym in test_symbols:
    url = "https://api.marketaux.com/v1/news/all"
    params = {
        "symbols": sym,
        "filter_entities": "true",
        "language": "en",
        "limit": 5,
        "api_token": API_TOKEN
    }
    
    try:
        r = requests.get(url, params=params, timeout=10)
        print(f"\n🔍 {sym} — HTTP {r.status_code}")
        
        if r.status_code == 200:
            data = r.json()
            articles = data.get("data", [])
            print(f"   기사 수: {len(articles)}")
            
            for i, article in enumerate(articles[:3]):
                title = article.get("title", "N/A")[:60]
                entities = article.get("entities", [])
                
                # 해당 심볼의 sentiment_score 추출
                sent_score = None
                for ent in entities:
                    if ent.get("symbol") == sym:
                        sent_score = ent.get("sentiment_score")
                        break
                
                print(f"   [{i+1}] score={sent_score} | {title}")
            
            # 메타 정보
            meta = data.get("meta", {})
            print(f"   📋 meta: {json.dumps(meta)}")
        else:
            print(f"   ⚠️ 응답: {r.text[:300]}")
    except Exception as e:
        print(f"   ❌ 에러: {e}")
