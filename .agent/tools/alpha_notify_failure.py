"""
alpha_notify_failure.py — 스캔 실패 시 텔레그램 알림 발송 (V3)
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
    except Exception:
        meta = {}

    total = meta.get("total", 503)
    received = meta.get("received", 0)
    receive_rate = meta.get("receive_rate", 0)
    step1 = meta.get("step1", 0)
    step2 = meta.get("step2", 0)
    step3 = meta.get("step3", 0)
    step4 = meta.get("step4", 0)
    fmp_calls = meta.get("fmp_calls", 0)
    fmp_remaining = meta.get("fmp_remaining", 0)
    elapsed = meta.get("elapsed_min", 0)
    engine = meta.get("engine", "Unknown")

    msg = (
        "⚠️ *스캔 실패 알림*\n\n"
        f"📊 *수신율*: {received}/{total}종목 ({receive_rate}%)\n\n"
        f"*단계별 결과:*\n"
        f"  1단계(체급): {step1}건\n"
        f"  2단계(에너지): {step2}건\n"
        f"  3단계(내실): {step3}건\n"
        f"  4단계(성장): {step4}건\n\n"
        f"📡 FMP 사용: {fmp_calls}콜 (잔여: {fmp_remaining})\n"
        f"⏱️ 소요: {elapsed}분\n"
        f"🔧 엔진: {engine}\n\n"
        "다시 시도하시겠습니까?\n"
        "→ \"시도\" 입력: 처음부터 재시도\n"
        "→ \"종료\" 입력: 오늘은 건너뜀"
    )

    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"},
        timeout=30,
    )
    print(f"⚠️ 스캔 실패 알림 전송 완료")


if __name__ == "__main__":
    notify_failure()
