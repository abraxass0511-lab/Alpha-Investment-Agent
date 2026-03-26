"""
alpha_rebalancer.py — 에이전트 알파의 리밸런서

매일 아침 스캔 후 실행하여 보유 종목의 적격 여부를 재검증합니다.
1~6단계 중 하나라도 부합하지 않는 종목 → 매도 추천 (승인 대기)
신규 매수 추천 종목 → 매수 추천 (승인 대기)

매도 기준:
  ② 1~6단계 중 하나라도 탈락 → 다음날 리포트에서 승인 요청
  (①번 트레일링 스탑은 alpha_guardian.py에서 장중 자동 처리)

출력: output_reports/rebalance_recommendations.json
"""

import os
import sys
import json
import csv
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()


def load_csv(filepath):
    """CSV 파일을 읽어 심볼 딕셔너리로 반환합니다."""
    data = {}
    if not os.path.exists(filepath):
        return data
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                sym = row.get("Symbol", "").strip()
                if sym:
                    data[sym] = row
    except:
        pass
    return data


def get_held_stocks():
    """KIS API로 현재 보유 종목을 조회합니다."""
    try:
        sys.path.insert(0, os.path.dirname(__file__))
        from alpha_trader import AlphaTrader

        trader = AlphaTrader()
        result = trader.get_balance()
        if not result:
            return []

        holdings, _ = result
        held = []
        for h in holdings:
            sym = h.get('ovrs_pdno', '').strip()
            qty = int(float(h.get('ovrs_cblc_qty', '0')))
            if sym and qty > 0:
                held.append({
                    "symbol": sym,
                    "qty": qty,
                    "buy_avg": float(h.get('pchs_avg_pric', '0')),
                    "current": float(h.get('now_pric2', '0')),
                    "pnl_rate": float(h.get('evlu_pfls_rt', '0')),
                    "pnl_amt": float(h.get('frcr_evlu_pfls_amt', '0')),
                })
        return held
    except Exception as e:
        print(f"🚨 보유 종목 조회 에러: {e}")
        return []


def check_held_against_scan(held_stocks, scan_data, picks_data):
    """
    보유 종목을 1~6단계 기준으로 재검증합니다.

    - daily_scan_latest.csv에 있음 = 1~4단계 통과
    - final_picks_latest.csv에 있음 = 5~6단계까지 통과
    - 없으면 → 탈락 (어떤 단계에서 탈락했는지 분석)
    """
    sell_recommendations = []

    for stock in held_stocks:
        sym = stock["symbol"]
        reasons = []

        if sym in scan_data:
            row = scan_data[sym]
            # 스캔에 있으면 1~4단계 통과, 5~6단계 체크
            market_cap = float(row.get("MarketCap", "0"))
            price = float(row.get("Price", "0"))
            ma50 = float(row.get("MA50", "0"))
            roe = float(row.get("ROE(%)", "0"))

            # 그래도 세부 기준 재확인
            if market_cap < 10_000_000_000:
                reasons.append("1단계(체급) 탈락: 시총 $10B 미만")
            if price < ma50 and ma50 > 0:
                reasons.append(f"2단계(에너지) 탈락: 종가 ${price:.2f} < 50MA ${ma50:.2f}")
            if roe < 15:
                reasons.append(f"3단계(내실) 탈락: ROE {roe:.1f}% < 15%")

            # 5~6단계 체크: final_picks에 없으면 탈락
            if sym not in picks_data and not reasons:
                reasons.append("5~6단계(심리/기세) 탈락: 최종 선정 기준 미달")

        else:
            # 스캔에 없음 → 1~4단계 중 탈락
            # 어디서 탈락했는지 구체적으로 분석
            reasons.append("1~4단계 탈락: 오늘 스캔에서 기준 미달로 제외됨")

            # 가능한 경우 추가 상세 원인 분석
            # (scan에 없는 종목은 raw 데이터가 없으므로 간략 표기)

        if reasons:
            sell_recommendations.append({
                "symbol": sym,
                "qty": stock["qty"],
                "buy_avg": stock["buy_avg"],
                "current": stock["current"],
                "pnl_rate": stock["pnl_rate"],
                "pnl_amt": stock["pnl_amt"],
                "reasons": reasons,
                "action": "SELL",
            })

    return sell_recommendations


def get_buy_recommendations(held_symbols, picks_data):
    """
    보유하지 않은 신규 매수 추천 종목을 가져옵니다.
    final_picks에 있지만 아직 보유하지 않은 종목 → 매수 추천
    """
    buy_recommendations = []

    for sym, row in picks_data.items():
        if sym not in held_symbols:
            buy_recommendations.append({
                "symbol": sym,
                "name": row.get("Name", sym),
                "price": row.get("Price", "0"),
                "reason": row.get("Reason", row.get("GrowthReason", "기준 통과")),
                "action": "BUY",
            })

    return buy_recommendations


def run_rebalancer():
    """리밸런싱 분석을 실행합니다."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    print("=" * 55)
    print(f"⚖️ 알파 리밸런서 — 포트폴리오 적격 심사 ({now})")
    print("=" * 55)

    # 1. 보유 종목 조회
    print("\n📊 [1] 보유 종목 조회...")
    held_stocks = get_held_stocks()

    if not held_stocks:
        print("📭 보유 종목 없음 — 매도 검증 생략.")
    else:
        print(f"📋 보유 종목: {len(held_stocks)}개 — {', '.join(s['symbol'] for s in held_stocks)}")

    # 2. 오늘 스캔 결과 로드
    print("\n📋 [2] 스캔 결과 로드...")
    scan_data = load_csv("output_reports/daily_scan_latest.csv")
    picks_data = load_csv("output_reports/final_picks_latest.csv")
    print(f"   1~4단계 통과: {len(scan_data)}종목")
    print(f"   5~6단계 통과: {len(picks_data)}종목")

    # 3. 매도 추천 (보유 종목 중 탈락한 것)
    print("\n🔍 [3] 보유 종목 재검증...")
    sell_recs = []
    if held_stocks:
        sell_recs = check_held_against_scan(held_stocks, scan_data, picks_data)
        if sell_recs:
            print(f"🚨 매도 추천: {len(sell_recs)}종목")
            for s in sell_recs:
                print(f"   🔻 {s['symbol']}: {', '.join(s['reasons'])}")
        else:
            print("✅ 모든 보유 종목 적격 — 매도 추천 없음.")

    # 4. 매수 추천 (보유하지 않은 신규 선정 종목)
    print("\n🔍 [4] 신규 매수 종목 확인...")
    held_symbols = [s["symbol"] for s in held_stocks]
    buy_recs = get_buy_recommendations(held_symbols, picks_data)
    if buy_recs:
        print(f"📈 매수 추천: {len(buy_recs)}종목")
        for b in buy_recs:
            print(f"   🟢 {b['symbol']} ({b['name']}): {b['reason']}")
    else:
        print("📭 신규 매수 추천 없음.")

    # 5. 결과 저장
    recommendations = {
        "timestamp": now,
        "sell": sell_recs,
        "buy": buy_recs,
        "held_count": len(held_stocks),
        "scan_passed": len(scan_data),
        "picks_passed": len(picks_data),
    }

    output_path = "output_reports/rebalance_recommendations.json"
    os.makedirs("output_reports", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(recommendations, f, indent=2, ensure_ascii=False)

    print(f"\n💾 리밸런싱 분석 저장: {output_path}")
    print(f"   매도 추천: {len(sell_recs)}건 / 매수 추천: {len(buy_recs)}건")

    return recommendations


if __name__ == "__main__":
    run_rebalancer()
