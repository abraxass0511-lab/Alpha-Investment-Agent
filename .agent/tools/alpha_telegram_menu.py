"""
alpha_telegram_menu.py — 에이전트 알파 텔레그램 메뉴 봇

대표님이 텔레그램에서 버튼을 누르면 실시간으로 응답합니다.

메뉴:
  📊 전체 수익률 — 총 자산 및 누적 수익률
  📈 종목별 수익률 — 보유 종목 개별 수익률
  💵 예수금 현황 — 매수 가능 금액
  💰 실시간 잔고 — 보유 종목 수량 및 평가금액
  🔍 오늘자 스캔 — 5단계 필터 결과 요약
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


def ensure_no_webhook():
    """Webhook이 설정되어 있으면 제거 (getUpdates와 충돌 방지)"""
    try:
        r = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getWebhookInfo", timeout=5)
        wh = r.json().get("result", {})
        wh_url = wh.get("url", "")
        if wh_url:
            print(f"⚠️ Webhook 감지: {wh_url}")
            print("   → Webhook 제거 중... (getUpdates와 동시 사용 불가)")
            requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteWebhook", timeout=5)
            print("   ✅ Webhook 제거 완료")
        else:
            print("✅ Webhook 없음 — getUpdates 정상 사용")
    except Exception as e:
        print(f"⚠️ Webhook 확인 에러: {e}")


def get_updates():
    """Telegram getUpdates — offset 없이 최근 100건 조회 (시간 필터로 중복 방지)"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    params = {"timeout": 5, "allowed_updates": ["message", "callback_query"], "limit": 100}
    try:
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        print(f"📡 getUpdates 응답: ok={data.get('ok')} | result 개수={len(data.get('result', []))}")
        if not data.get('ok'):
            print(f"   ❌ 에러: {data.get('description', 'unknown')}")
        if r.status_code == 200:
            return data.get("result", [])
    except Exception as e:
        print(f"❌ getUpdates 에러: {e}")
    return []


# ═══════════════════════════════════════════════════════
# 리플라이 키보드 (상시 하단 고정)
# ═══════════════════════════════════════════════════════
REPLY_KEYBOARD = {
    "keyboard": [
        ["📊 전체 수익률", "📈 종목별 수익률"],
        ["💵 예수금 현황", "💰 실시간 잔고"],
        ["🔍 오늘자 스캔", "🛑 긴급 전량 매도"],
    ],
    "resize_keyboard": True,
    "is_persistent": True,
}


def send_menu():
    send_message(
        "🤖 *알파 에이전트 메뉴*\n\n하단 버튼을 눌러주세요, 대표님!",
        reply_markup=REPLY_KEYBOARD,
    )


# ═══════════════════════════════════════════════════════
# 각 버튼 핸들러
# ═══════════════════════════════════════════════════════
def get_trader():
    from alpha_trader import AlphaTrader
    return AlphaTrader()


def handle_total_return():
    """📊 전체 수익률 — Worker 경유 (24시간 가동) → KIS 직접 폴백"""
    # 1차: Worker 경유 (장 외 시간에도 동작)
    try:
        worker_url = os.getenv("WORKER_URL", "")
        worker_key = os.getenv("WORKER_API_KEY", "alpha-internal")
        if worker_url:
            r = requests.get(
                f"{worker_url}/api/portfolio",
                headers={"Authorization": f"Bearer {worker_key}"},
                timeout=15,
            )
            if r.status_code == 200:
                data = r.json()
                # ★ Worker가 KIS 실패를 감지한 경우 → KIS 직접 폴백
                if data.get("api_error"):
                    print(f"⚠️ Worker KIS 에러: {data.get('error_detail')} → KIS 직접 폴백")
                    raise Exception("Worker KIS API error")
                holdings = data.get("holdings", [])
                usd_amt = data.get("buying_power", "0")

                if not holdings:
                    return f"📊 *전체 수익률*\n\n📭 현재 보유 종목이 없습니다.\n💰 예수금: *${usd_amt}*\n\n현금 100% 상태입니다, 대표님! 🛡️"

                total_invested = 0
                total_eval = 0
                total_pnl = 0

                for h in holdings:
                    qty = h.get("qty", 0)
                    buy_avg = h.get("buy_avg", 0)
                    cur = h.get("current", 0)
                    pnl = h.get("pnl_amt", 0)
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
                msg += f"📋 보유 종목: {len([h for h in holdings if h.get('qty', 0) > 0])}개\n"
                msg += f"💵 예수금: *${usd_amt}*"
                return msg
    except Exception as e:
        print(f"⚠️ Worker 전체수익률 조회 에러: {e}, KIS 직접 조회 시도")

    # 2차: KIS 직접 호출 (폴백)
    try:
        trader = get_trader()
        result = trader.get_balance()
        if not result:
            return "⚠️ 잔고 조회에 실패했습니다.\nKIS 모의투자 서버가 점검 중이거나 미국 장 외 시간일 수 있습니다."

        holdings, _ = result
        if not holdings:
            buying = trader.get_buying_power(symbol="AAPL", price="0")
            usd = buying.get("ord_psbl_frcr_amt", "N/A") if buying else "조회실패"
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
    """📈 종목별 수익률 — Worker 경유 → KIS 폴백"""
    # 1차: Worker 경유
    try:
        worker_url = os.getenv("WORKER_URL", "")
        worker_key = os.getenv("WORKER_API_KEY", "alpha-internal")
        if worker_url:
            r = requests.get(
                f"{worker_url}/api/portfolio",
                headers={"Authorization": f"Bearer {worker_key}"},
                timeout=15,
            )
            if r.status_code == 200:
                data = r.json()
                if data.get("api_error"):
                    print(f"⚠️ Worker KIS 에러 → KIS 직접 폴백")
                    raise Exception("Worker KIS API error")
                holdings = data.get("holdings", [])
                if not holdings:
                    return "📈 *종목별 수익률*\n\n📭 보유 종목이 없습니다, 대표님."

                msg = "📈 *종목별 수익률*\n\n"
                active = [h for h in holdings if h.get("qty", 0) > 0]
                for h in active:
                    sym = h.get("symbol", "?")
                    qty = h.get("qty", 0)
                    buy_avg = h.get("buy_avg", 0)
                    cur = h.get("current", 0)
                    pnl = h.get("pnl_amt", 0)
                    pnl_rt = h.get("pnl_rate", 0)

                    emoji = "🟢" if pnl >= 0 else "🔴"
                    msg += f"{emoji} *{sym}* ({pnl_rt:+.1f}%)\n"
                    msg += f"   {qty}주 | 매입 ${buy_avg:.2f} → 현재 ${cur:.2f}\n"
                    msg += f"   손익: {pnl:+,.2f}\n\n"

                if active:
                    best = max(active, key=lambda h: h.get("pnl_rate", 0))
                    msg += f"🏆 효자 종목: *{best.get('symbol', '?')}*"
                return msg
    except Exception as e:
        print(f"⚠️ Worker 종목별수익률 조회 에러: {e}, KIS 폴백")

    # 2차: KIS 직접
    try:
        trader = get_trader()
        result = trader.get_balance()
        if not result:
            return "⚠️ 잔고 조회에 실패했습니다."

        holdings, _ = result
        if not holdings:
            return "📈 *종목별 수익률*\n\n📭 보유 종목이 없습니다, 대표님."

        msg = "📈 *종목별 수익률*\n\n"
        active = [h for h in holdings if int(float(h.get('ovrs_cblc_qty', '0'))) > 0]
        for h in active:
            sym = h.get('ovrs_pdno', '?')
            qty = int(float(h.get('ovrs_cblc_qty', '0')))
            buy_avg = float(h.get('pchs_avg_pric', '0'))
            cur = float(h.get('now_pric2', '0'))
            pnl_rt = float(h.get('evlu_pfls_rt', '0'))
            pnl = float(h.get('frcr_evlu_pfls_amt', '0'))

            emoji = "🟢" if pnl >= 0 else "🔴"
            msg += f"{emoji} *{sym}* ({pnl_rt:+.1f}%)\n"
            msg += f"   {qty}주 | 매입 ${buy_avg:.2f} → 현재 ${cur:.2f}\n"
            msg += f"   손익: {pnl:+,.2f}\n\n"

        if active:
            best = max(active, key=lambda h: float(h.get('evlu_pfls_rt', '0')))
            msg += f"🏆 효자 종목: *{best.get('ovrs_pdno', '?')}*"

        return msg

    except Exception as e:
        return f"⚠️ 조회 에러: {e}"


def handle_deposit():
    """💵 예수금 현황 — Worker 경유 → KIS 폴백"""
    # 1차: Worker 경유
    try:
        worker_url = os.getenv("WORKER_URL", "")
        worker_key = os.getenv("WORKER_API_KEY", "alpha-internal")
        if worker_url:
            r = requests.get(
                f"{worker_url}/api/portfolio",
                headers={"Authorization": f"Bearer {worker_key}"},
                timeout=15,
            )
            if r.status_code == 200:
                data = r.json()
                if data.get("api_error"):
                    print(f"⚠️ Worker KIS 에러 → KIS 직접 폴백")
                    raise Exception("Worker KIS API error")
                usd_amt = data.get("buying_power", "0")
                holdings = data.get("holdings", [])

                total_eval = sum(h.get("current", 0) * h.get("qty", 0) for h in holdings if h.get("qty", 0) > 0)
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
        print(f"⚠️ Worker 예수금 조회 에러: {e}, KIS 폴백")

    # 2차: KIS 직접
    try:
        trader = get_trader()
        buying = trader.get_buying_power(symbol="AAPL", price="0")

        if not buying:
            return "⚠️ 예수금 조회에 실패했습니다.\nKIS 모의투자 서버 점검 또는 장 외 시간일 수 있습니다."

        usd_amt = buying.get("ord_psbl_frcr_amt", "0")

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
    """💰 실시간 잔고 — Worker 경유 → KIS 폴백"""
    # 1차: Worker 경유
    try:
        worker_url = os.getenv("WORKER_URL", "")
        worker_key = os.getenv("WORKER_API_KEY", "alpha-internal")
        if worker_url:
            r = requests.get(
                f"{worker_url}/api/portfolio",
                headers={"Authorization": f"Bearer {worker_key}"},
                timeout=15,
            )
            if r.status_code == 200:
                data = r.json()
                if data.get("api_error"):
                    print(f"⚠️ Worker KIS 에러 → KIS 직접 폴백")
                    raise Exception("Worker KIS API error")
                holdings = data.get("holdings", [])
                usd_amt = data.get("buying_power", "0")

                if not holdings:
                    return f"💰 *실시간 잔고*\n\n📭 보유 종목 없음. 현금 100% 상태입니다.\n💵 예수금: *${usd_amt}*"

                active = [h for h in holdings if h.get("qty", 0) > 0]
                total_eval = 0

                msg = f"💰 *실시간 잔고*\n\n"
                msg += f"📋 현재 *{len(active)}종목* 보유 중:\n"

                for h in active:
                    sym = h.get("symbol", "?")
                    qty = h.get("qty", 0)
                    cur = h.get("current", 0)
                    eval_amt = cur * qty
                    total_eval += eval_amt
                    msg += f"  • *{sym}*: {qty}주 × ${cur:.2f} = ${eval_amt:,.2f}\n"

                msg += f"\n📈 총 평가액: *${total_eval:,.2f}*"
                msg += f"\n💵 예수금: *${usd_amt}*"
                return msg
    except Exception as e:
        print(f"⚠️ Worker 잔고 조회 에러: {e}, KIS 폴백")

    # 2차: KIS 직접
    try:
        trader = get_trader()
        result = trader.get_balance()
        if not result:
            return "⚠️ 잔고 조회에 실패했습니다.\nKIS 모의투자 서버 점검 또는 장 외 시간일 수 있습니다."

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
    """🔍 오늘자 스캔 — 최신 결과를 repo에서 가져온 후 표시"""
    try:
        # ★ 최신 스캔 결과 pull (daily 워크플로우가 커밋한 데이터)
        import subprocess
        try:
            subprocess.run(
                ["git", "pull", "--rebase", "--quiet"],
                timeout=15, capture_output=True
            )
        except Exception:
            pass  # pull 실패해도 기존 파일로 진행

        meta_path = "output_reports/metadata.json"
        if not os.path.exists(meta_path):
            return "🔍 *오늘자 스캔*\n\n❌ 아직 오늘 스캔이 실행되지 않았습니다."

        with open(meta_path, "r") as f:
            meta = json.load(f)

        scan_time = meta.get("timestamp", "N/A")

        # step12: 1+2단계 합산 (Finnhub 최적화로 통합 조회)
        step12 = meta.get('step12', meta.get('step1', 0))

        msg = f"🔍 *오늘자 스캔 결과*\n\n"
        msg += f"📅 스캔 시각: {scan_time[:16]}\n\n"
        msg += f"`1+2단계` 체급+내실 : {meta.get('total', 503)} → *{step12}건*\n"
        msg += f"`3단계` 에너지 : → *{meta.get('step3', 0)}건*\n"
        msg += f"`4단계` 성장   : → *{meta.get('step4', 0)}건*\n"
        msg += f"`5단계` 모멘텀 Elite 5 : → *{meta.get('step5', 0)}건*\n\n"

        step5 = meta.get('step5', 0)
        if step5 > 0:
            msg += f"🔥 최종 통과 종목 *{step5}개*! 리포트를 확인해 주세요."
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
# 승인/예약 관련 헬퍼 함수
# ═══════════════════════════════════════════════════════
PENDING_FILE = "output_reports/pending_approval.json"

def _is_market_open():
    """미국 장 개장 여부 (US/Eastern 9:30~16:00, 월~금)"""
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo
    now_et = datetime.now(ZoneInfo("America/New_York"))
    if now_et.weekday() >= 5:
        return False
    hour_min = now_et.hour * 60 + now_et.minute
    return 570 <= hour_min <= 960  # 9:30~16:00

def _load_buy_symbols():
    """final_picks_latest.csv에서 매수 종목 심볼 로드 (5단계 파이프라인 기준)"""
    # ★ 최신 결과 pull (daily 워크플로우가 커밋한 데이터)
    import subprocess
    try:
        subprocess.run(
            ["git", "pull", "--rebase", "--quiet"],
            timeout=15, capture_output=True
        )
    except Exception:
        pass

    import csv as csv_mod
    picks_path = "output_reports/final_picks_latest.csv"
    if not os.path.exists(picks_path):
        return []
    try:
        with open(picks_path, "r") as f:
            reader = csv_mod.DictReader(f)
            # V6: Sentiment 필터 제거 → Status=BUY인 종목만 (5단계 모멘텀 기준)
            symbols = []
            for row in reader:
                status = row.get("Status", "")
                if "BUY" in status:
                    symbols.append(row["Symbol"])
            return symbols
    except:
        return []

def _save_pending_approval(symbols):
    """예약 매수 저장"""
    os.makedirs("output_reports", exist_ok=True)
    with open(PENDING_FILE, "w") as f:
        json.dump({
            "approved": True,
            "symbols": symbols,
            "approved_at": datetime.now().isoformat(),
        }, f)
    print(f"📋 예약 저장: {symbols}")

def _clear_pending_approval():
    """예약 취소"""
    if os.path.exists(PENDING_FILE):
        os.remove(PENDING_FILE)
        print("🛑 예약 취소됨")

def _execute_buy_via_worker(symbols):
    """Worker 경유 KIS 매수 실행"""
    try:
        worker_url = os.getenv("WORKER_URL", "")
        worker_key = os.getenv("WORKER_API_KEY", "alpha-internal")
        if worker_url and symbols:
            r = requests.post(
                f"{worker_url}/api/buy",
                headers={"Authorization": f"Bearer {worker_key}"},
                json={"symbols": symbols, "approved": True},
                timeout=30
            )
            print(f"   Worker 매수 요청: {r.status_code}")
    except Exception as e:
        print(f"   ⚠️ Worker 매수 요청 에러: {e}")

def check_pending_approval():
    """예약 매수 확인 → 장 개장 시 자동 집행"""
    if not os.path.exists(PENDING_FILE):
        return
    if not _is_market_open():
        return
    
    with open(PENDING_FILE, "r") as f:
        pending = json.load(f)
    
    symbols = pending.get("symbols", [])
    approved_at = pending.get("approved_at", "")
    
    if symbols:
        print(f"⚔️ 예약 매수 집행! 종목: {symbols} (승인: {approved_at})")
        send_message(
            f"⚔️ *[알파 예약 매수 집행]*\n"
            f"대표님 승인({approved_at[:16]}) 기반 자동 집행!\n\n"
            f"🔖 종목: *{', '.join(symbols)}*\n"
            f"⏳ KIS API 매수 중...",
            reply_markup=REPLY_KEYBOARD
        )
        _execute_buy_via_worker(symbols)
        _clear_pending_approval()


# ═══════════════════════════════════════════════════════
# 텍스트 메시지 → 핸들러 매핑 (리플라이 키보드용)
# ═══════════════════════════════════════════════════════
TEXT_HANDLERS = {
    "📊 전체 수익률": handle_total_return,
    "📈 종목별 수익률": handle_stock_return,
    "💵 예수금 현황": handle_deposit,
    "💰 실시간 잔고": handle_balance,
    "🔍 오늘자 스캔": handle_today_scan,
    "🛑 긴급 전량 매도": handle_emergency_sell,
}


def process_updates():
    """새 메시지를 확인하고 처리합니다. (시간 기반 필터 — offset 불필요)"""
    updates = get_updates()

    if not updates:
        print("📭 새 메시지 없음.")
        return

    # 현재 시간 기준 10분 이내 메시지만 처리 (5분 간격 + 5분 버퍼)
    now = time.time()
    cutoff = now - 600  # 10분 = 600초

    processed = 0
    for update in updates:
        update_id = update["update_id"]

        # 텍스트 메시지 (리플라이 키보드 버튼 클릭 시)
        if "message" in update:
            msg = update["message"]
            msg_time = msg.get("date", 0)

            # 5분 이전 메시지는 건너뛰기 (중복 처리 방지)
            if msg_time < cutoff:
                continue

            text = msg.get("text", "").strip()
            from_id = str(msg.get("from", {}).get("id", ""))

            # 본인 확인
            if from_id != str(CHAT_ID):
                continue

            processed += 1

            # 메뉴 / 시작
            if text.lower() in ["/menu", "/start", "메뉴"]:
                print(f"📋 메뉴 요청")
                send_menu()

            # 긴급 전량 매도 확인
            elif text == "전량매도":
                print(f"🛑 긴급 전량 매도 실행!")
                response = execute_emergency_sell()
                send_message(response, reply_markup=REPLY_KEYBOARD)

            # 리플라이 키보드 버튼 매칭
            elif text in TEXT_HANDLERS:
                print(f"🔘 버튼: {text}")
                handler = TEXT_HANDLERS[text]
                response = handler()
                send_message(response, reply_markup=REPLY_KEYBOARD)

            # 승인/반려 (장 상태에 따라 즉시 집행 or 예약)
            elif text in ["승인", "반려"]:
                print(f"✅ 승인/반려 입력: {text}")
                if text == "승인":
                    # 장 상태 확인
                    market_open = _is_market_open()
                    
                    # 매수 종목 목록 로드
                    symbols = _load_buy_symbols()
                    if not symbols:
                        send_message(
                            "⚠️ *매수 대상 종목이 없습니다.*\n"
                            "스캔 결과를 먼저 확인해 주세요.",
                            reply_markup=REPLY_KEYBOARD
                        )
                    elif market_open:
                        # 장 개장 중 → 즉시 집행
                        send_message(
                            "⚔️ *[알파 즉시 집행]*\n"
                            f"대표님 승인 확인! *{', '.join(symbols)}* 매수를 진행합니다.\n\n"
                            "⏳ Worker 경유 KIS API 집행 중...\n"
                            "완료 시 결과를 보고드리겠습니다.",
                            reply_markup=REPLY_KEYBOARD
                        )
                        _execute_buy_via_worker(symbols)
                    else:
                        # 장 폐장 → 예약 저장
                        _save_pending_approval(symbols)
                        send_message(
                            "📋 *[알파 매수 예약 완료]*\n"
                            f"대표님 승인 접수! 다음 장 개장 시 자동 집행합니다.\n\n"
                            f"🔖 예약 종목: *{', '.join(symbols)}*\n"
                            f"⏰ 미국 장 개장: 한국시간 23:30 (월~금)\n\n"
                            "취소하시려면 \"반려\"를 입력해 주세요.",
                            reply_markup=REPLY_KEYBOARD
                        )
                else:
                    # 반려 → 예약도 취소
                    _clear_pending_approval()
                    send_message(
                        "🛑 *[반려 확인]*\n"
                        "매수를 취소합니다. 예약이 있었다면 함께 취소됩니다.\n"
                        "현재 포트폴리오를 유지합니다.",
                        reply_markup=REPLY_KEYBOARD
                    )

            # 그 외 모든 질문 → AI 대화 엔진
            else:
                print(f"🧠 AI 질문: {text}")
                try:
                    from alpha_ai_chat import ask_gemini
                    response = ask_gemini(text)
                    send_message(response, reply_markup=REPLY_KEYBOARD)
                except Exception as e:
                    print(f"⚠️ AI 에러: {e}")
                    send_message(f"⚠️ AI 답변 생성 에러: {e}", reply_markup=REPLY_KEYBOARD)

    # 처리된 메시지 확인(confirm) → 다음 실행 시 중복 방지
    if updates:
        last_id = updates[-1]["update_id"]
        # offset = last_id + 1로 다시 호출하여 Telegram 서버에서 확인 처리
        confirm_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
        try:
            requests.get(confirm_url, params={"offset": last_id + 1, "timeout": 1}, timeout=5)
            print(f"💾 Telegram 서버 offset 확인: {last_id + 1}")
        except:
            pass

    print(f"✅ 처리 완료: {processed}건 (전체 {len(updates)}건 중 최근 35분)")


if __name__ == "__main__":
    print("=" * 50)
    print(f"🤖 알파 텔레그램 메뉴 봇 ({datetime.now().strftime('%H:%M')})")
    print("=" * 50)
    
    # Webhook 충돌 확인 및 제거
    ensure_no_webhook()
    
    # 예약 매수 확인 (장 개장 시 자동 집행)
    check_pending_approval()
    
    process_updates()
