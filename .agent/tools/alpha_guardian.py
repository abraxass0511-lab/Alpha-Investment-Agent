"""
alpha_guardian.py — 에이전트 알파의 수호자 (Trailing Stop)

보유 종목의 고점을 추적하고, 고점 대비 -10% 하락 시 자동 매도 + 즉시 텔레그램 보고.
미국 장중(KST 23:30 ~ 06:00) 30분마다 자동 실행.

매도 기준 ①: 트레일링 스탑 (Trailing Stop)
  - 매수 이후 기록한 최고가(Peak Price) 대비 -10% 하락 → 즉시 매도
  - 공식: Current Price ≤ Peak Price × 0.9
  - 주가가 오르면 고점도 따라 올라감 → 수익 보존
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

# 트레일링 스탑 비율
TRAILING_STOP_PCT = 0.10  # 고점 대비 10% 하락 시 매도

# 고점 기록 파일
PEAK_FILE = "output_reports/peak_prices.json"


def send_telegram(text):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"⚠️ 텔레그램 에러: {e}")


# ─────────────────────────────────────────────────────
# 고점 추적 관리
# ─────────────────────────────────────────────────────
def load_peak_prices():
    """저장된 고점 기록을 불러옵니다."""
    if os.path.exists(PEAK_FILE):
        try:
            with open(PEAK_FILE, "r") as f:
                return json.load(f)
        except:
            return {}
    return {}


def save_peak_prices(peaks):
    """고점 기록을 저장합니다."""
    os.makedirs(os.path.dirname(PEAK_FILE), exist_ok=True)
    with open(PEAK_FILE, "w") as f:
        json.dump(peaks, f, indent=2, ensure_ascii=False)


def update_peak(peaks, symbol, current_price, buy_price):
    """
    고점을 업데이트합니다.
    - 현재가가 기존 고점보다 높으면 → 고점 갱신
    - 처음 보는 종목이면 → 매입가를 초기 고점으로 설정
    """
    if symbol not in peaks:
        # 신규 종목: 매입가와 현재가 중 높은 값을 고점으로
        peaks[symbol] = {
            "peak": max(current_price, buy_price),
            "buy_price": buy_price,
            "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        print(f"  📌 {symbol}: 신규 추적 시작 (고점: ${peaks[symbol]['peak']:.2f})")
    elif current_price > peaks[symbol]["peak"]:
        old_peak = peaks[symbol]["peak"]
        peaks[symbol]["peak"] = current_price
        peaks[symbol]["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        print(f"  📈 {symbol}: 고점 갱신! ${old_peak:.2f} → ${current_price:.2f}")
    else:
        print(f"  📊 {symbol}: 고점 ${peaks[symbol]['peak']:.2f} 유지 (현재: ${current_price:.2f})")

    return peaks


# ─────────────────────────────────────────────────────
# 메인: 가디언 감시 로직
# ─────────────────────────────────────────────────────
def run_guardian():
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    print("=" * 55)
    print(f"🛡️ 알파 가디언 — 트레일링 스탑 감시 ({now})")
    print("=" * 55)

    worker_url = os.getenv("WORKER_URL", "")
    worker_key = os.getenv("WORKER_API_KEY", "alpha-internal")

    if not worker_url:
        print("❌ WORKER_URL 미설정")
        return

    # 1. 보유 종목 조회 (Worker 경유)
    print("\n📊 [1] 보유 종목 조회 (Worker 경유)...")
    try:
        r = requests.get(
            f"{worker_url}/api/portfolio",
            headers={"Authorization": f"Bearer {worker_key}"},
            timeout=15,
        )
        if r.status_code != 200:
            print(f"❌ 잔고 조회 실패 (HTTP {r.status_code})")
            return

        data = r.json()
        holdings = data.get("holdings", [])
    except Exception as e:
        print(f"❌ 잔고 조회 에러: {e}")
        return

    if not holdings:
        print("📭 보유 종목 없음 — 감시 종료.")
        return

    print(f"📋 보유 종목: {len(holdings)}개\n")

    # 2. 고점 기록 로드
    peaks = load_peak_prices()

    # 3. 각 종목 트레일링 스탑 체크
    stop_targets = []

    for h in holdings:
        symbol = h.get("symbol", "")
        qty = h.get("qty", 0)
        buy_avg = h.get("buy_avg", 0)
        current = h.get("current", 0)

        if qty <= 0 or not symbol:
            continue

        # 고점 업데이트
        peaks = update_peak(peaks, symbol, current, buy_avg)

        peak_price = peaks[symbol]["peak"]
        trailing_stop_price = peak_price * (1 - TRAILING_STOP_PCT)

        # 수익률 계산
        pnl_from_buy = ((current - buy_avg) / buy_avg) * 100 if buy_avg > 0 else 0
        pnl_from_peak = ((current - peak_price) / peak_price) * 100 if peak_price > 0 else 0

        print(f"  📍 {symbol}: 매입 ${buy_avg:.2f} | 고점 ${peak_price:.2f} | "
              f"현재 ${current:.2f} | 손절선 ${trailing_stop_price:.2f}")
        print(f"     매입 대비: {pnl_from_buy:+.1f}% | 고점 대비: {pnl_from_peak:+.1f}%")

        # 트레일링 스탑 발동 체크
        if current <= trailing_stop_price:
            print(f"  🚨🚨🚨 트레일링 스탑 발동! {symbol} 고점 대비 {pnl_from_peak:.1f}% 하락!")
            stop_targets.append({
                "symbol": symbol,
                "qty": qty,
                "buy_avg": buy_avg,
                "peak": peak_price,
                "current": current,
                "pnl_from_buy": pnl_from_buy,
                "pnl_from_peak": pnl_from_peak,
            })

    # 4. 고점 기록 저장
    save_peak_prices(peaks)
    print(f"\n💾 고점 기록 저장 완료 ({len(peaks)}종목)")

    # 5. 트레일링 스탑 발동 종목 매도 (Worker 경유)
    if not stop_targets:
        print("\n✅ 모든 종목 안전. 트레일링 스탑 발동 없음.")
        return

    print(f"\n🚨 [2] 트레일링 스탑 발동! {len(stop_targets)}종목 즉시 매도...")

    sell_results = []
    for t in stop_targets:
        symbol = t["symbol"]
        qty = t["qty"]
        current = t["current"]

        # 시장가에 가깝게 지정가 매도
        sell_price = round(current * 0.995, 2)
        print(f"  🔻 {symbol}: {qty}주 매도 @ ${sell_price}")

        try:
            r = requests.post(
                f"{worker_url}/api/sell",
                headers={
                    "Authorization": f"Bearer {worker_key}",
                    "Content-Type": "application/json",
                },
                json={"symbol": symbol, "qty": qty, "price": sell_price},
                timeout=15,
            )
            result = r.json()
            success = result.get("success", False)
        except Exception as e:
            print(f"  ⚠️ 매도 API 에러: {e}")
            success = False

        sell_results.append({**t, "success": success, "sell_price": sell_price})
        time.sleep(0.5)

    # 6. 즉시 텔레그램 보고
    msg = f"🚨 *[알파 트레일링 스탑 — 수익 확정 매도]*\n"
    msg += f"📅 {now}\n\n"

    for r in sell_results:
        status = "✅ 매도완료" if r["success"] else "❌ 매도실패"
        pnl_emoji = "🟢" if r["pnl_from_buy"] >= 0 else "🔴"

        if r["pnl_from_buy"] >= 0:
            msg += f"{pnl_emoji} *{r['symbol']}* — 수익 확정!\n"
            msg += f"   매입: ${r['buy_avg']:.2f} → 고점: ${r['peak']:.2f} → 매도: ${r['sell_price']:.2f}\n"
            msg += f"   수익률: *{r['pnl_from_buy']:+.1f}%* (고점 대비 {r['pnl_from_peak']:.1f}% 조정)\n"
            msg += f"   {status}\n\n"
        else:
            msg += f"{pnl_emoji} *{r['symbol']}* — 손절 매도\n"
            msg += f"   매입: ${r['buy_avg']:.2f} → 현재: ${r['sell_price']:.2f}\n"
            msg += f"   손실: *{r['pnl_from_buy']:.1f}%*\n"
            msg += f"   {status}\n\n"

    msg += f"─────────────────\n"
    msg += f"⚙️ 트레일링 스탑: 고점 대비 -{TRAILING_STOP_PCT*100:.0f}%\n"
    msg += f"🛡️ _대표님의 수익을 보존하기 위한 자동 매도입니다._"

    send_telegram(msg)
    print(f"\n📨 트레일링 스탑 매도 결과 보고 완료!")

    # 7. 매도된 종목은 고점 기록에서 제거
    for r in sell_results:
        if r["success"] and r["symbol"] in peaks:
            del peaks[r["symbol"]]
    save_peak_prices(peaks)


if __name__ == "__main__":
    run_guardian()
