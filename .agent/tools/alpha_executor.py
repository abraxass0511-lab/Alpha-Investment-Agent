"""
alpha_executor.py — 에이전트 알파의 집행관

대표님의 텔레그램 "승인" 메시지를 수신하면,
최종 선정 종목(final_picks_latest.csv)을 KIS 모의투자 API로 자동 매수합니다.

실행 흐름:
  1. 텔레그램에서 최근 메시지 확인 → "승인" 수신 여부 판별
  2. final_picks_latest.csv에서 매수 대상 종목 로드
  3. 매수가능금액 조회 → 종목별 균등 분배
  4. KIS API로 지정가 매수 주문 실행
  5. 매수 결과를 텔레그램으로 보고
"""

import os
import json
import csv
import requests
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# 텔레그램 설정
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# ─────────────────────────────────────────────────────
# 텔레그램 유틸리티
# ─────────────────────────────────────────────────────
def send_telegram(text):
    """텔레그램 메시지를 전송합니다."""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("⚠️ 텔레그램 설정 누락")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"⚠️ 텔레그램 전송 에러: {e}")


def check_approval():
    """
    텔레그램에서 대표님의 "승인" 메시지를 확인합니다.
    최근 10개 메시지 중 "승인"이 포함된 메시지가 있으면 True.
    (1시간 이내의 메시지만 유효)
    """
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("⚠️ 텔레그램 설정 누락")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    params = {"offset": -10, "limit": 10}

    try:
        res = requests.get(url, params=params, timeout=10)
        data = res.json()

        if not data.get("ok"):
            print(f"❌ 텔레그램 API 에러: {data}")
            return False

        results = data.get("result", [])
        now = datetime.utcnow()

        for update in reversed(results):  # 최신 메시지부터
            msg = update.get("message", {})
            text = msg.get("text", "").strip()
            msg_date = datetime.utcfromtimestamp(msg.get("date", 0))
            sender_id = str(msg.get("chat", {}).get("id", ""))

            # 조건: 대표님(CHAT_ID)이 보낸 / 1시간 이내 / "승인" 포함
            if sender_id == CHAT_ID and (now - msg_date) < timedelta(hours=1):
                if "승인" in text:
                    print(f"✅ 대표님 승인 확인! (메시지: '{text}', 시각: {msg_date})")
                    return True

        print("⏳ 아직 대표님의 승인 메시지가 없습니다.")
        return False

    except Exception as e:
        print(f"🚨 텔레그램 확인 에러: {e}")
        return False


# ─────────────────────────────────────────────────────
# 매수 대상 종목 로드
# ─────────────────────────────────────────────────────
def load_buy_targets():
    """
    final_picks_latest.csv에서 매수 대상 종목을 읽어옵니다.
    Sentiment >= 0.7 필터가 이미 적용된 최종 리스트입니다.
    """
    picks_file = "output_reports/final_picks_latest.csv"

    if not os.path.exists(picks_file):
        print("❌ final_picks_latest.csv 파일이 없습니다.")
        return []

    targets = []
    try:
        with open(picks_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                symbol = row.get("Symbol", "").strip()
                if symbol:
                    targets.append({
                        "symbol": symbol,
                        "name": row.get("Name", symbol),
                        "price": row.get("Price", "0"),
                    })
    except Exception as e:
        print(f"🚨 CSV 읽기 에러: {e}")
        return []

    if not targets:
        print("📭 매수 대상 종목이 없습니다. (필터 통과 종목 0건)")
    else:
        print(f"📋 매수 대상: {len(targets)}개 종목 — {', '.join(t['symbol'] for t in targets)}")

    return targets


# ─────────────────────────────────────────────────────
# 자동 매수 실행
# ─────────────────────────────────────────────────────
def execute_buy_orders(targets):
    """
    KIS API를 통해 매수 주문을 실행합니다.
    - 총 매수가능금액의 90%를 종목 수로 균등 분배
    - 각 종목의 현재가 기준 지정가 매수
    """
    # AlphaTrader 임포트
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from alpha_trader import AlphaTrader

    trader = AlphaTrader()

    # 1. 매수가능금액 확인
    power = trader.get_buying_power(symbol=targets[0]["symbol"], price="0")
    if not power:
        send_telegram("🚨 *[알파 집행 실패]*\n매수가능금액 조회에 실패했습니다.")
        return []

    total_usd = float(power["ord_psbl_frcr_amt"])
    print(f"💰 총 USD 매수가능금액: ${total_usd:,.2f}")

    if total_usd < 100:
        send_telegram(f"🚨 *[알파 집행 중단]*\n매수가능금액 부족 (${total_usd:.2f})")
        return []

    # 2. 종목당 배분 금액 (총액의 90%를 균등 분배, 10%는 안전마진)
    budget_per_stock = (total_usd * 0.9) / len(targets)
    print(f"📊 종목당 배분: ${budget_per_stock:,.2f} ({len(targets)}종목)")

    # 3. 종목별 매수 실행
    results = []
    for t in targets:
        symbol = t["symbol"]
        name = t["name"]

        # 현재가 조회 (매수가능금액 API에서 가격 참조)
        price_check = trader.get_buying_power(symbol=symbol, price="0")
        if not price_check:
            results.append({"symbol": symbol, "status": "❌ 가격조회실패", "qty": 0, "price": 0})
            continue

        # 매수가능수량으로 역산하여 현재가 추정
        max_qty = int(price_check.get("max_ord_psbl_qty", "0"))
        avail_amt = float(price_check.get("ord_psbl_frcr_amt", "0"))

        if max_qty <= 0:
            results.append({"symbol": symbol, "status": "❌ 매수불가", "qty": 0, "price": 0})
            continue

        est_price = avail_amt / max_qty  # 추정 현재가
        qty = int(budget_per_stock / est_price)  # 배분 금액으로 살 수 있는 수량

        if qty <= 0:
            results.append({"symbol": symbol, "status": "❌ 수량부족", "qty": 0, "price": est_price})
            continue

        # 지정가 매수 (현재가에서 약간 높게 설정하여 체결 확보)
        order_price = round(est_price * 1.005, 2)  # +0.5% 마진
        print(f"  🎯 {symbol}: {qty}주 @ ${order_price} (배분: ${budget_per_stock:,.0f})")

        success = trader.buy_order(
            symbol=symbol,
            quantity=qty,
            price=order_price,
            exchange="NASD"
        )

        results.append({
            "symbol": symbol,
            "name": name,
            "status": "✅ 주문완료" if success else "❌ 주문실패",
            "qty": qty,
            "price": order_price,
        })

        time.sleep(0.5)  # API 호출 간격

    return results


# ─────────────────────────────────────────────────────
# 매수 결과 보고
# ─────────────────────────────────────────────────────
def report_execution(results):
    """매수 결과를 텔레그램으로 보고합니다."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    msg = f"🎯 *[알파 자동매수 집행 보고]*\n"
    msg += f"📅 {now}\n\n"

    total_invested = 0
    success_count = 0

    for r in results:
        symbol = r["symbol"]
        status = r["status"]
        qty = r["qty"]
        price = r["price"]
        name = r.get("name", symbol)

        if "✅" in status:
            success_count += 1
            invested = qty * price
            total_invested += invested
            msg += f"✅ *{name} ({symbol})*\n"
            msg += f"   {qty}주 × ${price:.2f} = *${invested:,.2f}*\n\n"
        else:
            msg += f"❌ *{symbol}* — {status}\n\n"

    msg += f"─────────────────\n"
    msg += f"📊 성공: {success_count}/{len(results)}건\n"
    msg += f"💵 총 투자금: *${total_invested:,.2f}*\n"
    msg += f"\n🛡️ _알파가 대표님의 자산을 지키겠습니다._"

    send_telegram(msg)
    print(f"\n📨 매수 결과 보고 완료 (성공: {success_count}/{len(results)})")


# ═══════════════════════════════════════════════════════
# 메인: 승인 확인 → 매수 집행 → 결과 보고
# ═══════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 55)
    print("⚔️  에이전트 알파 — 집행 모드")
    print("=" * 55)

    # 1단계: 텔레그램 승인 확인
    print("\n📡 [1] 텔레그램에서 대표님 승인 확인 중...")
    approved = check_approval()

    if not approved:
        print("\n🛡️ 승인 없음. 대기 모드를 유지합니다.")
        send_telegram("⏳ *[알파 대기]*\n승인 메시지가 확인되지 않았습니다.\n\"승인\" 이라고 답장해 주시면 자동 매수를 시작합니다.")
        exit(0)

    # 2단계: 매수 대상 종목 로드
    print("\n📋 [2] 매수 대상 종목 로드...")
    targets = load_buy_targets()

    if not targets:
        send_telegram("🛡️ *[알파 보고]*\n매수 대상 종목이 없습니다.\n정밀 필터링 기준 미달 — *전액 현금 보유를 권고*드립니다.")
        exit(0)

    # 3단계: 매수 집행
    print(f"\n⚔️ [3] {len(targets)}개 종목 매수 집행 시작...")
    send_telegram(f"⚔️ *[알파 집행 시작]*\n대표님 승인 확인 — {len(targets)}개 종목 매수를 시작합니다.")
    results = execute_buy_orders(targets)

    # 4단계: 결과 보고
    print("\n📨 [4] 매수 결과 보고...")
    report_execution(results)

    print("\n" + "=" * 55)
    print("🏁 집행 완료!")
