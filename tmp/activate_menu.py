"""텔레그램에 리플라이 키보드 메뉴를 활성화합니다."""
import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

keyboard = {
    "keyboard": [
        ["📊 전체 수익률", "📈 종목별 수익률"],
        ["💵 예수금 현황", "💰 실시간 잔고"],
        ["🔍 오늘자 스캔", "🛑 긴급 전량 매도"],
    ],
    "resize_keyboard": True,
    "is_persistent": True,
}

url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
payload = {
    "chat_id": CHAT_ID,
    "text": "🤖 *알파 에이전트 메뉴가 활성화되었습니다!*\n\n하단 버튼을 눌러주세요, 대표님! 👇",
    "parse_mode": "Markdown",
    "reply_markup": json.dumps(keyboard),
}

r = requests.post(url, json=payload, timeout=10)
print(f"Status: {r.status_code}")
print(f"Response: {r.json().get('ok')}")
