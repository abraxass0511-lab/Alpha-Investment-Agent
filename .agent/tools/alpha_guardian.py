"""
alpha_guardian.py — 에이전트 알파의 수호자

보유 종목을 감시하여 -10% 이상 하락 시 자동 매도 + 즉시 텔레그램 보고.
미국 장중(KST 23:30 ~ 06:00) 30분마다 자동 실행.

기능:
  1. 보유 종목 잔고 조회
  2. 각 종목의 현재가 vs 매입가 비교
  3. -10% 이상 하락 → 자동 매도 + 즉시 알림
  4. 체결 내역 확인 → 결과 보고
"""

import os
import sys
import time
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# 텔레그램 설정
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# 손절 기준
STOP_LOSS_THRESHOLD = -10.0  # -10%


def send_telegram(text):
    """텔레그램 메시지를 전송합니다."""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"⚠️ 텔레그램 전송 에러: {e}")


def run_guardian():
    """보유 종목을 감시하고 손절 조건 발생 시 자동 매도합니다."""

    # AlphaTrader 임포트
    sys.path.insert(0, os.path.dirname(__file__))
    from alpha_trader import AlphaTrader

    trader = AlphaTrader()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    print("=" * 55)
    print(f"🛡️ 알파 가디언 — 포트폴리오 감시 ({now})")
    print("=" * 55)

    # 1. 보유 종목 조회
    print("\n📊 [1] 보유 종목 조회 중...")
    result = trader.get_balance()
    if not result:
        print("❌ 잔고 조회 실패")
        return

    holdings, summary = result

    if not holdings:
        print("📭 보유 종목 없음 — 감시 대상 없이 종료합니다.")
        return

    print(f"📋 보유 종목: {len(holdings)}개")

    # 2. 각 종목의 손실률 확인
    stop_loss_targets = []
    portfolio_status = []

    for h in holdings:
        symbol = h.get('ovrs_pdno', '')
        qty = int(float(h.get('ovrs_cblc_qty', '0')))
        buy_avg = float(h.get('pchs_avg_pric', '0'))
        current = float(h.get('now_pric2', '0'))
        pnl_rate = float(h.get('evlu_pfls_rt', '0'))  # 평가손익률(%)

        if qty <= 0 or not symbol:
            continue

        status = {
            "symbol": symbol,
            "qty": qty,
            "buy_avg": buy_avg,
            "current": current,
            "pnl_rate": pnl_rate,
        }
        portfolio_status.append(status)

        print(f"  📈 {symbol}: {qty}주 | 매입: ${buy_avg:.2f} | 현재: ${current:.2f} | 손익: {pnl_rate:.1f}%")

        # -10% 이하 → 손절 대상
        if pnl_rate <= STOP_LOSS_THRESHOLD:
            stop_loss_targets.append(status)
            print(f"  🚨 ⚠️ {symbol} → {pnl_rate:.1f}% 하락! 손절 대상!")

    # 3. 손절 대상이 없으면 안전 보고
    if not stop_loss_targets:
        print(f"\n✅ 모든 종목 안전. 손절 대상 없음.")
        return

    # 4. 손절 매도 실행 + 즉시 텔레그램 알림
    print(f"\n🚨 [2] 손절 대상 {len(stop_loss_targets)}종목 매도 실행!")

    sell_results = []
    for target in stop_loss_targets:
        symbol = target["symbol"]
        qty = target["qty"]
        current_price = target["current"]

        # 즉시 매도 (현재가 약간 아래로 지정가 → 체결 확보)
        sell_price = round(current_price * 0.995, 2)  # -0.5% 마진
        print(f"  🔻 {symbol}: {qty}주 매도 @ ${sell_price}")

        success = trader.sell_order(
            symbol=symbol,
            quantity=qty,
            price=sell_price,
            exchange="NASD"
        )

        sell_results.append({
            "symbol": symbol,
            "qty": qty,
            "price": sell_price,
            "pnl_rate": target["pnl_rate"],
            "success": success,
        })

        time.sleep(0.5)

    # 5. 손절 결과 텔레그램 즉시 보고
    msg = f"🚨 *[알파 가디언 — 긴급 손절 매도]*\n"
    msg += f"📅 {now}\n\n"

    for r in sell_results:
        status = "✅ 매도완료" if r["success"] else "❌ 매도실패"
        msg += f"🔻 *{r['symbol']}* ({r['pnl_rate']:.1f}% 하락)\n"
        msg += f"   {r['qty']}주 × ${r['price']:.2f} — {status}\n\n"

    msg += f"─────────────────\n"
    msg += f"⚠️ *손절 기준: {STOP_LOSS_THRESHOLD}%*\n"
    msg += f"🛡️ _대표님의 자산을 보호하기 위한 자동 매도입니다._"

    send_telegram(msg)
    print(f"\n📨 손절 매도 결과 텔레그램 보고 완료!")

    # 6. 체결 확인
    print("\n📋 [3] 체결 내역 확인...")
    time.sleep(2)  # 체결 처리 대기
    orders = trader.get_order_status()
    if orders:
        filled = [o for o in orders if o.get('ccld_qty', '0') != '0']
        if filled:
            fill_msg = f"📋 *[체결 확인]*\n"
            for o in filled:
                sym = o.get('pdno', '?')
                fill_qty = o.get('ccld_qty', '0')
                fill_price = o.get('ccld_pric', '0')
                side = "매수" if o.get('sll_buy_dvsn_cd', '') == '02' else "매도"
                fill_msg += f"✅ {sym}: {side} {fill_qty}주 @ ${fill_price} 체결\n"
            send_telegram(fill_msg)


if __name__ == "__main__":
    run_guardian()
