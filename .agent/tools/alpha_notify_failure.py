"""
alpha_notify_failure.py - 스캔 실패 시 텔레그램 알림 발송
"""
import json
import os
import requests

def notify_failure():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Telegram config missing")
        return

    try:
        meta = json.load(open("output_reports/metadata.json"))
    except:
        meta = {"total": 503, "yahoo_collected": 0}

    total = meta.get("total", 503)
    collected = meta.get("yahoo_collected", 0)
    missing = total - collected

    msg = (
        "\u26a0\ufe0f *\uc2a4\uce94 \uc2e4\ud328 \uc54c\ub9bc*\n\n"
        f"\u26a0\ufe0f 1\ub2e8\uacc4(Yahoo \uc218\uc9d1), {total}\uac1c \uc885\ubaa9 \uc911 {missing}\uac1c\uac00 \ub204\ub77d\ub418\uc5c8\uc2b5\ub2c8\ub2e4.\n"
        f"(\uc218\uc9d1 \uc644\ub8cc: {collected}/{total})\n\n"
        "\ub2e4\uc2dc \uc2dc\ub3c4\ud558\uc2dc\uaca0\uc2b5\ub2c8\uae4c?\n"
        "\u2192 \"\uc2dc\ub3c4\" \uc785\ub825: \ucc98\uc74c\ubd80\ud130 \uc7ac\uc2dc\ub3c4\n"
        "\u2192 \"\uc885\ub8cc\" \uc785\ub825: \uc624\ub298\uc740 \uac74\ub108\ub6f0"
    )

    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"},
        timeout=30,
    )
    print(f"\u26a0\ufe0f \uc2a4\uce94 \uc2e4\ud328 \uc54c\ub9bc \uc804\uc1a1 \uc644\ub8cc (\ub204\ub77d: {missing}/{total})")

if __name__ == "__main__":
    notify_failure()
