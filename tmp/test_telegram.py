"""텔레그램 봇 연결 상태 진단"""
import os
import requests
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

print("=" * 50)
print("🔍 텔레그램 봇 연결 진단")
print("=" * 50)

# 1. 토큰 확인
print(f"\n[1] 토큰: {'✅ 설정됨' if TOKEN else '❌ 없음'}")
print(f"[2] Chat ID: {'✅ 설정됨' if CHAT_ID else '❌ 없음'}")

if not TOKEN:
    print("❌ TELEGRAM_BOT_TOKEN이 .env에 없습니다!")
    exit()

# 2. 봇 정보 확인
print("\n[3] 봇 정보 조회...")
r = requests.get(f"https://api.telegram.org/bot{TOKEN}/getMe", timeout=10)
print(f"    Status: {r.status_code}")
if r.status_code == 200:
    bot = r.json().get("result", {})
    print(f"    ✅ 봇 이름: @{bot.get('username', '?')}")
    print(f"    ✅ 봇 ID: {bot.get('id', '?')}")
else:
    print(f"    ❌ 에러: {r.text}")

# 3. 대기 중인 업데이트 확인
print("\n[4] 대기 중인 메시지 확인...")
r = requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates", params={"timeout": 1}, timeout=10)
if r.status_code == 200:
    updates = r.json().get("result", [])
    print(f"    📬 대기 중인 업데이트: {len(updates)}건")
    for u in updates[-5:]:  # 최근 5개만
        if "message" in u:
            msg = u["message"]
            text = msg.get("text", "")
            date = msg.get("date", 0)
            from_id = msg.get("from", {}).get("id", "?")
            from_dt = __import__("datetime").datetime.fromtimestamp(date).strftime("%H:%M:%S")
            print(f"    📩 [{from_dt}] from:{from_id} → '{text}'")
        elif "callback_query" in u:
            cb = u["callback_query"]
            data = cb.get("data", "")
            print(f"    🔘 콜백: '{data}'")
else:
    print(f"    ❌ 에러: {r.text}")

# 4. 테스트 메시지 전송
print("\n[5] 테스트 메시지 전송...")
r = requests.post(
    f"https://api.telegram.org/bot{TOKEN}/sendMessage",
    json={"chat_id": CHAT_ID, "text": "🔧 알파 봇 연결 테스트 — 이 메시지가 보이면 연결 정상입니다!"},
    timeout=10
)
if r.status_code == 200:
    print("    ✅ 테스트 메시지 전송 성공!")
else:
    print(f"    ❌ 전송 실패: {r.status_code} - {r.text}")

print("\n" + "=" * 50)
print("진단 완료")
