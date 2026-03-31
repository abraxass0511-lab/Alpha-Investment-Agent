"""
alpha_notify_failure.py — 스캔 실패 시 텔레그램 알림 발송 (V5)
Finnhub Only 엔진 대응
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
    step12 = meta.get("step12", 0)
    step3 = meta.get("step3", 0)
    step4 = meta.get("step4", 0)
    finnhub_calls = meta.get("finnhub_calls", 0)
    elapsed = meta.get("elapsed_min", 0)
    engine = meta.get("engine", "Finnhub+Yahoo V5")
    success = meta.get("success_all", False)

    # 성공 시에는 실패 알림 보내지 않음
    if success and step4 > 0:
        print("✅ 스캔 성공 — 실패 알림 불필요")
        return

    # 구체적 실패 원인
    fail_reason = meta.get("fail_reason", "")
    fail_detail = meta.get("fail_detail", "")
    s5_quota = meta.get("step5_quota_fail", 0)
    s5_api_err = meta.get("step5_api_error", 0)
    s6_api_fail = meta.get("step6_api_fail", 0)

    # 원인별 메시지 구성
    reason_line = ""
    if fail_reason == "wikipedia_fetch_failed":
        reason_line = "\n🚨 *원인: Wikipedia S&P 500 목록 수집 실패*\n"
    elif fail_detail:
        reason_line = f"\n🚨 *원인: {fail_detail}*\n"

    api_issue_lines = ""
    if s5_quota > 0 or s5_api_err > 0 or s6_api_fail > 0:
        api_issue_lines = "\n*API 장애 상세:*\n"
        if s5_quota > 0:
            api_issue_lines += f"  🚨 5단계 MarketAux 쿼터 부족: {s5_quota}종목\n"
        if s5_api_err > 0:
            api_issue_lines += f"  ⚠️ 5단계 MarketAux API 오류: {s5_api_err}종목\n"
        if s6_api_fail > 0:
            api_issue_lines += f"  ⚠️ 6단계 모멘텀 API 실패: {s6_api_fail}종목\n"

    msg = (
        "⚠️ *스캔 실패 알림*\n\n"
        f"{reason_line}"
        f"*단계별 결과:*\n"
        f"  1+2단계(체급+내실): {step12}건 / {total}종목\n"
        f"  3단계(에너지): {step3}건\n"
        f"  4단계(성장): {step4}건\n"
        f"{api_issue_lines}\n"
        f"📡 Finnhub: {finnhub_calls}콜\n"
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
