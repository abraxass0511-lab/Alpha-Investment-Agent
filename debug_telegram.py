"""Telegram API 디버그 — 메시지 수신 확인"""
import os
import requests
from dotenv import load_dotenv

load_dotenv()
token = os.getenv("TELEGRAM_BOT_TOKEN")
chat_id = os.getenv("TELEGRAM_CHAT_ID")

print(f"Token exists: {bool(token)}")
print(f"Chat ID: {chat_id}")

if not token:
    print("ERROR: TELEGRAM_BOT_TOKEN not set!")
    exit(1)

# 1) offset 없이 호출
r = requests.get(
    f"https://api.telegram.org/bot{token}/getUpdates",
    params={"timeout": 1, "limit": 10},
    timeout=10,
)
data = r.json()
updates = data.get("result", [])
print(f"\n[offset 없음] Updates: {len(updates)}건")
for u in updates:
    msg = u.get("message", {})
    text = msg.get("text", "?")[:40]
    date = msg.get("date", 0)
    from_id = msg.get("from", {}).get("id", "?")
    print(f"  update_id={u['update_id']} | from={from_id} | text={text} | date={date}")

# 2) offset=-1로 호출 (최신 1건만)
r2 = requests.get(
    f"https://api.telegram.org/bot{token}/getUpdates",
    params={"timeout": 1, "limit": 1, "offset": -1},
    timeout=10,
)
data2 = r2.json()
updates2 = data2.get("result", [])
print(f"\n[offset=-1] Updates: {len(updates2)}건")
for u in updates2:
    msg = u.get("message", {})
    text = msg.get("text", "?")[:40]
    date = msg.get("date", 0)
    print(f"  update_id={u['update_id']} | text={text} | date={date}")

# 3) getMe — 봇 정보 확인
r3 = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=5)
me = r3.json().get("result", {})
print(f"\n[봇 정보] @{me.get('username', '?')} (id={me.get('id', '?')})")

# 4) Webhook 확인 — webhook이 설정되어있으면 getUpdates 안됨!
r4 = requests.get(f"https://api.telegram.org/bot{token}/getWebhookInfo", timeout=5)
wh = r4.json().get("result", {})
wh_url = wh.get("url", "")
print(f"\n[Webhook] URL: '{wh_url}'")
if wh_url:
    print("⚠️ WEBHOOK이 설정되어 있습니다! getUpdates는 webhook과 동시에 사용 불가!")
    print("   → 이것이 '새 메시지 없음'의 원인입니다!")
else:
    print("✅ Webhook 미설정 — getUpdates 정상 사용 가능")
