"""
Alpha Guardian — 장중 포트폴리오 실시간 감시 (10분 간격)

매도 트리거:
  ① 트레일링 스탑: 최근 고점 대비 -10% → 즉시 매도
  ② 50MA 이탈: 현재가 < 50일 이동평균 → 즉시 매도

데이터 소스: Finnhub (무제한) + Yahoo 백업
매매 실행: Cloudflare Worker → KIS API
알림: 텔레그램
"""

import os
import sys
import json
import time
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(__file__))

FINNHUB_KEY = os.getenv("FINNHUB_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
WORKER_URL = os.getenv("WORKER_URL")
WORKER_API_KEY = os.getenv("WORKER_API_KEY")

TRAILING_STOP_PCT = -10  # -10%


# ============================================================
# 텔레그램 알림
# ============================================================
def send_alert(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"⚠️ 텔레그램 미설정. 메시지: {message}")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        r = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown",
        }, timeout=10)
        if r.status_code == 200:
            print("📱 텔레그램 알림 전송 완료")
        else:
            print(f"⚠️ 텔레그램 에러: {r.status_code}")
    except Exception as e:
        print(f"⚠️ 텔레그램 에러: {e}")


# ============================================================
# 보유종목 조회 (Worker → KIS)
# ============================================================
def get_holdings():
    if not WORKER_URL or not WORKER_API_KEY:
        print("⚠️ Worker URL/API Key 미설정")
        return []

    try:
        r = requests.get(
            f"{WORKER_URL}/api/portfolio",
            headers={"X-API-Key": WORKER_API_KEY},
            timeout=15,
        )
        if r.status_code == 200:
            data = r.json()
            holdings = data.get("holdings", data.get("output1", []))
            result = []
            for h in holdings:
                sym = h.get("ovrs_pdno", h.get("symbol", "")).strip()
                qty = int(float(h.get("ovrs_cblc_qty", h.get("qty", "0"))))
                if sym and qty > 0:
                    result.append({
                        "symbol": sym,
                        "qty": qty,
                        "buy_avg": float(h.get("pchs_avg_pric", h.get("buy_avg", "0"))),
                        "current": float(h.get("now_pric2", h.get("current", "0"))),
                        "pnl_rate": float(h.get("evlu_pfls_rt", h.get("pnl_rate", "0"))),
                    })
            return result
        else:
            print(f"⚠️ 포트폴리오 조회 실패: HTTP {r.status_code}")
    except Exception as e:
        print(f"⚠️ 포트폴리오 조회 에러: {e}")
    return []


# ============================================================
# Finnhub 현재가 조회
# ============================================================
def get_current_price(symbol):
    if not FINNHUB_KEY:
        return None
    try:
        url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_KEY}"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            price = data.get("c", 0)  # current price
            if price and price > 0:
                return price
    except Exception as e:
        print(f"⚠️ {symbol} 시세 조회 에러: {e}")
    return None


# ============================================================
# 50MA + 최근 고점 계산 (Finnhub /candle)
# ============================================================
def get_ma50_and_peak(symbol):
    """50MA와 최근 50일 최고가를 동시에 계산 — Yahoo 1차"""

    # 1차: Yahoo Finance (빠르고 안정적)
    try:
        import yfinance as yf
        t = yf.Ticker(symbol)
        hist = t.history(period="3mo")
        if len(hist) >= 50:
            closes = hist["Close"].tolist()
            ma50 = sum(closes[-50:]) / 50
            peak = max(closes[-50:])
            return round(ma50, 2), round(peak, 2)
    except Exception as e:
        print(f"    ⚠️ {symbol} Yahoo 캔들 에러: {e}")

    # 2차: Finnhub 백업
    if FINNHUB_KEY:
        try:
            now = int(time.time())
            days_80 = now - (80 * 24 * 60 * 60)
            url = f"https://finnhub.io/api/v1/stock/candle?symbol={symbol}&resolution=D&from={days_80}&to={now}&token={FINNHUB_KEY}"
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                data = r.json()
                if data.get("s") == "ok":
                    closes = data.get("c", [])
                    if len(closes) >= 50:
                        ma50 = sum(closes[-50:]) / 50
                        peak = max(closes[-50:])
                        return round(ma50, 2), round(peak, 2)
        except Exception as e:
            print(f"    ⚠️ {symbol} Finnhub 캔들 에러: {e}")

    return None, None


# ============================================================
# 매도 실행 (Worker → KIS)
# ============================================================
def execute_sell(symbol, qty, reason):
    """Worker를 통해 즉시 매도 실행"""
    if not WORKER_URL or not WORKER_API_KEY:
        print(f"⚠️ Worker 미설정. 매도 불가: {symbol}")
        return False

    try:
        r = requests.post(
            f"{WORKER_URL}/api/sell",
            headers={
                "X-API-Key": WORKER_API_KEY,
                "Content-Type": "application/json",
            },
            json={
                "symbol": symbol,
                "qty": qty,
                "order_type": "market",
                "reason": reason,
            },
            timeout=15,
        )
        if r.status_code == 200:
            print(f"✅ {symbol} 매도 주문 성공 ({qty}주)")
            return True
        else:
            print(f"⚠️ {symbol} 매도 주문 실패: HTTP {r.status_code}")
            body = r.text[:200]
            print(f"   응답: {body}")
    except Exception as e:
        print(f"⚠️ {symbol} 매도 에러: {e}")
    return False


# ============================================================
# 메인 감시 로직
# ============================================================
def run_guardian():
    print(f"🛡️ [Alpha Guardian] 포트폴리오 감시 시작")
    print(f"   시간: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"   기준: 트레일링 스탑 {TRAILING_STOP_PCT}% | 50MA 이탈")

    # 1. 보유종목 조회
    holdings = get_holdings()
    if not holdings:
        print("📭 보유종목 없음. 감시 종료.")
        return

    print(f"   보유: {len(holdings)}종목 — {', '.join(h['symbol'] for h in holdings)}")

    alerts = []
    sells = []

    # 2. 각 종목 체크
    for h in holdings:
        sym = h["symbol"]
        qty = h["qty"]
        buy_avg = h["buy_avg"]

        # 현재가 조회
        current = get_current_price(sym)
        if current is None:
            print(f"    ⚠️ {sym} 시세 조회 실패 — 건너뜀")
            continue

        # 50MA + 최근 고점
        ma50, peak = get_ma50_and_peak(sym)
        if ma50 is None:
            print(f"    ⚠️ {sym} 50MA 계산 실패 — 건너뜀")
            continue

        print(f"    📊 {sym}: 현재가 ${current:.2f} | 50MA ${ma50:.2f} | 고점 ${peak:.2f} | 매입가 ${buy_avg:.2f}")

        # ── 체크 ① 트레일링 스탑: 최근 고점 대비 -10% ──
        if peak > 0:
            drop_from_peak = ((current - peak) / peak) * 100
            if drop_from_peak <= TRAILING_STOP_PCT:
                reason = f"🔴 트레일링 스탑: 고점 ${peak:.2f} 대비 {drop_from_peak:.1f}% 하락"
                print(f"    {reason}")
                alerts.append({"symbol": sym, "reason": reason, "qty": qty, "current": current})
                sells.append({"symbol": sym, "qty": qty, "reason": reason})
                continue  # 이미 매도 트리거 → 50MA 체크 불필요

        # ── 체크 ② 50MA 이탈 ──
        if current < ma50:
            reason = f"🔴 50MA 이탈: 현재가 ${current:.2f} < 50MA ${ma50:.2f}"
            print(f"    {reason}")
            alerts.append({"symbol": sym, "reason": reason, "qty": qty, "current": current})
            sells.append({"symbol": sym, "qty": qty, "reason": reason})
            continue

        print(f"    ✅ {sym} 정상 (50MA 위, 스탑 미도달)")
        time.sleep(1.5)  # Finnhub 분당 60콜 준수

    # 3. 매도 실행 + 알림
    if sells:
        alert_msg = f"🚨 *알파 가디언 긴급 매도 알림*\n\n"
        alert_msg += f"⏰ {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n\n"

        for s in sells:
            sym = s["symbol"]
            qty = s["qty"]
            reason = s["reason"]

            alert_msg += f"*{sym}* ({qty}주)\n{reason}\n"

            # 즉시 매도 실행
            success = execute_sell(sym, qty, reason)
            if success:
                alert_msg += f"→ ✅ 매도 주문 완료\n\n"
            else:
                alert_msg += f"→ ⚠️ 매도 주문 실패 (수동 확인 필요)\n\n"

        alert_msg += f"_Alpha Guardian V1 — 10분 감시_"
        send_alert(alert_msg)
    else:
        print(f"\n✅ 전 종목 정상. 다음 체크까지 대기.")


if __name__ == "__main__":
    # 장 시간 체크 (DST 자동 반영) — 장 외 시간이면 즉시 종료
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo

    now_et = datetime.now(ZoneInfo("America/New_York"))
    hour_min = now_et.hour * 60 + now_et.minute

    if now_et.weekday() >= 5 or hour_min < 570 or hour_min > 960:
        # 주말 또는 장 시간 외 (9:30 ET 이전 또는 16:00 ET 이후)
        print(f"📅 장 외 시간 ({now_et.strftime('%H:%M ET')}). 감시 불필요.")
        exit(0)

    run_guardian()
