"""
alpha_telegram_menu.py — 에이전트 알파 텔레그램 메뉴 봇

대표님이 텔레그램에서 버튼을 누르면 실시간으로 응답합니다.

메뉴:
  📊 전체 수익률 — 총 자산 및 누적 수익률
  📈 종목별 수익률 — 보유 종목 개별 수익률
  💵 예수금 현황 — 매수 가능 금액
  💰 실시간 잔고 — 보유 종목 수량 및 평가금액
  🔍 오늘자 스캔 — 6단계 필터 결과 요약
  🛑 긴급 전량 매도 — 모든 포지션 즉시 정리
"""

import os
import sys
import json
import time
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
OFFSET_FILE = "output_reports/telegram_offset.json"

sys.path.insert(0, os.path.dirname(__file__))


# ═══════════════════════════════════════════════════════
# 텔레그램 API 유틸리티
# ═══════════════════════════════════════════════════════
def send_message(text, reply_markup=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"⚠️ 전송 에러: {e}")


def answer_callback(callback_query_id, text=""):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery"
    payload = {"callback_query_id": callback_query_id, "text": text}
    try:
        requests.post(url, json=payload, timeout=5)
    except:
        pass


def get_updates(offset=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    params = {"timeout": 5, "allowed_updates": ["message", "callback_query"]}
    if offset:
        params["offset"] = offset
    try:
        r = requests.get(url, params=params, timeout=10)
        if r.status_code == 200:
            return r.json().get("result", [])
    except:
        pass
    return []


def load_offset():
    try:
        if os.path.exists(OFFSET_FILE):
            with open(OFFSET_FILE, "r") as f:
                return json.load(f).get("offset", 0)
    except:
        pass
    return 0


def save_offset(offset):
    os.makedirs(os.path.dirname(OFFSET_FILE), exist_ok=True)
    with open(OFFSET_FILE, "w") as f:
        json.dump({"offset": offset}, f)


# ═══════════════════════════════════════════════════════
# 메뉴 키보드
# ═══════════════════════════════════════════════════════
MENU_KEYBOARD = {
    "inline_keyboard": [
        [
            {"text": "📊 전체 수익률", "callback_data": "total_return"},
            {"text": "📈 종목별 수익률", "callback_data": "stock_return"},
        ],
        [
            {"text": "💵 예수금 현황", "callback_data": "deposit"},
            {"text": "💰 실시간 잔고", "callback_data": "balance"},
        ],
        [
            {"text": "🔍 오늘자 스캔", "callback_data": "today_scan"},
            {"text": "🛑 긴급 전량 매도", "callback_data": "emergency_sell"},
        ],
    ]
}


def send_menu():
    send_message(
        "🤖 *알파 에이전트 메뉴*\n\n무엇을 확인하시겠습니까, 대표님?",
        reply_markup=MENU_KEYBOARD,
    )


# ═══════════════════════════════════════════════════════
# 각 버튼 핸들러
# ═══════════════════════════════════════════════════════
def get_trader():
    from alpha_trader import AlphaTrader
    return AlphaTrader()


def handle_total_return():
    """📊 전체 수익률"""
    try:
        trader = get_trader()
        result = trader.get_balance()
        if not result:
            return "⚠️ 잔고 조회에 실패했습니다, 대표님."

        holdings, _ = result
        if not holdings:
            buying = trader.get_buying_power(symbol="AAPL", price="0")
            usd = buying.get("ord_psbl_frcr_amt", "N/A") if buying else "N/A"
            return f"📊 *전체 수익률*\n\n📭 현재 보유 종목이 없습니다.\n💰 예수금: *${usd}*\n\n현금 100% 상태입니다, 대표님! 🛡️"

        total_invested = 0
        total_eval = 0
        total_pnl = 0

        for h in holdings:
            qty = int(float(h.get('ovrs_cblc_qty', '0')))
            buy_avg = float(h.get('pchs_avg_pric', '0'))
            cur = float(h.get('now_pric2', '0'))
            pnl = float(h.get('frcr_evlu_pfls_amt', '0'))
            if qty <= 0:
                continue
            total_invested += buy_avg * qty
            total_eval += cur * qty
            total_pnl += pnl

        total_rate = (total_pnl / total_invested * 100) if total_invested > 0 else 0
        emoji = "🚀" if total_pnl >= 0 else "📉"

        msg = f"📊 *전체 수익률*\n\n"
        msg += f"💰 총 평가금액: *${total_eval:,.2f}*\n"
        msg += f"💵 투자 원금: ${total_invested:,.2f}\n"
        msg += f"{emoji} 누적 수익률: *{total_rate:+.1f}%* ({total_pnl:+,.2f})\n"
        msg += f"📋 보유 종목: {len([h for h in holdings if int(float(h.get('ovrs_cblc_qty', '0'))) > 0])}개"

        return msg

    except Exception as e:
        return f"⚠️ 조회 에러: {e}"


def handle_stock_return():
    """📈 종목별 수익률"""
    try:
        trader = get_trader()
        result = trader.get_balance()
        if not result:
            return "⚠️ 잔고 조회에 실패했습니다."

        holdings, _ = result
        if not holdings:
            return "📈 *종목별 수익률*\n\n📭 보유 종목이 없습니다, 대표님."

        msg = "📈 *종목별 수익률*\n\n"
        for h in holdings:
            sym = h.get('ovrs_pdno', '?')
            qty = int(float(h.get('ovrs_cblc_qty', '0')))
            buy_avg = float(h.get('pchs_avg_pric', '0'))
            cur = float(h.get('now_pric2', '0'))
            pnl_rt = float(h.get('evlu_pfls_rt', '0'))
            pnl = float(h.get('frcr_evlu_pfls_amt', '0'))

            if qty <= 0:
                continue

            emoji = "🟢" if pnl >= 0 else "🔴"
            msg += f"{emoji} *{sym}* ({pnl_rt:+.1f}%)\n"
            msg += f"   {qty}주 | 매입 ${buy_avg:.2f} → 현재 ${cur:.2f}\n"
            msg += f"   손익: {pnl:+,.2f}\n\n"

        best = max(holdings, key=lambda h: float(h.get('evlu_pfls_rt', '0')))
        best_sym = best.get('ovrs_pdno', '?')
        msg += f"🏆 효자 종목: *{best_sym}*"

        return msg

    except Exception as e:
        return f"⚠️ 조회 에러: {e}"


def handle_deposit():
    """💵 예수금 현황"""
    try:
        trader = get_trader()
        buying = trader.get_buying_power(symbol="AAPL", price="0")

        if not buying:
            return "⚠️ 예수금 조회에 실패했습니다."

        usd_amt = buying.get("ord_psbl_frcr_amt", "0")

        # 총 자산 대비 현금 비중 계산
        result = trader.get_balance()
        cash_ratio = 100
        if result:
            holdings, _ = result
            total_eval = sum(
                float(h.get('now_pric2', '0')) * int(float(h.get('ovrs_cblc_qty', '0')))
                for h in holdings
                if int(float(h.get('ovrs_cblc_qty', '0'))) > 0
            )
            total_asset = total_eval + float(usd_amt)
            cash_ratio = (float(usd_amt) / total_asset * 100) if total_asset > 0 else 100

        msg = f"💵 *예수금 현황*\n\n"
        msg += f"💰 즉시 매수 가능: *${usd_amt}*\n"
        msg += f"📊 현금 비중: {cash_ratio:.0f}%\n\n"

        if cash_ratio >= 80:
            msg += "🛡️ 대부분 현금 보유 중입니다. 안전한 상태입니다!"
        elif cash_ratio >= 50:
            msg += "⚖️ 적절한 현금 비중을 유지하고 있습니다."
        else:
            msg += "📈 투자 비중이 높습니다. 시장 변동에 유의해 주세요."

        return msg

    except Exception as e:
        return f"⚠️ 조회 에러: {e}"


def handle_balance():
    """💰 실시간 잔고"""
    try:
        trader = get_trader()
        result = trader.get_balance()
        if not result:
            return "⚠️ 잔고 조회에 실패했습니다."

        holdings, _ = result
        if not holdings:
            return "💰 *실시간 잔고*\n\n📭 보유 종목 없음. 현금 100% 상태입니다."

        active = [h for h in holdings if int(float(h.get('ovrs_cblc_qty', '0'))) > 0]
        total_eval = 0

        msg = f"💰 *실시간 잔고*\n\n"
        msg += f"📋 현재 *{len(active)}종목* 보유 중:\n"

        for h in active:
            sym = h.get('ovrs_pdno', '?')
            qty = int(float(h.get('ovrs_cblc_qty', '0')))
            cur = float(h.get('now_pric2', '0'))
            eval_amt = cur * qty
            total_eval += eval_amt

            msg += f"  • *{sym}*: {qty}주 × ${cur:.2f} = ${eval_amt:,.2f}\n"

        msg += f"\n📈 총 평가액: *${total_eval:,.2f}*"

        return msg

    except Exception as e:
        return f"⚠️ 조회 에러: {e}"


def handle_today_scan():
    """🔍 오늘자 스캔"""
    try:
        meta_path = "output_reports/metadata.json"
        if not os.path.exists(meta_path):
            return "🔍 *오늘자 스캔*\n\n❌ 아직 오늘 스캔이 실행되지 않았습니다."

        with open(meta_path, "r") as f:
            meta = json.load(f)

        scan_time = meta.get("timestamp", "N/A")

        msg = f"🔍 *오늘자 스캔 결과*\n\n"
        msg += f"📅 스캔 시각: {scan_time[:16]}\n\n"
        msg += f"`1단계` 체급   : {meta.get('total', 503)} → *{meta.get('step1', 0)}건*\n"
        msg += f"`2단계` 내실   : → *{meta.get('step2', 0)}건*\n"
        msg += f"`3단계` 에너지 : → *{meta.get('step3', 0)}건*\n"
        msg += f"`4단계` 성장   : → *{meta.get('step4', 0)}건*\n"
        msg += f"`5단계` 심리   : → *{meta.get('step5', 0)}건*\n"
        msg += f"`6단계` 기세   : → *{meta.get('step6', 0)}건*\n\n"

        step6 = meta.get('step6', 0)
        if step6 > 0:
            msg += f"🔥 최종 통과 종목 *{step6}개*! 리포트를 확인해 주세요."
        else:
            msg += "🛡️ 오늘은 기준 충족 종목이 없습니다. 현금 보유 권고!"

        return msg

    except Exception as e:
        return f"⚠️ 조회 에러: {e}"


def handle_emergency_sell():
    """🛑 긴급 전량 매도 — 1차 확인"""
    return (
        "🛑 *긴급 전량 매도 확인*\n\n"
        "⚠️ 모든 보유 종목을 *즉시 매도*합니다.\n"
        "이 작업은 *되돌릴 수 없습니다.*\n\n"
        "정말 실행하시겠습니까?\n"
        "→ \"전량매도\" 라고 입력해 주세요."
    )


def execute_emergency_sell():
    """🛑 긴급 전량 매도 — 실행"""
    try:
        trader = get_trader()
        result = trader.get_balance()
        if not result:
            return "⚠️ 잔고 조회 실패. 매도를 중단합니다."

        holdings, _ = result
        active = [h for h in holdings if int(float(h.get('ovrs_cblc_qty', '0'))) > 0]

        if not active:
            return "📭 보유 종목이 없습니다. 이미 현금 100% 상태입니다."

        msg = "🛑 *[긴급 전량 매도 실행]*\n\n"
        for h in active:
            sym = h.get('ovrs_pdno', '?')
            qty = int(float(h.get('ovrs_cblc_qty', '0')))
            cur = float(h.get('now_pric2', '0'))
            sell_price = round(cur * 0.995, 2)

            success = trader.sell_order(symbol=sym, quantity=qty, price=sell_price, exchange="NASD")
            status = "✅ 완료" if success else "❌ 실패"
            msg += f"  {status} *{sym}* {qty}주 × ${sell_price}\n"
            time.sleep(0.5)

        msg += "\n🛡️ 긴급 매도 처리가 완료되었습니다, 대표님."
        return msg

    except Exception as e:
        return f"⚠️ 매도 에러: {e}"


# ═══════════════════════════════════════════════════════
# 메인: 메시지/콜백 처리
# ═══════════════════════════════════════════════════════
CALLBACK_HANDLERS = {
    "total_return": handle_total_return,
    "stock_return": handle_stock_return,
    "deposit": handle_deposit,
    "balance": handle_balance,
    "today_scan": handle_today_scan,
    "emergency_sell": handle_emergency_sell,
}


def process_updates():
    """새 메시지/콜백을 확인하고 처리합니다."""
    offset = load_offset()
    updates = get_updates(offset)

    if not updates:
        print("📭 새 메시지 없음.")
        return

    for update in updates:
        update_id = update["update_id"]

        # 콜백 쿼리 (버튼 클릭)
        if "callback_query" in update:
            cb = update["callback_query"]
            cb_id = cb["id"]
            data = cb.get("data", "")
            from_id = str(cb.get("from", {}).get("id", ""))

            # 본인 확인
            if from_id != str(CHAT_ID):
                answer_callback(cb_id, "권한이 없습니다.")
                save_offset(update_id + 1)
                continue

            print(f"🔘 버튼 클릭: {data}")
            answer_callback(cb_id, "처리 중...")

            handler = CALLBACK_HANDLERS.get(data)
            if handler:
                response = handler()
                send_message(response, reply_markup=MENU_KEYBOARD)
            else:
                send_message("⚠️ 알 수 없는 명령입니다.")

        # 텍스트 메시지
        elif "message" in update:
            msg = update["message"]
            text = msg.get("text", "").strip()
            from_id = str(msg.get("from", {}).get("id", ""))

            if from_id != str(CHAT_ID):
                save_offset(update_id + 1)
                continue

            if text.lower() in ["/menu", "/start", "메뉴"]:
                print(f"📋 메뉴 요청")
                send_menu()
            elif text == "전량매도":
                print(f"🛑 긴급 전량 매도 실행!")
                response = execute_emergency_sell()
                send_message(response, reply_markup=MENU_KEYBOARD)

        save_offset(update_id + 1)


if __name__ == "__main__":
    print("=" * 50)
    print(f"🤖 알파 텔레그램 메뉴 봇 ({datetime.now().strftime('%H:%M')})")
    print("=" * 50)
    process_updates()
